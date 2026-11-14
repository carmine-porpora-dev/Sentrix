import json
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.data.paths import REPO_ROOT
from app.data.seeds import read_seed_events
from app.models.api import ErrorResponse
from app.models.notifications import NotificationDraft
from tests.support import ctx_of, make_request, make_run

OPENAPI = json.loads((REPO_ROOT / "docs" / "spec" / "openapi.json").read_text(encoding="utf-8"))
OPERATIONS = {
    op["operationId"]: (method.upper(), path, op)
    for path, methods in OPENAPI["paths"].items()
    for method, op in methods.items()
}
PARAMS = {
    "event_id": "match_2027",
    "run_id": "run_1",
    "layer": "edges_vc",
    "dept_id": "municipal_police",
    "action_id": "act_1",
    "notification_id": "1",
}
BBOX = {"bbox": "14.2275,40.8295,14.2450,40.8365"}


def event_body(event_id: str) -> dict[str, Any]:
    seed = next(e for e in read_seed_events() if e.id == "match_2027")
    body = seed.model_dump(mode="json", exclude={"revision", "created_at", "updated_at"})
    return {**body, "id": event_id}


DRAFT = {
    "run_id": "run_1", "iteration": 1, "type": "traffic_post", "target": "incrocio_1",
    "target_label": "Incrocio 1", "window": "departure", "priority": "normal", "simulation": True,
}  # fmt: skip

# (nome del caso, operazione, parametri della chiamata). Un caso per operazione, più le varianti
# che cambiano il percorso nel codice (esportazione CSV, risorse di un run).
CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("health", "health", {}),
    ("login", "login", {"json": {"password": "fake-app-password"}}),
    ("logout", "logout", {}),
    ("me", "me", {}),
    ("list_events", "list_events", {}),
    ("get_event", "get_event", {}),
    ("create_event", "create_event", {"json": event_body("contratto_1")}),
    ("update_event", "update_event", {"json": event_body("match_2027")}),
    ("reset_event", "reset_event", {}),
    ("resolve_event", "resolve_event", {}),
    ("network_edges", "network_edges", {"params": BBOX}),
    ("transit_stops", "transit_stops", {"params": BBOX}),
    ("transit_lines", "transit_lines", {}),
    ("pmtiles", "pmtiles", {}),  # nel database di prova il file non c'è: 404 dichiarato
    ("create_run", "create_run", {"json": {"event_id": "match_2027", "attendance_level": "mid"}}),
    ("list_runs", "list_runs", {}),
    ("get_run", "get_run", {}),
    ("run_metrics", "run_metrics", {"params": {"iteration": 0}}),
    ("run_layer", "run_layer", {"params": {"iteration": 0}}),
    ("run_decisions", "run_decisions", {}),
    ("run_notifications", "run_notifications", {}),
    ("ack_notification", "ack_notification", {}),
    ("export_run", "export_run", {}),
    ("export_run_csv", "export_run", {"params": {"format": "csv", "what": "metrics"}}),
    ("vdept_registry", "vdept_registry", {}),
    ("vdept_registry_run", "vdept_registry", {"params": {"run_id": "run_1"}}),
    ("create_vdept_request", "create_vdept_request", {"json": DRAFT}),
    ("get_vdept_request", "get_vdept_request", {}),
    ("manual_response", "manual_response", {"json": {"decision": "accept"}}),
    ("live_flow", "live_flow", {"headers": {"X-View": "live"}}),
    ("list_sensors", "list_sensors", {}),
]


def test_i_casi_coprono_tutte_le_operazioni_del_contratto(app: FastAPI) -> None:
    assert app.openapi() == OPENAPI  # il contratto salvato è quello dell'app che si prova
    assert {operation for _, operation, _ in CASES} == set(OPERATIONS)
    assert len(OPERATIONS) == 29 and len({name for name, _, _ in CASES}) == len(CASES)


@pytest.fixture
def prepared(app: FastAPI, authed: TestClient) -> TestClient:
    repo = ctx_of(app).repo
    repo.add_run(make_run("run_1"))
    repo.add_operation_request(make_request("act_1", state="RECEIVED"))
    repo.add_notification(  # il bollettino che `ack_notification` conferma (id 1)
        NotificationDraft(
            run_id="run_1",
            iteration=1,
            channel="emergency_bulletin",
            recipient_id="questura",
            recipient_label="Questura",
            kind="traffic_bulletin",
            text="prova",
            state="SENT",
            simulation=True,
        ),
        then=("DELIVERED",),
    )
    return authed


@pytest.mark.parametrize(("name", "operation", "call"), CASES, ids=[c[0] for c in CASES])
def test_ogni_operazione_risponde_come_dichiara_il_contratto(
    prepared: TestClient, name: str, operation: str, call: dict[str, Any]
) -> None:
    method, template, declared = OPERATIONS[operation]
    path = re.sub(r"\{(\w+)\}", lambda m: PARAMS[m.group(1)], template)
    response = prepared.request(method, path, **call)

    assert response.status_code != 500, response.text
    assert str(response.status_code) in declared["responses"], (
        f"{name}: {response.status_code} non è dichiarato ({sorted(declared['responses'])})"
    )
    if response.status_code >= 400:
        error = ErrorResponse.model_validate(response.json()).error  # formato comune di 06
        assert error.code == error.code.upper() and error.message
        if response.status_code == 429:
            assert "retry-after" in response.headers
    elif response.headers["content-type"].startswith("application/json"):
        assert response.json() is not None  # corpo JSON valido (il modello l'ha già verificato)


def test_gli_stati_visti_sono_vari_e_nessuno_e_inatteso(prepared: TestClient) -> None:
    """Il giro completo tocca successi, errori di validazione, non trovato e dati assenti."""
    seen: set[int] = set()
    for name, operation, call in CASES:
        method, template, _ = OPERATIONS[operation]
        path = re.sub(r"\{(\w+)\}", lambda m: PARAMS[m.group(1)], template)
        seen.add(prepared.request(method, path, **call).status_code)
        if name == "logout":  # l'uscita chiude la sessione: si rientra per le chiamate dopo
            prepared.post("/api/auth/login", json={"password": "fake-app-password"})
    # 503: l'app di prova non ha i dati della mappa (grafo, feed), e lo dichiara
    assert {200, 201, 404, 503} <= seen
    assert seen <= {200, 201, 202, 400, 404, 409, 503}


def test_senza_sessione_ogni_operazione_protetta_dice_401_nel_formato_comune(
    client: TestClient,
) -> None:
    public = {"health", "login", "logout", "me"}
    for operation, (method, template, _) in OPERATIONS.items():
        if operation in public:
            continue
        path = re.sub(r"\{(\w+)\}", lambda m: PARAMS[m.group(1)], template)
        response = client.request(method, path)
        assert response.status_code == 401, operation
        assert ErrorResponse.model_validate(response.json()).error.code == "UNAUTHENTICATED"


MISSING = {key: "fantasma" for key in ("event_id", "run_id", "dept_id", "action_id")} | {
    "layer": "edges_vc",
    "notification_id": "999999",
}


def test_risorse_inesistenti_e_corpi_sbagliati_mai_500_e_sempre_nel_formato_comune(
    prepared: TestClient,
) -> None:
    """Gli stessi percorsi con id che non esistono e, dove c'è un corpo, con un corpo vuoto."""
    checked = 0
    public = {"health", "login", "logout", "me"}
    for name, operation, call in CASES:
        method, template, declared = OPERATIONS[operation]
        if operation in public or operation == "pmtiles":
            continue
        path = re.sub(r"\{(\w+)\}", lambda m: MISSING[m.group(1)], template)
        broken = {**call, **({"json": {}} if "json" in call else {})}
        response = prepared.request(method, path, **broken)
        checked += 1
        assert response.status_code != 500, (name, response.text)
        assert str(response.status_code) in declared["responses"], (name, response.status_code)
        if response.status_code >= 400:
            ErrorResponse.model_validate(response.json())
    assert checked >= 20  # le chiamate fatte davvero, non zero per sbaglio
