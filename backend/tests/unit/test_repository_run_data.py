import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.clock import ROME
from app.db.repository import Repository
from app.models.agents import AgentResult
from app.models.api import Feature, FeatureCollection
from app.models.run import PlanItem
from tests.agents_support import candidate, measure
from tests.operations_support import make_repo
from tests.support import make_run

END = datetime(2026, 11, 9, 10, 5, tzinfo=ROME)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    repository = make_repo(tmp_path)
    repository.add_run(make_run("run_1"))
    return repository


def result(agent: str = "traffic", iteration: int = 0, duration: int = 12) -> AgentResult:
    return AgentResult(
        run_id="run_1",
        agent=agent,
        iteration=iteration,
        input_hash="a" * 64,
        tools_called=["t"],
        tool_output_ids=["m.run_1.it0.x"],
        findings=[],
        recommendations=[],
        data_sources=[],
        data_kind=[],
        assumptions=[],
        requires_approval=False,
        text="Sintesi.",
        text_origin="template",
        duration_ms=duration,
        validation="fallback",
    )


# --- run ----------------------------------------------------------------------------------------


def test_il_run_cambia_stato_iterazione_e_ripianificazioni(repo: Repository) -> None:
    updated = repo.update_run("run_1", state="VERIFY", iteration=2, replans=1)
    assert (updated.state, updated.iteration, updated.replans) == ("VERIFY", 2, 1)
    assert repo.get_run("run_1") == updated


def test_un_run_concluso_ha_la_fine_e_uno_in_errore_il_messaggio(repo: Repository) -> None:
    done = repo.update_run("run_1", state="DONE", ended_at=END)
    assert done.ended_at == END
    repo.add_run(make_run("run_2"))
    failed = repo.update_run("run_2", state="ERROR", error="Motore non disponibile", ended_at=END)
    assert failed.error == "Motore non disponibile"


def test_un_cambio_che_lascia_il_run_incoerente_non_cambia_niente(repo: Repository) -> None:
    for changes in (
        {"state": "DONE"},  # manca la fine
        {"state": "ERROR", "ended_at": END},  # manca il messaggio
        {"replans": 4},  # oltre il tetto
        {"iteration": -1},
    ):
        with pytest.raises(ValidationError):
            repo.update_run("run_1", **changes)
    assert repo.get_run("run_1") == make_run("run_1")


def test_un_run_che_non_c_e_non_si_aggiorna(repo: Repository) -> None:
    with pytest.raises(LookupError, match="'run_9'"):
        repo.update_run("run_9", state="ANALYZE")


# --- risultati degli agenti ---------------------------------------------------------------------


def test_i_risultati_degli_agenti_tornano_nell_ordine_di_scrittura(repo: Repository) -> None:
    results = [
        result("event_demand"),
        result("traffic"),
        result("operations", 1),
        result("operations", 2),
    ]
    for item in results:
        repo.add_agent_result(item)
    assert repo.list_agent_results("run_1") == results
    assert repo.list_agent_results("run_9") == []


# --- piano --------------------------------------------------------------------------------------


def test_il_piano_si_scrive_e_si_aggiorna_per_seq(repo: Repository) -> None:
    recommendation = candidate("c1").recommendation
    repo.put_plan_item("run_1", PlanItem(seq=2, recommendation=recommendation, status="proposed"))
    repo.put_plan_item("run_1", PlanItem(seq=1, recommendation=recommendation, status="proposed"))
    repo.put_plan_item(
        "run_1",
        PlanItem(
            seq=1, recommendation=recommendation, status="accepted", action_id="act_run_1_001"
        ),
    )
    items = repo.list_plan_items("run_1")
    assert [(i.seq, i.status, i.action_id) for i in items] == [
        (1, "accepted", "act_run_1_001"),
        (2, "proposed", None),
    ]


def test_un_elemento_di_piano_di_un_run_che_non_c_e_non_si_scrive(repo: Repository) -> None:
    item = PlanItem(seq=1, recommendation=candidate("c1").recommendation, status="proposed")
    with pytest.raises(sqlite3.IntegrityError):
        repo.put_plan_item("run_9", item)


# --- metriche -----------------------------------------------------------------------------------


def test_le_metriche_di_un_iterazione_si_sostituiscono_per_id(repo: Repository) -> None:
    first = measure(("road", "departure", "veh_hours"), 4820.0, "veic·h")
    second = measure(("road", "departure", "od_time.mean"), 38.4, "min")
    repo.put_metrics("run_1", 0, [first, second])
    repo.put_metrics("run_1", 1, [measure(("road", "departure", "veh_hours"), 1.0, "veic·h", it=1)])
    newer = measure(("road", "departure", "veh_hours"), 4000.0, "veic·h")
    repo.put_metrics("run_1", 0, [newer])
    assert repo.list_metrics("run_1", 0) == [newer, second]  # stesso id sostituito, resto intatto
    assert len(repo.list_metrics("run_1", 1)) == 1 and repo.list_metrics("run_1", 2) == []


# --- layer --------------------------------------------------------------------------------------


def test_i_layer_si_scrivono_si_leggono_e_si_sostituiscono(repo: Repository) -> None:
    layer = FeatureCollection(features=[Feature(id="a", geometry=None, properties={"vc": 1.2})])
    repo.put_layer("run_1", 0, "edges_vc", layer)
    repo.put_layer("run_1", 0, "closures", FeatureCollection(features=[]))
    assert repo.get_layer("run_1", 0, "edges_vc") == layer
    assert repo.list_layer_names("run_1", 0) == ["closures", "edges_vc"]
    repo.put_layer("run_1", 0, "edges_vc", FeatureCollection(features=[]))
    assert repo.get_layer("run_1", 0, "edges_vc") == FeatureCollection(features=[])
    assert (
        repo.get_layer("run_1", 1, "edges_vc") is None and repo.list_layer_names("run_1", 1) == []
    )
