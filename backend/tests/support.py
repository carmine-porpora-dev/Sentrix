import copy
import csv
import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
from fastapi import FastAPI
from shapely.geometry import LineString  # type: ignore[import-untyped]

from app.api.context import AppContext
from app.geo import haversine_m
from app.models.config import EngineConfig
from app.models.event import Event
from app.models.geo import GeoPoint
from app.models.operations import OperationRequest
from app.models.run import Run

GTFS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_gtfs"


@dataclass
class FeedServer:
    """Server HTTP locale (127.0.0.1): un feed zip, un redirect, un 404, un contenuto non-zip."""

    url: str
    zip_bytes: bytes
    user_agents: list[str] = field(default_factory=list)


def make_zip(directory: Path, destination: Path) -> Path:
    """Zip con i file .txt di `directory` (come un feed GTFS)."""
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.glob("*.txt")):
            archive.write(path, path.name)
    return destination


DELETE = object()  # segnaposto: «togli questa chiave»


def mutated(raw: dict[str, Any], path: tuple[str | int, ...], value: Any) -> dict[str, Any]:
    """Copia di `raw` con il valore al `path` sostituito (o la chiave tolta, se value è DELETE)."""
    data = copy.deepcopy(raw)
    node: Any = data
    for key in path[:-1]:
        node = node[key]
    if value is DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return data


# --- grafo stradale di prova (resolver e resolve_seeds) -------------------------------------

BBOX = (14.2275, 40.8295, 14.2450, 40.8365)  # quello proposto in 01 5.1
CARACCIOLO = "Via Francesco Caracciolo"
DOHRN = "Viale Anton Dohrn"

STREET_NODES = {
    1: (14.2300, 40.8320),
    2: (14.2350, 40.8325),
    3: (14.2400, 40.8330),
    4: (14.2450, 40.8335),
    5: (14.2200, 40.8280),  # a ovest, fuori dal bbox
    6: (14.2250, 40.8290),
    7: (14.2350, 40.8400),  # a nord, fuori dal bbox
    8: (14.2380, 40.8410),
    9: (14.2700, 40.8960),  # un'altra «Via Francesco Caracciolo», lontana
    10: (14.2705, 40.8965),
    11: (14.2000, 40.8000),  # 11 e 12: stesse coordinate, per i pareggi
    12: (14.2000, 40.8000),
}


def build_street_graph(node_order: list[int] | None = None) -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node in node_order or list(STREET_NODES):
        lon, lat = STREET_NODES[node]
        g.add_node(node, x=lon, y=lat)

    def add(u: int, v: int, name: Any, k: int = 0, **extra: Any) -> None:
        g.add_edge(u, v, key=k, name=name, length_m=100.0, **extra)

    for a, b in [(1, 2), (2, 3)]:  # via Caracciolo nel bbox, nei due sensi
        add(a, b, CARACCIOLO)
        add(b, a, CARACCIOLO)
    add(3, 4, f"{DOHRN}; {CARACCIOLO}")  # nome fuso da OSMnx
    add(4, 3, f"{DOHRN}; {CARACCIOLO}")
    add(5, 6, CARACCIOLO)  # la stessa via, a ovest del bbox
    add(9, 10, CARACCIOLO)  # e a nord, lontano
    add(10, 9, CARACCIOLO)
    add(7, 8, "Via Torre Caracciolo")
    add(8, 7, "Via Tristano Caracciolo")
    add(4, 1, "Via Francesco Caracciolo Nuova")
    add(1, 7, None)  # senza nome
    add(7, 1, 42)  # nome che non è testo: ignorato
    add(1, 2, "Via Marina", k=1)  # arco parallelo
    # Un arco curvo: gli estremi sono a ovest, ma la linea sale fino a 40.85 (fuori dal bbox).
    # La media degli estremi (14.2275, 40.8305) cadrebbe dentro il bbox, il punto medio della
    # linea (circa 14.2273, 40.8485) no.
    curve = LineString([(14.2250, 40.8290), (14.2275, 40.8500), (14.2300, 40.8320)])
    add(6, 1, "Via Curva", geometry=curve)
    return g


HIGHWAY = {  # la classe OSM di ogni arco di `build_street_graph`; il resto è «residential»
    (1, 2, 0): "primary",
    (2, 1, 0): "primary",
    (2, 3, 0): ["primary", "residential"],  # due classi insieme
    (3, 2, 0): ["primary", "residential"],
    (3, 4, 0): "secondary",
    (4, 3, 0): "secondary",
    (9, 10, 0): "tertiary",
    (10, 9, 0): "tertiary",
    (1, 7, 0): "tertiary_link",  # `_link` conta come la sua classe
    (7, 1, 0): "tertiary_link",
}


def build_classed_street_graph() -> nx.MultiDiGraph:
    """`build_street_graph` con la classe OSM (`highway`) di ogni arco."""
    graph = build_street_graph()
    for u, v, k, data in graph.edges(keys=True, data=True):
        data["highway"] = HIGHWAY.get((u, v, k), "residential")
    return graph


# --- grafo grezzo di prova per il motore (come lo salva scripts/prepare_osm.py) ------------------


def build_raw_road_graph() -> nx.MultiDiGraph:
    """Tredici archi con tutti i casi di `engine.graph`; un attributo assente è assente dall'arco.

    chiave   classe          lanes  maxspeed  oneway  length_m
    1-2-0    primary         3      60        sì      300
    1-2-1    tertiary        —      40        sì      310     (arco parallelo)
    2-3-0    primary         —      —         sì      500
    3-4-0    residential     2      —         sì      100
    4-5-0    emergency_bay   —      —         sì       60     (classe che road_defaults non prevede)
    5-1-0    (senza highway) —      —         sì      150
    3-3-0    residential     —      —         sì       20     (anello su se stesso)
    2-1-0    primary         4      —         no      300     (doppio senso: lanes OSM = totale)
    3-2-0    tertiary        2      —         no      500
    4-3-0    residential     3      —         no      100     (dispari)
    5-4-0    residential     1      —         no       60
    1-5-0    primary         —      —         no      150     (doppio senso senza lanes)
    2-5-0    primary         2      —         (assente) 200   (in OSM l'assenza = doppio senso)
    """
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node, (lon, lat) in {
        1: (14.2300, 40.8320),
        2: (14.2350, 40.8325),
        3: (14.2400, 40.8330),
        4: (14.2450, 40.8335),
        5: (14.2500, 40.8340),
    }.items():
        g.add_node(node, x=lon, y=lat)

    def add(
        u: int, v: int, k: int, length_m: float, oneway: bool | None = True, **extra: Any
    ) -> None:
        if oneway is not None:
            extra["oneway"] = oneway
        g.add_edge(u, v, key=k, length_m=length_m, **extra)

    add(1, 2, 0, 300.0, highway="primary", lanes=3, maxspeed_kmh=60)
    add(1, 2, 1, 310.0, highway="tertiary", maxspeed_kmh=40)
    add(2, 3, 0, 500.0, highway="primary")
    add(3, 4, 0, 100.0, highway="residential", lanes=2)
    add(4, 5, 0, 60.0, highway="emergency_bay")
    add(5, 1, 0, 150.0)
    add(3, 3, 0, 20.0, highway="residential")
    add(2, 1, 0, 300.0, oneway=False, highway="primary", lanes=4)
    add(3, 2, 0, 500.0, oneway=False, highway="tertiary", lanes=2)
    add(4, 3, 0, 100.0, oneway=False, highway="residential", lanes=3)
    add(5, 4, 0, 60.0, oneway=False, highway="residential", lanes=1)
    add(1, 5, 0, 150.0, oneway=False, highway="primary")
    add(2, 5, 0, 200.0, oneway=None, highway="primary", lanes=2)
    return g


def graph_fingerprint(graph: nx.MultiDiGraph) -> str:
    """sha256 di nodi e archi con tutti i loro attributi: stesso contenuto, stessa impronta;
    qualunque attributo cambiato (anche in un solo arco) la cambia. Serve a provare che una
    funzione non modifica la rete che riceve."""
    digest = hashlib.sha256()
    for node, data in sorted(graph.nodes(data=True), key=lambda item: item[0]):
        digest.update(repr((node, sorted(data.items()))).encode())
    for u, v, k, data in sorted(graph.edges(keys=True, data=True), key=lambda item: item[:3]):
        digest.update(repr((u, v, k, sorted(data.items()))).encode())
    return digest.hexdigest()


def write_gtfs(directory: Path, **tables: list[dict[str, Any]]) -> Path:
    """Scrive un feed GTFS di prova: per ogni file (`stops=[{...}, ...]` → `stops.txt`) una lista
    di righe; le colonne sono quelle usate dalle righe, nell'ordine di prima comparsa."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        columns = list(dict.fromkeys(key for row in rows for key in row))
        with (directory / f"{name}.txt").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, restval="")
            writer.writeheader()
            writer.writerows(rows)
    return directory


HUB = 1  # il nodo centrale della stella di prova


def engine_points(config: EngineConfig) -> list[GeoPoint]:
    """Ogni punto che il motore trasforma in nodo (zone, arrivi, estremi O/D), una volta sola."""
    zones = {zone.id: zone.centroid for zone in config.demand.zones}
    points = [*zones.values(), *(d.point for d in config.demand.car_destinations)]
    for pair in config.demand.od_pairs:
        for end in (pair.origin, pair.destination):
            points.append(zones[end.zone] if end.zone is not None else end.point)  # type: ignore[arg-type]
    return list({(p.lat, p.lon): p for p in points}.values())


def build_star_raw_graph(config: EngineConfig) -> nx.MultiDiGraph:
    """Il grafo come lo salva `prepare_osm`, a stella: il nodo 1 è al centro di `make_event()` e
    ogni punto del motore ha un nodo (2…) collegato al centro da due archi `primary`. Ogni cammino
    passa dal centro, quindi chiudere l'arco che entra in un punto di arrivo lascia senza cammino
    tutte le coppie che vi arrivano."""
    center = make_event().area_center
    raw: nx.MultiDiGraph = nx.MultiDiGraph()
    raw.add_node(HUB, x=center.lon, y=center.lat)
    for node, point in enumerate(engine_points(config), start=HUB + 1):
        raw.add_node(node, x=point.lon, y=point.lat)
        length = float(haversine_m(point.lat, point.lon, (center.lat, center.lon)))
        for u, v in ((HUB, node), (node, HUB)):
            raw.add_edge(
                u,
                v,
                key=0,
                length_m=max(length, 10.0),
                highway="primary",
                oneway=False,
                name=f"Raggio {node}",
            )
    return raw


def make_event(**changes: Any) -> Event:
    """Un Evento valido con numeri tondi, senza override: per i test del motore.

    arrivo 12:00-15:00, picco 13:30 → la fascia 13:30-14:00 ha 5/18 della domanda;
    deflusso 18:00-21:00, picco 18:30 → la fascia 18:30-19:00 ha 3/10;
    affluenza 18.000 / 36.000 / 72.000 (con 36.000 la fascia di arrivo ha 10.000 persone).
    """
    fields: dict[str, Any] = {
        "id": "test_event",
        "name": "Evento di prova",
        "date": "2026-09-26",
        "area_center": {"lat": 40.8320, "lon": 14.2350, "label": "Rotonda Diaz"},
        "area_radius_m": 400,
        "arrival": {"start": "12:00", "end": "15:00", "peak": "13:30"},
        "departure": {"start": "18:00", "end": "21:00", "peak": "18:30"},
        "attendance": {"low": 18000, "mid": 36000, "high": 72000},
        "background": {"arrival_peak_share": 0.3, "departure_peak_share": 0.3},
        "resources": [
            {
                "window": window,
                "municipal_police_patrols_total": 6,
                "municipal_police_patrols_committed": 3,
                "traffic_control_signal_changes_max": 3,
                "transport_control_reserve_buses": 8,
                "transport_control_hour_extensions": 1,
            }
            for window in ("arrival", "departure")
        ],
        "created_at": "2026-11-09T10:00:00+01:00",
        "updated_at": "2026-11-09T10:00:00+01:00",
    }
    return Event.model_validate({**fields, **changes})


def make_run(run_id: str = "run_1", **changes: Any) -> Run:
    """Un run valido su una revisione che esiste (i preset hanno la revisione 1)."""
    fields: dict[str, Any] = {
        "id": run_id,
        "event_id": "match_2027",
        "event_revision": 1,
        "attendance_level": "mid",
        "state": "INTAKE",
        "iteration": 0,
        "replans": 0,
        "started_at": "2026-11-09T10:00:00+01:00",
        "ended_at": None,
        "params_hash": "0" * 64,
        "seed": 42,
        "llm_mode": "template",
        "error": None,
    }
    return Run.model_validate({**fields, **changes})


def make_request(action_id: str = "act_1", **changes: Any) -> OperationRequest:
    fields: dict[str, Any] = {
        "action_id": action_id,
        "run_id": "run_1",
        "iteration": 1,
        "department": "municipal_police",
        "type": "traffic_post",
        "target": "incrocio_1",
        "target_label": "Incrocio 1",
        "window": "departure",
        "priority": "normal",
        "state": "RECEIVED",
        "simulation": True,
    }
    return OperationRequest.model_validate({**fields, **changes})


def ctx_of(app: FastAPI) -> AppContext:
    """Il contesto di un'app già avviata (database, limiti...): per preparare i dati dei test."""
    ctx: AppContext = app.state.ctx
    return ctx
