import threading

import networkx as nx

from app.data.gtfs import GtfsError, GtfsFeed, RouteClasses, classify_routes, load_feed
from app.data.paths import DataPaths
from app.engine.graph import GraphError, load_road_graph
from app.models.config import EngineConfig
from app.models.edge_overrides import EdgeOverrides


class MapDataUnavailable(Exception):
    """Il grafo o il feed mancano o non si leggono: il messaggio dice cosa."""


class MapData:
    """`graph` e `feed` si possono dare già pronti (i test). `config` è il `engine.yaml` con cui si
    leggono i dati e si riconoscono le linee: uno solo per tutti."""

    def __init__(
        self,
        paths: DataPaths,
        *,
        graph: nx.MultiDiGraph | None = None,
        feed: GtfsFeed | None = None,
        config: EngineConfig | None = None,
    ) -> None:
        self._paths = paths
        self._graph = graph
        self._feed = feed
        self.config = config or EngineConfig.from_yaml()
        self._lock = threading.Lock()

    def graph(self) -> nx.MultiDiGraph:
        with self._lock:
            if self._graph is None:
                try:
                    self._graph = load_road_graph(
                        self._paths.osm_graph, self.config, EdgeOverrides.from_yaml()
                    )
                except GraphError as exc:
                    raise MapDataUnavailable(
                        f"I dati dei motori non sono disponibili: {exc}"
                    ) from exc
            return self._graph

    def feed(self) -> GtfsFeed:
        with self._lock:
            if self._feed is None:
                try:
                    self._feed = load_feed(self._paths.gtfs_feed)
                except GtfsError as exc:
                    raise MapDataUnavailable(
                        f"I dati dei motori non sono disponibili: {exc}"
                    ) from exc
            return self._feed

    def route_classes(self) -> RouteClasses:
        """Le linee del feed per classe (metro, funicolari, bus), come le riconoscono i motori."""
        try:
            return classify_routes(self.feed(), self.config.transit.route_classification)
        except GtfsError as exc:
            raise MapDataUnavailable(f"I dati dei motori non sono disponibili: {exc}") from exc
