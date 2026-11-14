import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml
from fastapi import Request

from app.api.ratelimit import RateLimiter
from app.api.session import SessionManager
from app.data.live_flow import LiveFlowService, build_live_flow
from app.data.map_data import MapData
from app.data.paths import DataPaths
from app.data.seeds import DEFAULT_SEEDS_DIR
from app.db.repository import Repository
from app.llm.client import LlmClient
from app.llm.factory import build_llm_client
from app.models.agents_config import AgentsConfig
from app.models.api_config import ApiConfig
from app.models.catalog import CatalogConfig
from app.models.config import EngineConfig
from app.models.emergency_services import EmergencyServicesConfig
from app.models.sensors import SensorsConfig
from app.notifications.bulletins import BulletinService
from app.notifications.whatsapp import WhatsAppNotifier
from app.notifications.whatsapp_client import Transport
from app.operations.center import OperationsCenter
from app.operations.registry import DepartmentRegistry
from app.orchestrator.engines import Engines
from app.orchestrator.service import EngineProvider, RunService
from app.settings import Settings

logger = logging.getLogger(__name__)


def load_sensors() -> SensorsConfig | None:
    """I sensori previsti (spech.md 11.5), o `None` se il file manca o non è valido.

    A differenza degli altri file di `config/`, un errore qui **non ferma il server**: i sensori
    previsti sono un accenno senza dati, e non devono poter togliere SCENARIO o LIVE. Il problema
    si legge nel log e `GET /api/sensors` risponde 503; tutto il resto funziona come prima. Il file
    vero lo valida un test, quindi un errore non arriva in produzione dal deploy.
    """
    try:
        return SensorsConfig.from_yaml()
    except (OSError, ValueError, yaml.YAMLError):  # ValidationError è un ValueError
        logger.exception("config/sensors.yaml non letto: GET /api/sensors risponderà 503")
        return None


def load_bulletins(repo: Repository) -> BulletinService | None:
    """I bollettini ai servizi di emergenza (spech.md 12.3), o `None` se
    `config/emergency_services.yaml` manca o non è valido. Come per i sensori, un errore qui **non
    ferma il server** né toglie nulla a un run: i bollettini sono una comunicazione in più, e senza
    il file semplicemente non partono (si legge nel log). Il file vero lo valida un test."""
    try:
        config = EmergencyServicesConfig.from_yaml()
    except (OSError, ValueError, yaml.YAMLError):  # ValidationError è un ValueError
        logger.exception("config/emergency_services.yaml non letto: i bollettini non partiranno")
        return None
    return BulletinService(repo, config, EngineConfig.from_yaml().metrics.vc_critical_threshold)


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    config: ApiConfig
    registry: DepartmentRegistry
    operations: OperationsCenter
    llm: LlmClient
    runs: RunService
    map_data: MapData
    live: LiveFlowService
    sensors: SensorsConfig | None  # None se config/sensors.yaml non si legge (`load_sensors`)
    repo: Repository
    seeds_dir: Path
    clock: Callable[[], float]
    sessions: SessionManager | None  # None se password o segreto mancano: nessuno può entrare
    login_limiter: RateLimiter
    run_session_limiter: RateLimiter
    run_global_limiter: RateLimiter


def build_context(
    settings: Settings,
    clock: Callable[[], float],
    *,
    config: ApiConfig | None = None,
    seeds_dir: Path | None = None,
    engines: Engines | None = None,
    map_data: MapData | None = None,
    live: LiveFlowService | None = None,
    whatsapp_transport: Transport | None = None,
) -> AppContext:
    """`engines`: motori già pronti (i test); altrimenti si caricano dai dati al primo run. `live`:
    il servizio LIVE già pronto (i test, con un TomTom finto); altrimenti si costruisce dalle
    impostazioni. `whatsapp_transport`: il trasporto HTTP di WhatsApp (i test: uno finto)."""
    config = config or ApiConfig.from_yaml()
    paths = DataPaths(settings.data_dir)
    map_data = map_data or MapData(paths)
    repo = Repository(paths.database)
    registry = DepartmentRegistry.from_yaml()
    agents_config = AgentsConfig.from_yaml()
    llm = build_llm_client(settings, repo)
    center = OperationsCenter(
        repo, registry, add_runs_default=EngineConfig.from_yaml().transit.add_runs_default
    )
    sessions = (
        SessionManager(settings.session_secret, config.session_hours * 3600, clock)
        if settings.auth_configured and settings.session_secret
        else None
    )
    return AppContext(
        settings=settings,
        config=config,
        registry=registry,
        operations=center,
        llm=llm,
        map_data=map_data,
        live=live or build_live_flow(settings, clock),
        sensors=load_sensors(),
        runs=RunService(
            repo=repo,
            center=center,
            llm=llm,
            provider=EngineProvider(map_data, agents_config.labels.route_classes, engines),
            config=agents_config,
            catalog=CatalogConfig.from_yaml(),
            notifier=WhatsAppNotifier(repo, settings.whatsapp, transport=whatsapp_transport),
            bulletins=load_bulletins(repo),
        ),
        repo=repo,
        seeds_dir=seeds_dir or DEFAULT_SEEDS_DIR,
        clock=clock,
        sessions=sessions,
        login_limiter=RateLimiter(config.login_failures, clock),
        run_session_limiter=RateLimiter(config.runs_per_session, clock),
        run_global_limiter=RateLimiter(config.runs_global, clock),
    )


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx
