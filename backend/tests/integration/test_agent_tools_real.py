import datetime as dt

import networkx as nx
import pytest

from app.agents.tools import event_demand_tools, traffic_tools, transit_tools
from app.engine.demand import build_demand
from app.engine.run import RoadEngine
from app.engine.transit import TransitNetwork
from app.engine.transit_run import TransitEngine
from app.models.agents_config import AgentsConfig
from app.models.base import Window
from app.models.config import EngineConfig
from app.models.event import Event

pytestmark = pytest.mark.realdata

AS_OF = dt.datetime(2026, 11, 11, 10, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize("event_id", ["match_2027", "regate_sep_2026"])
def test_strumenti_sui_risultati_veri_del_motore(
    event_id: str,
    seed_events: dict[str, Event],
    road_config: EngineConfig,
    road_graph: nx.MultiDiGraph,
    transit_network: TransitNetwork,
) -> None:
    event = seed_events[event_id]
    config = AgentsConfig.from_yaml()
    road = RoadEngine(road_graph, road_config)
    transit = TransitEngine(transit_network, road_config)
    windows: tuple[Window, ...] = ("arrival", "departure")
    demands = {w: build_demand(event, "mid", w, road_config, road_graph) for w in windows}
    prefix = ("run_real", "it0")
    road_results = {
        w: road.run(event, "mid", w, [], id_prefix=prefix, as_of=AS_OF).result for w in windows
    }
    transit_results = {
        w: transit.run(event, demands[w], [], id_prefix=prefix, as_of=AS_OF) for w in windows
    }

    agents = [
        event_demand_tools(event, "mid", demands, run_id="run_real", as_of=AS_OF),
        traffic_tools(road_results, run_id="run_real", iteration=0, as_of=AS_OF, config=config),
        transit_tools(transit_results, run_id="run_real", iteration=0, as_of=AS_OF, config=config),
    ]
    for tools in agents:
        known = [m.id for m in tools.measures]
        assert len(known) == len(set(known)), f"{tools.agent}: id duplicati"
        for signal in tools.signals:
            assert set(signal.evidence_ids) <= set(known), (tools.agent, signal)
    triggers = {s.trigger for tools in agents for s in tools.signals}
    # sui preset veri il motore trova incroci critici e carichi del TPL: ci sono segnali di entrambi
    assert "critical_intersection" in triggers
    assert triggers & {"section_overloaded", "stop_overloaded", "stop_overloaded_unsafe"}
