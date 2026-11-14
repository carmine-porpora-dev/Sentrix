import ast
import asyncio
import dataclasses
import json
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.operations import ACTIVE_STATES, OperationRequest
from tests.operations_support import Sleeps, make_center, make_draft
from tests.support import ctx_of, make_request, make_run

BODY: dict[str, Any] = {
    "run_id": "run_1",
    "iteration": 1,
    "type": "traffic_post",
    "target": "incrocio_1",
    "target_label": "Incrocio 1",
    "window": "departure",
    "priority": "normal",
    "simulation": True,
}


def store_request(app: FastAPI, **changes: Any) -> str:
    repo = ctx_of(app).repo
    if repo.get_run("run_1") is None:
        repo.add_run(make_run("run_1"))
    request = make_request(**changes)
    repo.add_operation_request(request)
    return request.action_id


# --- registro --------------------------------------------------------------------------------


def test_registro_dei_quattro_dipartimenti_virtuali(authed: TestClient) -> None:
    body = authed.get("/api/vdept").json()
    departments = {d["id"]: d for d in body["departments"]}
    assert set(departments) == {
        "traffic_control",
        "municipal_police",
        "transport_control",
        "public_comms",
    }
    for department in departments.values():
        assert department["label"].endswith("(virtuale)")
        assert department["endpoint"] == f"internal://{department['id']}"  # nessun ente reale
    assert body["resources"] == []


def test_registro_con_run_sconosciuto_404(authed: TestClient) -> None:
    assert authed.get("/api/vdept", params={"run_id": "fantasma"}).status_code == 404


def test_registro_con_un_run_da_le_risorse_dell_evento_e_i_consumi(
    app: FastAPI, authed: TestClient
) -> None:
    repo = ctx_of(app).repo
    repo.add_run(make_run("run_1"))
    before = authed.get("/api/vdept", params={"run_id": "run_1"}).json()["resources"]
    police = [r for r in before if (r["resource"], r["window"]) == ("patrols", "departure")]
    assert police == [
        {
            "department": "municipal_police",
            "window": "departure",
            "resource": "patrols",
            "total": 6,
            "used": 5,
            "remaining": 1,
        }
    ]
    assert len(before) == 8
    repo.add_operation_request(make_request("act_1", state="ACCEPTED"))  # un presidio in vigore
    after = authed.get("/api/vdept", params={"run_id": "run_1"}).json()["resources"]
    assert [r["remaining"] for r in after if r["resource"] == "patrols"] == [
        0,
        3,
    ]  # partenza, poi arrivo
    repo.add_run(make_run("run_2"))  # un altro run riparte dalle risorse dell'Evento
    other = authed.get("/api/vdept", params={"run_id": "run_2"}).json()["resources"]
    assert [r["remaining"] for r in other if r["resource"] == "patrols"] == [1, 3]


# --- creazione di una richiesta ----------------------------------------------------------------


def test_creazione_valida_da_una_richiesta_created_con_la_sua_storia(
    app: FastAPI, authed: TestClient
) -> None:
    ctx_of(app).repo.add_run(make_run("run_1"))
    response = authed.post("/api/vdept/municipal_police/requests", json=BODY)
    assert response.status_code == 201
    view = response.json()
    request = view["request"]
    assert request["action_id"] == "act_1_001" and request["state"] == "CREATED"
    assert request["department"] == "municipal_police" and request["simulation"] is True
    assert [(e["from_state"], e["to_state"]) for e in view["events"]] == [(None, "CREATED")]
    again = authed.get(f"/api/vdept/municipal_police/requests/{request['action_id']}").json()
    assert again == view  # quello che si crea è quello che si rilegge
    second = authed.post("/api/vdept/municipal_police/requests", json=BODY).json()
    assert second["request"]["action_id"] == "act_1_002"


def test_la_richiesta_creata_non_parte_da_sola(app: FastAPI, authed: TestClient) -> None:
    ctx_of(app).repo.add_run(make_run("run_1"))
    authed.post("/api/vdept/municipal_police/requests", json=BODY)
    assert ctx_of(app).repo.list_decisions("run_1") == []  # nessun invio, nessuna decisione


def test_creazione_su_un_run_sconosciuto_404(authed: TestClient) -> None:
    response = authed.post("/api/vdept/municipal_police/requests", json=BODY)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Run non trovato"


def test_un_alternativa_a_una_richiesta_non_rifiutata_400(app: FastAPI, authed: TestClient) -> None:
    ctx_of(app).repo.add_run(make_run("run_1"))
    first = authed.post("/api/vdept/municipal_police/requests", json=BODY).json()["request"]
    response = authed.post(
        "/api/vdept/traffic_control/requests",
        json={**BODY, "type": "signal_plan_change", "alternative_of": first["action_id"]},
    )
    assert response.status_code == 400
    field = response.json()["error"]["details"]["fields"][0]
    assert field["path"] == "alternative_of" and field["type"] == "invalid_alternative"


def test_simulation_e_obbligatorio_e_vero(app: FastAPI, authed: TestClient) -> None:
    without = {k: v for k, v in BODY.items() if k != "simulation"}
    for bad in (
        without,
        {**BODY, "simulation": False},
        {**BODY, "simulation": 0},
        {**BODY, "simulation": "true"},
        {**BODY, "simulation": None},
    ):
        response = authed.post("/api/vdept/municipal_police/requests", json=bad)
        assert response.status_code == 400, bad
        fields = response.json()["error"]["details"]["fields"]
        assert fields[0]["path"] == "simulation"
    ctx_of(app).repo.add_run(make_run("run_1"))  # niente è stato scritto in nessun caso
    with ctx_of(app).repo._connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM operation_requests").fetchone()[0] == 0


def test_dipartimento_sconosciuto_404(authed: TestClient) -> None:
    assert authed.post("/api/vdept/ente_reale/requests", json=BODY).status_code == 404


def test_un_dipartimento_gestisce_solo_i_suoi_tipi(authed: TestClient) -> None:
    response = authed.post(
        "/api/vdept/public_comms/requests", json={**BODY, "type": "traffic_post"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"][0]["path"] == "type"


@pytest.mark.parametrize(
    "extra",
    [
        {"action_id": "x"},
        {"state": "ACCEPTED"},
        {"department": "public_comms"},
        {"reject_code": "X"},
    ],
)
def test_il_corpo_non_porta_i_campi_del_server(authed: TestClient, extra: dict[str, str]) -> None:
    response = authed.post("/api/vdept/municipal_police/requests", json={**BODY, **extra})
    assert response.status_code == 400  # identificativo, dipartimento ed esito li decide il server


# --- lettura e risposta manuale --------------------------------------------------------------


def test_lettura_di_una_richiesta(app: FastAPI, authed: TestClient) -> None:
    store_request(app)
    response = authed.get("/api/vdept/municipal_police/requests/act_1")
    assert response.status_code == 200
    view = response.json()
    assert view["request"]["action_id"] == "act_1" and view["request"]["simulation"] is True
    assert [(e["from_state"], e["to_state"]) for e in view["events"]] == [(None, "RECEIVED")]


def test_una_richiesta_si_legge_solo_dal_suo_dipartimento(app: FastAPI, authed: TestClient) -> None:
    store_request(app)
    assert authed.get("/api/vdept/public_comms/requests/act_1").status_code == 404
    assert authed.get("/api/vdept/municipal_police/requests/fantasma").status_code == 404


MANUAL_ACCEPT = {"decision": "accept"}
MANUAL_REJECT = {"decision": "reject", "reject_code": "UNAVAILABLE", "reject_reason": "esaurite"}


def test_risposta_manuale_solo_se_in_received(app: FastAPI, authed: TestClient) -> None:
    for state in ("CREATED", "SENT", "ACCEPTED", "IN_PROGRESS", "COMPLETED"):
        action = f"act_{state.lower()}"
        store_request(app, action_id=action, state=state)
        response = authed.post(
            f"/api/vdept/municipal_police/requests/{action}/manual-response", json=MANUAL_ACCEPT
        )
        assert response.status_code == 409, state
        assert response.json()["error"]["details"] == {"state": state}
    store_request(
        app, action_id="act_rej", state="REJECTED", reject_code="X", reject_reason="motivo"
    )
    path = "/api/vdept/municipal_police/requests/act_rej/manual-response"
    assert authed.post(path, json=MANUAL_ACCEPT).status_code == 409


def test_una_richiesta_ricevuta_ma_non_inviata_con_la_risposta_manuale_e_409(
    app: FastAPI, authed: TestClient
) -> None:
    store_request(app, action_id="act_ok", state="RECEIVED")  # nessun invio la sta aspettando
    path = "/api/vdept/municipal_police/requests/act_ok/manual-response"
    for body in (MANUAL_ACCEPT, MANUAL_REJECT):
        response = authed.post(path, json=body)
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "NOT_AWAITING_RESPONSE"
        assert "non è attiva" in error["message"] and error["details"] == {"state": "RECEIVED"}
    stored = ctx_of(app).repo.get_operation_request("act_ok")
    assert stored is not None and stored.state == "RECEIVED"  # niente è cambiato


@pytest.fixture
def waiting(app: FastAPI) -> Iterator[Callable[[], tuple[str, Future[OperationRequest]]]]:
    """Un invio con la risposta manuale in attesa, su un altro thread (com'è nell'applicazione:
    l'orchestratore gira in un ciclo, l'endpoint su un altro thread)."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    ctx = ctx_of(app)
    sleeps = Sleeps()
    center = make_center(ctx.repo, sleeps, ctx.registry)
    app.state.ctx = dataclasses.replace(ctx, operations=center)
    ctx.repo.add_run(make_run("run_1"))

    def start() -> tuple[str, Future[OperationRequest]]:
        action = center.create(make_draft(target_label=f"Incrocio {time.monotonic_ns()}")).action_id
        future = asyncio.run_coroutine_threadsafe(center.dispatch(action, manual=True), loop)
        for _ in range(500):  # fino a 5 s: aspetta che la richiesta sia arrivata a RECEIVED
            stored = ctx.repo.get_operation_request(action)
            if stored is not None and stored.state == "RECEIVED":
                return action, future
            time.sleep(0.01)
        raise AssertionError("la richiesta non è arrivata a RECEIVED")

    yield start
    asyncio.run_coroutine_threadsafe(center.settle(), loop).result(timeout=5)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def test_risposta_manuale_accetta_l_invio_che_aspettava(
    app: FastAPI, authed: TestClient, waiting: Callable[[], tuple[str, Future[OperationRequest]]]
) -> None:
    action, future = waiting()
    response = authed.post(
        f"/api/vdept/municipal_police/requests/{action}/manual-response", json=MANUAL_ACCEPT
    )
    assert response.status_code == 200
    view = response.json()
    assert view["request"]["state"] == "ACCEPTED"
    assert [e["to_state"] for e in view["events"]][-1] == "ACCEPTED"
    assert future.result(timeout=5).state == "ACCEPTED"  # e chi aspettava ha avuto l'esito
    decisions = ctx_of(app).repo.list_decisions("run_1")
    assert [d.actor for d in decisions] == ["orchestrator", "user"]


def test_risposta_manuale_rifiuta_con_il_codice_e_il_motivo_dell_utente(
    app: FastAPI, authed: TestClient, waiting: Callable[[], tuple[str, Future[OperationRequest]]]
) -> None:
    action, future = waiting()
    response = authed.post(
        f"/api/vdept/municipal_police/requests/{action}/manual-response", json=MANUAL_REJECT
    )
    assert response.status_code == 200
    request = response.json()["request"]
    assert (request["state"], request["reject_code"], request["reject_reason"]) == (
        "REJECTED",
        "UNAVAILABLE",
        "esaurite",
    )
    assert future.result(timeout=5).state == "REJECTED"
    assert ctx_of(app).repo.list_decisions("run_1")[-1].actor == "user"


def test_accettare_oltre_le_risorse_e_409_e_si_puo_ancora_rifiutare(
    app: FastAPI, authed: TestClient, waiting: Callable[[], tuple[str, Future[OperationRequest]]]
) -> None:
    """Match 2027: una pattuglia libera. La prima accettazione passa, la seconda no (la regola del
    dipartimento vale anche a mano): 409 con il motivo, la richiesta resta in attesa."""
    first, future_1 = waiting()
    second, future_2 = waiting()
    path = "/api/vdept/municipal_police/requests/{}/manual-response"
    assert authed.post(path.format(first), json=MANUAL_ACCEPT).status_code == 200
    blocked = authed.post(path.format(second), json=MANUAL_ACCEPT)
    assert blocked.status_code == 409
    error = blocked.json()["error"]
    assert error["code"] == "ACCEPT_NOT_ALLOWED"
    assert error["details"] == {"reject_code": "UNAVAILABLE"}
    assert error["message"] == (
        "Non si può accettare: Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, "
        "6 già impegnate ai varchi. La richiesta si può rifiutare."
    )
    stored = ctx_of(app).repo.get_operation_request(second)
    assert stored is not None and stored.state == "RECEIVED"  # il tentativo non ha cambiato niente
    assert not future_2.done()  # e chi aspettava la risposta aspetta ancora
    rejected = authed.post(path.format(second), json=MANUAL_REJECT)
    assert rejected.status_code == 200 and rejected.json()["request"]["state"] == "REJECTED"
    assert future_1.result(timeout=5).state == "ACCEPTED"
    assert future_2.result(timeout=5).state == "REJECTED"


def test_una_seconda_risposta_e_409(
    authed: TestClient, waiting: Callable[[], tuple[str, Future[OperationRequest]]]
) -> None:
    action, future = waiting()
    path = f"/api/vdept/municipal_police/requests/{action}/manual-response"
    assert authed.post(path, json=MANUAL_ACCEPT).status_code == 200
    again = authed.post(path, json=MANUAL_REJECT)
    assert again.status_code == 409
    assert again.json()["error"]["details"]["state"] in ACTIVE_STATES  # già in vigore, e avanza
    future.result(timeout=5)


def test_la_risposta_e_del_dipartimento_della_richiesta(
    authed: TestClient, waiting: Callable[[], tuple[str, Future[OperationRequest]]]
) -> None:
    action, future = waiting()
    assert (
        authed.post(
            f"/api/vdept/public_comms/requests/{action}/manual-response", json=MANUAL_ACCEPT
        ).status_code
        == 404
    )
    authed.post(
        f"/api/vdept/municipal_police/requests/{action}/manual-response", json=MANUAL_ACCEPT
    )
    future.result(timeout=5)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"decision": "forse"},
        {"decision": "reject"},
        {"decision": "reject", "reject_code": "X"},
        {"decision": "reject", "reject_code": " ", "reject_reason": "motivo"},
        {"decision": "accept", "reject_code": "X"},
        {"decision": "accept", "reject_reason": "x"},
    ],
)
def test_risposta_manuale_non_valida_400(app: FastAPI, authed: TestClient, body: object) -> None:
    store_request(app)
    path = "/api/vdept/municipal_police/requests/act_1/manual-response"
    assert authed.post(path, json=body).status_code == 400


def test_risposta_manuale_a_richiesta_inesistente_404(authed: TestClient) -> None:
    path = "/api/vdept/municipal_police/requests/fantasma/manual-response"
    assert authed.post(path, json=MANUAL_ACCEPT).status_code == 404


# --- principio 3: nessun contatto con l'esterno ----------------------------------------------


def test_il_modulo_dei_dipartimenti_non_importa_client_http() -> None:
    source = Path(__file__).resolve().parents[2] / "app" / "api" / "vdept.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    forbidden = {"httpx", "httpx2", "requests", "urllib", "http", "socket", "aiohttp", "urllib3"}
    assert not imported & forbidden


def test_nessuna_risposta_contiene_indirizzi_esterni(authed: TestClient) -> None:
    text = json.dumps(authed.get("/api/vdept").json())
    assert "http://" not in text and "https://" not in text
