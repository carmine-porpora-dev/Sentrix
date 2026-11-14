from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.models.api import ErrorResponse

_DESCRIPTIONS = {
    400: "Richiesta non valida (errori per campo in `details.fields`)",
    401: "Non autenticato",
    404: "Risorsa non trovata",
    409: "Conflitto di stato",
    429: "Troppe richieste (`Retry-After` in secondi)",
    503: "Fonte o dati non disponibili",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Le risposte di errore di un endpoint, per il parametro `responses` di FastAPI."""
    return {code: {"model": ErrorResponse, "description": _DESCRIPTIONS[code]} for code in codes}


def _error_ref(code: int) -> dict[str, Any]:
    return {
        "description": _DESCRIPTIONS[code],
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}},
    }


def build_openapi(app: FastAPI) -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    for operations in schema["paths"].values():
        for operation in operations.values():
            responses = operation["responses"]
            if responses.pop("422", None) is not None:
                responses["400"] = _error_ref(400)
            if "security" in operation:
                responses.setdefault("401", _error_ref(401))
    components = schema.get("components", {}).get("schemas", {})
    for unused in ("HTTPValidationError", "ValidationError"):
        components.pop(unused, None)
    app.openapi_schema = schema
    return schema
