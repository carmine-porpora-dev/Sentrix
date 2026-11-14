import shutil
from pathlib import Path

import osmnx as ox
import pytest

from app.data.gtfs import load_feed
from app.data.map_data import MapData, MapDataUnavailable
from app.data.paths import DataPaths
from app.engine.graph import clear_road_graph_cache
from app.models.config import EngineConfig, RoadDefault
from tests.support import GTFS_FIXTURE, build_classed_street_graph, build_raw_road_graph

PREFIX = "I dati dei motori non sono disponibili"


def test_i_dati_dati_gia_pronti_non_toccano_il_disco(tmp_path: Path) -> None:
    graph, feed = build_classed_street_graph(), load_feed(GTFS_FIXTURE)
    data = MapData(DataPaths(tmp_path / "non_esiste"), graph=graph, feed=feed)
    assert data.graph() is graph and data.feed() is feed


def test_senza_il_grafo_si_dice_cosa_manca(tmp_path: Path) -> None:
    with pytest.raises(MapDataUnavailable, match=PREFIX) as error:
        MapData(DataPaths(tmp_path)).graph()
    assert "graph_drive.graphml" in str(error.value)


def test_senza_il_feed_si_dice_cosa_manca(tmp_path: Path) -> None:
    with pytest.raises(MapDataUnavailable, match=PREFIX):
        MapData(DataPaths(tmp_path)).feed()


def test_il_feed_si_legge_una_volta_sola(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    shutil.copytree(GTFS_FIXTURE, paths.gtfs_feed)
    data = MapData(paths)
    assert data.feed() is data.feed()
    assert set(data.feed().stops["stop_id"]) >= {"S1", "S2"}


def test_le_linee_del_feed_diverso_da_engine_yaml_non_si_classificano() -> None:
    """Il mini-feed non ha i route_id di Napoli scritti in engine.yaml: lo dice, non li inventa."""
    data = MapData(DataPaths(Path("/non/esiste")), feed=load_feed(GTFS_FIXTURE))
    with pytest.raises(MapDataUnavailable, match=PREFIX) as error:
        data.route_classes()
    assert "engine.yaml" in str(error.value)


def test_senza_feed_le_linee_non_si_classificano(tmp_path: Path) -> None:
    with pytest.raises(MapDataUnavailable, match=PREFIX):
        MapData(DataPaths(tmp_path)).route_classes()


def test_il_grafo_si_costruisce_con_la_configurazione_data(tmp_path: Path) -> None:
    paths = DataPaths(tmp_path)
    paths.osm_graph.parent.mkdir(parents=True)
    ox.save_graphml(build_raw_road_graph(), paths.osm_graph)
    config = EngineConfig.from_yaml()
    defaults = dict(config.road_defaults)
    defaults["primary"] = RoadDefault(lanes=5, speed_kmh=90, capacity_per_lane=1000)
    clear_road_graph_cache()
    try:
        own = MapData(paths, config=config.model_copy(update={"road_defaults": defaults}))
        assert own.graph().edges[2, 3, 0]["lanes"] == 5
        assert MapData(paths).graph().edges[2, 3, 0]["lanes"] == 2  # i valori di engine.yaml
    finally:
        clear_road_graph_cache()
