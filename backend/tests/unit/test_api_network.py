import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.errors import DATA_UNAVAILABLE_MESSAGE
from app.data.gtfs import load_feed
from app.data.map_data import MapData
from app.data.paths import DataPaths
from app.data.seeds import DEFAULT_SEEDS_DIR
from app.main import create_app
from app.models.config import EngineConfig, RouteClassification
from app.settings import Settings
from tests.conftest import FakeClock, log_in
from tests.orchestrator_support import engines_with
from tests.support import CARACCIOLO, GTFS_FIXTURE, build_classed_street_graph

NARROW = "14.229,40.831,14.236,40.834"  # piccolo: tutte le strade
WIDE = "14.19,40.79,14.28,40.90"  # grande: solo le maggiori
EVERYTHING = "14.0,40.0,15.0,41.0"  # oltre `network.max_span_deg`

DATA_ENDPOINTS = [
    ("get", "/api/network/edges", {"bbox": NARROW}),
    ("get", "/api/transit/stops", {"bbox": NARROW}),
    ("get", "/api/transit/lines", {}),
    ("post", "/api/events/match_2027/resolve", {}),
]


def mini_config() -> EngineConfig:
    """`engine.yaml` con le linee del mini-GTFS (R1, R2, R3) al posto di quelle di Napoli."""
    config = EngineConfig.from_yaml()
    classification = RouteClassification.model_validate(
        {
            "metro_line_1": {"route_ids": ["R1"]},
            "metro_line_6": {"route_ids": ["R2"]},
            "funicular": {"route_ids": ["R3"]},
        }
    )
    transit = config.transit.model_copy(update={"route_classification": classification})
    return config.model_copy(update={"transit": transit})


@pytest.fixture
def mapped(settings: Settings, clock: FakeClock) -> Iterator[TestClient]:
    """Un'app con i dati della mappa già caricati, sessione aperta."""
    map_data = MapData(
        DataPaths(settings.data_dir),
        graph=build_classed_street_graph(),
        feed=load_feed(GTFS_FIXTURE),
        config=mini_config(),
    )
    app = create_app(settings, clock=clock, engines=engines_with(()), map_data=map_data)
    with TestClient(app) as client:
        log_in(client)
        yield client


def event_body(event_id: str, **changes: Any) -> dict[str, Any]:
    seed = json.loads((DEFAULT_SEEDS_DIR / "regate_sep_2026.json").read_text("utf-8"))
    body = {k: v for k, v in seed.items() if k not in ("revision", "created_at", "updated_at")}
    return {**body, "id": event_id, "closures": [], "transit_disruptions": [], **changes}


# --- richiesta non valida ----------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/network/edges", "/api/transit/stops"])
@pytest.mark.parametrize(
    "bbox",
    [
        None,
        "",
        "1,2,3",
        "1,2,3,4,5",
        "a,b,c,d",
        "14.3,40.8,14.2,40.9",  # ovest > est
        "14.2,40.9,14.3,40.8",  # sud > nord
        "14.2,40.8,14.2,40.9",  # ovest == est
        "-181,40,14,41",
        "14,40,181,41",
        "14,-91,15,41",
        "14,40,15,91",
        "nan,40,15,41",
        "14,40,inf,41",
    ],
)
def test_bbox_non_valido_400(authed: TestClient, path: str, bbox: str | None) -> None:
    """Il controllo viene prima dei dati: vale anche dove non ce ne sono."""
    params = {} if bbox is None else {"bbox": bbox}
    response = authed.get(path, params=params)
    assert response.status_code == 400, (bbox, response.text)
    assert response.json()["error"]["details"]["fields"][0]["path"] == "bbox"


@pytest.mark.parametrize("path", ["/api/network/edges", "/api/transit/stops"])
def test_un_area_troppo_estesa_400(mapped: TestClient, path: str) -> None:
    response = mapped.get(path, params={"bbox": EVERYTHING})
    assert response.status_code == 400
    (field,) = response.json()["error"]["details"]["fields"]
    assert (field["path"], field["type"]) == ("bbox", "bbox_too_large")
    assert "0.25 gradi" in field["message"]


@pytest.mark.parametrize("path", ["/api/network/edges", "/api/transit/stops"])
def test_un_area_larga_quanto_il_limite_va_bene(mapped: TestClient, path: str) -> None:
    assert mapped.get(path, params={"bbox": "14.0,40.5,14.25,40.75"}).status_code == 200
    assert mapped.get(path, params={"bbox": "14.0,40.5,14.2501,40.75"}).status_code == 400
    assert mapped.get(path, params={"bbox": "14.0,40.5,14.25,40.7501"}).status_code == 400


# --- strade ------------------------------------------------------------------------------------


def test_le_strade_in_un_area_piccola(mapped: TestClient) -> None:
    response = mapped.get("/api/network/edges", params={"bbox": NARROW})
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert [f["id"] for f in body["features"]] == [
        "1-2-0", "1-7-0", "2-3-0", "1-2-1", "4-1-0", "6-1-0"
    ]  # fmt: skip
    first = body["features"][0]
    assert first["geometry"]["type"] == "LineString"
    assert first["properties"] == {
        "edge_key": "1-2-0",
        "reverse_key": "2-1-0",
        "name": CARACCIOLO,
        "highway": "primary",
        "length_m": 100,
    }


def test_le_strade_in_un_area_grande_sono_le_maggiori(mapped: TestClient) -> None:
    body = mapped.get("/api/network/edges", params={"bbox": WIDE}).json()
    assert [f["id"] for f in body["features"]] == ["1-2-0", "1-7-0", "2-3-0", "3-4-0", "9-10-0"]


def test_un_area_senza_strade_da_una_collezione_vuota(mapped: TestClient) -> None:
    response = mapped.get("/api/network/edges", params={"bbox": "14.5,41.0,14.51,41.01"})
    assert (response.status_code, response.json()["features"]) == (200, [])


# --- fermate e linee ---------------------------------------------------------------------------


def test_le_fermate_in_un_area(mapped: TestClient) -> None:
    body = mapped.get("/api/transit/stops", params={"bbox": "14.229,40.831,14.241,40.835"}).json()
    assert [f["id"] for f in body["features"]] == ["S1", "S2", "S3", "S6"]
    s2 = next(f for f in body["features"] if f["id"] == "S2")
    assert s2["properties"] == {
        "stop_id": "S2",
        "name": "RIVIERA DI CHIAIA",
        "routes": ["CHIAIA", "F1", "L1"],
        "kind": "real",
    }
    assert s2["geometry"] == {"type": "Point", "coordinates": [14.2352, 40.833]}


def test_le_linee_di_metro_e_funicolari(mapped: TestClient) -> None:
    body = mapped.get("/api/transit/lines").json()
    assert [(f["id"], f["properties"]["route_class"]) for f in body["features"]] == [
        ("R1", "metro_line_1"),
        ("R2", "metro_line_6"),
        ("R3", "funicular"),
    ]  # niente bus (R4, R6) né la metro L2 (R5), che il modello non considera
    assert all(f["geometry"]["type"] == "LineString" for f in body["features"])


# --- anteprima di un Evento --------------------------------------------------------------------


def test_l_anteprima_di_un_preset_ha_il_centro_e_gli_arrivi_in_auto(mapped: TestClient) -> None:
    response = mapped.post("/api/events/match_2027/resolve")
    assert response.status_code == 200
    kinds = [f["properties"]["kind"] for f in response.json()["features"]]
    assert kinds[0] == "area_center"
    assert set(kinds) <= {"area_center", "car_destination", "closure", "stop"}
    assert "car_destination" in kinds  # i punti di arrivo di engine.yaml
    # i dati di prova non hanno le strade di Napoli: le chiusure del preset non si risolvono
    assert "closure" not in kinds


def test_l_anteprima_segue_la_revisione_corrente(mapped: TestClient) -> None:
    closure = {
        "label": "Via Caracciolo",
        "street_names": [CARACCIOLO],
        "bbox": [14.2275, 40.8295, 14.245, 40.8365],
    }
    stop = {"label": "Rotonda Diaz chiusa", "stop_name": "ROTONDA DIAZ", "window": "both"}
    created = mapped.post(
        "/api/events", json=event_body("mio", closures=[closure], transit_disruptions=[stop])
    )
    assert created.status_code == 201, created.text

    def kinds() -> list[str]:
        features = mapped.post("/api/events/mio/resolve").json()["features"]
        return [f["properties"]["kind"] for f in features]

    before = kinds()
    assert before.count("closure") == 6 and before.count("stop") == 1

    updated = mapped.put("/api/events/mio", json=event_body("mio"))  # senza chiusure né fermate
    assert updated.status_code == 200, updated.text
    after = kinds()
    assert "closure" not in after and "stop" not in after


def test_l_anteprima_di_un_evento_inesistente_404(mapped: TestClient, authed: TestClient) -> None:
    assert mapped.post("/api/events/fantasma/resolve").status_code == 404
    # prima si controlla l'esistenza, poi i dati: anche senza dati un evento che non c'è è un 404
    assert authed.post("/api/events/fantasma/resolve").status_code == 404


def test_l_anteprima_non_modifica_l_evento(mapped: TestClient) -> None:
    before = mapped.get("/api/events/match_2027").json()
    mapped.post("/api/events/match_2027/resolve")
    assert mapped.get("/api/events/match_2027").json() == before


# --- senza i dati ------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "params"), DATA_ENDPOINTS)
def test_senza_i_dati_503_con_il_motivo(
    authed: TestClient, method: str, path: str, params: dict[str, str]
) -> None:
    response = authed.request(method, path, params=params)
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "DATA_UNAVAILABLE"
    assert error["message"] == DATA_UNAVAILABLE_MESSAGE
    assert "make data" not in response.text and "graphml" not in response.text


@pytest.mark.parametrize(("method", "path", "params"), DATA_ENDPOINTS)
def test_senza_sessione_401(
    client: TestClient, method: str, path: str, params: dict[str, str]
) -> None:
    assert client.request(method, path, params=params).status_code == 401
