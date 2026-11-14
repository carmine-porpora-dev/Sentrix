from collections import Counter
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol

import networkx as nx

from app.data.gtfs import GtfsFeed
from app.engine.demand import Demand, build_demand
from app.engine.run import RoadEngine, RoadResult
from app.engine.transit import TransitNetwork
from app.engine.transit_run import TransitEngine, TransitResult
from app.models.base import Window
from app.models.config import EngineConfig
from app.models.event import Event
from app.models.operations import OperationRequest
from app.models.run import AttendanceLevel


class Engines(Protocol):
    def demand(self, event: Event, level: AttendanceLevel, window: Window) -> Demand: ...

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
        """`effect_of`: le misure introdotte in questa iterazione, di cui il risultato dice anche
        l'effetto locale (`engine.measure_effects`)."""
        ...

    def transit(
        self,
        event: Event,
        demand: Demand,
        requests: Sequence[OperationRequest],
        *,
        id_prefix: Sequence[str],
        as_of: datetime,
    ) -> TransitResult: ...

    def routes_serving(self, stop_id: str) -> list[str]:
        """Le classi di linea che fermano alla fermata, la più frequente per prima."""
        ...


class RealEngines:
    """I motori veri. `route_classes` sono le classi di linea che una misura può avere come
    bersaglio (`labels.route_classes` di `agents.yaml`): `bus` non è una di esse."""

    def __init__(
        self,
        graph: nx.MultiDiGraph,
        road: RoadEngine,
        transit: TransitEngine,
        network: TransitNetwork,
        config: EngineConfig,
        route_classes: Collection[str],
    ) -> None:
        self._graph = graph
        self._road = road
        self._transit = transit
        self._network = network
        self._config = config
        self._route_classes = frozenset(route_classes)

    def demand(self, event: Event, level: AttendanceLevel, window: Window) -> Demand:
        return build_demand(event, level, window, self._config, self._graph)

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
        run = self._road.run(
            event, level, window, requests, id_prefix=id_prefix, as_of=as_of, effect_of=effect_of
        )
        return run.result

    def transit(
        self,
        event: Event,
        demand: Demand,
        requests: Sequence[OperationRequest],
        *,
        id_prefix: Sequence[str],
        as_of: datetime,
    ) -> TransitResult:
        return self._transit.run(event, demand, requests, id_prefix=id_prefix, as_of=as_of)

    def routes_serving(self, stop_id: str) -> list[str]:
        feed: GtfsFeed = self._network.feed
        at_stop = feed.stop_times[feed.stop_times["stop_id"] == stop_id]["trip_id"]
        routes = feed.trips[feed.trips["trip_id"].isin(at_stop)]["route_id"]
        counts = Counter(
            kind
            for route_id in routes
            if (kind := self._network.classes.of(str(route_id))) in self._route_classes
        )
        return [kind for kind, _ in counts.most_common()]
