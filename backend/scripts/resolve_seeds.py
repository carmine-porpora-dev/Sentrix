import argparse
import html
import json
import math
import sys
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from app.data.gtfs import read_table
from app.data.osm_graph import load_osm_graph
from app.data.paths import DataPaths
from app.data.resolvers import (
    ResolveError,
    edge_coordinates,
    edge_key,
    nearest_edges,
    nearest_node,
    resolve_closure,
    resolve_stop,
)
from app.data.seeds import DEFAULT_SEEDS_DIR, SeedError, read_seed_events
from app.geo import METERS_PER_DEGREE
from app.models.config import EngineConfig
from app.models.event import Event
from app.models.geo import GeoPoint
from app.models.live_segments import LiveSegmentsConfig
from scripts.common import add_data_dir_arg, atomic_write_text, default_data_dir

GEOJSON_NAME = "seed_check.geojson"
HTML_NAME = "seed_check.html"

# MapLibre GL JS da cdnjs, versione fissata e con hash di integrità (sha384 dei file scaricati). La
# pagina serve solo a chi la apre nel proprio browser: nessun dato esce.
MAPLIBRE_VERSION = "4.7.1"
MAPLIBRE_BASE = f"https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/{MAPLIBRE_VERSION}"
MAPLIBRE_JS_SRI = "sha384-SYKAG6cglRMN0RVvhNeBY0r3FYKNOJtznwA0v7B5Vp9tr31xAHsZC0DqkQ/pZDmj"
MAPLIBRE_CSS_SRI = "sha384-MinO0mNliZ3vwppuPOUnGa+iq619pfMhLVUXfC4LHwSCvF9H+6P/KO4Q7qBOYV5V"

AREA_CIRCLE_VERTICES = 64
COORD_DECIMALS = 6  # ≈ 0,1 m
# Un tratto LIVE deve cadere su una strada: oltre questa distanza dall'arco OSM più vicino è un
# errore (le coordinate le sceglie pick_live_segments, ma il file si può ritoccare a mano).
LIVE_ON_ROAD_MAX_M = 25.0
NETWORK_DECIMALS = 5  # ≈ 1 m: basta per lo sfondo


@dataclass
class Row:
    """Una riga dell'esito, per il terminale e per la tabella della pagina."""

    group: str  # Chiusure | Fermate | Punti
    event: str | None
    label: str
    ok: bool
    detail: str


@dataclass
class CheckResult:
    features: list[dict[str, Any]] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    edge_keys: dict[str, list[list[str]]] = field(default_factory=dict)  # evento → per chiusura
    stop_ids: dict[str, list[list[str]]] = field(default_factory=dict)  # evento → per interruzione
    seed_failures: int = 0  # chiusure o fermate non risolte: bloccano la scrittura dei preset

    @property
    def failures(self) -> list[Row]:
        return [row for row in self.rows if not row.ok]


# --- geometrie -------------------------------------------------------------------------------


def point_feature(lat: float, lon: float, **properties: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [round(lon, COORD_DECIMALS), round(lat, COORD_DECIMALS)],
        },
        "properties": properties,
    }


def line_feature(coords: list[list[float]], **properties: Any) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": properties,
    }


def circle_feature(center: GeoPoint, radius_m: float, **properties: Any) -> dict[str, Any]:
    d_lat = radius_m / METERS_PER_DEGREE
    d_lon = d_lat / math.cos(math.radians(center.lat))
    ring = [
        [
            round(
                center.lon + d_lon * math.cos(2 * math.pi * i / AREA_CIRCLE_VERTICES),
                COORD_DECIMALS,
            ),
            round(
                center.lat + d_lat * math.sin(2 * math.pi * i / AREA_CIRCLE_VERTICES),
                COORD_DECIMALS,
            ),
        ]
        for i in range(AREA_CIRCLE_VERTICES)
    ]
    ring.append(ring[0])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": properties,
    }


def network_geojson(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Sfondo della pagina: la rete stradale, una linea per coppia di nodi (non per senso)."""
    seen: set[frozenset[int]] = set()
    features = []
    for u, v, k in sorted(graph.edges(keys=True)):
        pair = frozenset((u, v))
        if pair in seen:
            continue
        seen.add(pair)
        features.append(line_feature(edge_coordinates(graph, (u, v, k), NETWORK_DECIMALS)))
    return {"type": "FeatureCollection", "features": features}


# --- verifica --------------------------------------------------------------------------------


def check_event(
    event: Event, graph: nx.MultiDiGraph, stops: pd.DataFrame, result: CheckResult
) -> None:
    result.features.append(
        circle_feature(event.area_center, event.area_radius_m, kind="area", event=event.id)
    )
    result.edge_keys[event.id] = []
    for closure in event.closures:
        # Con i nomi si ricalcola da zero; una chiusura solo per chiavi (scelte a mano) le tiene.
        fresh = closure.model_copy(update={"edge_keys": []}) if closure.street_names else closure
        try:
            keys = resolve_closure(fresh, graph)
        except ResolveError as exc:
            result.seed_failures += 1
            result.edge_keys[event.id].append([])
            result.rows.append(Row("Chiusure", event.id, closure.label, False, str(exc)))
            continue
        result.edge_keys[event.id].append(keys)
        length = 0.0
        for key in keys:
            u, v, k = (int(part) for part in key.split("-"))
            data = graph.edges[u, v, k]
            length += float(data["length_m"])
            result.features.append(
                line_feature(
                    edge_coordinates(graph, (u, v, k), COORD_DECIMALS),
                    kind="closure",
                    event=event.id,
                    label=closure.label,
                    edge_key=key,
                    name=data.get("name") if isinstance(data.get("name"), str) else "(senza nome)",
                    length_m=round(float(data["length_m"])),
                )
            )
        result.rows.append(
            Row("Chiusure", event.id, closure.label, True, f"{len(keys)} archi, {length:.0f} m")
        )

    result.stop_ids[event.id] = []
    for disruption in event.transit_disruptions:
        try:
            ids = resolve_stop(disruption.stop_name, stops)
        except ResolveError as exc:
            result.seed_failures += 1
            result.stop_ids[event.id].append([])
            result.rows.append(Row("Fermate", event.id, disruption.label, False, str(exc)))
            continue
        result.stop_ids[event.id].append(ids)
        for stop_id in ids:
            row = stops[stops["stop_id"] == stop_id].iloc[0]
            result.features.append(
                point_feature(
                    float(row["stop_lat"]),
                    float(row["stop_lon"]),
                    kind="stop",
                    event=event.id,
                    label=disruption.label,
                    stop_id=stop_id,
                    name=str(row["stop_name"]).strip(),
                )
            )
        result.rows.append(
            Row(
                "Fermate", event.id, disruption.label, True, f"{len(ids)} fermate: {', '.join(ids)}"
            )
        )


def check_point(
    point: GeoPoint,
    graph: nx.MultiDiGraph,
    max_distance_m: float,
    result: CheckResult,
    *,
    kind: str,
    label: str,
    event: str | None = None,
    connected: AbstractSet[int] | None = None,
    **extra: Any,
) -> None:
    """Controlla che il punto abbia un nodo entro `max_distance_m` e, se `connected` è dato, che
    quel nodo appartenga alla componente principale della rete: un nodo fuori (es. un ramo di
    uscita senza ritorno) si raggiunge solo in un senso e la sua domanda andrebbe persa."""
    node, distance = nearest_node(point, graph)
    near = distance <= max_distance_m
    linked = connected is None or node in connected
    ok = near and linked
    detail = f"nodo {node} a {distance:.0f} m"
    if not near:
        detail += f" (massimo {max_distance_m:.0f} m)"
    if not linked:
        detail += (
            ": fuori dalla componente principale della rete, non si arriva da o verso la città"
        )
    result.rows.append(Row("Punti", event, label, ok, detail))
    result.features.append(
        point_feature(
            point.lat,
            point.lon,
            kind=kind,
            label=label,
            event=event,
            ok=ok,
            node=node,
            distance_m=round(distance),
            **extra,
        )  # fmt: skip
    )
    x, y = float(graph.nodes[node]["x"]), float(graph.nodes[node]["y"])
    result.features.append(
        point_feature(y, x, kind="node", label=f"Nodo {node}", event=event, ok=ok)
    )
    result.features.append(
        line_feature(
            [
                [round(point.lon, COORD_DECIMALS), round(point.lat, COORD_DECIMALS)],
                [round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)],
            ],
            kind="snap",
            event=event,
            ok=ok,
        )  # fmt: skip
    )


def main_component(graph: nx.MultiDiGraph) -> frozenset[int]:
    """I nodi della componente fortemente connessa più grande: da ognuno si arriva a ogni altro."""
    return frozenset(max(nx.strongly_connected_components(graph), key=len, default=()))


def check_points(
    events: list[Event], graph: nx.MultiDiGraph, config: EngineConfig, result: CheckResult
) -> None:
    limit = config.node_snap_max_distance_m
    main = main_component(graph)
    for event in events:
        label = f"Centro area: {event.area_center.label or event.name}"
        check_point(
            event.area_center, graph, limit, result, kind="area_center", label=label,
            event=event.id, connected=main,
        )  # fmt: skip
    demand = config.demand
    for zone in demand.zones:
        check_point(
            zone.centroid, graph, limit, result, kind="zone", label=f"Zona {zone.name}",
            zone_id=zone.id, zone_type=zone.type, weight_pct=zone.weight_pct, connected=main,
        )  # fmt: skip
    for destination in demand.car_destinations:
        check_point(
            destination.point, graph, limit, result, kind="car_destination",
            label=f"Arrivo auto: {destination.point.label or 'senza etichetta'}",
            share_pct=destination.share_pct, connected=main,
        )  # fmt: skip
    for pair in demand.od_pairs:
        for role, endpoint in (("origine", pair.origin), ("destinazione", pair.destination)):
            if endpoint.point is not None:  # le zone sono già sopra
                check_point(
                    endpoint.point, graph, limit, result, kind="od_point",
                    label=f"O/D {pair.label} ({role})", pair_id=pair.id, connected=main,
                )  # fmt: skip


def check_live_segments(
    live: LiveSegmentsConfig, graph: nx.MultiDiGraph, result: CheckResult
) -> None:
    """Ogni tratto LIVE deve cadere su una strada: si mostra su quale (nome OSM e classe)."""
    points = [GeoPoint(lat=s.lat, lon=s.lon) for s in live.segments]
    for segment, (key, distance) in zip(live.segments, nearest_edges(points, graph), strict=True):
        data = graph.edges[key]
        raw_name = data.get("name")
        name = raw_name if isinstance(raw_name, str) else "(senza nome)"
        ok = distance <= LIVE_ON_ROAD_MAX_M
        detail = (
            f"su «{name}» ({data.get('highway')}), a {distance:.0f} m dall'arco {edge_key(*key)}"
        )
        if not ok:
            detail += f": oltre {LIVE_ON_ROAD_MAX_M:.0f} m, non è su una strada"
        label = segment.label or segment.id  # il modello garantisce l'etichetta
        result.rows.append(Row("Tratti LIVE", None, label, ok, detail))
        result.features.append(
            point_feature(
                segment.lat,
                segment.lon,
                kind="live_segment",
                label=segment.label,
                segment_id=segment.id,
                osm_name=name,
                highway=str(data.get("highway")),
                edge_key=edge_key(*key),
                distance_m=round(distance),
                ok=ok,
            )  # fmt: skip
        )


def check(
    events: list[Event],
    graph: nx.MultiDiGraph,
    stops: pd.DataFrame,
    config: EngineConfig,
    live: LiveSegmentsConfig | None = None,
) -> CheckResult:
    result = CheckResult()
    for event in events:
        check_event(event, graph, stops, result)
    check_points(events, graph, config, result)
    if live is not None:
        check_live_segments(live, graph, result)
    return result


# --- file dei preset -------------------------------------------------------------------------


def patched_seed(
    raw: dict[str, Any], edge_keys: list[list[str]], stop_ids: list[list[str]]
) -> dict[str, Any]:
    """Il JSON del preset con `edge_keys` e `stop_ids` risolti. Il resto resta com'è, nello stesso
    ordine delle chiavi."""
    result = json.loads(json.dumps(raw))
    for closure, keys in zip(result["closures"], edge_keys, strict=True):
        closure["edge_keys"] = keys
    for disruption, ids in zip(result["transit_disruptions"], stop_ids, strict=True):
        disruption["stop_ids"] = ids
    return result


def seed_text(raw: dict[str, Any]) -> str:
    return json.dumps(raw, ensure_ascii=False, indent=2) + "\n"


def write_seeds(events: list[Event], result: CheckResult, seeds_dir: Path) -> list[str]:
    """Aggiorna i file; restituisce gli id dei preset cambiati. Ogni file viene riconvalidato."""
    changed = []
    for event in events:
        path = seeds_dir / f"{event.id}.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        patched = patched_seed(raw, result.edge_keys[event.id], result.stop_ids[event.id])
        Event.model_validate(patched)  # mai scrivere un preset che il modello rifiuterebbe
        text = seed_text(patched)
        if text != path.read_text(encoding="utf-8"):
            atomic_write_text(path, text)
            changed.append(event.id)
    return changed


# --- pagina HTML -----------------------------------------------------------------------------

PAGE = (Path(__file__).with_name("resolve_seeds_page.html")).read_text(encoding="utf-8")


def script_safe_json(value: Any) -> str:
    """JSON da mettere dentro <script>: ogni `<` diventa `\\u003c` (JSON valido), così non può
    comparire `</script>` né `<!--` nei dati."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_page(
    result: CheckResult, network: dict[str, Any], events: list[Event], bounds: list[list[float]]
) -> str:
    rows = "\n".join(
        '<tr class="{cls}"><td>{group}</td><td>{event}</td><td>{label}</td>'
        "<td><b>{status}</b> {detail}</td></tr>".format(
            cls="ok" if row.ok else "err",
            group=html.escape(row.group),
            event=html.escape(row.event or "—"),
            label=html.escape(row.label),
            status="OK" if row.ok else "ERRORE",
            detail=html.escape(row.detail),
        )
        for row in result.rows
    )
    data = {
        "features": {"type": "FeatureCollection", "features": result.features},
        "network": network,
        "events": [{"id": e.id, "name": e.name, "date": e.date.isoformat()} for e in events],
        "bounds": bounds,
    }
    return (
        PAGE.replace("__MAPLIBRE_CSS__", f"{MAPLIBRE_BASE}/maplibre-gl.css")
        .replace("__MAPLIBRE_CSS_SRI__", MAPLIBRE_CSS_SRI)
        .replace("__MAPLIBRE_JS__", f"{MAPLIBRE_BASE}/maplibre-gl.js")
        .replace("__MAPLIBRE_JS_SRI__", MAPLIBRE_JS_SRI)
        .replace("__ROWS__", rows)
        .replace("__SUMMARY__", html.escape(summary(result)))
        .replace("__DATA__", script_safe_json(data))
    )


def summary(result: CheckResult) -> str:
    bad = len(result.failures)
    total = len(result.rows)
    return f"{total - bad} voci su {total} risolte" + (f", {bad} NON risolte" if bad else "")


def graph_bounds(graph: nx.MultiDiGraph) -> list[list[float]]:
    xs = [float(d["x"]) for _, d in graph.nodes(data=True)]
    ys = [float(d["y"]) for _, d in graph.nodes(data=True)]
    return [[min(xs), min(ys)], [max(xs), max(ys)]]


# --- ingresso --------------------------------------------------------------------------------


def run(data_dir: Path, seeds_dir: Path, *, dry_run: bool) -> int:
    paths = DataPaths(data_dir)
    graph_path = paths.osm_graph
    if not graph_path.is_file():
        print(f"Manca il grafo stradale {graph_path}: esegui prima `make data`.", file=sys.stderr)
        return 2
    stops = read_table(paths.gtfs_feed, "stops.txt")
    if stops is None:
        print(
            f"Manca il feed GTFS in {paths.gtfs_feed}: esegui prima `make data`.",
            file=sys.stderr,
        )
        return 2
    try:
        events = read_seed_events(seeds_dir)
    except SeedError as exc:
        print(f"Preset non utilizzabili: {exc}", file=sys.stderr)
        return 2

    graph = load_osm_graph(graph_path)
    result = check(events, graph, stops, EngineConfig.from_yaml(), LiveSegmentsConfig.from_yaml())

    report_dir = data_dir / "report"
    atomic_write_text(
        report_dir / GEOJSON_NAME,
        json.dumps({"type": "FeatureCollection", "features": result.features}, ensure_ascii=False),
    )
    atomic_write_text(
        report_dir / HTML_NAME,
        render_page(result, network_geojson(graph), events, graph_bounds(graph)),
    )

    for row in result.rows:
        print(
            f"[{'OK ' if row.ok else 'ERR'}] {row.group:9} {row.event or '-':16} "
            f"{row.label}: {row.detail}"
        )
    print(summary(result))
    print(f"Pagina di verifica: {report_dir / HTML_NAME}")

    if result.seed_failures:
        print(
            "Chiusure o fermate non risolte: i preset NON sono stati modificati.", file=sys.stderr
        )
    elif dry_run:
        print("--dry-run: i preset non sono stati modificati.")
    else:
        changed = write_seeds(events, result, seeds_dir)
        print(f"Preset aggiornati: {', '.join(changed) if changed else 'nessuno (già risolti)'}")
    return 1 if result.failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Risolve i preset e genera la pagina di verifica.")
    add_data_dir_arg(parser)
    parser.add_argument(
        "--seeds-dir", type=Path, default=DEFAULT_SEEDS_DIR, help="default: seeds/events"
    )
    parser.add_argument("--dry-run", action="store_true", help="non modificare i file dei preset")
    args = parser.parse_args(argv)
    return run(args.data_dir or default_data_dir(), args.seeds_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
