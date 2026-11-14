from pathlib import Path

import networkx as nx
import pytest

from app.data.gtfs import load_feed
from app.data.paths import DataPaths, default_data_dir
from app.data.seeds import read_seed_events
from app.engine.graph import load_road_graph, require_graph_file
from app.engine.transit import TransitNetwork, load_transit_network
from app.models.config import EngineConfig
from app.models.edge_overrides import EdgeOverrides
from app.models.event import Event

GRAPH_PATH = DataPaths(default_data_dir()).osm_graph
FEED_PATH = DataPaths(default_data_dir()).gtfs_feed


@pytest.fixture(scope="session")
def road_config() -> EngineConfig:
    return EngineConfig.from_yaml()


@pytest.fixture(scope="session")
def road_graph_path() -> Path:
    require_graph_file(GRAPH_PATH)  # GraphError: «Manca il grafo stradale …: esegui `make data`»
    return GRAPH_PATH


@pytest.fixture(scope="session")
def road_graph(road_config: EngineConfig, road_graph_path: Path) -> nx.MultiDiGraph:
    return load_road_graph(road_graph_path, road_config, EdgeOverrides.from_yaml())


@pytest.fixture(scope="session")
def seed_events() -> dict[str, Event]:
    return {event.id: event for event in read_seed_events()}


@pytest.fixture(scope="session")
def transit_network(road_config: EngineConfig) -> TransitNetwork:
    """Il feed ANM di DATA_DIR e gli itinerari di engine.yaml risolti (2,6 s una tantum).
    `GtfsError` («Manca il feed GTFS …: esegui `make data`») se il feed non c'è."""
    return load_transit_network(load_feed(FEED_PATH), road_config.transit)
