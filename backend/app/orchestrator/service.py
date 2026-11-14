import asyncio
import hashlib
import secrets
import threading
from collections.abc import Collection, Coroutine
from typing import Any

from app.agents.runner import AgentRunner
from app.clock import now_rome
from app.data.map_data import MapData, MapDataUnavailable
from app.db.repository import Repository
from app.engine.run import RoadEngine
from app.engine.transit import TransitConfigError, load_transit_network
from app.engine.transit_run import TransitEngine
from app.llm.client import LlmClient
from app.models.agents_config import AgentsConfig
from app.models.base import LlmMode
from app.models.catalog import CatalogConfig
from app.models.config import EngineConfig
from app.models.departments import DepartmentsConfig
from app.models.event import Event
from app.models.run import AttendanceLevel, Run
from app.notifications.bulletins import BulletinService
from app.notifications.whatsapp import WhatsAppNotifier
from app.operations.center import OperationsCenter
from app.orchestrator.engines import Engines, RealEngines
from app.orchestrator.state_machine import Orchestrator


class EnginesUnavailable(Exception):
    """I dati dei motori mancano o non si leggono: il messaggio dice cosa."""


class EngineProvider:
    """I motori, caricati al primo uso. `engines` li dà già pronti (i test)."""

    def __init__(
        self,
        map_data: MapData,
        route_classes: Collection[str],
        engines: Engines | None = None,
    ) -> None:
        self._map_data = map_data
        self._route_classes = route_classes
        self._engines = engines
        self._lock = threading.Lock()

    def get(self) -> Engines:
        with self._lock:
            if self._engines is None:
                self._engines = self._load()
            return self._engines

    def _load(self) -> Engines:
        config = EngineConfig.from_yaml()
        try:
            graph = self._map_data.graph()
            network = load_transit_network(self._map_data.feed(), config.transit)
        except MapDataUnavailable as exc:
            raise EnginesUnavailable(str(exc)) from exc
        except TransitConfigError as exc:
            raise EnginesUnavailable(f"I dati dei motori non sono disponibili: {exc}") from exc
        return RealEngines(
            graph,
            RoadEngine(graph, config),
            TransitEngine(network, config),
            network,
            config,
            self._route_classes,
        )


def params_hash(event: Event) -> str:
    """Impronta di ciò che decide i numeri di un run: engine.yaml, catalog.yaml, departments.yaml
    e l'Evento (nella sua revisione). Due run con la stessa impronta, a parità di motore, danno gli
    stessi numeri."""
    parts = [
        EngineConfig.from_yaml().content_hash(),
        CatalogConfig.from_yaml().content_hash(),
        DepartmentsConfig.from_yaml().content_hash(),
        event.content_hash(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def new_run(event: Event, level: AttendanceLevel, llm_mode: LlmMode) -> Run:
    """Un run appena creato (`INTAKE`) sulla revisione corrente dell'Evento."""
    return Run(
        id=f"run_{secrets.token_hex(4)}",
        event_id=event.id,
        event_revision=event.revision,
        attendance_level=level,
        state="INTAKE",
        iteration=0,
        replans=0,
        started_at=now_rome(),
        params_hash=params_hash(event),
        seed=EngineConfig.from_yaml().seed,
        llm_mode=llm_mode,
    )


class RunService:
    def __init__(
        self,
        *,
        repo: Repository,
        center: OperationsCenter,
        llm: LlmClient,
        provider: EngineProvider,
        config: AgentsConfig,
        catalog: CatalogConfig,
        notifier: WhatsAppNotifier | None = None,
        bulletins: BulletinService | None = None,
    ) -> None:
        self._repo = repo
        self._center = center
        self._llm = llm
        self._provider = provider
        self._config = config
        self._catalog = catalog
        self._notifier = notifier
        self._bulletins = bulletins
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self, event: Event, level: AttendanceLevel, *, manual: bool) -> Run:
        """Crea il run (`INTAKE`) e lo lancia in secondo piano. `EnginesUnavailable` se i dati
        mancano: in quel caso non resta nessuna riga."""
        engines = await asyncio.to_thread(self._provider.get)
        run = new_run(event, level, self._llm.mode)
        self._repo.add_run(run)
        orchestrator = Orchestrator(
            repo=self._repo,
            center=self._center,
            runner=AgentRunner(self._llm, self._config, self._catalog),
            engines=engines,
            config=self._config,
        )
        self._spawn(self._execute(orchestrator, run.id, manual))
        return run

    def _spawn(self, work: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, orchestrator: Orchestrator, run_id: str, manual: bool) -> Run:
        """Il run fino a `DONE` o `ERROR`. Solo dopo `DONE`, ognuna in un compito suo, partono la
        notifica WhatsApp (spech 12.4, lenta: il servizio ha un timeout di 15 s) e i bollettini
        simulati ai servizi di emergenza (12.3): il run è già finito e non aspetta né può fallire
        per loro, e l'una non aspetta l'altra."""
        run = await orchestrator.execute(run_id, manual=manual)
        if run.state == "DONE":
            if self._notifier is not None:
                self._spawn(self._notifier.notify_run(run_id))
            if self._bulletins is not None:
                self._spawn(self._bulletins.notify_run(run_id))
        return run

    async def close(self) -> None:
        """All'arresto: i run in corso si interrompono (restano senza fine nel database)."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
