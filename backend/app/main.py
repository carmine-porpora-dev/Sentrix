import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.api import auth, events, health, live, network, notifications, runs, sensors, vdept
from app.api.context import build_context
from app.api.errors import install_error_handlers
from app.api.frontend import DEFAULT_FRONTEND_DIR, mount_frontend
from app.api.openapi import build_openapi
from app.data.live_flow import LiveFlowService
from app.data.map_data import MapData
from app.data.seeds import load_seed_events
from app.llm.cache import DEFAULT_DEMO_CACHE_DIR, DemoCacheError, import_demo_cache
from app.models.api_config import ApiConfig
from app.notifications.whatsapp_client import Transport
from app.orchestrator.engines import Engines
from app.settings import Settings, load_env_file

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], float] = time.time,
    config: ApiConfig | None = None,
    seeds_dir: Path | None = None,
    demo_cache_dir: Path | None = None,
    frontend_dir: Path | None = None,
    engines: Engines | None = None,
    map_data: MapData | None = None,
    live_flow: LiveFlowService | None = None,
    whatsapp_transport: Transport | None = None,
) -> FastAPI:
    """I parametri servono ai test (impostazioni, orologio, limiti, preset); in esecuzione normale
    si leggono `.env` e ambiente all'avvio."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if settings is None:
            load_env_file()
        ctx = build_context(
            settings or Settings.from_env(),
            clock,
            config=config,
            seeds_dir=seeds_dir,
            engines=engines,
            map_data=map_data,
            live=live_flow,
            whatsapp_transport=whatsapp_transport,
        )
        load_seed_events(ctx.repo, ctx.seeds_dir)  # idempotente: i preset già presenti restano
        try:  # la cache demo (05 1): le risposte registrate, senza sovrascrivere
            imported = import_demo_cache(ctx.repo, demo_cache_dir or DEFAULT_DEMO_CACHE_DIR)
            logger.info("cache demo: %d voci importate", imported)
        except DemoCacheError:
            # l'applicazione parte lo stesso (ripiega sui template) ma l'errore si vede
            logger.exception("cache demo non importata")
        app.state.ctx = ctx
        yield
        await ctx.runs.close()  # i run ancora in corso si interrompono
        await ctx.live.aclose()

    app = FastAPI(
        title="Sentrix",
        lifespan=lifespan,
        # Né /docs né /openapi.json: sarebbero pubblici, e tutto tranne /api/health vuole la
        # sessione (06 1). Il contratto è docs/spec/openapi.json (scripts/export_openapi.py).
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        # operationId = nome della funzione: nomi leggibili nei tipi TypeScript generati.
        generate_unique_id_function=lambda route: route.name,
    )
    install_error_handlers(app)
    for module in (health, auth, events, network, runs, notifications, vdept, live, sensors):
        app.include_router(module.router)
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]
    # ciò che nessuna rotta riconosce è un file dell'interfaccia compilata
    mount_frontend(app, frontend_dir or DEFAULT_FRONTEND_DIR)
    return app


app = create_app()
