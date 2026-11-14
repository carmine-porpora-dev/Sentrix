import datetime as dt
import time

import networkx as nx
import pytest

from app.data.seeds import read_seed_events
from app.engine.run import ROAD_BUDGET_S, RoadEngine
from app.models.base import WINDOWS, Window
from app.models.config import EngineConfig
from app.models.event import Event
from app.models.operations import OperationRequest
from tests.support import make_request

pytestmark = pytest.mark.perf

SEED_IDS = sorted(event.id for event in read_seed_events())
AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_una_fascia_entro_il_budget(
    road_graph: nx.MultiDiGraph,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
    window: Window,
) -> None:
    event = seed_events[event_id]
    engine = RoadEngine(road_graph, road_config)  # nuovo: R da calcolare

    started = time.perf_counter()
    cold = engine.run(event, "high", window, id_prefix=("perf", "it0"), as_of=AS_OF)
    cold_wall = time.perf_counter() - started
    assert not cold.timings.reference_cached

    # tutti e tre i tipi di misura che toccano la rete, sui bersagli proposti dal motore stesso
    result = cold.result
    intersections = result.metrics.critical_intersections
    edges = ",".join(edge.edge_key for edge in result.metrics.critical_edges[:3])
    requests: list[OperationRequest] = [
        make_request(
            "act_1", type="traffic_post", target=str(intersections[0].node),
            window=window, iteration=1, state="ACCEPTED",
        ),
        make_request(
            "act_2", type="signal_plan_change", target=str(intersections[-1].node),
            window=window, iteration=1, state="ACCEPTED",
            payload={"favored_edge_key": intersections[-1].edge_key},
        ),
        make_request(
            "act_3", type="detour_signage", target=edges,
            window=window, iteration=1, state="ACCEPTED",
        ),
    ]  # fmt: skip
    started = time.perf_counter()
    measured = engine.run(event, "high", window, requests, id_prefix=("perf", "it1"), as_of=AS_OF)
    measured_wall = time.perf_counter() - started
    assert measured.timings.reference_cached
    assert measured.result.applied == ("act_1", "act_2", "act_3")

    for label, run, wall in (
        ("a freddo", cold, cold_wall),
        ("con 3 misure", measured, measured_wall),
    ):
        t = run.timings
        print(
            f"\n{event_id} {window} high {label}: {t.total_s:.2f} s "
            f"(R {t.reference_s:.2f}, assegnazione {t.assign_s:.2f}, metriche {t.metrics_s:.2f}) "
            f"= {t.total_s / ROAD_BUDGET_S:.0%} del budget di {ROAD_BUDGET_S:.0f} s"
        )
        assert t.total_s <= ROAD_BUDGET_S, f"{label}: {t.total_s:.2f} s"
        assert wall <= ROAD_BUDGET_S, f"{label}: {wall:.2f} s con la costruzione del risultato"
