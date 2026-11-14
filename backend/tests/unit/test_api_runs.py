import asyncio
import csv
import io
import re
import statistics
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.runner import AgentRunner
from app.api.errors import DATA_UNAVAILABLE_MESSAGE
from app.main import create_app
from app.models.api import Feature, FeatureCollection
from app.models.provenance import Measured
from app.models.run import Run
from app.orchestrator.state_machine import Orchestrator
from app.settings import Settings
from tests.agents_support import CATALOG, CONFIG, measure
from tests.conftest import FakeClock, client_from, log_in
from tests.llm_support import make_client
from tests.operations_support import StepClock, make_center
from tests.orchestrator_support import Rig, engines_with
from tests.support import ctx_of, make_run

TWO = ((1001, "Piazza Vittoria", 1.2), (1002, "Piazza Sannazaro", 1.2))
NEW_RUN = {"event_id": "match_2027", "attendance_level": "mid", "manual_response": False}


# --- POST /api/runs --------------------------------------------------------------------------


def test_l_avvio_risponde_202_e_il_run_esiste(app: FastAPI, authed: TestClient) -> None:
    response = authed.post("/api/runs", json=NEW_RUN)
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    run = ctx_of(app).repo.get_run(run_id)
    assert run is not None
    assert (run.event_id, run.event_revision, run.attendance_level) == ("match_2027", 1, "mid")
    assert (run.llm_mode, run.seed) == ("template", 42)
    assert re.fullmatch(r"[0-9a-f]{64}", run.params_hash)


def test_run_diversi_hanno_id_diversi_e_la_stessa_impronta(
    app: FastAPI, authed: TestClient
) -> None:
    first = authed.post("/api/runs", json=NEW_RUN).json()["run_id"]
    second = authed.post("/api/runs", json=NEW_RUN).json()["run_id"]
    repo = ctx_of(app).repo
    assert first != second
    one, two = repo.get_run(first), repo.get_run(second)
    assert one is not None and two is not None and one.params_hash == two.params_hash
    other = authed.post("/api/runs", json={**NEW_RUN, "event_id": "regate_sep_2026"}).json()[
        "run_id"
    ]
    third = repo.get_run(other)
    assert third is not None and third.params_hash != one.params_hash  # un altro Evento


def test_il_run_usa_la_revisione_corrente_dell_evento(app: FastAPI, authed: TestClient) -> None:
    repo = ctx_of(app).repo
    event = repo.get_event("match_2027")
    assert event is not None
    repo.update_event(event.model_copy(update={"name": "Match 2027 (aggiornato)"}))
    run = repo.get_run(authed.post("/api/runs", json=NEW_RUN).json()["run_id"])
    assert run is not None and run.event_revision == 2


def test_senza_i_dati_dei_motori_503_e_nessun_run(
    settings: Settings, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    """Un'istanza senza grafo e feed parte lo stesso, ma non avvia analisi: lo dice, senza
    lasciare un run a metà. Il messaggio non ha percorsi del server né comandi: stanno nel log."""
    unarmed = create_app(settings, clock=clock)  # nessun motore, nessun dato in tmp_path
    with TestClient(unarmed) as c, caplog.at_level("ERROR", logger="app.api.errors"):
        log_in(c)
        response = c.post("/api/runs", json=NEW_RUN)
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "ENGINES_UNAVAILABLE"
        assert error["message"] == DATA_UNAVAILABLE_MESSAGE
        assert str(settings.data_dir) not in response.text and "make data" not in response.text
        assert ctx_of(unarmed).repo.list_runs() == []
    detail = next(r.getMessage() for r in caplog.records if r.name == "app.api.errors")
    assert "ENGINES_UNAVAILABLE" in detail and "make data" in detail


def test_evento_inesistente_404(authed: TestClient) -> None:
    response = authed.post("/api/runs", json={**NEW_RUN, "event_id": "fantasma"})
    assert response.status_code == 404


def test_manual_response_e_facoltativo(authed: TestClient) -> None:
    body = {"event_id": "match_2027", "attendance_level": "high"}
    assert authed.post("/api/runs", json=body).status_code == 202


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"event_id": "match_2027"},
        {"event_id": "match_2027", "attendance_level": "altissimo"},
        {"event_id": "Match 2027", "attendance_level": "mid"},
        {**NEW_RUN, "manual_response": "forse"},
        {**NEW_RUN, "extra": 1},
    ],
)
def test_corpo_non_valido_400(authed: TestClient, body: dict[str, object]) -> None:
    assert authed.post("/api/runs", json=body).status_code == 400


# --- limiti: 3 al minuto per sessione, 20 all'ora in tutto -----------------------------------


def test_tre_al_minuto_per_sessione(authed: TestClient, clock: FakeClock) -> None:
    assert [authed.post("/api/runs", json=NEW_RUN).status_code for _ in range(3)] == [202] * 3
    response = authed.post("/api/runs", json=NEW_RUN)
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["details"] == {"retry_after_s": 60}
    assert response.headers["retry-after"] == "60"
    clock.advance(59)
    assert authed.post("/api/runs", json=NEW_RUN).status_code == 429
    clock.advance(1)  # al sessantesimo secondo il primo è fuori dalla finestra
    assert authed.post("/api/runs", json=NEW_RUN).status_code == 202


def test_il_limite_per_sessione_non_e_per_ip(app: FastAPI, authed: TestClient) -> None:
    for _ in range(3):
        authed.post("/api/runs", json=NEW_RUN)
    other = client_from(app, "198.51.100.4")  # altra sessione, anche con altro IP
    log_in(other)
    assert other.post("/api/runs", json=NEW_RUN).status_code == 202
    same_ip = client_from(app, "testclient")  # stesso IP, altra sessione
    log_in(same_ip)
    assert same_ip.post("/api/runs", json=NEW_RUN).status_code == 202


def test_venti_all_ora_in_tutto(app: FastAPI, clock: FakeClock) -> None:
    with TestClient(app) as first:
        log_in(first)
        users = [first] + [client_from(app, f"192.0.2.{n}") for n in range(2, 8)]
        for user in users[1:]:
            log_in(user)
        statuses = []
        for user in users:  # 7 sessioni × 3 richieste = 21 tentativi nello stesso minuto
            statuses += [user.post("/api/runs", json=NEW_RUN).status_code for _ in range(3)]
        assert statuses.count(202) == 20 and statuses.count(429) == 1
        assert statuses[-1] == 429  # la ventunesima, di chiunque sia
        denied = users[-1].post("/api/runs", json=NEW_RUN)
        assert denied.status_code == 429
        assert int(denied.headers["retry-after"]) > 60  # aspetta la finestra oraria, non il minuto
        clock.advance(3600)
        assert users[0].post("/api/runs", json=NEW_RUN).status_code == 202


def test_un_rifiuto_per_il_limite_globale_non_consuma_quello_di_sessione(
    app: FastAPI, clock: FakeClock
) -> None:
    with TestClient(app) as early:
        log_in(early)
        clients = [client_from(app, f"192.0.2.{n}") for n in range(2, 9)]
        for c in clients:
            log_in(c)
        for c in clients[:6]:
            for _ in range(3):
                c.post("/api/runs", json=NEW_RUN)  # 18
        for _ in range(2):
            early.post("/api/runs", json=NEW_RUN)  # 20: il globale è pieno
        assert early.post("/api/runs", json=NEW_RUN).status_code == 429  # globale
        clock.advance(60)  # la finestra di sessione (1 minuto) si svuota, quella oraria no
        assert early.post("/api/runs", json=NEW_RUN).status_code == 429  # ancora il globale
        clock.advance(3540)  # un'ora dalla prima richiesta: il globale si libera
        for _ in range(3):
            assert early.post("/api/runs", json=NEW_RUN).status_code == 202


def test_senza_sessione_non_si_consuma_il_limite(app: FastAPI, client: TestClient) -> None:
    for _ in range(50):
        assert client.post("/api/runs", json=NEW_RUN).status_code == 401
    log_in(client)
    assert client.post("/api/runs", json=NEW_RUN).status_code == 202  # il budget è intatto


def test_anche_le_richieste_sbagliate_contano(authed: TestClient) -> None:
    for _ in range(3):
        assert authed.post("/api/runs", json={}).status_code == 400
    assert authed.post("/api/runs", json=NEW_RUN).status_code == 429


def test_i_limiti_sono_quelli_del_file_di_configurazione(
    settings: Settings, clock: FakeClock
) -> None:
    from app.models.api_config import ApiConfig

    base = ApiConfig.from_yaml()
    tight = base.model_copy(
        update={"runs_per_session": base.runs_per_session.model_copy(update={"limit": 1})}
    )
    app = create_app(settings, clock=clock, config=tight, engines=engines_with(()))
    with TestClient(app) as c:
        log_in(c)
        assert c.post("/api/runs", json=NEW_RUN).status_code == 202
        assert c.post("/api/runs", json=NEW_RUN).status_code == 429


# --- storico e lettura -----------------------------------------------------------------------


def test_storico_vuoto(authed: TestClient) -> None:
    assert authed.get("/api/runs").json() == []


def test_storico_dal_piu_recente_e_filtro_per_evento(app: FastAPI, authed: TestClient) -> None:
    repo = ctx_of(app).repo
    repo.add_run(make_run("run_a", started_at="2026-11-09T10:00:00+01:00"))
    repo.add_run(make_run("run_b", started_at="2026-11-09T12:00:00+01:00"))
    repo.add_run(
        make_run("run_c", event_id="regate_sep_2026", started_at="2026-11-09T11:00:00+01:00")
    )
    assert [r["id"] for r in authed.get("/api/runs").json()] == ["run_b", "run_c", "run_a"]
    only = authed.get("/api/runs", params={"event_id": "match_2027"}).json()
    assert [r["id"] for r in only] == ["run_b", "run_a"]
    assert authed.get("/api/runs", params={"event_id": "fantasma"}).json() == []
    assert Run.model_validate(only[0]).event_id == "match_2027"


def test_lettura_di_un_run(app: FastAPI, authed: TestClient) -> None:
    run = make_run("run_x", state="PLAN", iteration=1)
    ctx_of(app).repo.add_run(run)
    response = authed.get("/api/runs/run_x")
    assert response.status_code == 200
    view = response.json()
    assert Run.model_validate(view["run"]) == run
    # un run senza nulla di scritto: niente stati, piano né richieste, mai inventati
    assert (view["timeline"], view["plan"]) == ([], [])
    assert (view["requests"], view["degraded"]) == ([], [])
    assert [a["agent"] for a in view["agents"]] == [
        "event_demand",
        "traffic",
        "transit",
        "operations",
    ]
    assert all(a["text"] is None for a in view["agents"])


def test_run_inesistente_404_su_ogni_endpoint(authed: TestClient) -> None:
    for path in (
        "/api/runs/fantasma",
        "/api/runs/fantasma/metrics?iteration=0",
        "/api/runs/fantasma/layers/closures?iteration=0",
        "/api/runs/fantasma/decisions",
        "/api/runs/fantasma/export",
        "/api/runs/fantasma/export?format=csv&what=metrics",
    ):
        response = authed.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["message"] == "Run non trovato"


def test_lettura_del_run_sotto_i_50_ms(app: FastAPI, authed: TestClient) -> None:
    ctx_of(app).repo.add_run(make_run("run_lento"))
    for _ in range(3):
        authed.get("/api/runs/run_lento")  # a caldo
    times = []
    for _ in range(30):
        start = time.perf_counter()
        assert authed.get("/api/runs/run_lento").status_code == 200
        times.append((time.perf_counter() - start) * 1000)
    assert statistics.median(times) < 50, f"mediana {statistics.median(times):.1f} ms"


# --- un run vero, letto dall'API -------------------------------------------------------------


def finished_run(app: FastAPI, tmp: Path) -> str:
    """Un run completo (la scena di rifiuto di 04 7, motori finti, testi di riserva) scritto nel
    database dell'app con un Centro che non aspetta: l'API lo legge come qualunque altro."""
    ctx = ctx_of(app)
    ctx.repo.add_run(make_run("run_1", llm_mode="template"))
    rig = Rig(
        Orchestrator(
            repo=ctx.repo,
            center=make_center(ctx.repo),
            runner=AgentRunner(make_client(ctx.repo, None, mode="template"), CONFIG, CATALOG),
            engines=engines_with(TWO),
            config=CONFIG,
            clock=StepClock(),
        ),
        ctx.repo,
        make_center(ctx.repo),
        engines_with(TWO),
    )
    asyncio.run(rig.orchestrator.execute("run_1"))
    return "run_1"


@pytest.fixture
def run_id(app: FastAPI, tmp_path: Path) -> str:
    return finished_run(app, tmp_path)


@pytest.fixture
def empty_run_id(app: FastAPI) -> str:
    ctx_of(app).repo.add_run(make_run("run_vuoto"))
    return "run_vuoto"


def test_il_run_in_lettura_ha_timeline_agenti_piano_e_richieste(
    authed: TestClient, run_id: str
) -> None:
    view = authed.get(f"/api/runs/{run_id}").json()
    assert view["run"]["state"] == "DONE" and view["run"]["iteration"] == 2
    assert [t["state"] for t in view["timeline"]] == [
        "INTAKE",
        "ANALYZE",
        "RECONCILE",
        "PLAN",
        "DISPATCH",
        "AWAIT",
        "VERIFY",
        "REPLAN",
        "DISPATCH",
        "AWAIT",
        "VERIFY",
        "DONE",
    ]
    assert [(a["agent"], a["state"]) for a in view["agents"]] == [
        ("event_demand", "done_fallback"),
        ("traffic", "done_fallback"),
        ("transit", "done_fallback"),
        ("operations", "done_fallback"),
    ]
    traffic = view["agents"][1]
    assert traffic["text_origin"] == "template" and traffic["tools_called"][0] == "apply_closures"
    assert traffic["findings"][0]["trigger"] == "critical_intersection"
    assert [p["status"] for p in view["plan"]] == ["accepted", "replaced", "accepted"]
    requests = view["requests"]
    assert [r["request"]["type"] for r in requests] == [
        "traffic_post",
        "traffic_post",
        "signal_plan_change",
        "citizen_notice",
    ]
    assert requests[1]["request"]["state"] == "REJECTED"
    assert [e["to_state"] for e in requests[1]["events"]] == [
        "CREATED",
        "SENT",
        "RECEIVED",
        "REJECTED",
    ]
    assert view["degraded"] == []  # in modalità template i testi di riserva non sono un guasto


def test_un_run_appena_creato_ha_gli_agenti_in_attesa(
    authed: TestClient, empty_run_id: str
) -> None:
    view = authed.get(f"/api/runs/{empty_run_id}").json()
    assert view["timeline"] == [] and view["plan"] == [] and view["requests"] == []
    assert {a["state"] for a in view["agents"]} == {"waiting"}
    assert all(a["text"] is None and a["findings"] == [] for a in view["agents"])


@pytest.mark.parametrize(
    ("state", "running"),
    [
        ("ANALYZE", {"event_demand", "traffic", "transit"}),
        ("PLAN", {"operations"}),
        ("VERIFY", set()),
    ],
)
def test_gli_agenti_che_lavorano_dipendono_dallo_stato(
    app: FastAPI, authed: TestClient, state: str, running: set[str]
) -> None:
    ctx_of(app).repo.add_run(make_run("run_x", state=state))
    agents = authed.get("/api/runs/run_x").json()["agents"]
    assert {a["agent"] for a in agents if a["state"] == "running"} == running


def test_un_run_in_errore_ha_gli_agenti_senza_risultato_in_errore(
    app: FastAPI, authed: TestClient
) -> None:
    ctx_of(app).repo.add_run(
        make_run(
            "run_err",
            state="ERROR",
            error="Motore non disponibile",
            ended_at="2026-11-09T10:01:00+01:00",
        )
    )
    agents = authed.get("/api/runs/run_err").json()["agents"]
    assert {a["state"] for a in agents} == {"error"}


def test_le_metriche_dell_iterazione_zero_non_hanno_delta(authed: TestClient, run_id: str) -> None:
    body = authed.get(f"/api/runs/{run_id}/metrics", params={"iteration": 0}).json()
    assert body["run_id"] == run_id and body["iteration"] == 0 and body["deltas"] == []
    ids = [m["id"] for m in body["metrics"]]
    assert any(i.endswith(".event.attendance") for i in ids)
    assert all(
        m["kind"] in ("real", "estimate", "simulated") and m["source"] for m in body["metrics"]
    )


def test_i_delta_sono_numeri_con_la_loro_provenienza(authed: TestClient, run_id: str) -> None:
    body = authed.get(f"/api/runs/{run_id}/metrics", params={"iteration": 2}).json()
    assert body["iteration"] == 2 and body["deltas"]
    delta = next(d for d in body["deltas"] if d["metric_id"].endswith(".road.departure.veh_hours"))
    previous, baseline = delta["vs_previous"], delta["vs_baseline"]
    # i motori finti rispondono sempre con gli stessi id (iterazione 0): il delta porta comunque
    # l'iterazione richiesta
    assert delta["metric_id"] == "m.run_1.it0.road.departure.veh_hours"
    assert previous["id"] == "m.run_1.it2.delta.prev.road.departure.veh_hours"
    assert baseline["id"] == "m.run_1.it2.delta.base.road.departure.veh_hours"
    assert previous["value"] == 0 and previous["source"] == "orchestrator.delta v1"
    assert previous["inputs"] == [delta["metric_id"], delta["metric_id"]]
    assert previous["unit"] == "veic·h" and previous["kind"] == "simulated"
    assert "meno" in previous["method"] and previous["assumptions"]


def put(app: FastAPI, iteration: int, *measures: Measured) -> None:
    ctx_of(app).repo.put_metrics("run_vuoto", iteration, measures)


def test_i_delta_hanno_il_valore_la_differenza_e_il_tipo_dei_due_numeri(
    app: FastAPI, authed: TestClient
) -> None:
    ctx_of(app).repo.add_run(make_run("run_vuoto", state="VERIFY", iteration=2))
    put(
        app,
        0,
        measure(("road", "departure", "veh_hours"), 4820.0, "veic·h", it=0),
        measure(("road", "departure", "od_time.mean"), 38.4, "min", "estimate", it=0),
    )
    put(
        app,
        1,
        measure(("road", "departure", "veh_hours"), 4000.0, "veic·h", it=1),
        measure(("road", "departure", "od_time.mean"), 40.0, "min", "simulated", it=1),
    )
    put(
        app,
        2,
        measure(("road", "departure", "veh_hours"), 4500.5, "veic·h", it=2),
        measure(("road", "departure", "od_time.mean"), 39.9, "min", "simulated", it=2),
    )
    body = authed.get("/api/runs/run_vuoto/metrics", params={"iteration": 2}).json()
    veh, od = body["deltas"]
    assert (veh["vs_previous"]["value"], veh["vs_baseline"]["value"]) == (500.5, -319.5)
    assert veh["vs_previous"]["kind"] == "simulated" and veh["vs_previous"]["unit"] == "veic·h"
    assert veh["vs_previous"]["inputs"] == [
        "m.run_1.it2.road.departure.veh_hours",
        "m.run_1.it1.road.departure.veh_hours",
    ]
    assert veh["vs_baseline"]["inputs"][1] == "m.run_1.it0.road.departure.veh_hours"
    assert (od["vs_previous"]["value"], od["vs_baseline"]["value"]) == (-0.1, 1.5)
    assert od["vs_previous"]["kind"] == "simulated"  # entrambi simulati
    assert od["vs_baseline"]["kind"] == "estimate"  # un dato stimato e uno simulato: stima
    first = authed.get("/api/runs/run_vuoto/metrics", params={"iteration": 1}).json()["deltas"][0]
    assert first["vs_previous"]["value"] == first["vs_baseline"]["value"] == -820.0


def test_gli_archi_critici_del_csv_sono_quelli_aperti_oltre_la_soglia_dal_piu_carico(
    app: FastAPI, authed: TestClient
) -> None:
    ctx = ctx_of(app)
    ctx.repo.add_run(
        make_run("run_vuoto", state="DONE", iteration=1, ended_at="2026-11-09T11:00:00+01:00")
    )

    def edge(key: str, vc: float, closed: bool = False, name: str | None = None) -> Feature:
        props = {"edge_key": key, "vc": vc, "closed": closed, "length_m": 100.0, "name": name}
        return Feature(id=key, geometry=None, properties=props)

    ctx.repo.put_layer(
        "run_vuoto", 0, "edges_vc", FeatureCollection(features=[edge("a", 0.9), edge("b", 0.95)])
    )
    ctx.repo.put_layer(
        "run_vuoto",
        1,
        "edges_vc",
        FeatureCollection(
            features=[
                edge("c", 1.2, name="=Via"),
                edge("d", 1.5, closed=True),
                edge("a", 1.2),
                edge("e", 1.3),
            ]
        ),
    )
    text = authed.get(
        "/api/runs/run_vuoto/export", params={"format": "csv", "what": "critical_edges"}
    ).text
    rows = [r for r in csv.reader(io.StringIO(text))][1:]
    assert [(r[0], r[1]) for r in rows] == [("0", "b"), ("1", "e"), ("1", "a"), ("1", "c")]
    assert rows[3][2] == "'=Via"  # un nome non diventa una formula
    assert rows[0][3:] == ["0.95", "100.0"]


@pytest.mark.parametrize(("mode", "degraded"), [("live", ["llm_fallback"]), ("template", [])])
def test_i_testi_di_riserva_sono_un_degrado_solo_se_l_llm_era_atteso(
    app: FastAPI, authed: TestClient, run_id: str, mode: str, degraded: list[str]
) -> None:
    ctx = ctx_of(app)
    ctx.repo.add_run(make_run("run_mode", llm_mode=mode))
    for result in ctx.repo.list_agent_results(run_id):
        ctx.repo.add_agent_result(result.model_copy(update={"run_id": "run_mode"}))
    assert authed.get("/api/runs/run_mode").json()["degraded"] == degraded


def test_il_riepilogo_di_operations_e_l_ultimo_risultato(authed: TestClient, run_id: str) -> None:
    operations = authed.get(f"/api/runs/{run_id}").json()["agents"][3]
    assert operations["text"].startswith("Rifiutata la richiesta di presidio stradale")  # il REPLAN
    assert operations["tools_called"] == ["list_alternatives_for_measure", "get_request_status"]


def test_i_delta_non_ci_sono_per_i_testi_e_per_le_metriche_nuove(
    authed: TestClient, run_id: str
) -> None:
    body = authed.get(f"/api/runs/{run_id}/metrics", params={"iteration": 1}).json()
    covered = {d["metric_id"] for d in body["deltas"]}
    texts = {m["id"] for m in body["metrics"] if isinstance(m["value"], str)}
    assert texts and not texts & covered
    assert not any(".event." in i for i in covered)  # la domanda esiste solo all'iterazione 0


def test_un_iterazione_non_ancora_calcolata_404(authed: TestClient, run_id: str) -> None:
    for path in ("metrics", "layers/closures"):
        response = authed.get(f"/api/runs/{run_id}/{path}", params={"iteration": 3})
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "L'iterazione 3 non è ancora calcolata"


@pytest.mark.parametrize("path", ["metrics", "layers/closures"])
def test_l_iterazione_zero_e_calcolata_solo_quando_ha_le_metriche(
    app: FastAPI, authed: TestClient, empty_run_id: str, path: str
) -> None:
    """Finché il run analizza, la 0 c'è già per `run.iteration` ma non ha nulla: un 200 vuoto
    verrebbe letto come «nessuna metrica» e tenuto, quindi è un 404 (e l'interfaccia riprova)."""
    url = f"/api/runs/{empty_run_id}/{path}"
    response = authed.get(url, params={"iteration": 0})
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "L'iterazione 0 non è ancora calcolata"
    ctx_of(app).repo.put_metrics(
        empty_run_id, 0, [measure(("road", "departure", "veh_hours"), 4820.0, "veic·h")]
    )
    assert authed.get(url, params={"iteration": 0}).status_code == 200


def test_un_iterazione_contata_ma_senza_metriche_e_ancora_404(
    app: FastAPI, authed: TestClient, empty_run_id: str
) -> None:
    """Tra l'aggiornamento di `run.iteration` e il salvataggio dei risultati (VERIFY)."""
    repo = ctx_of(app).repo
    repo.put_metrics(
        empty_run_id, 0, [measure(("road", "departure", "veh_hours"), 4820.0, "veic·h")]
    )
    repo.update_run(empty_run_id, iteration=1)
    assert (
        authed.get(f"/api/runs/{empty_run_id}/metrics", params={"iteration": 0}).status_code == 200
    )
    one = authed.get(f"/api/runs/{empty_run_id}/metrics", params={"iteration": 1})
    assert one.status_code == 404
    layer = authed.get(f"/api/runs/{empty_run_id}/layers/edges_vc", params={"iteration": 1})
    assert layer.status_code == 404


def test_i_livelli_dell_iterazione_hanno_le_finestre_unite(authed: TestClient, run_id: str) -> None:
    layer = authed.get(f"/api/runs/{run_id}/layers/critical_intersections", params={"iteration": 0})
    features = layer.json()["features"]
    assert layer.status_code == 200 and layer.json()["type"] == "FeatureCollection"
    assert [(f["id"], f["properties"]["window"]) for f in features] == [
        ("departure:1001", "departure"),
        ("departure:1002", "departure"),
    ]


@pytest.mark.parametrize(
    "layer",
    [
        "edges_vc",
        "closures",
        "critical_intersections",
        "stops",
        "sections",
        "event_area",
        "requests",
    ],
)
def test_i_sette_livelli_si_leggono(authed: TestClient, run_id: str, layer: str) -> None:
    response = authed.get(f"/api/runs/{run_id}/layers/{layer}", params={"iteration": 1})
    assert response.status_code == 200 and response.json()["type"] == "FeatureCollection"


def test_un_livello_che_il_motore_non_ha_prodotto_e_vuoto(authed: TestClient, run_id: str) -> None:
    body = authed.get(f"/api/runs/{run_id}/layers/closures", params={"iteration": 1}).json()
    assert body == {"type": "FeatureCollection", "features": []}


def test_ogni_numero_di_un_popup_ha_provenienza(authed: TestClient, run_id: str) -> None:
    """Ogni feature di `edges_vc`, `stops` e `sections` dichiara da quale `Measured` viene il suo
    numero, e quel `Measured` esiste tra le metriche della stessa iterazione."""
    for iteration in (0, 1, 2):
        known = {
            m["id"]
            for m in authed.get(
                f"/api/runs/{run_id}/metrics", params={"iteration": iteration}
            ).json()["metrics"]
        }
        for layer in ("edges_vc", "stops", "sections"):
            body = authed.get(
                f"/api/runs/{run_id}/layers/{layer}", params={"iteration": iteration}
            ).json()
            for feature in body["features"]:
                assert feature["properties"]["evidence_id"] in known, (
                    iteration,
                    layer,
                    feature["id"],
                )
    edges = authed.get(f"/api/runs/{run_id}/layers/edges_vc", params={"iteration": 0}).json()
    by_id = {f["id"]: f["properties"]["evidence_id"] for f in edges["features"]}
    assert by_id["departure:9-1001-0"].endswith(".road.departure.critical_edges.count")


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs/run_1/layers/inventato?iteration=0",
        "/api/runs/run_1/layers/closures",  # iteration obbligatorio: nessun default inventato
        "/api/runs/run_1/layers/closures?iteration=-1",
        "/api/runs/run_1/metrics",
        "/api/runs/run_1/metrics?iteration=-1",
        "/api/runs/run_1/export?format=xml",
        "/api/runs/run_1/export?format=csv",  # manca `what`
        "/api/runs/run_1/export?format=csv&what=altro",
    ],
)
def test_parametri_non_validi_400(authed: TestClient, run_id: str, path: str) -> None:
    assert authed.get(path).status_code == 400


def test_l_esportazione_json_ha_evento_run_piano_richieste_decisioni_e_metriche(
    authed: TestClient, run_id: str
) -> None:
    body = authed.get(f"/api/runs/{run_id}/export").json()
    assert body["event"]["id"] == "match_2027" and body["run"]["id"] == run_id
    assert [p["status"] for p in body["plan"]] == ["accepted", "replaced", "accepted"]
    assert len(body["requests"]) == 4 and body["requests"][0]["events"]
    assert body["decisions"][0]["decision"] == "Passo a INTAKE"
    assert [m["iteration"] for m in body["metrics"]] == [0, 1, 2]
    assert all(m["metrics"] for m in body["metrics"])
    assert authed.get(f"/api/runs/{run_id}/export", params={"format": "json"}).json() == body


def test_la_revisione_dell_evento_esportata_e_quella_del_run(
    app: FastAPI, authed: TestClient, run_id: str
) -> None:
    ctx = ctx_of(app)
    event = ctx.repo.get_event("match_2027")
    assert event is not None
    ctx.repo.update_event(event.model_copy(update={"name": "Un altro nome"}))  # revisione 2
    assert authed.get(f"/api/runs/{run_id}/export").json()["event"]["name"] == event.name


def test_l_esportazione_csv_delle_metriche(authed: TestClient, run_id: str) -> None:
    response = authed.get(f"/api/runs/{run_id}/export", params={"format": "csv", "what": "metrics"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="{run_id}_metrics.csv"'
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == [
        "iteration",
        "metric_id",
        "value",
        "unit",
        "kind",
        "source",
        "method",
        "as_of",
    ]
    assert {r[0] for r in rows[1:]} == {"0", "1", "2"}
    assert any(r[1].endswith(".event.attendance") for r in rows[1:])


def test_l_esportazione_csv_degli_archi_critici(
    app: FastAPI, authed: TestClient, run_id: str
) -> None:
    response = authed.get(
        f"/api/runs/{run_id}/export", params={"format": "csv", "what": "critical_edges"}
    )
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["iteration", "edge_key", "name", "vc", "length_m"]
    first = [r for r in rows[1:] if r[0] == "0"]
    assert [r[1] for r in first] == ["departure:9-1001-0", "departure:9-1002-0"] or [
        r[1] for r in first
    ]
    assert all(float(r[3]) > 0.9 for r in rows[1:])  # solo oltre la soglia critica


# --- avvio vero, fino in fondo ------------------------------------------------------------------


def test_un_run_avviato_dall_api_arriva_a_done(settings: Settings, clock: FakeClock) -> None:
    """Dall'avvio alla fine, con i ritardi veri dei dipartimenti (1,5 s): il polling li vede."""
    app = create_app(settings, clock=clock, engines=engines_with(TWO[:1]))
    with TestClient(app) as c:
        log_in(c)
        run_id = c.post("/api/runs", json=NEW_RUN).json()["run_id"]
        seen: list[str] = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            view = c.get(f"/api/runs/{run_id}").json()
            if not seen or seen[-1] != view["run"]["state"]:
                seen.append(view["run"]["state"])
            # Mentre il run lavora si riceve un 404 o l'iterazione completa, mai un 200 vuoto.
            # Il layer si legge prima delle metriche: se c'è, le metriche (salvate dopo) ci sono.
            for iteration in range(view["run"]["iteration"] + 1):
                layer = c.get(
                    f"/api/runs/{run_id}/layers/event_area", params={"iteration": iteration}
                )
                metrics = c.get(f"/api/runs/{run_id}/metrics", params={"iteration": iteration})
                assert layer.status_code in (200, 404) and metrics.status_code in (200, 404)
                if layer.status_code == 200:
                    assert metrics.status_code == 200, seen
                if metrics.status_code == 200:
                    assert metrics.json()["metrics"], (iteration, seen)
            if view["run"]["state"] in ("DONE", "ERROR"):
                break
            time.sleep(0.05)
        order = ["INTAKE", "ANALYZE", "RECONCILE", "PLAN", "DISPATCH", "AWAIT", "VERIFY", "DONE"]
        assert seen[-1] == "DONE" and [order.index(s) for s in seen] == sorted(
            order.index(s) for s in seen
        ), seen
        final = c.get(f"/api/runs/{run_id}").json()
        assert [p["status"] for p in final["plan"]] == ["accepted"]
        assert c.get(f"/api/runs/{run_id}/metrics", params={"iteration": 1}).status_code == 200


# --- decisioni -------------------------------------------------------------------------------


def test_log_decisioni_in_ordine(app: FastAPI, authed: TestClient, empty_run_id: str) -> None:
    repo = ctx_of(app).repo
    for index in range(3):
        repo.append_decision(
            run_id=empty_run_id,
            actor="system",
            decision=f"decisione {index}",
            rationale="prova",
            refs=[f"m.x.{index}"],
        )
    rows = authed.get(f"/api/runs/{empty_run_id}/decisions").json()
    assert [r["seq"] for r in rows] == [1, 2, 3]
    assert rows[1]["decision"] == "decisione 1" and rows[1]["refs"] == ["m.x.1"]
    assert rows[0]["actor"] == "system"


def test_log_decisioni_vuoto(authed: TestClient, empty_run_id: str) -> None:
    assert authed.get(f"/api/runs/{empty_run_id}/decisions").json() == []


def test_il_log_decisioni_non_si_modifica_dall_api(authed: TestClient, empty_run_id: str) -> None:
    path = f"/api/runs/{empty_run_id}/decisions"
    for method in ("post", "put", "patch", "delete"):
        assert getattr(authed, method)(path).status_code == 405


def test_stesse_impostazioni_stessa_app(settings: Settings, clock: FakeClock) -> None:
    """Due app con la stessa cartella dati condividono il database (e quindi i run)."""
    first = create_app(settings, clock=clock)
    second = create_app(replace(settings), clock=clock)
    with TestClient(first), TestClient(second) as c:
        ctx_of(first).repo.add_run(make_run("run_cond"))
        log_in(c)
        assert [r["id"] for r in c.get("/api/runs").json()] == ["run_cond"]
