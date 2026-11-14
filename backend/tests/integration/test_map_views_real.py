import time
from collections.abc import Iterator
from typing import Any

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.data.map_data import MapData
from app.data.map_views import event_preview, network_edges, transit_lines, transit_stops
from app.data.paths import DataPaths, default_data_dir
from app.data.resolvers import parse_edge_key
from app.engine.transit import TransitNetwork
from app.main import create_app
from app.models.api import Feature, FeatureCollection
from app.models.api_config import ApiConfig
from app.models.event import Event
from app.settings import Settings
from tests.conftest import PASSWORD, SESSION_SECRET, log_in
from tests.orchestrator_support import engines_with

pytestmark = pytest.mark.realdata

CONFIG = ApiConfig.from_yaml().network
SEEDS = ["match_2027", "regate_sep_2026"]
SECONDS = 2.0  # una vista della mappa, anche la più grande, non deve far attendere l'utente


def around(event: Event, span: float) -> tuple[float, float, float, float]:
    """Un'area quadrata di `span` gradi centrata sull'evento."""
    center, half = event.area_center, span / 2
    return center.lon - half, center.lat - half, center.lon + half, center.lat + half


def coordinates(feature: Feature) -> Any:
    assert feature.geometry is not None
    return feature.geometry["coordinates"]


def number(feature: Feature, name: str) -> float:
    value = feature.properties[name]
    assert isinstance(value, int | float)
    return float(value)


def kinds(preview: FeatureCollection) -> list[str]:
    return [str(f.properties["kind"]) for f in preview.features]


@pytest.fixture(scope="module")
def map_data(road_graph: nx.MultiDiGraph, transit_network: TransitNetwork) -> MapData:
    """I dati già caricati dalle fixture di sessione: nessuna seconda lettura da disco."""
    return MapData(DataPaths(default_data_dir()), graph=road_graph, feed=transit_network.feed)


# --- le strade ---------------------------------------------------------------------------------


@pytest.mark.parametrize("event_id", SEEDS)
def test_i_due_sensi_di_ogni_strada_si_abbinano_senza_ripetizioni(
    map_data: MapData, seed_events: dict[str, Event], event_id: str
) -> None:
    graph = map_data.graph()
    edges = network_edges(graph, around(seed_events[event_id], 0.011), CONFIG)
    assert 20 < len(edges.features) <= CONFIG.max_features
    seen: set[str] = set()
    for feature in edges.features:
        key, back = feature.properties["edge_key"], feature.properties["reverse_key"]
        u, v, k = parse_edge_key(str(key))
        assert graph.has_edge(u, v, k)
        assert key not in seen
        seen.add(str(key))
        if back is not None:
            bu, bv, bk = parse_edge_key(str(back))
            assert (bu, bv) == (v, u) and graph.has_edge(bu, bv, bk)
            assert back not in seen  # un senso solo una volta, o come strada o come ritorno
            seen.add(str(back))
    two_way = [f for f in edges.features if f.properties["reverse_key"] is not None]
    assert two_way and len(two_way) < len(edges.features)  # a Napoli ci sono sensi unici


@pytest.mark.parametrize("event_id", SEEDS)
def test_le_chiusure_dei_preset_sono_strade_maggiori_con_i_due_sensi(
    map_data: MapData, seed_events: dict[str, Event], event_id: str
) -> None:
    """Quello che il preset chiude è anche ciò che l'utente vede e può scegliere sulla mappa."""
    event = seed_events[event_id]
    graph = map_data.graph()
    preview = event_preview(event, graph, map_data.feed().stops, map_data.config)
    closed = {
        str(f.properties["edge_key"]) for f in preview.features if f.properties["kind"] == "closure"
    }
    assert closed
    shown: set[str] = set()
    for feature in network_edges(graph, around(event, 0.1), CONFIG).features:
        shown.add(str(feature.properties["edge_key"]))
        if feature.properties["reverse_key"] is not None:
            shown.add(str(feature.properties["reverse_key"]))
    assert closed <= shown, sorted(closed - shown)


def test_l_area_piu_grande_sta_nei_limiti(map_data: MapData, seed_events: dict[str, Event]) -> None:
    started = time.perf_counter()
    edges = network_edges(
        map_data.graph(), around(seed_events["match_2027"], CONFIG.max_span_deg), CONFIG
    )
    assert time.perf_counter() - started < SECONDS
    assert 100 < len(edges.features) <= CONFIG.max_features
    assert len(edges.model_dump_json()) < 2_000_000  # circa 1,3 MB misurati
    classes = {str(f.properties["highway"]).split(", ")[0] for f in edges.features}
    assert classes <= set(CONFIG.major_classes)  # in grande, solo le strade maggiori


# --- le fermate e le linee ---------------------------------------------------------------------


@pytest.mark.parametrize("event_id", SEEDS)
def test_le_fermate_attorno_all_evento(
    map_data: MapData, seed_events: dict[str, Event], event_id: str
) -> None:
    bbox = around(seed_events[event_id], 0.011)
    stops = transit_stops(map_data.feed(), bbox, CONFIG)
    assert len(stops.features) > 5
    west, south, east, north = bbox
    for feature in stops.features:
        lon, lat = coordinates(feature)
        assert west <= lon <= east and south <= lat <= north
        assert feature.properties["kind"] == "real" and feature.properties["name"]
    assert any(f.properties["routes"] for f in stops.features)


def test_tutta_napoli_di_fermate_sta_nei_limiti(
    map_data: MapData, seed_events: dict[str, Event]
) -> None:
    started = time.perf_counter()
    stops = transit_stops(
        map_data.feed(), around(seed_events["match_2027"], CONFIG.max_span_deg), CONFIG
    )
    assert time.perf_counter() - started < SECONDS
    assert 1000 < len(stops.features) <= CONFIG.max_features


def test_le_linee_di_metro_e_funicolari_di_napoli(map_data: MapData) -> None:
    lines = transit_lines(
        map_data.feed(), map_data.route_classes(), ("metro_line_1", "metro_line_6", "funicular")
    )
    by_class: dict[str, list[str]] = {}
    for feature in lines.features:
        by_class.setdefault(str(feature.properties["route_class"]), []).append(str(feature.id))
    assert {kind: len(ids) for kind, ids in by_class.items()} == {
        "metro_line_1": 1,
        "metro_line_6": 1,
        "funicular": 3,
    }
    assert all(len(coordinates(f)) >= 2 for f in lines.features)
    one = next(f for f in lines.features if f.properties["route_class"] == "metro_line_1")
    assert len(coordinates(one)) >= 15  # la L1 ha molte fermate


# --- l'anteprima dei preset --------------------------------------------------------------------


@pytest.mark.parametrize("event_id", SEEDS)
def test_tutto_cio_che_i_preset_chiudono_si_risolve(
    map_data: MapData, seed_events: dict[str, Event], event_id: str
) -> None:
    event = seed_events[event_id]
    preview = event_preview(event, map_data.graph(), map_data.feed().stops, map_data.config)
    labels = {f.properties["label"] for f in preview.features if f.properties["kind"] == "closure"}
    assert labels == {closure.label for closure in event.closures}
    stop_labels = {
        f.properties["label"] for f in preview.features if f.properties["kind"] == "stop"
    }
    assert stop_labels == {d.label for d in event.transit_disruptions}
    first = preview.features[0]
    assert first.properties["kind"] == "area_center"
    assert number(first, "distance_m") <= map_data.config.node_snap_max_distance_m


def test_le_chiusure_del_match_sono_quelle_attese(
    map_data: MapData, seed_events: dict[str, Event]
) -> None:
    event = seed_events["match_2027"]
    preview = event_preview(event, map_data.graph(), map_data.feed().stops, map_data.config)
    assert kinds(preview).count("closure") == 6  # Via Caracciolo (2 sensi) e Viale Dohrn (4)
    assert kinds(preview).count("stop") == 2  # Arco Mirelli: due banchine
    assert kinds(preview).count("car_destination") == 5  # i punti di arrivo di engine.yaml
    regate = event_preview(
        seed_events["regate_sep_2026"], map_data.graph(), map_data.feed().stops, map_data.config
    )
    assert kinds(regate).count("closure") == 6 and kinds(regate).count("stop") == 0


# --- via API -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api(map_data: MapData, tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    settings = Settings(
        env="local",
        data_dir=tmp_path_factory.mktemp("data"),
        app_password=PASSWORD,
        session_secret=SESSION_SECRET,
    )
    app = create_app(settings, engines=engines_with(()), map_data=map_data)
    with TestClient(app) as client:
        log_in(client)
        yield client


@pytest.mark.parametrize("event_id", SEEDS)
def test_le_quattro_risposte_sono_json_valido_sui_dati_veri(
    api: TestClient, seed_events: dict[str, Event], event_id: str
) -> None:
    west, south, east, north = around(seed_events[event_id], 0.011)
    bbox = f"{west},{south},{east},{north}"
    edges = api.get("/api/network/edges", params={"bbox": bbox})
    stops = api.get("/api/transit/stops", params={"bbox": bbox})
    lines = api.get("/api/transit/lines")
    resolved = api.post(f"/api/events/{event_id}/resolve")
    for response in (edges, stops, lines, resolved):
        assert response.status_code == 200, response.text
        assert response.json()["type"] == "FeatureCollection" and response.json()["features"]
    assert kinds_of(resolved.json()).count("closure") == 6


def kinds_of(body: dict[str, list[dict[str, dict[str, str]]]]) -> list[str]:
    return [f["properties"]["kind"] for f in body["features"]]
