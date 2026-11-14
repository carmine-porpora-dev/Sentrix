import hashlib
import hmac

from fastapi import APIRouter, Request, Response

from app.api.deps import Ctx, session_of
from app.api.errors import ApiError, rate_limited
from app.api.openapi import errors
from app.api.session import SESSION_COOKIE
from app.models.api import AuthState, LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _password_matches(given: str, expected: str) -> bool:
    """Confronto a tempo costante. Si confrontano gli hash, non le password: la lunghezza di
    quella vera non traspare dal tempo di risposta."""
    return hmac.compare_digest(
        hashlib.sha256(given.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


# `public_access` si scrive solo se è vero: con l'accesso protetto le risposte sono quelle di sempre
@router.post(
    "/login",
    response_model=AuthState,
    response_model_exclude_defaults=True,
    responses=errors(401, 429, 503),
)
def login(body: LoginRequest, request: Request, response: Response, ctx: Ctx) -> AuthState:
    if ctx.settings.public_access:  # accesso libero: non c'è una password da chiedere né un cookie
        return AuthState(authenticated=True, public_access=True)
    if ctx.sessions is None or ctx.settings.app_password is None:
        raise ApiError(503, "AUTH_NOT_CONFIGURED", "L'accesso non è configurato su questo server")
    ip = request.client.host if request.client else "sconosciuto"
    # Il tentativo si conta prima di guardare la password, e si scarta se era giusta: una raffica
    # di richieste insieme non può quindi superare il limite.
    wait = ctx.login_limiter.try_acquire(ip)
    if wait:
        raise rate_limited("Troppi tentativi di accesso errati: riprova tra poco", wait)
    if not _password_matches(body.password, ctx.settings.app_password):
        raise ApiError(401, "INVALID_PASSWORD", "Password errata")
    ctx.login_limiter.release(ip)
    token, _ = ctx.sessions.issue()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ctx.sessions.lifetime_s,
        path="/",
        httponly=True,
        samesite="lax",
        secure=ctx.settings.secure_cookies,
    )
    return AuthState(authenticated=True)


@router.post("/logout", response_model=AuthState, response_model_exclude_defaults=True)
def logout(request: Request, response: Response, ctx: Ctx) -> AuthState:
    """Non richiede la sessione: chi esce con un cookie già scaduto deve poterlo ripulire. Con
    l'accesso libero non si esce da nulla: resta tutto aperto."""
    if ctx.settings.public_access:
        return AuthState(authenticated=True, public_access=True)
    session = session_of(request, ctx)
    if session is not None and ctx.sessions is not None:
        ctx.sessions.revoke(session)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=ctx.settings.secure_cookies,
    )
    return AuthState(authenticated=False)


@router.get("/me", response_model=AuthState, response_model_exclude_defaults=True)
def me(request: Request, ctx: Ctx) -> AuthState:
    if ctx.settings.public_access:
        return AuthState(authenticated=True, public_access=True)
    return AuthState(authenticated=session_of(request, ctx) is not None)
