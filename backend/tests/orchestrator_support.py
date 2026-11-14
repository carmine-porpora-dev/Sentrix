import json
import threading
import time
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agents.runner import AgentRunner
from app.data.seeds import read_seed_events
from app.db.repository import Repository
from app.engine.demand import Demand
from app.engine.run import RoadResult
from app.engine.transit_run import TransitResult
from app.llm.client import LlmBackend
from app.models.agents_config import AgentsConfig
from app.models.base import WINDOWS, LlmMode, Window
from app.models.event import Event
from app.models.operations import OperationRequest
from app.models.run import AttendanceLevel, Run
from app.operations.center import OperationsCenter
from app.orchestrator.journal import state_transitions
from app.orchestrator.state_machine import Orchestrator
from tests.agents_support import CATALOG, CONFIG, demand, road_result, transit_result
from tests.llm_support import make_client
from tests.operations_support import StepClock, make_center, make_repo
from tests.support import make_run


def quiet_transit(window: Window) -> TransitResult:
    """Un trasporto senza criticità: nessun segnale, quindi nessuna misura."""
    return transit_result(
        window,
        trips={"metro_line_1": 6, "metro_line_6": 3, "funicular": 18},
        loads={"metro_line_1": 0.5, "metro_line_6": 0.2, "funicular": 0.5},
        stops=(),
    )


def empty_road(window: Window) -> RoadResult:
    return road_result(window, intersections=(), edges=())


# Le risposte valide di un LLM che propone due presìdi, li mette nel piano, sceglie la prima
# alternativa e scrive l'avviso: lo scenario con due incroci critici e una sola pattuglia libera.
PLAN = json.dumps(
    {
        "text": "Prima l'incrocio più grave.",
        "plan": [
            {"candidate": "c1", "rationale": "È il primo."},
            {"candidate": "c2", "rationale": "Poi il secondo."},
        ],
    }
)
TRAFFIC = json.dumps(
    {
        "text": "Due incroci critici nel deflusso.",
        "findings": [
            {"signal": "s1", "summary": "Il primo incrocio è saturo."},
            {"signal": "s2", "summary": "Il secondo incrocio è saturo."},
        ],
        "recommendations": [
            {"signal": "s1", "measure_type": "traffic_post", "rationale": "Serve un presidio."},
            {"signal": "s2", "measure_type": "traffic_post", "rationale": "Serve un presidio."},
        ],
    }
)
REPLAN = json.dumps(
    {"text": "Si chiede il cambio di piano.", "choice": "a1", "rationale": "Prima."}
)
NOTICE = json.dumps({"text": "Misure in vigore per l'evento."})
LIVE_ANSWERS = {
    "Sei il Traffic Agent": TRAFFIC,
    "scegliere quali misure candidate": PLAN,
    "scegliere quale alternativa": REPLAN,
    "scrivere l'avviso ai cittadini": NOTICE,
}


class RoutingBackend:
    """Un servizio LLM finto che risponde in base all'agente (dal prompt), non all'ordine delle
    chiamate: Traffic e Transit girano insieme. Chi non ha una risposta dà un testo minimo."""

    def __init__(self, answers: Mapping[str, str]) -> None:
        self._answers = answers
        self.agents: list[str] = []
        self.sent: list[tuple[str, str]] = []  # (inizio del prompt, input) di ogni chiamata

    async def generate(
        self,
        *,
        model: str,
        system: str,
        contents: str,
        schema: Mapping[str, Any],
        temperature: float,
        timeout_s: float,
    ) -> str:
        self.sent.append((system[:30], contents))
        for marker, answer in self._answers.items():
            if marker in system:
                self.agents.append(marker)
                return answer
        return '{"text": "Nessun rilievo."}'


@dataclass
class Call:
    kind: str  # road | transit
    window: str
    iteration: str  # «it0», «it1»…
    actions: tuple[str, ...]
    started: float
    ended: float


@dataclass
class StubEngines:
    """Risultati costruiti a mano, uguali a ogni iterazione, e il registro di chi è stato
    chiamato, quando e con quali richieste."""

    road_results: Mapping[Window, RoadResult]
    transit_results: Mapping[Window, TransitResult]
    delay_s: float = 0.0
    transit_delay_s: float | None = None  # se diverso da `delay_s`
    fail_road: Exception | None = None
    calls: list[Call] = field(default_factory=list)
    effect_of: list[tuple[Window, str, tuple[str, ...]]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _record(self, call: Call) -> None:
        with self._lock:
            self.calls.append(call)

    def demand(self, event: Event, level: AttendanceLevel, window: Window) -> Demand:
        return demand(window)

    def road(
        self,
        event: Event,
        level: AttendanceLevel,
        window: Window,
        requests: Sequence[OperationRequest],
        *,
        id_prefix: Sequence[str],
        as_of: datetime,
        effect_of: Collection[str] = (),
    ) -> RoadResult:
        started = time.perf_counter()
        time.sleep(self.delay_s)
        self.effect_of.append((window, id_prefix[1], tuple(sorted(effect_of))))
        if self.fail_road is not None:
            raise self.fail_road
        actions = tuple(r.action_id for r in requests)
        self._record(Call("road", window, id_prefix[1], actions, started, time.perf_counter()))
        return self.road_results[window]

    def transit(
        self,
        event: Event,
        demand: Demand,
        requests: Sequence[OperationRequest],
        *,
        id_prefix: Sequence[str],
        as_of: datetime,
    ) -> TransitResult:
        started = time.perf_counter()
        time.sleep(self.delay_s if self.transit_delay_s is None else self.transit_delay_s)
        actions = tuple(r.action_id for r in requests)
        window = demand.window
        self._record(Call("transit", window, id_prefix[1], actions, started, time.perf_counter()))
        return self.transit_results[window]

    def routes_serving(self, stop_id: str) -> list[str]:
        return ["metro_line_1"]

    def computed(self, kind: str) -> list[tuple[str, str]]:
        """(iterazione, finestra) di ogni calcolo di quel motore, in ordine d'iterazione."""
        return sorted((c.iteration, c.window) for c in self.calls if c.kind == kind)


def engines_with(
    departure_intersections: tuple[tuple[int, str, float], ...] = (),
    **road_kwargs: object,
) -> StubEngines:
    """Una strada con incroci critici nel deflusso, niente nell'arrivo; un trasporto tranquillo."""
    return StubEngines(
        road_results={
            "arrival": empty_road("arrival"),
            "departure": road_result(
                "departure",
                intersections=departure_intersections,
                edges=(),
                **road_kwargs,  # type: ignore[arg-type]
            ),
        },
        transit_results={w: quiet_transit(w) for w in WINDOWS},
    )


def zero_resources_event() -> Event:
    """Match 2027 senza pattuglie, cambi semaforici né bus di riserva: tutto è rifiutato."""
    base = next(e for e in read_seed_events() if e.id == "match_2027")
    data = base.model_dump(mode="json")
    for window in data["resources"]:
        for name in window:
            if name != "window":
                window[name] = 0
    return Event.model_validate({**data, "id": "senza_risorse"})


@dataclass
class Rig:
    orchestrator: Orchestrator
    repo: Repository
    center: OperationsCenter
    engines: StubEngines

    def states(self, run_id: str = "run_1") -> list[str]:
        """Gli stati attraversati, dal registro decisioni."""
        return [state for state, _ in state_transitions(self.repo.list_decisions(run_id))]


def make_rig(
    tmp_path: Path,
    engines: StubEngines,
    *,
    config: AgentsConfig = CONFIG,
    mode: LlmMode = "template",
    backend: LlmBackend | None = None,
    event: Event | None = None,
) -> Rig:
    """Il run `run_1` sul preset Match 2027, o sull'`event` dato (che si aggiunge al database)."""
    repo = make_repo(tmp_path)
    if event is not None:
        repo.add_event(event)
    repo.add_run(make_run("run_1", event_id=event.id if event else "match_2027", llm_mode=mode))
    center = make_center(repo)
    llm = make_client(repo, backend, mode=mode)
    orchestrator = Orchestrator(
        repo=repo,
        center=center,
        runner=AgentRunner(llm, config, CATALOG),
        engines=engines,
        config=config,
        clock=StepClock(),
    )
    return Rig(orchestrator, repo, center, engines)


def run_of(rig: Rig) -> Run:
    run = rig.repo.get_run("run_1")
    assert run is not None
    return run
