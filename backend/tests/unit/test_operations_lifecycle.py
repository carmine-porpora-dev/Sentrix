import itertools
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.db.repository import Repository, StateConflict
from app.models.operations import OperationRequest, RequestState
from app.operations.lifecycle import (
    ORCHESTRATOR,
    TRANSITIONS,
    InvalidAlternative,
    InvalidTransition,
    LifecycleError,
    RequestLifecycle,
    RunNotFound,
    check_transition,
)
from app.operations.registry import UnknownDepartment, UnsupportedRequestType
from tests.operations_support import StepClock, make_draft, make_repo, registry

STATES: tuple[RequestState, ...] = get_args(RequestState)
POLICE = "municipal_police"


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_repo(tmp_path, "run_1", "run_2")


@pytest.fixture
def lifecycle(repo: Repository) -> RequestLifecycle:
    return RequestLifecycle(repo, registry(), StepClock())


def received(lifecycle: RequestLifecycle) -> OperationRequest:
    request = lifecycle.create(make_draft(), POLICE)
    request = lifecycle.advance(request, "SENT")
    return lifecycle.advance(request, "RECEIVED")


# --- la tabella delle transizioni -----------------------------------------------------------------

ALLOWED = {
    ("CREATED", "SENT"),
    ("SENT", "RECEIVED"),
    ("RECEIVED", "ACCEPTED"),
    ("RECEIVED", "REJECTED"),
    ("ACCEPTED", "IN_PROGRESS"),
    ("IN_PROGRESS", "COMPLETED"),
}


def test_la_tabella_ha_sette_stati_e_sei_transizioni() -> None:
    assert set(TRANSITIONS) == set(STATES)
    assert {(a, b) for a, targets in TRANSITIONS.items() for b in targets} == ALLOWED


@pytest.mark.parametrize(("source", "target"), list(itertools.product(STATES, STATES)))
def test_tutte_le_quarantanove_coppie(source: RequestState, target: RequestState) -> None:
    """Consentite solo le sei in ordine; ogni altra (anche lo stesso stato, anche a ritroso) è un
    salto: `InvalidTransition`."""
    if (source, target) in ALLOWED:
        check_transition("act_1", source, target)
    else:
        with pytest.raises(InvalidTransition, match=f"da {source} non si va a {target}"):
            check_transition("act_1", source, target)


def test_rejected_e_completed_sono_finali() -> None:
    assert TRANSITIONS["REJECTED"] == frozenset()
    assert TRANSITIONS["COMPLETED"] == frozenset()


def test_il_messaggio_dice_cosa_era_consentito() -> None:
    with pytest.raises(InvalidTransition, match=r"consentite: ACCEPTED, REJECTED"):
        check_transition("act_1", "RECEIVED", "COMPLETED")
    with pytest.raises(InvalidTransition, match=r"consentite: nessuna"):
        check_transition("act_1", "REJECTED", "ACCEPTED")


# --- una richiesta dall'inizio alla fine --------------------------------------------------------


def test_il_percorso_completo_scrive_una_riga_per_transizione(
    lifecycle: RequestLifecycle, repo: Repository
) -> None:
    request = lifecycle.create(make_draft(), POLICE)
    assert request.state == "CREATED" and request.department == POLICE
    for state in ("SENT", "RECEIVED", "ACCEPTED", "IN_PROGRESS", "COMPLETED"):
        request = lifecycle.advance(
            request,
            state,
            actor=POLICE if state == "ACCEPTED" else None,
        )
    assert repo.get_operation_request(request.action_id) == request
    events = repo.list_operation_events(request.action_id)
    assert [(e.from_state, e.to_state) for e in events] == [
        (None, "CREATED"),
        ("CREATED", "SENT"),
        ("SENT", "RECEIVED"),
        ("RECEIVED", "ACCEPTED"),
        ("ACCEPTED", "IN_PROGRESS"),
        ("IN_PROGRESS", "COMPLETED"),
    ]
    assert [e.id for e in events] == sorted(e.id for e in events)
    assert [e.at for e in events] == sorted(e.at for e in events)  # in ordine di tempo


def test_la_creazione_ha_la_sua_riga_e_nessuna_decisione(
    lifecycle: RequestLifecycle, repo: Repository
) -> None:
    request = lifecycle.create(make_draft(), POLICE)
    (event,) = repo.list_operation_events(request.action_id)
    assert (event.from_state, event.to_state, event.reason) == (None, "CREATED", "Richiesta creata")
    assert repo.list_decisions("run_1") == []


def test_l_invio_e_l_esito_scrivono_una_decisione_gli_avanzamenti_no(
    lifecycle: RequestLifecycle, repo: Repository
) -> None:
    request = lifecycle.create(make_draft(), POLICE)
    request = lifecycle.advance(request, "SENT")
    request = lifecycle.advance(request, "RECEIVED")
    request = lifecycle.advance(request, "ACCEPTED", actor=POLICE, note="Pattuglia disponibile")
    request = lifecycle.advance(request, "IN_PROGRESS")
    lifecycle.advance(request, "COMPLETED")
    sent, accepted = repo.list_decisions("run_1")  # RECEIVED, IN_PROGRESS e COMPLETED: nessuna
    assert (sent.seq, accepted.seq) == (1, 2)
    assert sent.actor == ORCHESTRATOR
    assert sent.decision == f"Richiesta {request.action_id} inviata (simulata)"
    assert (
        "nessun ente reale" in sent.rationale and "Polizia Municipale (virtuale)" in sent.rationale
    )
    assert accepted.actor == POLICE
    assert accepted.decision == f"Richiesta {request.action_id} accettata"
    assert accepted.rationale == "Pattuglia disponibile"
    assert sent.refs == [request.action_id, "SENT"]


def test_il_rifiuto_ha_codice_motivo_e_decisione_del_dipartimento(
    lifecycle: RequestLifecycle, repo: Repository
) -> None:
    request = received(lifecycle)
    rejected = lifecycle.advance(
        request,
        "REJECTED",
        actor=POLICE,
        reject_code="UNAVAILABLE",
        reject_reason="Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, 6 già impegnate",
    )
    assert (rejected.state, rejected.reject_code) == ("REJECTED", "UNAVAILABLE")
    stored = repo.get_operation_request(request.action_id)
    assert stored == rejected
    event = repo.list_operation_events(request.action_id)[-1]
    assert (event.from_state, event.to_state) == ("RECEIVED", "REJECTED")
    assert event.reason == rejected.reject_reason
    decision = repo.list_decisions("run_1")[-1]
    assert decision.actor == POLICE
    assert decision.decision == f"Richiesta {request.action_id} rifiutata (UNAVAILABLE)"
    assert decision.rationale == rejected.reject_reason


@pytest.mark.parametrize("target", ["ACCEPTED", "IN_PROGRESS", "COMPLETED", "SENT", "REJECTED"])
def test_dopo_un_rifiuto_non_si_va_da_nessuna_parte(
    lifecycle: RequestLifecycle, repo: Repository, target: RequestState
) -> None:
    request = received(lifecycle)
    request = lifecycle.advance(
        request, "REJECTED", actor=POLICE, reject_code="X", reject_reason="no"
    )
    with pytest.raises(InvalidTransition):
        lifecycle.advance(request, target, actor=POLICE, reject_code="X", reject_reason="no")
    assert repo.get_operation_request(request.action_id) == request


# --- ciò che non si scrive -----------------------------------------------------------------------


@pytest.mark.parametrize("target", ["RECEIVED", "ACCEPTED", "REJECTED", "IN_PROGRESS", "COMPLETED"])
def test_un_salto_non_scrive_niente(
    lifecycle: RequestLifecycle, repo: Repository, target: RequestState
) -> None:
    request = lifecycle.create(make_draft(), POLICE)
    with pytest.raises(InvalidTransition):
        lifecycle.advance(request, target, actor=POLICE, reject_code="X", reject_reason="no")
    assert repo.get_operation_request(request.action_id) == request
    assert len(repo.list_operation_events(request.action_id)) == 1
    assert repo.list_decisions("run_1") == []


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"reject_code": "UNAVAILABLE"},
        {"reject_reason": "esaurite"},
        {"reject_code": "  ", "reject_reason": "esaurite"},
        {"reject_code": "UNAVAILABLE", "reject_reason": ""},
    ],
)
def test_un_rifiuto_senza_codice_o_motivo_e_un_errore(
    lifecycle: RequestLifecycle, repo: Repository, fields: dict[str, str]
) -> None:
    request = received(lifecycle)
    with pytest.raises(ValidationError, match="REJECTED richiede reject_code e reject_reason"):
        lifecycle.advance(request, "REJECTED", actor=POLICE, **fields)
    assert repo.get_operation_request(request.action_id) == request  # ancora RECEIVED
    assert [e.to_state for e in repo.list_operation_events(request.action_id)][-1] == "RECEIVED"


def test_un_codice_di_rifiuto_su_un_altra_transizione_e_un_errore(
    lifecycle: RequestLifecycle,
) -> None:
    request = received(lifecycle)
    with pytest.raises(ValidationError, match="hanno senso solo con state REJECTED"):
        lifecycle.advance(request, "ACCEPTED", actor=POLICE, reject_code="X")


@pytest.mark.parametrize("target", ["ACCEPTED", "REJECTED"])
def test_l_esito_vuole_chi_decide(lifecycle: RequestLifecycle, target: RequestState) -> None:
    request = received(lifecycle)
    with pytest.raises(LifecycleError, match="manca chi decide"):
        lifecycle.advance(request, target, reject_code="X", reject_reason="no")


def test_se_la_decisione_non_si_scrive_non_si_scrive_nemmeno_la_transizione(
    lifecycle: RequestLifecycle, repo: Repository
) -> None:
    """Tutto o niente: un attore che non è uno slug fa fallire la decisione, e con lei la riga e
    il cambio di stato (stessa transazione)."""
    request = received(lifecycle)
    with pytest.raises(ValidationError):
        lifecycle.advance(request, "ACCEPTED", actor="Non Valido")
    assert repo.get_operation_request(request.action_id) == request
    assert [e.to_state for e in repo.list_operation_events(request.action_id)][-1] == "RECEIVED"
    assert [d.actor for d in repo.list_decisions("run_1")] == [ORCHESTRATOR]  # solo l'invio


def test_due_esiti_insieme_non_riescono_entrambi(
    lifecycle: RequestLifecycle, repo: Repository
) -> None:
    """Una risposta manuale e un timeout che partono dalla stessa fotografia della richiesta: il
    secondo trova lo stato cambiato (`StateConflict`) e non scrive niente."""
    request = received(lifecycle)
    lifecycle.advance(request, "ACCEPTED", actor="user", note="Ok dall'operatore")
    with pytest.raises(StateConflict, match="attesa in RECEIVED, è in ACCEPTED"):
        lifecycle.advance(
            request, "REJECTED", actor="system", reject_code="TIMEOUT", reject_reason="Nessuna"
        )
    stored = repo.get_operation_request(request.action_id)
    assert stored is not None and stored.state == "ACCEPTED"
    events = repo.list_operation_events(request.action_id)
    assert [e.to_state for e in events].count("REJECTED") == 0
    assert [d.actor for d in repo.list_decisions("run_1")] == [ORCHESTRATOR, "user"]


# --- creazione ----------------------------------------------------------------------------------


def test_il_server_decide_identificativo_dipartimento_e_stato(
    lifecycle: RequestLifecycle, repo: Repository
) -> None:
    first = lifecycle.create(make_draft(), POLICE)
    second = lifecycle.create(make_draft(target_label="Incrocio Piazza Sannazaro"), POLICE)
    other = lifecycle.create(make_draft(run_id="run_2"), POLICE)
    assert [first.action_id, second.action_id] == ["act_1_001", "act_1_002"]
    assert other.action_id == "act_2_001"  # la numerazione è di ogni run
    assert len({first.action_id, second.action_id, other.action_id}) == 3
    assert [r.action_id for r in repo.list_operation_requests("run_1")] == [
        "act_1_001",
        "act_1_002",
    ]
    assert first.state == "CREATED" and first.department == POLICE


def test_la_richiesta_e_sempre_simulata(lifecycle: RequestLifecycle, repo: Repository) -> None:
    request = lifecycle.create(make_draft(), POLICE)
    assert request.simulation is True
    with repo._connection() as conn:
        assert conn.execute("SELECT simulation FROM operation_requests").fetchone()[0] == 1
    with pytest.raises(ValidationError, match="simulation"):
        make_draft(simulation=False)
    with pytest.raises(ValidationError, match="simulation"):
        make_draft(simulation=None)


def test_il_dipartimento_deve_gestire_il_tipo(lifecycle: RequestLifecycle) -> None:
    with pytest.raises(UnsupportedRequestType, match="'public_comms' non gestisce 'traffic_post'"):
        lifecycle.create(make_draft(), "public_comms")
    with pytest.raises(UnknownDepartment):
        lifecycle.create(make_draft(), "ente_reale")


def test_il_run_deve_esistere(lifecycle: RequestLifecycle, repo: Repository) -> None:
    with pytest.raises(RunNotFound, match="'run_9'"):
        lifecycle.create(make_draft(run_id="run_9"), POLICE)
    assert repo.list_operation_requests("run_9") == []


# --- alternative -------------------------------------------------------------------------------


def rejected(lifecycle: RequestLifecycle, **draft: str) -> OperationRequest:
    request = lifecycle.create(make_draft(**draft), POLICE)
    request = lifecycle.advance(request, "SENT")
    request = lifecycle.advance(request, "RECEIVED")
    return lifecycle.advance(
        request, "REJECTED", actor=POLICE, reject_code="UNAVAILABLE", reject_reason="esaurite"
    )


def test_un_alternativa_porta_alternative_of(lifecycle: RequestLifecycle, repo: Repository) -> None:
    original = rejected(lifecycle)
    alternative = lifecycle.create(
        make_draft(type="signal_plan_change", alternative_of=original.action_id, iteration=2),
        "traffic_control",
    )
    assert alternative.alternative_of == original.action_id
    assert alternative.department == "traffic_control"
    stored = repo.get_operation_request(alternative.action_id)
    assert stored is not None and stored.alternative_of == original.action_id


def test_un_alternativa_si_propone_solo_a_una_richiesta_rifiutata(
    lifecycle: RequestLifecycle,
) -> None:
    pending = lifecycle.create(make_draft(), POLICE)
    with pytest.raises(InvalidAlternative, match="CREATED"):
        lifecycle.create(
            make_draft(type="signal_plan_change", alternative_of=pending.action_id),
            "traffic_control",
        )


def test_un_alternativa_sostituisce_una_richiesta_dello_stesso_run(
    lifecycle: RequestLifecycle,
) -> None:
    original = rejected(lifecycle)
    with pytest.raises(InvalidAlternative, match="non è una richiesta di questo run"):
        lifecycle.create(
            make_draft(
                run_id="run_2", type="signal_plan_change", alternative_of=original.action_id
            ),
            "traffic_control",
        )
    with pytest.raises(InvalidAlternative, match="non è una richiesta di questo run"):
        lifecycle.create(
            make_draft(type="signal_plan_change", alternative_of="act_fantasma"), "traffic_control"
        )
