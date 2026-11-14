import platform

import fastapi
import pydantic
from fastapi import APIRouter

from app.api.deps import Ctx
from app.data.paths import DataPaths
from app.db.repository import SCHEMA_VERSION
from app.models.api import HealthData, HealthResponse

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(ctx: Ctx) -> HealthResponse:
    present = DataPaths(ctx.settings.data_dir).present()
    data = HealthData(
        osm=present["osm"],
        gtfs=present["gtfs"],
        pmtiles=present["pmtiles"],
        tomtom_key_present=ctx.settings.tomtom_key_present,
        gemini_key_present=ctx.settings.gemini_key_present,
        whatsapp_configured=ctx.settings.whatsapp.configured,
        whatsapp_provider=ctx.settings.whatsapp.provider,
    )
    degraded = [name for name, ok in present.items() if not ok]
    # senza password nessuno può entrare; con l'accesso libero (`PUBLIC_ACCESS`) entrano tutti
    if not ctx.settings.public_access and not ctx.settings.auth_configured:
        degraded.append("auth")
    return HealthResponse(
        status="degraded" if degraded else "ok",
        env=ctx.settings.env,
        data=data,
        degraded=degraded,
        versions={
            "python": platform.python_version(),
            "fastapi": fastapi.__version__,
            "pydantic": pydantic.VERSION,
            "db_schema": str(SCHEMA_VERSION),
        },
    )
