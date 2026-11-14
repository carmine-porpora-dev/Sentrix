from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from app.models.event import Event
from app.models.operations import ACTIVE_STATES, OperationRequest
from app.operations import resources
from app.operations.resources import InvalidPayload


@dataclass(frozen=True)
class Accept:
    reason: str


@dataclass(frozen=True)
class Reject:
    code: str
    reason: str


Verdict = Accept | Reject


@dataclass(frozen=True)
class RuleState:
    """Ciò che una regola può guardare."""

    event: Event
    requests: Sequence[OperationRequest]  # tutte quelle del run, in qualunque stato
    add_runs_default: int  # `n` di add_runs se la richiesta non lo dice (engine.yaml)


Rule = Callable[[OperationRequest, RuleState], Verdict]


def _balance(
    request: OperationRequest, state: RuleState, resource: str
) -> resources.ResourceBalance:
    return resources.balance(
        state.event,
        state.requests,
        resource,
        request.window,
        state.add_runs_default,
        excluding=request.action_id,
    )


def edge_keys(target: str) -> list[str]:
    """Le chiavi `u-v-k` di un bersaglio fatto di archi (separate da virgola)."""
    return [key.strip() for key in target.split(",") if key.strip()]


def _active(
    state: RuleState, request: OperationRequest, types: frozenset[str]
) -> list[OperationRequest]:
    return [
        other
        for other in state.requests
        if other.type in types
        and other.window == request.window
        and other.state in ACTIVE_STATES
        and other.action_id != request.action_id
    ]


def closed_edges(request: OperationRequest, state: RuleState) -> set[str]:
    """Gli archi chiusi nella finestra della richiesta: dall'Evento e dalle `close_road` attive."""
    closed = {
        key
        for closure in state.event.closures
        if closure.mode == "closed"
        for key in closure.edge_keys
    }
    for other in _active(state, request, frozenset({"close_road"})):
        closed.update(edge_keys(other.target))
    return closed


# --- Polizia Municipale -------------------------------------------------------------------------


def municipal_police(request: OperationRequest, state: RuleState) -> Verdict:
    """Accetta se `totali − impegnate − già assegnate nel run(finestra) ≥ 1`."""
    patrols = _balance(request, state, resources.PATROLS)
    if patrols.remaining >= 1:
        return Accept(
            f"Pattuglia disponibile: {patrols.remaining} libere su {patrols.total} nella "
            f"finestra {state.event.window_span(request.window)}"
        )
    return Reject(
        "UNAVAILABLE",
        f"Pattuglie esaurite nella finestra {state.event.window_span(request.window)}: "
        f"{patrols.total} totali, {patrols.used} già impegnate ai varchi",
    )


# --- Controllo Traffico -------------------------------------------------------------------------


def traffic_control(request: OperationRequest, state: RuleState) -> Verdict:
    """`signal_plan_change`: accetta se le modifiche già accettate sono meno del massimo.
    `close_road` e `detour_signage`: rifiuta se un arco bersaglio è già chiuso o già deviazione."""
    if request.type == "signal_plan_change":
        changes = _balance(request, state, resources.SIGNAL_CHANGES)
        if changes.remaining >= 1:
            return Accept(
                f"Modifica semaforica consentita: {changes.used} su {changes.total} usate "
                f"nella finestra {state.event.window_span(request.window)}"
            )
        return Reject(
            "LIMIT_REACHED",
            f"Limite di modifiche semaforiche raggiunto nella finestra "
            f"{state.event.window_span(request.window)}: {changes.used} su {changes.total}",
        )
    keys = edge_keys(request.target)
    if not keys:
        return Reject("INVALID_REQUEST", f"{request.type}: nessun arco indicato nel bersaglio")
    closed = closed_edges(request, state)
    detoured = {
        key
        for other in _active(state, request, frozenset({"detour_signage"}))
        for key in edge_keys(other.target)
    }
    if conflict := [key for key in keys if key in closed]:
        return Reject(
            "CONFLICT_ACTIVE_DETOUR", f"L'arco {conflict[0]} è già chiuso dal dispositivo"
        )
    if conflict := [key for key in keys if key in detoured]:
        return Reject("CONFLICT_ACTIVE_DETOUR", f"L'arco {conflict[0]} è già una deviazione attiva")
    return Accept(f"Nessun conflitto sugli archi: {', '.join(keys)}")


# --- Controllo Trasporti ------------------------------------------------------------------------


def transport_control(request: OperationRequest, state: RuleState) -> Verdict:
    """`add_runs`: accetta se i bus di riserva residui sono ≥ `n`. `extend_hours`: se i
    prolungamenti residui sono ≥ 1. `bus_detour`: rifiuta se un arco nominato è chiuso.
    `stop_suspension`: accetta."""
    span = state.event.window_span(request.window)
    if request.type == "add_runs":
        wanted = resources.units(request, state.add_runs_default)
        buses = _balance(request, state, resources.RESERVE_BUSES)
        if buses.remaining >= wanted:
            return Accept(
                f"Bus di riserva disponibili: servono {wanted}, ne restano {buses.remaining} "
                f"su {buses.total} nella finestra {span}"
            )
        return Reject(
            "NO_RESERVE",
            f"Bus di riserva insufficienti nella finestra {span}: servono {wanted}, "
            f"ne restano {buses.remaining} su {buses.total}",
        )
    if request.type == "extend_hours":
        extensions = _balance(request, state, resources.HOUR_EXTENSIONS)
        if extensions.remaining >= 1:
            return Accept(
                f"Prolungamento d'orario disponibile: {extensions.remaining} su "
                f"{extensions.total} nella finestra {span}"
            )
        return Reject(
            "NO_EXTENSION_LEFT",
            f"Prolungamenti d'orario esauriti nella finestra {span}: {extensions.total} totali",
        )
    if request.type == "bus_detour":
        avoided = request.payload.get("avoid_edge_keys")
        if (
            not isinstance(avoided, list)
            or not avoided
            or not all(isinstance(key, str) for key in avoided)
        ):
            return Reject(
                "INVALID_REQUEST", "bus_detour: serve 'avoid_edge_keys', una lista non vuota"
            )
        closed = closed_edges(request, state)
        if conflict := [key for key in avoided if key in closed]:
            return Reject(
                "CONFLICT_CLOSED_EDGE", f"L'arco {conflict[0]} è chiuso: la deviazione lo cita"
            )
        return Accept("Deviazione compatibile con le chiusure")
    return Accept(f"Sospensione della fermata {request.target_label} accettata")


# --- Comunicazione Pubblica ---------------------------------------------------------------------


def public_comms(request: OperationRequest, state: RuleState) -> Verdict:
    """Rifiuta se il testo cita una misura (per `action_id` o etichetta) che non è in vigore."""
    text = request.payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return Reject(
            "INVALID_REQUEST", "citizen_notice: manca il testo dell'avviso (payload.text)"
        )
    lowered = text.casefold()
    measures = [
        other
        for other in state.requests
        if other.type != "citizen_notice" and other.action_id != request.action_id
    ]
    approved_labels = {
        other.target_label.casefold() for other in measures if other.state in ACTIVE_STATES
    }
    # Un'etichetta approvata può contenerne una non approvata («Archi a monte di Piazza Vittoria»
    # contiene «Piazza Vittoria»): le etichette approvate si tolgono dal testo prima di cercare le
    # altre, dalla più lunga, e si cita per etichetta solo ciò che resta.
    outside_approved = lowered
    for approved in sorted(approved_labels, key=len, reverse=True):
        outside_approved = outside_approved.replace(approved, " ")
    for other in measures:
        if other.state in ACTIVE_STATES:
            continue
        by_id = other.action_id.casefold() in lowered
        label = other.target_label.casefold()
        by_label = label in outside_approved and label not in approved_labels
        if by_id or by_label:
            return Reject(
                "UNAPPROVED_MEASURE",
                f"Il testo cita la misura {other.action_id} ({other.target_label}), che è "
                f"{other.state}: si cita solo ciò che è stato approvato",
            )
    return Accept("Il testo cita solo misure approvate")


RULES: Mapping[str, Rule] = MappingProxyType(
    {
        "municipal_police": municipal_police,
        "traffic_control": traffic_control,
        "transport_control": transport_control,
        "public_comms": public_comms,
    }
)


def evaluate(request: OperationRequest, state: RuleState) -> Verdict:
    """La risposta del dipartimento della richiesta. Un payload malformato è un rifiuto con il suo
    motivo (`INVALID_REQUEST`), mai un'eccezione che ferma il run."""
    rule = RULES.get(request.department)
    if rule is None:
        return Reject("INVALID_REQUEST", f"Dipartimento '{request.department}' senza regole")
    try:
        return rule(request, state)
    except InvalidPayload as exc:
        return Reject("INVALID_REQUEST", str(exc))
