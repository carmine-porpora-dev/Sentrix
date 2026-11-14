import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import JsonValue
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db.repository import EventExists, EventNotFound
from app.models.api import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)

# Messaggi italiani per gli errori che nascono dal framework (rotta inesistente, metodo sbagliato).
VALIDATION_MESSAGE = "La richiesta non è valida"
_HTTP_MESSAGES = {
    404: ("NOT_FOUND", "Risorsa non trovata"),
    405: ("METHOD_NOT_ALLOWED", "Metodo non consentito per questa risorsa"),
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, JsonValue] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.headers = dict(headers or {})


def error_response(error: ApiError) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=error.code, message=error.message, details=error.details)
    )
    return JSONResponse(
        body.model_dump(mode="json"), status_code=error.status_code, headers=error.headers
    )


def invalid_field(path: str, message: str, kind: str) -> ApiError:
    """400 per UN campo (`kind` è un codice stabile: il frontend può tradurlo)."""
    fields: list[JsonValue] = [{"path": path, "message": message, "type": kind}]
    return ApiError(400, "VALIDATION_ERROR", VALIDATION_MESSAGE, {"fields": fields})


def rate_limited(message: str, wait_s: int) -> ApiError:
    """429 con l'attesa nel corpo e nell'intestazione `Retry-After` (secondi)."""
    return ApiError(
        429, "RATE_LIMITED", message, {"retry_after_s": wait_s}, {"Retry-After": str(wait_s)}
    )


def not_found(message: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", message)


def unavailable(code: str, message: str) -> ApiError:
    """503: il servizio non può rispondere ora (mancano i dati, non l'utente ha sbagliato)."""
    return ApiError(503, code, message)


DATA_UNAVAILABLE_MESSAGE = (
    "I dati dei motori non sono disponibili: il servizio non ha la rete stradale o il trasporto "
    "pubblico. Riprova più tardi."
)


def data_unavailable(code: str, cause: Exception) -> ApiError:
    """503 per i dati dei motori che mancano. L'interfaccia mostra un messaggio senza percorsi del
    server né comandi da terminale; il dettaglio (il file che manca, `make data`) va nel log."""
    logger.error("%s: %s", code, cause)
    return unavailable(code, DATA_UNAVAILABLE_MESSAGE)


def _field_path(location: tuple[int | str, ...]) -> str:
    # Si toglie «body»/«query»/«path»: il frontend vuole il percorso nel form, non nella richiesta.
    parts = location[1:] if location and location[0] in ("body", "query", "path") else location
    return ".".join(str(part) for part in parts)


async def _api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(exc)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields: list[JsonValue] = [
        {"path": _field_path(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return error_response(ApiError(400, "VALIDATION_ERROR", VALIDATION_MESSAGE, {"fields": fields}))


async def _event_exists(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, EventExists)
    return error_response(ApiError(409, "EVENT_EXISTS", "Esiste già un evento con questo id"))


async def _event_not_found(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, EventNotFound)
    return error_response(not_found("Evento non trovato"))


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = _HTTP_MESSAGES.get(
        exc.status_code, (f"HTTP_{exc.status_code}", str(exc.detail))
    )
    return error_response(ApiError(exc.status_code, code, message))


async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Errore non gestito", exc_info=exc)
    return error_response(ApiError(500, "INTERNAL_ERROR", "Errore interno del server"))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(EventExists, _event_exists)
    app.add_exception_handler(EventNotFound, _event_not_found)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)
