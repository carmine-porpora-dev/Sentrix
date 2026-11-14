from fastapi import APIRouter, Depends

from app.api.context import AppContext
from app.api.deps import Ctx, require_session
from app.api.errors import ApiError, invalid_field, not_found
from app.api.openapi import errors
from app.models.api import ManualResponse, RequestView, VdeptRegistry
from app.models.operations import OperationRequest, OperationRequestDraft
from app.operations.center import AcceptNotAllowed, NotAwaitingResponse
from app.operations.lifecycle import InvalidAlternative, RunNotFound
from app.operations.registry import UnknownDepartment, UnsupportedRequestType

router = APIRouter(prefix="/api/vdept", tags=["vdept"], dependencies=[Depends(require_session)])


def _request_or_404(ctx: AppContext, dept_id: str, action_id: str) -> OperationRequest:
    request = ctx.repo.get_operation_request(action_id)
    if request is None or request.department != dept_id:
        raise not_found("Richiesta non trovata")
    return request


@router.get("", response_model=VdeptRegistry, responses=errors(404))
def vdept_registry(ctx: Ctx, run_id: str | None = None) -> VdeptRegistry:
    """Il registro dei dipartimenti; con `run_id` anche le risorse (totale, usate, rimaste)."""
    if run_id is None:
        return VdeptRegistry(departments=ctx.registry.departments)
    try:
        balances = ctx.operations.resources(run_id)
    except RunNotFound as exc:
        raise not_found("Run non trovato") from exc
    return VdeptRegistry(departments=ctx.registry.departments, resources=balances)


@router.post(
    "/{dept_id}/requests", response_model=RequestView, status_code=201, responses=errors(400, 404)
)
def create_vdept_request(dept_id: str, body: OperationRequestDraft, ctx: Ctx) -> RequestView:
    """Solo per test e ispezione (l'orchestratore usa la chiamata in-process). La richiesta nasce
    `CREATED`: non parte da sola. `simulation` deve essere `true`: lo garantisce il modello, che lo
    rifiuta altrimenti (400)."""
    try:
        request = ctx.operations.lifecycle.create(body, dept_id)
    except UnknownDepartment as exc:
        raise not_found("Dipartimento non trovato") from exc
    except RunNotFound as exc:
        raise not_found("Run non trovato") from exc
    except UnsupportedRequestType as exc:
        raise invalid_field(
            "type",
            f"il dipartimento '{dept_id}' non gestisce '{body.type}'",
            "unsupported_request_type",
        ) from exc
    except InvalidAlternative as exc:
        raise invalid_field("alternative_of", str(exc), "invalid_alternative") from exc
    return RequestView(request=request, events=ctx.repo.list_operation_events(request.action_id))


@router.get("/{dept_id}/requests/{action_id}", response_model=RequestView, responses=errors(404))
def get_vdept_request(dept_id: str, action_id: str, ctx: Ctx) -> RequestView:
    """La richiesta con le sue transizioni (`operation_events`, una riga per ogni passaggio)."""
    request = _request_or_404(ctx, dept_id, action_id)
    return RequestView(request=request, events=ctx.repo.list_operation_events(action_id))


@router.post(
    "/{dept_id}/requests/{action_id}/manual-response",
    response_model=RequestView,
    responses=errors(404, 409),
)
def manual_response(dept_id: str, action_id: str, body: ManualResponse, ctx: Ctx) -> RequestView:
    """Accetta o rifiuta (con codice e motivo) una richiesta `RECEIVED` inviata con la risposta
    manuale; la decisione è dell'utente (attore `user`). Il rifiuto è sempre possibile;
    l'accettazione solo se la regola del dipartimento la permetterebbe (409 `ACCEPT_NOT_ALLOWED`,
    con il motivo e il codice della regola: la richiesta resta in attesa e si può ancora
    rifiutare). 409 `NOT_AWAITING_RESPONSE` se la richiesta non è in `RECEIVED` o se la risposta
    manuale non è attiva per lei (run senza risposta manuale, tempo scaduto, già risposta)."""
    _request_or_404(ctx, dept_id, action_id)  # 404 se non esiste o è di un altro dipartimento
    try:
        decided = ctx.operations.respond_manually(action_id, body)
    except NotAwaitingResponse as exc:
        raise ApiError(409, "NOT_AWAITING_RESPONSE", str(exc), {"state": exc.state}) from exc
    except AcceptNotAllowed as exc:
        raise ApiError(409, "ACCEPT_NOT_ALLOWED", str(exc), {"reject_code": exc.code}) from exc
    return RequestView(request=decided, events=ctx.repo.list_operation_events(action_id))
