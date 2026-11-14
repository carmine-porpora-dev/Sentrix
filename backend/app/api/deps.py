from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import APIKeyCookie

from app.api.context import AppContext, get_ctx
from app.api.errors import ApiError, invalid_field
from app.api.session import SESSION_COOKIE, Session

Ctx = Annotated[AppContext, Depends(get_ctx)]

# La «sessione» di chiunque con l'accesso libero (`PUBLIC_ACCESS`): una sola e uguale per tutti,
# senza cookie né scadenza. Il suo `sid` è anche la chiave dei limiti per sessione (`POST
# /api/runs`): con l'accesso libero i visitatori li condividono, come già succede dietro il proxy
# per il login.
PUBLIC_SESSION = Session(sid="public", expires_at=0)

# Dichiara lo schema di sicurezza nell'OpenAPI; la verifica la fa `require_session`.
_cookie_scheme = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="Cookie di sessione ottenuto con POST /api/auth/login",
)


def session_of(request: Request, ctx: AppContext) -> Session | None:
    """La sessione del cookie, se valida. Per gli endpoint che funzionano anche senza (`me`)."""
    if ctx.settings.public_access:
        return PUBLIC_SESSION
    if ctx.sessions is None:
        return None
    return ctx.sessions.verify(request.cookies.get(SESSION_COOKIE))


def require_session(ctx: Ctx, token: str | None = Depends(_cookie_scheme)) -> Session:
    if ctx.settings.public_access:
        return PUBLIC_SESSION
    session = ctx.sessions.verify(token) if ctx.sessions else None
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "Accesso richiesto: effettua il login")
    return session


Authenticated = Annotated[Session, Depends(require_session)]


def parse_bbox(
    bbox: Annotated[str, Query(description="ovest,sud,est,nord (gradi decimali)")],
) -> tuple[float, float, float, float]:
    """`bbox=ovest,sud,est,nord` come nei seed (01 2), con le stesse regole di coerenza."""

    def fail(message: str) -> ApiError:
        return invalid_field("bbox", message, "invalid_bbox")

    try:
        west, south, east, north = (float(part) for part in bbox.split(","))
    except ValueError:
        raise fail("servono quattro numeri separati da virgole: ovest,sud,est,nord") from None
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise fail("coordinate fuori intervallo o in ordine sbagliato (ovest < est, sud < nord)")
    return west, south, east, north


Bbox = Annotated[tuple[float, float, float, float], Depends(parse_bbox)]
