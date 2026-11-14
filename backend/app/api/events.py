from fastapi import APIRouter, Depends

from app.api.deps import Ctx, require_session
from app.api.errors import ApiError, data_unavailable, invalid_field, not_found
from app.api.openapi import errors
from app.clock import now_rome
from app.data.map_data import MapDataUnavailable
from app.data.map_views import event_preview
from app.data.seeds import read_seed_events
from app.models.api import FeatureCollection
from app.models.event import Event, EventInput, EventSummary

router = APIRouter(prefix="/api/events", tags=["events"], dependencies=[Depends(require_session)])


def _as_new_event(body: EventInput) -> Event:
    """L'Evento completo da un corpo: i campi del server li fissa il repository (`update_event`
    sovrascrive revisione e date, `add_event` li prende da qui)."""
    now = now_rome()
    return Event.model_validate({**dict(body), "revision": 1, "created_at": now, "updated_at": now})


@router.get("", response_model=list[EventSummary])
def list_events(ctx: Ctx) -> list[EventSummary]:
    return ctx.repo.list_events()


@router.get("/{event_id}", response_model=Event, responses=errors(404))
def get_event(event_id: str, ctx: Ctx) -> Event:
    event = ctx.repo.get_event(event_id)
    if event is None:
        raise not_found("Evento non trovato")
    return event


@router.post("", response_model=Event, status_code=201, responses=errors(409))
def create_event(body: EventInput, ctx: Ctx) -> Event:
    event = _as_new_event(body)
    ctx.repo.add_event(event)
    return event


@router.put("/{event_id}", response_model=Event, responses=errors(404))
def update_event(event_id: str, body: EventInput, ctx: Ctx) -> Event:
    """`revision` +1 e `updated_at` li decide il repository; la revisione sostituita resta
    consultabile (i run che l'hanno usata ritrovano l'evento com'era)."""
    if body.id != event_id:
        raise invalid_field("id", "deve coincidere con l'id nel percorso", "id_mismatch")
    return ctx.repo.update_event(_as_new_event(body))


@router.post("/{event_id}/reset", response_model=Event, responses=errors(404, 409))
def reset_event(event_id: str, ctx: Ctx) -> Event:
    """Solo per i preset: rimette il contenuto del file seed. È una nuova revisione, non una
    cancellazione: la versione modificata dall'utente resta nello storico."""
    summary = next((s for s in ctx.repo.list_events() if s.id == event_id), None)
    if summary is None:
        raise not_found("Evento non trovato")
    if not summary.is_seed:
        raise ApiError(409, "NOT_A_SEED", "Solo i preset si possono ripristinare dal file")
    seed = next((e for e in read_seed_events(ctx.seeds_dir) if e.id == event_id), None)
    if seed is None:
        raise not_found("File del preset non trovato")
    return ctx.repo.update_event(seed)


@router.post("/{event_id}/resolve", response_model=FeatureCollection, responses=errors(404, 503))
def resolve_event(event_id: str, ctx: Ctx) -> FeatureCollection:
    """Anteprima GeoJSON di ciò che il risolutore trova per l'evento (revisione corrente): strade
    chiuse, fermate interrotte, centro dell'area e punti di arrivo in auto. Ciò che non si
    risolve non compare: il run lo segnalerebbe."""
    event = ctx.repo.get_event(event_id)
    if event is None:
        raise not_found("Evento non trovato")
    try:
        return event_preview(
            event, ctx.map_data.graph(), ctx.map_data.feed().stops, ctx.map_data.config
        )
    except MapDataUnavailable as exc:
        raise data_unavailable("DATA_UNAVAILABLE", exc) from exc
