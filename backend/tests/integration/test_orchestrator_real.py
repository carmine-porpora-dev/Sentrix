import asyncio
import csv
import io
import json
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.agents.templates import (
    fallback_analysis,
    fallback_event_demand,
    fallback_notice,
)
from app.data.seeds import load_seed_events
from app.db.repository import Repository
from app.engine.run import RoadEngine
from app.engine.transit import TransitNetwork
from app.engine.transit_run import TransitEngine
from app.llm.cache import DEFAULT_DEMO_CACHE_DIR, read_demo_file
from app.main import create_app
from app.models.agents_config import AgentsConfig
from app.models.catalog import CatalogConfig
from app.models.config import EngineConfig
from app.models.llm_config import LlmConfig
from app.orchestrator.engines import Engines, RealEngines
from app.settings import Settings
from scripts.warm_demo_cache import RecordingClient, check_coverage, run_event
from tests.conftest import PASSWORD, SESSION_SECRET, log_in

pytestmark = pytest.mark.realdata

SEED_EVENTS = ["match_2027", "regate_sep_2026"]
MAX_SECONDS = 90  # 05 4: il ciclo completo in cache_only, per ciascun evento
CONFIG, CATALOG = AgentsConfig.from_yaml(), CatalogConfig.from_yaml()


@pytest.fixture(scope="session")
def engines(
    road_graph: nx.MultiDiGraph, transit_network: TransitNetwork, road_config: EngineConfig
) -> Engines:
    return RealEngines(
        road_graph,
        RoadEngine(road_graph, road_config),
        TransitEngine(transit_network, road_config),
        transit_network,
        road_config,
        CONFIG.labels.route_classes,
    )


# --- la cache demo copre un run nuovo ------------------------------------------------------------


@pytest.mark.parametrize("event_id", SEED_EVENTS)
def test_la_cache_demo_copre_un_run_nuovo_di_ogni_evento_seed(
    event_id: str, engines: Engines
) -> None:
    """Il test che segnala le voci demo mancanti (09 4): dopo ogni modifica a prompt, schemi,
    catalogo, motore, seed o modello, qui si vede che serve rilanciare `warm_demo_cache.py`."""
    file = read_demo_file(DEFAULT_DEMO_CACHE_DIR / f"{event_id}.json")
    started = time.perf_counter()
    holes = asyncio.run(check_coverage(file, engines=engines, config=CONFIG, catalog=CATALOG))
    assert holes == [], (
        f"La cache demo di {event_id} non copre un run nuovo ({', '.join(holes)}): "
        "rilancia `cd backend && uv run python -m scripts.warm_demo_cache` (usa la chiave Gemini)"
    )
    assert time.perf_counter() - started < MAX_SECONDS


# --- dall'API, in cache_only ---------------------------------------------------------------------


@pytest.mark.parametrize("event_id", SEED_EVENTS)
def test_un_run_dall_api_in_cache_only_arriva_a_done_con_i_testi_dell_llm(
    tmp_path: Path, engines: Engines, event_id: str
) -> None:
    model = read_demo_file(DEFAULT_DEMO_CACHE_DIR / f"{event_id}.json").model
    settings = Settings(
        env="local",
        data_dir=tmp_path / "data",
        app_password=PASSWORD,
        session_secret=SESSION_SECRET,
        llm_mode="cache_only",
        gemini_model=model,
    )
    with TestClient(create_app(settings, engines=engines)) as client:
        log_in(client)
        started = time.perf_counter()
        body = {"event_id": event_id, "attendance_level": "mid", "manual_response": False}
        run_id = client.post("/api/runs", json=body).json()["run_id"]
        view: dict[str, Any] = {}
        while time.perf_counter() - started < MAX_SECONDS:
            view = client.get(f"/api/runs/{run_id}").json()
            if view["run"]["state"] in ("DONE", "ERROR"):
                break
            time.sleep(0.25)
        elapsed = time.perf_counter() - started
        assert view["run"]["state"] == "DONE", view["run"].get("error")
        assert elapsed < MAX_SECONDS, f"{elapsed:.0f} s"
        assert view["degraded"] == []
        assert {a["state"] for a in view["agents"]} == {"done"}  # nessun testo di riserva
        assert {a["text_origin"] for a in view["agents"]} == {"llm_cache"}
        assert view["plan"] and any(p["status"] == "accepted" for p in view["plan"])
        assert [t["state"] for t in view["timeline"]][-1] == "DONE"
        notice = view["requests"][-1]["request"]
        assert notice["type"] == "citizen_notice" and notice["state"] in (
            "ACCEPTED",
            "IN_PROGRESS",
            "COMPLETED",
        )
        # ogni numero della mappa ha la sua provenienza, sui dati veri
        known = {
            m["id"]
            for m in client.get(f"/api/runs/{run_id}/metrics", params={"iteration": 0}).json()[
                "metrics"
            ]
        }
        for layer in ("edges_vc", "stops", "sections"):
            features = client.get(
                f"/api/runs/{run_id}/layers/{layer}", params={"iteration": 0}
            ).json()["features"]
            assert features, layer
            assert all(f["properties"]["evidence_id"] in known for f in features), layer
        check_exports(client, run_id, view["run"]["iteration"])
        check_local_effects(client, run_id, view)


def check_exports(client: TestClient, run_id: str, last_iteration: int) -> None:
    """I tre file dell'esportazione (06 5) sono validi e dicono la stessa cosa, sui dati veri: il
    JSON ha tutto con la provenienza completa, il CSV delle metriche le stesse righe del JSON, il
    CSV degli archi critici tante righe quante dicono le metriche `critical_edges.count`."""
    url = f"/api/runs/{run_id}/export"
    package = client.get(url, params={"format": "json"}).json()
    assert list(package) == ["event", "run", "plan", "requests", "decisions", "metrics"]
    assert (
        package["run"]["id"] == run_id
        and package["event"]["revision"] == (package["run"]["event_revision"])
    )
    assert package["plan"] and package["requests"] and package["decisions"]
    assert [m["iteration"] for m in package["metrics"]] == list(range(last_iteration + 1))
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for entry in package["metrics"]:
        from_api = client.get(
            f"/api/runs/{run_id}/metrics", params={"iteration": entry["iteration"]}
        )
        assert (
            entry["metrics"] == from_api.json()["metrics"]
        )  # lo stesso che si vede nell'interfaccia
        for measured in entry["metrics"]:
            for field in ("id", "unit", "kind", "source", "method", "as_of"):
                assert measured[field] not in (None, ""), (measured["id"], field)
            assert (entry["iteration"], measured["id"]) not in by_key
            by_key[(entry["iteration"], measured["id"])] = measured

    metrics = client.get(url, params={"format": "csv", "what": "metrics"})
    assert metrics.headers["content-type"].startswith("text/csv")
    assert f'filename="{run_id}_metrics.csv"' in metrics.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(metrics.text)))
    assert list(rows[0]) == [
        "iteration",
        "metric_id",
        "value",
        "unit",
        "kind",
        "source",
        "method",
        "as_of",
    ]
    assert {(int(r["iteration"]), r["metric_id"]) for r in rows} == set(by_key) and len(
        rows
    ) == len(by_key)
    for row in rows:
        measured = by_key[(int(row["iteration"]), row["metric_id"])]
        value = measured["value"]
        assert row["value"] == value if isinstance(value, str) else float(row["value"]) == value
        assert (row["unit"], row["kind"], row["as_of"]) == (
            measured["unit"], measured["kind"], measured["as_of"]
        )  # fmt: skip

    edges = client.get(url, params={"format": "csv", "what": "critical_edges"})
    assert f'filename="{run_id}_critical_edges.csv"' in edges.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(edges.text)))
    assert list(rows[0]) == ["iteration", "edge_key", "name", "vc", "length_m"]
    for iteration in range(last_iteration + 1):
        mine = [r for r in rows if int(r["iteration"]) == iteration]
        counted = sum(
            int(m["value"])
            for (it, mid), m in by_key.items()
            if it == iteration and mid.endswith(".critical_edges.count")
        )
        assert len(mine) == counted > 0, iteration
        loads = [float(r["vc"]) for r in mine]
        assert loads == sorted(loads, reverse=True)  # dal più carico


def check_local_effects(client: TestClient, run_id: str, view: dict[str, Any]) -> None:
    """02 7: ogni misura stradale accettata, con un arco con carico, ha `vc_before` e `vc_after`
    tra le metriche dell'iterazione in cui è entrata in vigore: `rapporto` SIMULATO con la sua
    provenienza, e nessuna misura di altro tipo ne ha."""
    effect_types = {"traffic_post", "signal_plan_change", "detour_signage"}
    active = ("ACCEPTED", "IN_PROGRESS", "COMPLETED")
    requests = [item["request"] for item in view["requests"] if item["request"]["state"] in active]
    by_iteration: dict[int, dict[str, dict[str, Any]]] = {}
    for iteration in range(view["run"]["iteration"] + 1):
        metrics = client.get(f"/api/runs/{run_id}/metrics", params={"iteration": iteration}).json()
        by_iteration[iteration] = {m["id"]: m for m in metrics["metrics"]}
    found = 0
    for request in requests:
        stem = f"m.{run_id}.it{request['iteration']}.road.{request['window']}.measure_effect."
        ids = [f"{stem}{request['action_id']}.vc_before", f"{stem}{request['action_id']}.vc_after"]
        have = [i in by_iteration[request["iteration"]] for i in ids]
        if request["type"] not in effect_types:
            assert not any(have), request["action_id"]
            continue
        assert have == [True, True], (request["action_id"], request["type"])
        found += 1
        before, after = (by_iteration[request["iteration"]][i] for i in ids)
        for measured in (before, after):
            assert (measured["unit"], measured["kind"]) == ("rapporto", "simulated")
            assert measured["value"] > 0 and measured["source"] == "engine.measure_effects v1"
            assert measured["inputs"] and measured["assumptions"]
    assert found > 0, "nessuna misura stradale ha un effetto locale"
    # ogni effetto è di una richiesta in vigore: nessun numero orfano
    stray = [
        i
        for metrics in by_iteration.values()
        for i in metrics
        if ".measure_effect." in i
        and i.split(".measure_effect.")[1].rsplit(".", 1)[0]
        not in {r["action_id"] for r in requests}
    ]
    assert stray == []


# --- il rifiuto dato a mano, in cache_only, sui dati veri ---------------------------------------


def test_un_rifiuto_manuale_porta_alla_ripianificazione_anche_in_cache_only(
    tmp_path: Path, engines: Engines
) -> None:
    """Il piano registrato con Gemini non contiene rifiuti (l'LLM vede le risorse e non chiede più
    pattuglie di quante ne restano): il ciclo rifiuto → ripianificazione → nuova simulazione si
    mostra con la risposta manuale. I testi della ripianificazione e dell'avviso non sono in
    cache: sono di riserva, e il run lo dichiara (`degraded`)."""
    model = read_demo_file(DEFAULT_DEMO_CACHE_DIR / "match_2027.json").model
    settings = Settings(
        env="local",
        data_dir=tmp_path / "data",
        app_password=PASSWORD,
        session_secret=SESSION_SECRET,
        llm_mode="cache_only",
        gemini_model=model,
    )
    with TestClient(create_app(settings, engines=engines)) as client:
        log_in(client)
        body = {"event_id": "match_2027", "attendance_level": "mid", "manual_response": True}
        run_id = client.post("/api/runs", json=body).json()["run_id"]
        answered: set[str] = set()
        rejected: str | None = None
        view: dict[str, Any] = {}
        deadline = time.perf_counter() + MAX_SECONDS
        while time.perf_counter() < deadline:
            view = client.get(f"/api/runs/{run_id}").json()
            if view["run"]["state"] in ("DONE", "ERROR"):
                break
            for item in view["requests"]:
                request = item["request"]
                if request["state"] != "RECEIVED" or request["action_id"] in answered:
                    continue
                refuse = rejected is None and request["type"] == "traffic_post"
                answer = (
                    {
                        "decision": "reject",
                        "reject_code": "UNAVAILABLE",
                        "reject_reason": "Pattuglia non disponibile",
                    }
                    if refuse
                    else {"decision": "accept"}
                )
                department, action = request["department"], request["action_id"]
                path = f"/api/vdept/{department}/requests/{action}/manual-response"
                assert client.post(path, json=answer).status_code == 200
                answered.add(request["action_id"])
                rejected = request["action_id"] if refuse else rejected
            time.sleep(0.1)
        assert view["run"]["state"] == "DONE", view["run"].get("error")
        assert rejected is not None
        run = view["run"]
        assert (run["iteration"], run["replans"]) == (2, 1)
        refused = next(
            r["request"] for r in view["requests"] if r["request"]["action_id"] == rejected
        )
        assert (refused["state"], refused["reject_code"]) == ("REJECTED", "UNAVAILABLE")
        replacement = next(
            r["request"] for r in view["requests"] if r["request"]["alternative_of"] == rejected
        )
        assert (
            replacement["type"] == "signal_plan_change"
            and replacement["target"] == refused["target"]
        )
        assert replacement["state"] in ("ACCEPTED", "IN_PROGRESS", "COMPLETED")
        statuses = [p["status"] for p in view["plan"]]
        assert "replaced" in statuses and "human_decision_required" not in statuses
        assert view["degraded"] == ["llm_fallback"]  # la ripianificazione non è in cache: riserva
        operations = view["agents"][3]
        assert operations["state"] == "done_fallback" and operations["text_origin"] == "template"
        assert {a["state"] for a in view["agents"][:3]} == {"done"}  # il resto viene dalla cache
        assert client.get(f"/api/runs/{run_id}/metrics", params={"iteration": 2}).json()["deltas"]


# --- la scena di rifiuto di 04 7 sui dati veri --------------------------------------------------


class ScriptedLlm:
    """Un LLM che risponde come un agente diligente ma sceglie, nel piano, i due presìdi del
    deflusso: la scena di 04 7. Le altre risposte sono i testi di riserva (già validi). Nessun
    servizio, nessuna rete."""

    async def generate(
        self,
        *,
        model: str,
        system: str,
        contents: str,
        schema: Mapping[str, Any],
        temperature: float,
        timeout_s: float,
    ) -> str:
        payload = json.loads(contents)
        if "scegliere quali misure candidate" in system:
            posts = [
                c
                for c in payload["candidates"]
                if c["measure_type"] == "traffic_post" and c["window"] == "departure"
            ][:2]
            assert len(posts) == 2, "il motore non dà due incroci critici nel deflusso"
            plan = [{"candidate": c["id"], "rationale": "Va presidiato."} for c in posts]
            return json.dumps({"text": "Due presìdi nel deflusso.", "plan": plan})
        if "scegliere quale alternativa" in system:
            return json.dumps(
                {
                    "text": "Si chiede la prima alternativa.",
                    "choice": "a1",
                    "rationale": "È la preferita.",
                }
            )
        if "scrivere l'avviso" in system:
            return fallback_notice(payload, CONFIG).model_dump_json()
        if "signals" in payload:
            return fallback_analysis(payload, CONFIG).model_dump_json()
        return fallback_event_demand(payload, CONFIG).model_dump_json()


def test_la_scena_di_rifiuto_di_04_7_con_i_dati_veri_di_match_2027(engines: Engines) -> None:
    """Due presìdi nel deflusso, una pattuglia libera (6 − 5): il primo è accettato, il secondo è
    rifiutato `UNAVAILABLE`; la ripianificazione propone il cambio di piano semaforico sullo stesso
    incrocio (alternativa 1), accettato; VERIFY calcola l'iterazione 1 e la 2. Sul grafo vero."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp) / "scena.sqlite")
        load_seed_events(repo)
        client = RecordingClient(
            mode="live",
            model="scriptato",
            daily_limit=1000,
            config=LlmConfig.from_yaml(),
            repo=repo,
            backend=ScriptedLlm(),
        )
        run = asyncio.run(
            run_event(
                "match_2027",
                client=client,
                repo=repo,
                engines=engines,
                config=CONFIG,
                catalog=CATALOG,
            )
        )
        assert client.fallbacks == [] and (run.state, run.iteration, run.replans) == ("DONE", 2, 1)
        first, second, replacement, notice = repo.list_operation_requests(run.id)
        assert (first.type, first.window, first.state) == ("traffic_post", "departure", "COMPLETED")
        assert (second.type, second.state, second.reject_code) == (
            "traffic_post",
            "REJECTED",
            "UNAVAILABLE",
        )
        assert second.reject_reason == (
            "Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, 6 già impegnate ai varchi"
        )
        assert (replacement.type, replacement.department) == (
            "signal_plan_change",
            "traffic_control",
        )
        assert (
            replacement.target == second.target and replacement.alternative_of == second.action_id
        )
        assert replacement.state == "COMPLETED" and replacement.payload["favored_edge_key"]
        assert notice.type == "citizen_notice" and notice.state == "COMPLETED"
        items = repo.list_plan_items(run.id)
        assert [i.status for i in items[:2]] == ["accepted", "replaced"]  # i due presìdi del piano
        swap = next(i for i in items if i.recommendation.measure_type == "signal_plan_change")
        assert swap.status == "accepted" and items[1].replaced_by == swap.seq
        # VERIFY: due iterazioni con le sole finestre toccate ricalcolate (il deflusso)
        for iteration in (1, 2):
            ids = [m.id for m in repo.list_metrics(run.id, iteration)]
            assert any(".road.departure." in i for i in ids)
        ids = [m.id for m in repo.list_metrics(run.id, 2)]
        assert f"m.{run.id}.it2.road.departure.veh_hours" in ids  # il deflusso è stato ricalcolato
        assert (
            f"m.{run.id}.it0.road.arrival.veh_hours" in ids
        )  # l'arrivo no: copia dell'iterazione 0
        assert f"m.{run.id}.it2.road.arrival.veh_hours" not in ids
