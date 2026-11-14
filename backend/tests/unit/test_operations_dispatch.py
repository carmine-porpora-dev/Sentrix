import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app.data.seeds import load_seed_events, read_seed_events
from app.db.repository import Repository
from app.models.catalog import CatalogConfig
from app.models.departments import DepartmentsConfig
from app.models.operations import OperationRequest
from app.operations import center as center_module
from app.operations.center import SYSTEM, OperationsCenter
from app.operations.lifecycle import InvalidTransition, RunNotFound
from app.operations.registry import DepartmentRegistry, UnsupportedRequestType
from tests.operations_support import Sleeps, make_center, make_draft, make_repo, registry, settled
from tests.support import make_run

POLICE = "municipal_police"
SANNAZARO = "Incrocio Piazza Sannazaro"


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_repo(tmp_path, "run_1", "run_2")


def post(center: OperationsCenter, label: str = "Incrocio Piazza Vittoria", **kw: Any) -> str:
    return center.create(make_draft(target_label=label, **kw)).action_id


def states(repo: Repository, action_id: str) -> list[str]:
    return [event.to_state for event in repo.list_operation_events(action_id)]


# --- un invio dall'inizio alla fine -----------------------------------------------------------


async def test_una_richiesta_accettata_percorre_il_ciclo(
    center: OperationsCenter, repo: Repository, sleeps: Sleeps
) -> None:
    action = post(center)
    decided = await center.dispatch(action)
    assert decided.state == "ACCEPTED"
    assert states(repo, action) == ["CREATED", "SENT", "RECEIVED", "ACCEPTED"]
    assert repo.get_operation_request(action) == decided
    assert sleeps.delays == [1.5]  # il ritardo di departments.yaml, tra la ricezione e l'esito
    # IN_PROGRESS e COMPLETED avanzano dopo, in secondo piano: l'invio non li aspetta
    await settled(center)
    assert states(repo, action) == [
        "CREATED",
        "SENT",
        "RECEIVED",
        "ACCEPTED",
        "IN_PROGRESS",
        "COMPLETED",
    ]
    assert sleeps.delays == [1.5, 1.5, 1.5]


async def test_l_invio_non_aspetta_l_avanzamento_simulato(
    center: OperationsCenter, repo: Repository
) -> None:
    action = post(center)
    await center.dispatch(action)
    stored = repo.get_operation_request(action)
    assert stored is not None and stored.state == "ACCEPTED"
    await settled(center)


async def test_una_richiesta_rifiutata_ha_codice_motivo_e_nessun_avanzamento(
    center: OperationsCenter, repo: Repository, sleeps: Sleeps
) -> None:
    first, second = post(center), post(center, SANNAZARO)
    await center.dispatch(first)
    refused = await center.dispatch(second)
    assert refused.state == "REJECTED" and refused.reject_code == "UNAVAILABLE"
    assert refused.reject_reason == (
        "Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, 6 già impegnate ai varchi"
    )
    assert states(repo, second) == ["CREATED", "SENT", "RECEIVED", "REJECTED"]
    await settled(center)
    assert states(repo, second)[-1] == "REJECTED"  # rifiutata: finita lì
    assert sleeps.delays.count(1.5) == 2 + 2  # due esiti + IN_PROGRESS e COMPLETED della prima


async def test_le_decisioni_sono_l_invio_e_l_esito(
    center: OperationsCenter, repo: Repository
) -> None:
    first, second = post(center), post(center, SANNAZARO)
    await center.dispatch(first)
    await center.dispatch(second)
    await settled(center)
    log = [(d.actor, d.decision) for d in repo.list_decisions("run_1")]
    assert log == [
        ("orchestrator", f"Richiesta {first} inviata (simulata)"),
        (POLICE, f"Richiesta {first} accettata"),
        ("orchestrator", f"Richiesta {second} inviata (simulata)"),
        (POLICE, f"Richiesta {second} rifiutata (UNAVAILABLE)"),
    ]  # RECEIVED, IN_PROGRESS e COMPLETED non scrivono decisioni


async def test_si_invia_una_richiesta_una_volta_sola(center: OperationsCenter) -> None:
    action = post(center)
    await center.dispatch(action)
    with pytest.raises(InvalidTransition, match="da ACCEPTED non si va a SENT"):
        await center.dispatch(action)
    with pytest.raises(LookupError, match="'act_fantasma'"):
        await center.dispatch("act_fantasma")
    await settled(center)


# --- la scena di rifiuto, dai dati -------------------------------------------------------------


async def test_con_match_2027_una_pattuglia_libera_due_richieste_insieme(
    center: OperationsCenter, repo: Repository
) -> None:
    """Le due richieste partono insieme: la regola le decide una alla volta, nell'ordine."""
    first, second = post(center), post(center, SANNAZARO)
    results = await asyncio.gather(center.dispatch(first), center.dispatch(second))
    assert [r.state for r in results] == ["ACCEPTED", "REJECTED"]
    assert results[1].reject_code == "UNAVAILABLE"
    after = {(b.window, b.resource): b for b in center.resources("run_1")}
    assert after[("departure", "patrols")].remaining == 0
    await settled(center)


async def test_con_il_seed_di_settembre_passano_entrambe(tmp_path: Path, sleeps: Sleeps) -> None:
    """Stessa regola, dati diversi (3 pattuglie libere): nessuna riga di codice cambia."""
    repo = Repository(tmp_path / "regate.sqlite")
    load_seed_events(repo)
    repo.add_run(make_run("run_1", event_id="regate_sep_2026"))
    center = make_center(repo, sleeps)
    ids = [post(center, f"Incrocio {n}") for n in range(4)]
    results = await asyncio.gather(*(center.dispatch(i) for i in ids))
    assert [r.state for r in results] == ["ACCEPTED"] * 3 + ["REJECTED"]  # 6 − 3 = 3 libere
    await settled(center)


async def test_le_risorse_di_un_run_non_toccano_quelle_di_un_altro(
    center: OperationsCenter,
) -> None:
    taken = post(center)
    await center.dispatch(taken)
    other = post(center, run_id="run_2")
    result = await center.dispatch(other)
    assert result.state == "ACCEPTED"  # nel run_2 la pattuglia è ancora libera
    free = lambda run: {  # noqa: E731
        (b.window, b.resource): b.remaining for b in center.resources(run)
    }[("departure", "patrols")]
    assert (free("run_1"), free("run_2")) == (0, 0)
    await settled(center)


def test_i_dati_di_un_run_sono_quelli_della_revisione_che_ha_usato(
    center: OperationsCenter, repo: Repository
) -> None:
    """Se l'Evento si modifica dopo, il run non cambia (06 3: revisioni)."""
    match = next(e for e in read_seed_events() if e.id == "match_2027")
    smaller = match.model_copy(
        update={
            "resources": [
                r.model_copy(update={"municipal_police_patrols_total": 5}) for r in match.resources
            ]
        }
    )
    repo.update_event(smaller)
    totals = {(b.window, b.resource): b.total for b in center.resources("run_1")}
    assert totals[("departure", "patrols")] == 6  # il run usa la revisione 1


def test_le_risorse_di_un_run_sconosciuto(center: OperationsCenter) -> None:
    with pytest.raises(RunNotFound, match="'run_9'"):
        center.resources("run_9")


# --- concorrenza -----------------------------------------------------------------------------


def test_due_thread_non_vedono_libera_la_stessa_ultima_pattuglia(
    center: OperationsCenter, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valutare una richiesta e scriverne l'esito è un'operazione sola: senza, due richieste che
    arrivano insieme vedono libera la stessa pattuglia e vengono accettate tutte e due."""
    requests = []
    for label in ("Uno", "Due"):
        request = center.create(make_draft(target_label=label))
        request = center.lifecycle.advance(request, "SENT")
        requests.append(center.lifecycle.advance(request, "RECEIVED"))
    real = center_module.evaluate

    def slow(request: OperationRequest, state: Any) -> Any:
        verdict = real(request, state)
        time.sleep(0.05)  # il tempo in cui, senza il blocco, l'altra richiesta valuterebbe
        return verdict

    monkeypatch.setattr(center_module, "evaluate", slow)
    results: list[OperationRequest] = []
    threads = [
        threading.Thread(target=lambda r=r: results.append(center._decide(r))) for r in requests
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(r.state for r in results) == ["ACCEPTED", "REJECTED"]


# --- timeout -------------------------------------------------------------------------------


async def test_un_dipartimento_che_non_risponde_va_in_timeout(
    repo: Repository,
) -> None:
    config = DepartmentsConfig.from_yaml().model_copy(update={"auto_timeout_s": 1})
    fast = DepartmentRegistry(config, CatalogConfig.from_yaml())

    async def never(_seconds: float) -> None:
        await asyncio.Event().wait()

    center = make_center(repo, never, fast)
    action = post(center)
    # un limite nostro: se il timeout del Centro non scattasse il test non deve restare in attesa
    decided = await asyncio.wait_for(center.dispatch(action), timeout=10)
    assert (decided.state, decided.reject_code) == ("REJECTED", "TIMEOUT")
    assert decided.reject_reason == "Nessuna risposta del dipartimento entro 1 s"
    assert states(repo, action) == ["CREATED", "SENT", "RECEIVED", "REJECTED"]
    last = repo.list_decisions("run_1")[-1]
    assert last.actor == SYSTEM and last.decision.endswith("rifiutata (TIMEOUT)")


# --- creazione e avanzamento ----------------------------------------------------------------


def test_un_timeout_che_arriva_dopo_una_risposta_lascia_la_risposta(
    center: OperationsCenter, repo: Repository
) -> None:
    """Se la risposta è arrivata un attimo prima il timeout non la sovrascrive: vale la risposta."""
    request = center.create(make_draft())
    request = center.lifecycle.advance(request, "SENT")
    waiting = center.lifecycle.advance(request, "RECEIVED")
    answered = center.lifecycle.advance(waiting, "ACCEPTED", actor="user", note="ok")
    assert center._time_out(waiting, 1) == answered  # `waiting` è la fotografia di prima
    assert states(repo, waiting.action_id)[-1] == "ACCEPTED"
    assert [d.actor for d in repo.list_decisions("run_1")] == ["orchestrator", "user"]


def test_settle_non_gira_a_vuoto_se_un_compito_e_finito_ma_la_sua_callback_no(
    center: OperationsCenter,
) -> None:
    """Un compito è finito ma la callback che lo toglie dall'insieme non è ancora girata (succede
    appena dopo un invio). Con `gather`, che su compiti già finiti non cede il passo al ciclo,
    `settle` girava a vuoto per sempre: qui lo si prova su un altro thread, con un limite, così un
    difetto del genere fa fallire il test invece di bloccare la suite."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    async def scenario() -> int:
        async def work() -> None:
            await asyncio.sleep(0)

        task = asyncio.create_task(work())
        center._background.add(task)
        task.add_done_callback(center._background.discard)
        await asyncio.sleep(0)
        await asyncio.sleep(0)  # il compito è finito, la callback è ancora in coda
        assert task.done() and task in center._background
        await center.settle()
        return len(center._background)

    try:
        remaining = asyncio.run_coroutine_threadsafe(scenario(), loop).result(timeout=3)
    finally:
        loop.call_soon_threadsafe(loop.stop)
    assert remaining == 0


def test_il_centro_da_il_catalogo_e_le_alternative(center: OperationsCenter) -> None:
    """Gli strumenti dell'agente Operations (05 2) passano tutti dal Centro."""
    assert [m.type for m in center.list_catalog()] == [m.type for m in registry().catalog.measures]
    assert len(center.list_catalog()) == 8

    class Lookup:
        def upstream_edges(self, node: str) -> list[str]:
            return [f"{node}-1-0"]

        def favored_edge_key(self, node: str) -> str | None:
            return f"{node}-2-0"

        def routes_serving(self, stop_id: str) -> list[str]:
            return []

    found = center.alternatives("traffic_post", "3550591146", "Incrocio", Lookup())
    assert [a.type for a in found] == ["signal_plan_change", "detour_signage"]
    # il bersaglio dell'originale arriva al motore e ne torna l'alternativa
    assert found[0].target == "3550591146" and found[0].payload == {
        "favored_edge_key": "3550591146-2-0"
    }
    assert found[1].target == "3550591146-1-0"


def test_il_dipartimento_lo_dice_il_registro_dal_tipo(center: OperationsCenter) -> None:
    assert center.create(make_draft()).department == POLICE
    signal = center.create(make_draft(type="signal_plan_change"))
    assert signal.department == "traffic_control"
    with pytest.raises(UnsupportedRequestType, match="'bombardamento'"):
        center.create(make_draft(type="bombardamento"))


async def test_un_avanzamento_simulato_che_fallisce_si_registra_non_ferma_nessuno(
    center: OperationsCenter,
    repo: Repository,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    action = post(center)
    real = center.lifecycle.advance

    def failing(request: OperationRequest, to_state: Any, **kw: Any) -> OperationRequest:
        if to_state == "IN_PROGRESS":
            raise RuntimeError("disco pieno")
        return real(request, to_state, **kw)

    monkeypatch.setattr(center.lifecycle, "advance", failing)
    with caplog.at_level(logging.ERROR):
        decided = await center.dispatch(action)
        await settled(center)
    assert decided.state == "ACCEPTED"
    assert states(repo, action)[-1] == "ACCEPTED"
    assert any(
        "interrotto" in record.message and action in record.message for record in caplog.records
    )
