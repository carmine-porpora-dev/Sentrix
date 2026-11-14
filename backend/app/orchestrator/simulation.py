import asyncio
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from app.agents.tools import AgentTools, event_demand_tools, traffic_tools, transit_tools
from app.db.repository import Repository
from app.engine.demand import Demand
from app.engine.run import RoadResult
from app.engine.transit_run import TransitResult
from app.models.agents_config import AgentsConfig
from app.models.api import FeatureCollection
from app.models.base import WINDOWS, Window
from app.models.event import Event
from app.models.operations import OperationRequest
from app.models.provenance import Measured
from app.models.run import AttendanceLevel
from app.orchestrator.engines import Engines
from app.orchestrator.layers import annotate_evidence, merge_by_name, requests_layer
from app.orchestrator.reconcile import closed_edges


class Simulation:
    def __init__(
        self,
        *,
        engines: Engines,
        repo: Repository,
        config: AgentsConfig,
        event: Event,
        level: AttendanceLevel,
        run_id: str,
        as_of: datetime,
    ) -> None:
        self._engines = engines
        self._repo = repo
        self._config = config
        self._event = event
        self._level = level
        self._run_id = run_id
        self._as_of = as_of
        self.demands: dict[Window, Demand] = {}
        self.road: dict[int, dict[Window, RoadResult]] = {}
        self.transit: dict[int, dict[Window, TransitResult]] = {}

    # --- il caso base (iterazione 0) ------------------------------------------------------------

    async def load_demands(self) -> AgentTools:
        """La domanda di ogni finestra e gli strumenti di Event & Demand."""
        for window in WINDOWS:
            self.demands[window] = await asyncio.to_thread(
                self._engines.demand, self._event, self._level, window
            )
        return event_demand_tools(
            self._event, self._level, self.demands, run_id=self._run_id, as_of=self._as_of
        )

    async def baseline_road(self) -> AgentTools:
        self.road[0] = await self._road(0, [], set(WINDOWS), {})
        return traffic_tools(self.road[0], **self._tool_args(0))

    async def baseline_transit(self) -> AgentTools:
        self.transit[0] = await self._transit(0, [], set(WINDOWS), {})
        return transit_tools(self.transit[0], **self._tool_args(0))

    def closed_edges(self) -> frozenset[str]:
        """Gli archi chiusi dall'Evento (nel caso base, in qualunque finestra)."""
        return closed_edges(self.road[0].values())

    # --- una nuova iterazione (VERIFY) ----------------------------------------------------------

    async def verify(
        self, iteration: int, requests: Sequence[OperationRequest], touched: Collection[Window]
    ) -> None:
        """Strada e TPL con tutte le `requests` in vigore, solo per le finestre `touched`: le altre
        copiano l'iterazione precedente. Strada e TPL girano insieme."""
        self.road[iteration], self.transit[iteration] = await asyncio.gather(
            self._road(iteration, requests, touched, self.road[iteration - 1]),
            self._transit(iteration, requests, touched, self.transit[iteration - 1]),
        )

    def window_spans(self) -> dict[str, str]:
        """L'orario di ogni finestra («21:00–23:00»), come lo scrive l'Evento."""
        return {w: self._event.window_span(w) for w in WINDOWS}

    def road_in(self, iteration: int, window: Window) -> RoadResult | None:
        return self.road[iteration].get(window)

    # --- salvataggio ----------------------------------------------------------------------------

    def store(self, iteration: int, extra: Sequence[Measured] = ()) -> None:
        """Le metriche (anche i valori derivati che gli agenti citano) e i layer dell'iterazione,
        con le due finestre unite e la provenienza di ogni numero della mappa."""
        road, transit = self.road[iteration], self.transit[iteration]
        derived = [
            *traffic_tools(road, **self._tool_args(iteration)).measures,
            *transit_tools(transit, **self._tool_args(iteration)).measures,
        ]
        metrics = list({m.id: m for m in [*extra, *derived]}.values())
        layers: dict[str, FeatureCollection] = merge_by_name(
            {
                w: annotate_evidence(
                    w, {**road[w].metrics.layers, **transit[w].metrics.layers}, derived
                )
                for w in WINDOWS
            }
        )
        layers["requests"] = requests_layer(self._repo.list_operation_requests(self._run_id))
        # prima i layer, poi le metriche: l'API considera calcolata un'iterazione quando ha le
        # metriche (`Repository.has_metrics`), e a quel punto i layer ci sono già
        for name, layer in layers.items():
            self._repo.put_layer(self._run_id, iteration, name, layer)
        self._repo.put_metrics(self._run_id, iteration, metrics)

    # --- dettagli -------------------------------------------------------------------------------

    def _tool_args(self, iteration: int) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "iteration": iteration,
            "as_of": self._as_of,
            "config": self._config,
        }

    async def _road(
        self,
        iteration: int,
        requests: Sequence[OperationRequest],
        touched: Collection[Window],
        before: dict[Window, RoadResult],
    ) -> dict[Window, RoadResult]:
        prefix = (self._run_id, f"it{iteration}")
        # le misure introdotte in questa iterazione: il motore ne dice l'effetto locale (02 7)
        new = frozenset(r.action_id for r in requests if r.iteration == iteration)
        return {
            w: await asyncio.to_thread(
                self._engines.road,
                self._event,
                self._level,
                w,
                requests,
                id_prefix=prefix,
                as_of=self._as_of,
                effect_of=new,
            )
            if w in touched
            else before[w]
            for w in WINDOWS
        }

    async def _transit(
        self,
        iteration: int,
        requests: Sequence[OperationRequest],
        touched: Collection[Window],
        before: dict[Window, TransitResult],
    ) -> dict[Window, TransitResult]:
        prefix = (self._run_id, f"it{iteration}")
        return {
            w: await asyncio.to_thread(
                self._engines.transit,
                self._event,
                self.demands[w],
                requests,
                id_prefix=prefix,
                as_of=self._as_of,
            )
            if w in touched
            else before[w]
            for w in WINDOWS
        }
