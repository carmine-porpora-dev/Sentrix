from typing import Any

import pytest
from pydantic import ValidationError

from app.models.operations import FIXED_ACTORS, Decision, OperationRequest
from app.models.run import FINAL_STATES, MAX_REPLANS, SENT_STATUSES, PlanItem, Run
from tests.support import DELETE, mutated

EVIDENCE = "m.run42.it1.road.critical_intersection.vc"
HASH = "b" * 64


def error_text(model: Any, data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        model.model_validate(data)
    return str(info.value)


# --- Run -----------------------------------------------------------------------------------


def run(state: str = "ANALYZE", **overrides: Any) -> dict[str, Any]:
    finished = state in ("DONE", "ERROR")
    data: dict[str, Any] = {
        "id": "run42",
        "event_id": "match_2027",
        "event_revision": 3,
        "attendance_level": "mid",
        "state": state,
        "iteration": 1,
        "replans": 1,
        "started_at": "2026-11-07T10:00:00+01:00",
        "ended_at": "2026-11-07T10:01:10+01:00" if finished else None,
        "params_hash": HASH,
        "seed": 42,
        "llm_mode": "cache_only",
        "error": "Il motore ha superato il tempo massimo" if state == "ERROR" else None,
    }
    return {**data, **overrides}


def test_run_valido_in_corso_e_terminato() -> None:
    running = Run.model_validate(run("AWAIT"))
    assert (running.id, running.event_id, running.state, running.ended_at) == (
        "run42",
        "match_2027",
        "AWAIT",
        None,
    )
    done = Run.model_validate(run("DONE"))
    assert done.ended_at is not None and done.error is None
    assert Run.model_validate_json(done.model_dump_json()) == done


@pytest.mark.parametrize(
    "state",
    [
        "INTAKE",
        "ANALYZE",
        "RECONCILE",
        "PLAN",
        "DISPATCH",
        "AWAIT",
        "REPLAN",
        "VERIFY",
        "DONE",
        "ERROR",
    ],
)
def test_tutti_i_dieci_stati(state: str) -> None:
    assert Run.model_validate(run(state)).state == state


def test_costanti_del_dominio() -> None:
    assert MAX_REPLANS == 3  # spech 2.1: massimo 3 ripianificazioni
    assert {"DONE", "ERROR"} == FINAL_STATES


@pytest.mark.parametrize("replans", [0, 1, 2, 3])
def test_ripianificazioni_da_0_a_3(replans: int) -> None:
    assert Run.model_validate(run(replans=replans)).replans == replans


def test_confini_validi_del_run() -> None:
    # Iterazione 0 = «senza misure». Un run può finire nell'istante in cui è iniziato (orologio
    # fermo nei test): solo una fine PRIMA dell'inizio è incoerente.
    assert Run.model_validate(run(iteration=0)).iteration == 0
    same = Run.model_validate(run("DONE", ended_at="2026-11-07T10:00:00+01:00"))
    assert same.ended_at == same.started_at


ENDED = {"ended_at": "2026-11-07T10:01:10+01:00"}  # un run terminato ha sempre ended_at

RUN_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("quattro ripianificazioni", {"replans": 4}, "less than or equal to 3"),
    ("ripianificazioni negative", {"replans": -1}, "greater than or equal to 0"),
    ("iterazione negativa", {"iteration": -1}, "greater than or equal to 0"),
    ("revisione zero", {"event_revision": 0}, "greater than or equal to 1"),
    ("livello di affluenza sconosciuto", {"attendance_level": "enorme"}, "attendance_level"),
    ("stato sconosciuto", {"state": "RUNNING"}, "state"),
    ("modalità LLM sconosciuta", {"llm_mode": "magia"}, "llm_mode"),
    ("hash corto", {"params_hash": "ab12"}, "String should match pattern"),
    ("hash in maiuscolo", {"params_hash": "B" * 64}, "String should match pattern"),
    ("seed negativo", {"seed": -1}, "greater than or equal to 0"),
    ("id del run con un punto", {"id": "run.42"}, "String should match pattern"),
    ("id dell'evento non è uno slug", {"event_id": "Match 2027"}, "String should match pattern"),
    ("run in corso con ended_at", {"ended_at": "2026-11-07T10:05:00+01:00"}, "se e solo se"),
    ("run terminato senza ended_at", {"state": "DONE", "ended_at": None}, "se e solo se"),
    (
        "fine prima dell'inizio",
        {"state": "DONE", "ended_at": "2026-11-07T09:00:00+01:00"},
        "non può precedere",
    ),
    ("ERROR senza messaggio", {**ENDED, "state": "ERROR", "error": None}, "error è valorizzato"),
    (
        "ERROR con messaggio vuoto",
        {**ENDED, "state": "ERROR", "error": "  "},
        "error è valorizzato",
    ),
    ("messaggio di errore su un run non in errore", {"error": "qualcosa"}, "error è valorizzato"),
    ("istante senza fuso", {"started_at": "2026-11-07T10:00:00"}, "timezone"),
    ("chiave sconosciuta", {"colore": "rosso"}, "Extra inputs are not permitted"),
]


@pytest.mark.parametrize(
    ("name", "overrides", "fragment"), RUN_CASES, ids=[c[0] for c in RUN_CASES]
)
def test_run_non_valido(name: str, overrides: dict[str, Any], fragment: str) -> None:
    assert fragment in error_text(Run, {**run(), **overrides}), name


def test_il_seed_non_ha_un_default_nel_modello() -> None:
    # Il seed è in engine.yaml (unica fonte): chi crea il run lo copia da lì, non lo eredita da qui.
    assert "seed\n  Field required" in error_text(Run, mutated(run(), ("seed",), DELETE))


def test_run_immutabile() -> None:
    r = Run.model_validate(run())
    with pytest.raises(ValidationError, match="frozen"):
        r.state = "DONE"  # type: ignore[misc]


# --- PlanItem ------------------------------------------------------------------------------


def recommendation() -> dict[str, Any]:
    return {
        "measure_type": "traffic_post",
        "target": "node_123",
        "department": "municipal_police",
        "window": "arrival",
        "rationale": "Rapporto v/c oltre la soglia critica",
        "evidence_ids": [EVIDENCE],
    }


def item(status: str = "proposed", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"seq": 1, "recommendation": recommendation(), "action_id": None,
                            "status": status, "replaced_by": None, "note": None}  # fmt: skip
    return {**data, **overrides}


GOOD_ITEMS = [
    item("proposed"),
    item("accepted", action_id="act1"),
    item("rejected", action_id="act1"),
    item("replaced", action_id="act1", replaced_by=2),
    item("human_decision_required"),
    item("human_decision_required", action_id="act1", note="nessuna alternativa rimasta"),
    item("discarded", note="duplicato: la stessa misura è già nel piano"),
]


@pytest.mark.parametrize(
    "data", GOOD_ITEMS, ids=[f"{d['status']}{'+az' if d['action_id'] else ''}" for d in GOOD_ITEMS]
)
def test_elementi_di_piano_validi(data: dict[str, Any]) -> None:
    p = PlanItem.model_validate(data)
    assert p.status == data["status"] and p.recommendation.measure_type == "traffic_post"
    assert PlanItem.model_validate_json(p.model_dump_json()) == p


PLAN_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("accettato senza richiesta", item("accepted"), "serve l'action_id"),
    ("rifiutato senza richiesta", item("rejected"), "serve l'action_id"),
    ("sostituito senza richiesta", item("replaced", replaced_by=2), "serve l'action_id"),
    ("proposto già inviato", item("proposed", action_id="act1"), "non è stata inviata"),
    ("scartato già inviato", item("discarded", action_id="act1", note="x"), "non è stata inviata"),
    ("sostituito senza alternativa", item("replaced", action_id="act1"), "serve replaced_by"),
    (
        "sostituito da se stesso",
        item("replaced", action_id="act1", replaced_by=1),
        "diverso da seq",
    ),
    (
        "alternativa su un elemento accettato",
        item("accepted", action_id="act1", replaced_by=2),
        "solo con status 'replaced'",
    ),
    ("scarto senza nota", item("discarded"), "serve la nota"),
    ("scarto con nota di spazi", item("discarded", note="   "), "serve la nota"),
    ("seq zero", item("proposed", seq=0), "greater than or equal to 1"),
    (
        "replaced_by zero",
        item("replaced", action_id="act1", replaced_by=0),
        "greater than or equal to 1",
    ),
    ("stato sconosciuto", item("fatto"), "status"),
    (
        "raccomandazione senza evidenze",
        item(recommendation={**recommendation(), "evidence_ids": []}),
        "at least 1 item",
    ),
    ("action_id con punto", item("accepted", action_id="act.1"), "String should match pattern"),
]


@pytest.mark.parametrize(("name", "data", "fragment"), PLAN_CASES, ids=[c[0] for c in PLAN_CASES])
def test_elemento_di_piano_non_valido(name: str, data: dict[str, Any], fragment: str) -> None:
    assert fragment in error_text(PlanItem, data), name


def test_confini_validi_dell_elemento_di_piano() -> None:
    # replaced_by = 1 è un'alternativa legittima (l'elemento 2 sostituito dal primo).
    p = PlanItem.model_validate(item("replaced", seq=2, action_id="act1", replaced_by=1))
    assert (p.seq, p.replaced_by) == (2, 1)


def test_stati_con_richiesta_inviata() -> None:
    assert {"accepted", "rejected", "replaced"} == SENT_STATUSES


# --- OperationRequest ----------------------------------------------------------------------


def request(state: str = "CREATED", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "action_id": "act1",
        "run_id": "run42",
        "iteration": 1,
        "department": "municipal_police",
        "type": "traffic_post",
        "target": "node_123",
        "target_label": "Piazza Vittoria",
        "target_geo": {"lat": 40.8345, "lon": 14.2440},
        "window": "arrival",
        "priority": "normal",
        "payload": {"note": "presidio ai varchi"},
        "state": state,
        "reject_code": "NO_PATROLS" if state == "REJECTED" else None,
        "reject_reason": "Nessuna pattuglia disponibile" if state == "REJECTED" else None,
        "alternative_of": None,
        "simulation": True,
    }
    return {**data, **overrides}


@pytest.mark.parametrize(
    "state", ["CREATED", "SENT", "RECEIVED", "ACCEPTED", "REJECTED", "IN_PROGRESS", "COMPLETED"]
)
def test_tutti_i_sette_stati_della_richiesta(state: str) -> None:
    r = OperationRequest.model_validate(request(state))
    assert r.state == state and r.simulation is True
    assert OperationRequest.model_validate_json(r.model_dump_json()) == r


def test_richiesta_alternativa_a_una_rifiutata() -> None:
    alt = OperationRequest.model_validate(
        request("CREATED", action_id="act2", alternative_of="act1")
    )
    assert alt.alternative_of == "act1"


def test_richiesta_senza_posizione_ne_payload() -> None:
    data = {k: v for k, v in request().items() if k not in ("target_geo", "payload")}
    r = OperationRequest.model_validate(data)
    assert r.target_geo is None and r.payload == {}


OP_CASES: list[tuple[str, dict[str, Any], str]] = [
    (
        "rifiutata senza codice",
        request("REJECTED", reject_code=None),
        "REJECTED richiede reject_code",
    ),
    (
        "rifiutata senza motivo",
        request("REJECTED", reject_reason=None),
        "REJECTED richiede reject_code",
    ),
    (
        "rifiutata con codice vuoto",
        request("REJECTED", reject_code=" "),
        "REJECTED richiede reject_code",
    ),
    (
        "rifiutata con motivo vuoto",
        request("REJECTED", reject_reason=""),
        "REJECTED richiede reject_code",
    ),
    (
        "rifiutata con motivo di soli spazi",
        request("REJECTED", reject_reason="  "),
        "REJECTED richiede reject_code",
    ),
    (
        "accettata con un codice di rifiuto",
        request("ACCEPTED", reject_code="X"),
        "solo con state REJECTED",
    ),
    (
        "inviata con un motivo di rifiuto",
        request("SENT", reject_reason="x"),
        "solo con state REJECTED",
    ),
    ("alternativa di se stessa", request(alternative_of="act1"), "alternativa di se stessa"),
    ("iterazione zero", request(iteration=0), "greater than or equal to 1"),
    (
        "dipartimento non è uno slug",
        request(department="Polizia Municipale"),
        "String should match pattern",
    ),
    ("tipo non è uno slug", request(type="Posto di blocco"), "String should match pattern"),
    ("bersaglio vuoto", request(target=""), "at least 1 character"),
    ("etichetta vuota", request(target_label=""), "at least 1 character"),
    ("finestra sconosciuta", request(window="both"), "window"),
    ("priorità sconosciuta", request(priority="urgente"), "priority"),
    ("stato sconosciuto", request("DONE"), "state"),
    ("payload non JSON", request(payload={"x": {1}}), "payload"),
    ("action_id con punto", request(action_id="act.1"), "String should match pattern"),
    ("run_id con spazio", request(run_id="run 42"), "String should match pattern"),
    (
        "posizione fuori range",
        request(target_geo={"lat": 99, "lon": 14}),
        "less than or equal to 90",
    ),
    ("chiave sconosciuta", request(colore="rosso"), "Extra inputs are not permitted"),
]


@pytest.mark.parametrize(("name", "data", "fragment"), OP_CASES, ids=[c[0] for c in OP_CASES])
def test_richiesta_non_valida(name: str, data: dict[str, Any], fragment: str) -> None:
    assert fragment in error_text(OperationRequest, data), name


# --- Il principio «azioni solo simulate» (04 3) --------------------------------


def test_simulation_manca_la_richiesta_e_rifiutata() -> None:
    # 04 3: «Creazione rifiutata se `simulation` manca o è falso». Nessun default che lo nasconda.
    assert "simulation\n  Field required" in error_text(
        OperationRequest, mutated(request(), ("simulation",), DELETE)
    )


@pytest.mark.parametrize("value", [False, 0, None, "true", "True", "yes", "", "false"])
def test_simulation_falso_o_non_vero_e_rifiutato(value: object) -> None:
    assert "simulation" in error_text(OperationRequest, mutated(request(), ("simulation",), value))


@pytest.mark.parametrize("value", [True, 1, 1.0])
def test_simulation_vero_vale_sempre_true_dopo_la_validazione(value: object) -> None:
    # pydantic converte 1 in True: l'invariante («sempre True») regge comunque.
    r = OperationRequest.model_validate(mutated(request(), ("simulation",), value))
    assert r.simulation is True


def test_la_richiesta_e_immutabile() -> None:
    r = OperationRequest.model_validate(request())
    with pytest.raises(ValidationError, match="frozen"):
        r.state = "ACCEPTED"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        r.simulation = False  # type: ignore[misc, assignment]


# --- Decision ------------------------------------------------------------------------------


def decision(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "run_id": "run42",
        "seq": 7,
        "at": "2026-11-07T10:00:30+01:00",
        "actor": "orchestrator",
        "decision": "Invio della richiesta act1 al dipartimento municipal_police",
        "rationale": "Il piano contiene una misura per l'incrocio critico",
        "refs": [EVIDENCE, "act1", "SENT"],
    }
    return {**data, **overrides}


def test_decisione_valida() -> None:
    d = Decision.model_validate(decision())
    assert (d.run_id, d.seq, d.actor) == ("run42", 7, "orchestrator")
    assert d.refs == [EVIDENCE, "act1", "SENT"] and d.at.utcoffset() is not None
    assert Decision.model_validate_json(d.model_dump_json()) == d


def test_il_primo_numero_progressivo_e_1() -> None:
    assert Decision.model_validate(decision(seq=1)).seq == 1


def test_refs_facoltativi() -> None:
    no_refs = {k: v for k, v in decision().items() if k != "refs"}
    assert Decision.model_validate(no_refs).refs == []


@pytest.mark.parametrize(
    "actor", [*FIXED_ACTORS, "municipal_police", "traffic_control", "transport_control"]
)
def test_gli_attori_fissi_e_i_dipartimenti_sono_ammessi(actor: str) -> None:
    assert Decision.model_validate(decision(actor=actor)).actor == actor


def test_gli_attori_fissi_sono_quelli_della_spec() -> None:
    assert set(FIXED_ACTORS) == {
        "system",
        "orchestrator",
        "event_demand",
        "traffic",
        "transit",
        "operations",
        "user",
    }


DECISION_CASES: list[tuple[str, dict[str, Any], str]] = [
    ("seq zero", decision(seq=0), "greater than or equal to 1"),
    ("attore non è uno slug", decision(actor="Polizia Municipale"), "String should match pattern"),
    ("decisione vuota", decision(decision=""), "at least 1 character"),
    ("motivazione vuota", decision(rationale=""), "at least 1 character"),
    ("riferimento vuoto", decision(refs=["act1", " "]), "non possono essere vuoti"),
    ("istante senza fuso", decision(at="2026-11-07T10:00:30"), "timezone"),
    ("run_id con punto", decision(run_id="run.42"), "String should match pattern"),
    ("chiave sconosciuta", decision(colore="rosso"), "Extra inputs are not permitted"),
]


@pytest.mark.parametrize(
    ("name", "data", "fragment"), DECISION_CASES, ids=[c[0] for c in DECISION_CASES]
)
def test_decisione_non_valida(name: str, data: dict[str, Any], fragment: str) -> None:
    assert fragment in error_text(Decision, data), name


def test_la_decisione_e_immutabile() -> None:
    d = Decision.model_validate(decision())
    with pytest.raises(ValidationError, match="frozen"):
        d.rationale = "riscritta"  # type: ignore[misc]
