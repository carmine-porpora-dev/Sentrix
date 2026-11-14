from fastapi import APIRouter, Depends

from app.api.deps import Ctx, require_session
from app.api.errors import ApiError, not_found
from app.api.openapi import errors
from app.db.repository import NotificationNotFound, NotificationStateConflict
from app.models.notifications import Notification
from app.notifications.bulletins import acknowledge

router = APIRouter(
    prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(require_session)]
)


@router.post(
    "/{notification_id}/ack",
    response_model=Notification,
    responses=errors(404, 409),
)
def ack_notification(notification_id: int, ctx: Ctx) -> Notification:
    """«Conferma ricezione» di un bollettino ai servizi di emergenza: la notifica passa a
    `ACKNOWLEDGED` e la conferma entra nel registro decisioni (attore `user`). 404 se non esiste;
    **409 `NOT_ACKNOWLEDGEABLE`** se è già confermata o non è un bollettino (WhatsApp non ha un
    ciclo di vita): `details.state` dice in che stato è."""
    try:
        return acknowledge(ctx.repo, notification_id)
    except NotificationNotFound as exc:
        raise not_found("Notifica non trovata") from exc
    except NotificationStateConflict as exc:
        raise ApiError(
            409,
            "NOT_ACKNOWLEDGEABLE",
            "Questa notifica non si può confermare",
            {"state": exc.found},
        ) from exc
