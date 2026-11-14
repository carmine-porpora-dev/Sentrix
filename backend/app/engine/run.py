import dataclasses
import logging
import multiprocessing
import os
import threading
import time
from collections.abc import Collection, Sequence
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from multiprocessing.synchronize import Barrier
from pathlib import Path
from threading import BrokenBarrierError
from types import TracebackType
from typing import Self

import networkx as nx

from app.clock import now_rome
from app.engine.assign import Assignment, assign
from app.engine.background import build_background
from app.engine.demand import build_demand
from app.engine.graph import load_road_graph, require_graph_file
from app.engine.measure_effects import EFFECT_TYPES, measure_effects
from app.engine.measures import apply_measures
from app.engine.metrics import RoadMetrics, build_reference, road_metrics
from app.engine.result import EngineResult
from app.models.base import Window
from app.models.config import EngineConfig
from app.models.edge_overrides import EdgeOverrides
from app.models.event import Event
from app.models.operations import OperationRequest
from app.models.run import AttendanceLevel

logger = logging.getLogger(__name__)

MAX_WORKERS = 2  # 02 8: un processo per finestra (arrivo e deflusso girano in parallelo)
ROAD_BUDGET_S = 8.0  # 02 8: `run` per una fascia su 1 vCPU; oltre, si profila prima di ottimizzare
# R occupa qualche MB per Evento e finestra: 2 eventi demo × 2 finestre, più qualche Evento creato
# dall'utente. Oltre, esce la più vecchia (si ricalcola, mai un risultato sbagliato).
REFERENCE_CACHE_SIZE = 8
# Caricare la rete in un processo dura ~0,5 s: un processo che non è pronto dopo 60 s è bloccato.
START_TIMEOUT_S = 60.0


class RoadRunError(RuntimeError):
    """Il calcolo non è partito o è stato interrotto (non un errore dei dati: quelli arrivano
    com'erano, `MeasureError`, `ResolveError`...)."""


class RoadResult(EngineResult):
    """Il risultato stradale: `applied` sono le misure che hanno cambiato la rete."""

    metrics: RoadMetrics


@dataclass(frozen=True, slots=True)
class RoadTimings:
    """Dove va il tempo di un `run` (secondi, `time.perf_counter`)."""

    reference_s: float  # ottenere R: ≈ 0 se già calcolata
    reference_cached: bool
    assign_s: float  # rete con le misure, traffico di fondo, domanda e assegnazione
    metrics_s: float
    total_s: float


@dataclass(frozen=True, slots=True)
class RoadRun:
    result: RoadResult
    timings: RoadTimings


class RoadEngine:
    """La rete di base, la configurazione e la cache di R: ciò che un processo tiene in memoria."""

    def __init__(
        self,
        base: nx.MultiDiGraph,
        config: EngineConfig,
        *,
        reference_cache_size: int = REFERENCE_CACHE_SIZE,
    ) -> None:
        self._base = base
        self._config = config
        self._cache_size = reference_cache_size
        self._references: dict[tuple[str, Window], Assignment] = {}  # in ordine di arrivo

    @property
    def edge_count(self) -> int:
        return self._base.number_of_edges()

    def _reference(self, event: Event, window: Window) -> tuple[Assignment, bool]:
        key = (event.content_hash(), window)  # la configurazione è quella del motore
        cached = key in self._references
        if not cached:
            self._references[key] = build_reference(self._base, event, window, self._config)
            while len(self._references) > self._cache_size:
                del self._references[next(iter(self._references))]
        return self._references[key], cached

    def run(
        self,
        event: Event,
        level: AttendanceLevel,
        window: Window,
        measures: Sequence[OperationRequest] = (),
        *,
        id_prefix: Sequence[str],
        as_of: datetime | None = None,
        effect_of: Collection[str] = (),
    ) -> RoadRun:
        """Domanda, rete con le misure, assegnazione e metriche di `window` al livello `level`.

        `measures` sono le richieste dell'iterazione (`apply_measures` ignora quelle di altre
        finestre e rifiuta quelle non accettate). `id_prefix` apre gli id dei `Measured` (run e
        iterazione, es. `("run42", "it1")`). `as_of` è l'istante dei numeri: uno solo per tutto il
        risultato (omesso = adesso).

        `effect_of` sono gli action_id delle misure introdotte in questa iterazione: per quelle
        stradali della finestra il risultato ha anche l'effetto locale (`measure_effects`), che
        costa una seconda assegnazione, quella senza di esse. Vuoto (il caso base) = nessuna.
        """
        as_of = as_of if as_of is not None else now_rome()
        t0 = time.perf_counter()
        reference, cached = self._reference(event, window)
        t1 = time.perf_counter()
        config = self._config
        network = apply_measures(self._base, event, window, measures, config)
        background = build_background(self._base, event, window, network.closed)
        demand = build_demand(event, level, window, config, self._base)
        assignment = assign(network.graph, background.volumes, demand.flows, config)
        t2 = time.perf_counter()
        metrics = road_metrics(
            self._base,
            network,
            assignment,
            reference,
            demand,
            event,
            config,
            background=background,
            id_prefix=id_prefix,
            as_of=as_of,
        )
        new = [
            m
            for m in measures
            if m.action_id in effect_of and m.window == window and m.type in EFFECT_TYPES
        ]
        if new:
            # lo stato di prima: le misure in vigore senza quelle introdotte in questa iterazione
            kept = [m for m in measures if m.action_id not in effect_of]
            before_network = apply_measures(self._base, event, window, kept, config)
            before_background = build_background(self._base, event, window, before_network.closed)
            before = assign(before_network.graph, before_background.volumes, demand.flows, config)
            effects = measure_effects(
                new,
                network.graph,
                before,
                assignment,
                window=window,
                id_prefix=id_prefix,
                as_of=as_of,
            )
            metrics = dataclasses.replace(metrics, measures=(*metrics.measures, *effects))
        t3 = time.perf_counter()
        result = RoadResult(
            event_id=event.id,
            level=level,
            window=window,
            applied=network.applied,
            metrics=metrics,
        )
        return RoadRun(result, RoadTimings(t1 - t0, cached, t2 - t1, t3 - t2, t3 - t0))


# --- il processo figlio ---------------------------------------------------------------------------

# Il `RoadEngine` del processo figlio, costruito da `_init_worker` all'avvio.
_ENGINE: RoadEngine | None = None
_ENGINE_LOAD_S = 0.0
_READY: Barrier | None = None  # condivisa dai processi del pool: serve ad `start()`


def _init_worker(
    graph_path: Path, config: EngineConfig, overrides: EdgeOverrides | None, ready: Barrier
) -> None:
    global _ENGINE, _ENGINE_LOAD_S, _READY  # noqa: PLW0603 (stato del processo figlio)
    started = time.perf_counter()
    _ENGINE = RoadEngine(load_road_graph(graph_path, config, overrides), config)
    _ENGINE_LOAD_S = time.perf_counter() - started
    _READY = ready


@dataclass(frozen=True, slots=True)
class WorkerInfo:
    pid: int
    edges: int
    load_s: float  # tempo per costruire la rete nel processo


def _worker_info() -> WorkerInfo:
    """Il lavoro di avvio: aspetta che tutti i processi abbiano la rete. Senza l'attesa il primo
    pronto prenderebbe anche il secondo lavoro, e il secondo processo partirebbe «a freddo»."""
    assert _ENGINE is not None and _READY is not None, "processo non inizializzato"
    _READY.wait(START_TIMEOUT_S)
    return WorkerInfo(os.getpid(), _ENGINE.edge_count, _ENGINE_LOAD_S)


def _run_job(
    event: Event,
    level: AttendanceLevel,
    window: Window,
    measures: tuple[OperationRequest, ...],
    id_prefix: tuple[str, ...],
    as_of: datetime | None,
    effect_of: tuple[str, ...],
) -> RoadRun:
    assert _ENGINE is not None, "processo non inizializzato"
    return _ENGINE.run(
        event, level, window, measures, id_prefix=id_prefix, as_of=as_of, effect_of=effect_of
    )


# --- il pool --------------------------------------------------------------------------------------


class RoadRunner:
    """`RoadEngine.run` in un pool di processi col grafo già caricato.

    `start()` (o il primo `run`) avvia i processi e attende che abbiano il grafo; `close()` li
    ferma. Se un processo muore (memoria, segnale) il `run` in corso fallisce con `RoadRunError` e
    il successivo riavvia il pool. Si può chiamare `run` da più thread.
    """

    def __init__(
        self,
        graph_path: Path,
        config: EngineConfig,
        overrides: EdgeOverrides | None = None,
        *,
        max_workers: int = MAX_WORKERS,
    ) -> None:
        self._graph_path = graph_path
        self._config = config
        self._overrides = overrides
        self._max_workers = max_workers
        self._executor: ProcessPoolExecutor | None = None
        self.workers: tuple[WorkerInfo, ...] = ()  # cosa ha ciascun processo, dopo l'avvio
        self._lock = threading.Lock()

    def start(self) -> None:
        """Avvia i processi e li fa partire col grafo caricato (non fa nulla se già avviato)."""
        with self._lock:
            if self._executor is None:
                self._start()

    def _start(self) -> None:
        require_graph_file(self._graph_path)  # l'errore chiaro qui, non un pool rotto
        started = time.perf_counter()
        # `spawn`: il server ha thread, e un `fork` li erediterebbe a metà.
        context = multiprocessing.get_context("spawn")
        executor = ProcessPoolExecutor(
            max_workers=self._max_workers,
            mp_context=context,
            initializer=_init_worker,
            initargs=(
                self._graph_path,
                self._config,
                self._overrides,
                context.Barrier(self._max_workers),
            ),
        )
        try:
            # Un processo nasce quando arriva un lavoro e non ce n'è uno libero: tanti lavori
            # quanti i processi, subito di seguito, li fanno nascere tutti (e la barriera di
            # `_worker_info` li tiene tutti occupati finché non sono pronti).
            futures = [executor.submit(_worker_info) for _ in range(self._max_workers)]
            infos = tuple(future.result() for future in futures)
        except BaseException as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            if isinstance(exc, BrokenExecutor | BrokenBarrierError):
                raise RoadRunError("Avvio dei processi di calcolo fallito") from exc
            raise
        self._executor = executor
        self.workers = infos
        logger.info(
            "Motore stradale pronto: %d processi, rete di %d archi, caricata in %.1f s "
            "(avvio totale %.1f s)",
            len(infos),
            infos[0].edges,
            max(info.load_s for info in infos),
            time.perf_counter() - started,
        )

    def run(
        self,
        event: Event,
        level: AttendanceLevel,
        window: Window,
        measures: Sequence[OperationRequest] = (),
        *,
        id_prefix: Sequence[str],
        as_of: datetime | None = None,
        effect_of: Collection[str] = (),
    ) -> RoadResult:
        """Come `RoadEngine.run`, in un processo figlio; logga i tempi e ritorna il risultato.

        Gli errori dei dati (`MeasureError`, `ResolveError`...) arrivano com'erano.
        """
        with self._lock:
            if self._executor is None:
                self._start()
            executor = self._executor
        assert executor is not None  # _start l'ha impostato o ha sollevato
        started = time.perf_counter()
        try:
            run = executor.submit(
                _run_job,
                event,
                level,
                window,
                tuple(measures),
                tuple(id_prefix),
                as_of,
                tuple(effect_of),
            ).result()
        except BrokenExecutor as exc:
            with self._lock:
                if self._executor is executor:
                    self._executor = None
                    executor.shutdown(wait=False, cancel_futures=True)
            raise RoadRunError(
                "Un processo di calcolo si è interrotto: il prossimo calcolo riavvia il pool"
            ) from exc
        self._log(event, level, window, run.timings, time.perf_counter() - started)
        return run.result

    @staticmethod
    def _log(
        event: Event, level: AttendanceLevel, window: Window, t: RoadTimings, elapsed_s: float
    ) -> None:
        logger.info(
            "Strada %s %s %s: %.2f s (R %.2f s%s, assegnazione %.2f s, metriche %.2f s; "
            "attesa e trasferimenti %.2f s)",
            event.id,
            level,
            window,
            t.total_s,
            t.reference_s,
            " in cache" if t.reference_cached else "",
            t.assign_s,
            t.metrics_s,
            elapsed_s - t.total_s,
        )
        if t.total_s > ROAD_BUDGET_S:
            logger.warning(
                "Strada %s %s %s: %.2f s, oltre il budget di %.0f s (02 8): profilare prima di "
                "ottimizzare",
                event.id,
                level,
                window,
                t.total_s,
                ROAD_BUDGET_S,
            )

    def close(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
