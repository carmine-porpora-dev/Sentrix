import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from app.db.repository import Repository
from app.models.api import ManualResponse
from app.models.catalog import CatalogConfig
from app.models.departments import DepartmentsConfig
from app.models.operations import OperationRequest
from app.operations import center as center_module
from app.operations.center import (
    SYSTEM,
    USER,
    AcceptNotAllowed,
    NotAwaitingResponse,
    OperationsCenter,
    _deliver,
)
from app.operations.lifecycle import InvalidTransition
from app.operations.registry import DepartmentRegistry
from tests.operations_support import Sleeps, make_center, make_draft, make_repo, settled
from tests.support import make_request

ACCEPT = ManualResponse(decision="accept")
REJECT = ManualResponse(
    decision="reject", reject_code="UNAVAILABLE", reject_reason="Nessuna pattuglia libera"
)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_repo(tmp_path, "run_1")


async def finished(task: "asyncio.Future[OperationRequest]") -> OperationRequest:
    """L'esito di un invio, con un limite: se chi aspettava non venisse svegliato, il test
    fallisce invece di restare in attesa."""
    return await asyncio.wait_for(task, timeout=5)


def states(repo: Repository, action_id: str) -> list[str]:
    return [event.to_state for event in repo.list_operation_events(action_id)]


async def received(
    center: OperationsCenter, repo: Repository, label: str = "Incrocio Dante"
) -> tuple[str, asyncio.Task[OperationRequest]]:
    """Una richiesta inviata con la risposta manuale, ferma in RECEIVED."""
    action = center.create(make_draft(target_label=label)).action_id
    task = asyncio.create_task(center.dispatch(action, manual=True))
    for _ in range(100):
        await asyncio.sleep(0)
        if states(repo, action)[-1] == "RECEIVED":
            return action, task
    raise AssertionError("la richiesta non è arrivata a RECEIVED")


# --- l'attesa ---------------------------------------------------------------------------------


async def test_la_richiesta_resta_in_received_finche_nessuno_risponde(
    center: OperationsCenter, repo: Repository, sleeps: Sleeps
) -> None:
    action, task = await received(center, repo)
    for _ in range(20):  # molti giri del ciclo: nessuno decide al posto della persona
        await asyncio.sleep(0)
    assert not task.done()
    assert states(repo, action) == ["CREATED", "SENT", "RECEIVED"]
    assert sleeps.delays == []  # nessun ritardo simulato: decide la persona
    center.respond_manually(action, ACCEPT)
    await finished(task)
    await settled(center)


async def test_accettare_porta_in_accepted_e_poi_avanza(
    center: OperationsCenter, repo: Repository
) -> None:
    action, task = await received(center, repo)
    answered = center.respond_manually(action, ACCEPT)
    assert answered.state == "ACCEPTED"
    assert (await finished(task)) == answered  # chi aspettava riceve la stessa richiesta
    await settled(center)
    assert states(repo, action) == [
        "CREATED",
        "SENT",
        "RECEIVED",
        "ACCEPTED",
        "IN_PROGRESS",
        "COMPLETED",
    ]


async def test_rifiutare_porta_codice_e_motivo_dell_utente(
    center: OperationsCenter, repo: Repository
) -> None:
    action, task = await received(center, repo)
    answered = center.respond_manually(action, REJECT)
    assert (answered.state, answered.reject_code) == ("REJECTED", "UNAVAILABLE")
    assert answered.reject_reason == "Nessuna pattuglia libera"
    assert (await finished(task)).state == "REJECTED"
    await settled(center)
    assert states(repo, action)[-1] == "REJECTED"  # un rifiuto non avanza


async def test_la_decisione_e_registrata_con_attore_user(
    center: OperationsCenter, repo: Repository
) -> None:
    accepted, task_a = await received(center, repo, "Uno")
    rejected, task_r = await received(center, repo, "Due")
    center.respond_manually(accepted, ACCEPT)
    center.respond_manually(rejected, REJECT)
    await asyncio.gather(finished(task_a), finished(task_r))
    await settled(center)
    log = [(d.actor, d.decision) for d in repo.list_decisions("run_1")]
    assert (USER, f"Richiesta {accepted} accettata") in log
    assert (USER, f"Richiesta {rejected} rifiutata (UNAVAILABLE)") in log
    assert [actor for actor, _ in log].count("orchestrator") == 2  # i due invii
    user_decision = next(d for d in repo.list_decisions("run_1") if d.actor == USER)
    assert user_decision.rationale.startswith("Accettata con la risposta manuale. ")
    assert (
        "Pattuglia disponibile: 1 libere su 6" in user_decision.rationale
    )  # il motivo della regola


async def test_l_utente_non_puo_accettare_cio_che_la_regola_rifiuta(
    center: OperationsCenter, repo: Repository
) -> None:
    """Con una sola pattuglia libera la prima accettazione passa, la seconda no: le risorse
    restano coerenti. La richiesta bloccata resta in attesa e si può ancora rifiutare."""
    first, task_1 = await received(center, repo, "Uno")
    second, task_2 = await received(center, repo, "Due")
    assert center.respond_manually(first, ACCEPT).state == "ACCEPTED"
    decisions_before = len(repo.list_decisions("run_1"))
    with pytest.raises(AcceptNotAllowed) as blocked:
        center.respond_manually(second, ACCEPT)
    assert blocked.value.code == "UNAVAILABLE"
    assert str(blocked.value) == (
        "Non si può accettare: Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, "
        "6 già impegnate ai varchi. La richiesta si può rifiutare."
    )
    # il tentativo non cambia niente: né stato, né storia, né decisioni, né attesa
    assert states(repo, second) == ["CREATED", "SENT", "RECEIVED"]
    assert len(repo.list_decisions("run_1")) == decisions_before
    assert second in center._waiting and not task_2.done()
    free = {(b.window, b.resource): b for b in center.resources("run_1")}
    assert (free[("departure", "patrols")].used, free[("departure", "patrols")].total) == (6, 6)
    # ... e si può ancora rifiutare, con il codice e il motivo dell'utente
    refused = center.respond_manually(second, REJECT)
    assert (refused.state, refused.reject_code) == ("REJECTED", "UNAVAILABLE")
    assert (await finished(task_2)).state == "REJECTED"
    await finished(task_1)
    await settled(center)


async def test_rifiutare_si_puo_sempre_anche_con_le_risorse_libere(
    center: OperationsCenter, repo: Repository
) -> None:
    """Il rifiuto non passa dalla regola: con una pattuglia libera, e con un codice qualunque."""
    action, task = await received(center, repo)
    answered = center.respond_manually(
        action,
        ManualResponse(decision="reject", reject_code="ALTRO", reject_reason="Decido io"),
    )
    assert (answered.state, answered.reject_code) == ("REJECTED", "ALTRO")
    await finished(task)


async def test_l_accettazione_manuale_segue_la_regola_di_ogni_dipartimento(
    center: OperationsCenter, repo: Repository
) -> None:
    """Il limite delle modifiche semaforiche, i bus di riserva, un payload malformato."""
    for number in range(3):  # il massimo di modifiche semaforiche dell'Evento è 3
        request = center.create(make_draft(type="signal_plan_change", target_label=f"S{number}"))
        request = center.lifecycle.advance(request, "SENT")
        request = center.lifecycle.advance(request, "RECEIVED")
        center.lifecycle.advance(request, "ACCEPTED", actor="traffic_control")
    cases = [
        (make_draft(type="signal_plan_change", target_label="Quarta"), "LIMIT_REACHED"),
        (make_draft(type="add_runs", target="metro_line_1", payload={"n": 0}), "INVALID_REQUEST"),
        (make_draft(type="add_runs", target="metro_line_1", payload={"n": 9}), "NO_RESERVE"),
    ]
    for draft, code in cases:
        action = center.create(draft).action_id
        task = asyncio.create_task(center.dispatch(action, manual=True))
        for _ in range(100):
            await asyncio.sleep(0)
            if states(repo, action)[-1] == "RECEIVED":
                break
        with pytest.raises(AcceptNotAllowed) as blocked:
            center.respond_manually(action, ACCEPT)
        assert blocked.value.code == code
        center.respond_manually(action, REJECT)  # rifiutare si può sempre
        await finished(task)
    await settled(center)


async def test_un_accettazione_manuale_e_una_decisione_automatica_non_accettano_la_stessa_pattuglia(
    center: OperationsCenter, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con una pattuglia libera, una persona che accetta e il dipartimento che decide da solo,
    nello stesso istante: valutare e scrivere l'esito è un'operazione sola per tutti e due, quindi
    una sola richiesta viene accettata."""
    manual, task = await received(center, repo, "Manuale")
    other = center.create(make_draft(target_label="Automatica"))
    other = center.lifecycle.advance(other, "SENT")
    other = center.lifecycle.advance(other, "RECEIVED")
    real = center_module.evaluate

    def slow(request: OperationRequest, state: Any) -> Any:
        verdict = real(request, state)
        time.sleep(0.05)  # senza il blocco, l'altra valuterebbe qui, con la pattuglia ancora libera
        return verdict

    monkeypatch.setattr(center_module, "evaluate", slow)

    def answer() -> str:
        try:
            return center.respond_manually(manual, ACCEPT).state
        except AcceptNotAllowed:
            return "BLOCCATA"

    results = await asyncio.gather(
        asyncio.to_thread(answer), asyncio.to_thread(center._decide, other)
    )
    outcomes = [results[0], results[1].state]
    assert sorted(outcomes) in (["ACCEPTED", "BLOCCATA"], ["ACCEPTED", "REJECTED"])
    stored = [
        repo.get_operation_request(a)
        for a in (manual, other.action_id)  # una sola ha preso l'ultima pattuglia
    ]
    assert sum(1 for r in stored if r is not None and r.state == "ACCEPTED") == 1
    if outcomes[0] == "BLOCCATA":
        center.respond_manually(manual, REJECT)
    await finished(task)
    await settled(center)


async def test_le_richieste_in_attesa_hanno_ognuna_la_sua_risposta(
    center: OperationsCenter, repo: Repository
) -> None:
    first, task_1 = await received(center, repo, "Uno")
    second, task_2 = await received(center, repo, "Due")
    center.respond_manually(second, REJECT)  # in ordine inverso
    assert (await finished(task_2)).state == "REJECTED" and not task_1.done()
    center.respond_manually(first, ACCEPT)
    assert (await finished(task_1)).state == "ACCEPTED"
    await settled(center)


async def test_si_puo_rispondere_da_un_altro_thread(
    center: OperationsCenter, repo: Repository
) -> None:
    """L'endpoint dell'API gira su un thread del pool, l'invio su un ciclo di eventi."""
    action, task = await received(center, repo)
    answered = await asyncio.to_thread(center.respond_manually, action, ACCEPT)
    assert (await finished(task)) == answered
    await settled(center)


async def test_chi_ha_avuto_la_risposta_non_resta_in_attesa(
    center: OperationsCenter, repo: Repository
) -> None:
    """Nessuna richiesta resta registrata tra quelle in attesa dopo l'esito, qualunque sia."""
    first, task_1 = await received(center, repo, "Uno")
    second, task_2 = await received(center, repo, "Due")
    assert set(center._waiting) == {first, second}
    center.respond_manually(first, ACCEPT)
    await finished(task_1)
    assert set(center._waiting) == {second}
    center.respond_manually(second, REJECT)
    await finished(task_2)
    assert center._waiting == {}
    await settled(center)


async def test_la_consegna_a_chi_ha_gia_smesso_di_aspettare_non_fa_danni() -> None:
    """Il tempo scade e il compito annulla l'attesa un attimo prima che arrivi la risposta: la
    consegna trova l'attesa già chiusa e non deve sollevare niente."""
    loop = asyncio.get_running_loop()
    request = make_request()
    expired: asyncio.Future[OperationRequest] = loop.create_future()
    expired.cancel()
    _deliver(expired, request)  # non solleva
    open_wait: asyncio.Future[OperationRequest] = loop.create_future()
    _deliver(open_wait, request)
    assert open_wait.result() == request


# --- quando non si può rispondere --------------------------------------------------------------


async def test_una_seconda_risposta_non_si_puo_dare(
    center: OperationsCenter, repo: Repository
) -> None:
    action, task = await received(center, repo)
    center.respond_manually(action, ACCEPT)
    with pytest.raises(NotAwaitingResponse, match="non attende una risposta"):
        center.respond_manually(action, REJECT)
    await finished(task)
    await settled(center)
    assert states(repo, action).count("ACCEPTED") == 1 and "REJECTED" not in states(repo, action)


@pytest.mark.parametrize("state", ["CREATED", "SENT"])
def test_prima_della_ricezione_non_si_risponde(
    center: OperationsCenter, state: str, repo: Repository
) -> None:
    request = center.create(make_draft())
    if state == "SENT":
        request = center.lifecycle.advance(request, "SENT")
    with pytest.raises(NotAwaitingResponse) as raised:
        center.respond_manually(request.action_id, ACCEPT)
    assert raised.value.state == state and "deve essere in RECEIVED" in str(raised.value)


def test_una_richiesta_ricevuta_senza_risposta_manuale_non_si_puo_decidere_a_mano(
    center: OperationsCenter,
) -> None:
    request = center.lifecycle.advance(center.create(make_draft()), "SENT")
    request = center.lifecycle.advance(request, "RECEIVED")  # nessun invio la sta aspettando
    with pytest.raises(NotAwaitingResponse, match="non è attiva"):
        center.respond_manually(request.action_id, ACCEPT)


async def test_una_richiesta_inviata_in_automatico_non_aspetta_nessuno(
    center: OperationsCenter,
) -> None:
    action = center.create(make_draft()).action_id
    await center.dispatch(action)  # senza risposta manuale: decide la regola
    with pytest.raises(NotAwaitingResponse):
        center.respond_manually(action, ACCEPT)
    await settled(center)


def test_una_richiesta_sconosciuta(center: OperationsCenter) -> None:
    with pytest.raises(LookupError, match="'act_fantasma'"):
        center.respond_manually("act_fantasma", ACCEPT)


# --- timeout -------------------------------------------------------------------------------


def one_second_registry() -> DepartmentRegistry:
    config = DepartmentsConfig.from_yaml().model_copy(update={"manual_timeout_s": 1})
    return DepartmentRegistry(config, CatalogConfig.from_yaml())


async def test_senza_risposta_entro_il_tempo_massimo_e_timeout(
    repo: Repository, sleeps: Sleeps
) -> None:
    center = make_center(repo, sleeps, one_second_registry())
    action = center.create(make_draft()).action_id
    # un limite nostro: se il timeout del Centro non scattasse il test non deve restare in attesa
    decided = await asyncio.wait_for(center.dispatch(action, manual=True), timeout=10)
    assert (decided.state, decided.reject_code) == ("REJECTED", "TIMEOUT")
    assert decided.reject_reason == "Nessuna risposta del dipartimento entro 1 s"
    assert states(repo, action) == ["CREATED", "SENT", "RECEIVED", "REJECTED"]
    last = repo.list_decisions("run_1")[-1]
    assert last.actor == SYSTEM and last.decision.endswith("rifiutata (TIMEOUT)")
    with pytest.raises(NotAwaitingResponse):  # dopo il timeout nessuno aspetta più
        center.respond_manually(action, ACCEPT)


async def test_se_la_risposta_arriva_mentre_scade_il_tempo_vale_una_sola(
    center: OperationsCenter, repo: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La persona ha letto la richiesta ancora `RECEIVED`, ma il timeout scrive il rifiuto un
    attimo prima che lei risponda: la sua risposta non sovrascrive niente (il confronto dello
    stato nel database la ferma) e l'esito resta quello del timeout."""
    action, task = await received(center, repo)
    stale = center.status(action)  # la fotografia di prima del timeout
    center._time_out(stale, 1)
    monkeypatch.setattr(center, "status", lambda _action: stale)  # la risposta parte da quella
    with pytest.raises(NotAwaitingResponse, match="un'altra risposta o il timeout"):
        center.respond_manually(action, ACCEPT)
    monkeypatch.undo()
    assert states(repo, action)[-1] == "REJECTED"
    assert [d.actor for d in repo.list_decisions("run_1")] == ["orchestrator", SYSTEM]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finished(task)


async def test_dopo_che_scade_il_tempo_la_risposta_trova_la_richiesta_rifiutata(
    center: OperationsCenter, repo: Repository
) -> None:
    action, task = await received(center, repo)
    center._time_out(center.status(action), 1)
    with pytest.raises(NotAwaitingResponse, match="REJECTED"):
        center.respond_manually(action, ACCEPT)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await finished(task)


async def test_dopo_un_timeout_non_si_puo_riavviare_l_invio(
    center: OperationsCenter, repo: Repository
) -> None:
    action, task = await received(center, repo)
    center._time_out(center.status(action), 1)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, InvalidTransition)):
        await finished(task)
    with pytest.raises(InvalidTransition):
        await center.dispatch(action, manual=True)
