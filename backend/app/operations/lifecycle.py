import threading
from collections.abc import Callable, Mapping
from datetime import datetime

from app.clock import now_rome
from app.db.repository import NewDecision, Repository
from app.models.operations import OperationRequest, OperationRequestDraft, RequestState
from app.operations.registry import DepartmentRegistry

TRANSITIONS: Mapping[RequestState, frozenset[RequestState]] = {
    "CREATED": frozenset({"SENT"}),
    "SENT": frozenset({"RECEIVED"}),
    "RECEIVED": frozenset({"ACCEPTED", "REJECTED"}),
    "ACCEPTED": frozenset({"IN_PROGRESS"}),
    "IN_PROGRESS": frozenset({"COMPLETED"}),
    "REJECTED": frozenset(),
    "COMPLETED": frozenset(),
}

ORCHESTRATOR = "orchestrator"


class LifecycleError(Exception):
    """Una richiesta che non si può creare o far avanzare."""


class InvalidTransition(LifecycleError):
    def __init__(self, action_id: str, from_state: RequestState, to_state: RequestState) -> None:
        allowed = ", ".join(sorted(TRANSITIONS[from_state])) or "nessuna"
        super().__init__(
            f"Richiesta '{action_id}': da {from_state} non si va a {to_state} "
            f"(consentite: {allowed})"
        )
        self.action_id = action_id
        self.from_state = from_state
        self.to_state = to_state


class RunNotFound(LifecycleError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"Run '{run_id}' non trovato")
        self.run_id = run_id


class InvalidAlternative(LifecycleError):
    """`alternative_of` non indica una richiesta rifiutata dello stesso run."""


def check_transition(action_id: str, from_state: RequestState, to_state: RequestState) -> None:
    """Solleva `InvalidTransition` se da `from_state` non si può andare a `to_state`."""
    if to_state not in TRANSITIONS[from_state]:
        raise InvalidTransition(action_id, from_state, to_state)


class RequestLifecycle:
    """Crea le richieste e le fa avanzare, scrivendo la storia di ognuna."""

    def __init__(
        self,
        repo: Repository,
        registry: DepartmentRegistry,
        clock: Callable[[], datetime] = now_rome,
    ) -> None:
        self._repo = repo
        self._registry = registry
        self._clock = clock
        self._creating = threading.Lock()  # il numero della richiesta si assegna contando

    def create(self, draft: OperationRequestDraft, department_id: str) -> OperationRequest:
        """Una richiesta `CREATED` del dipartimento `department_id`, che deve gestirne il tipo.
        Il dipartimento, l'identificativo e lo stato li decide il Centro, non chi la chiede."""
        self._registry.accepting(department_id, draft.type)
        if self._repo.get_run(draft.run_id) is None:
            raise RunNotFound(draft.run_id)
        if draft.alternative_of is not None:
            self._check_alternative(draft)
        with self._creating:
            number = len(self._repo.list_operation_requests(draft.run_id)) + 1
            request = OperationRequest.model_validate(
                {
                    **draft.model_dump(),
                    "action_id": f"act_{draft.run_id.removeprefix('run_')}_{number:03d}",
                    "department": department_id,
                    "state": "CREATED",
                }
            )
            self._repo.add_operation_request(request, at=self._clock(), reason="Richiesta creata")
        return request

    def _check_alternative(self, draft: OperationRequestDraft) -> None:
        rejected = self._repo.get_operation_request(draft.alternative_of or "")
        if rejected is None or rejected.run_id != draft.run_id:
            raise InvalidAlternative(
                f"'{draft.alternative_of}' non è una richiesta di questo run: un'alternativa "
                "sostituisce una richiesta rifiutata dello stesso run"
            )
        if rejected.state != "REJECTED":
            raise InvalidAlternative(
                f"'{rejected.action_id}' è {rejected.state}: si propone un'alternativa solo a una "
                "richiesta rifiutata"
            )

    def advance(
        self,
        request: OperationRequest,
        to_state: RequestState,
        *,
        actor: str | None = None,
        note: str | None = None,
        reject_code: str | None = None,
        reject_reason: str | None = None,
    ) -> OperationRequest:
        """Porta la richiesta a `to_state` e ne scrive la storia.

        - `actor` è chi decide l'esito (`ACCEPTED`, `REJECTED`): l'id del dipartimento, `user` per
          una risposta manuale, `system` per un timeout. Obbligatorio per l'esito, ignorato altrove.
        - `note` è il motivo, scritto nella riga di `operation_events` e (per l'esito) nella
          decisione.
        - Un rifiuto vuole `reject_code` e `reject_reason` non vuoti (lo impone la richiesta).
        """
        check_transition(request.action_id, request.state, to_state)
        if to_state in ("ACCEPTED", "REJECTED") and actor is None:
            raise LifecycleError(f"Richiesta '{request.action_id}': manca chi decide l'esito")
        # Si rivalida sempre: un rifiuto senza codice o motivo, o un codice di rifiuto su un'altra
        # transizione, è un errore della richiesta stessa (01 3), non una transizione da scrivere.
        updated = OperationRequest.model_validate(
            {
                **request.model_dump(),
                "state": to_state,
                "reject_code": reject_code,
                "reject_reason": reject_reason,
            }
        )
        reason = reject_reason if to_state == "REJECTED" else note
        self._repo.transition_operation_request(
            updated,
            from_state=request.state,
            reason=reason,
            decision=self._decision(updated, actor, note),
            at=self._clock(),
        )
        return updated

    def _decision(
        self, request: OperationRequest, actor: str | None, note: str | None
    ) -> NewDecision | None:
        """La voce del log di una transizione, se ne ha una: l'invio e l'esito."""
        refs = (request.action_id, request.state)
        match request.state:
            case "SENT":
                department = self._registry.department(request.department)
                return NewDecision(
                    actor=ORCHESTRATOR,
                    decision=f"Richiesta {request.action_id} inviata (simulata)",
                    rationale=(
                        f"{request.type} su {request.target_label} ({request.window}) "
                        f"a {department.label}: nessun ente reale è coinvolto"
                    ),
                    refs=refs,
                )
            case "ACCEPTED":
                return NewDecision(
                    actor=actor or "",
                    decision=f"Richiesta {request.action_id} accettata",
                    rationale=note or "Richiesta accettata",
                    refs=refs,
                )
            case "REJECTED":
                return NewDecision(
                    actor=actor or "",
                    decision=f"Richiesta {request.action_id} rifiutata ({request.reject_code})",
                    rationale=request.reject_reason or "",
                    refs=refs,
                )
            case _:
                return None
