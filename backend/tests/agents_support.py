import datetime as dt
from datetime import datetime
from typing import Any

from app.agents.payloads import (
    PlanCandidate,
    alternative_ids,
    analysis_input,
    notice_input,
    plan_input,
    replan_input,
)
from app.agents.tools import (
    EVENT_DEMAND_TOOLS,
    AgentTools,
    traffic_tools,
    transit_tools,
)
from app.clock import ROME
from app.engine.demand import Demand, ZoneDemand
from app.engine.metrics import CriticalEdge, CriticalIntersection, RoadMetrics
from app.engine.run import RoadResult
from app.engine.transit_metrics import SectionRow, TransitMetrics
from app.engine.transit_run import TransitResult
from app.models.agents import Recommendation
from app.models.agents_config import AgentsConfig
from app.models.api import Feature, FeatureCollection, ResourceBalance
from app.models.base import Window
from app.models.catalog import CatalogConfig
from app.models.provenance import Measured, make_measured, measured_id
from app.operations.alternatives import Alternative
from tests.support import make_request as make_operation

CONFIG = AgentsConfig.from_yaml()
CATALOG = CatalogConfig.from_yaml()
EVIDENCE = "m.run_1.it0.road.departure.critical_intersection.1.vc"
RUN = "run_1"
AS_OF = datetime(2026, 11, 11, 10, 0, tzinfo=ROME)
STATIC = "modello macroscopico statico non calibrato, non una previsione"


def measure(parts: tuple[str, ...], value: float | str, unit: str, kind: str = "simulated",
            source: str = "engine.metrics v1", it: int = 0) -> Measured:  # fmt: skip
    """Un `Measured` con l'id del motore: `parts` si può scrivere con i punti («od_time.mean»)."""
    flat = [piece for part in parts for piece in part.split(".")]
    return make_measured(
        id=measured_id(RUN, f"it{it}", *flat),
        value=value,
        unit=unit,
        kind=kind,  # type: ignore[arg-type]
        source=source,
        method="metodo di prova",
        inputs=["evento di prova"],
        assumptions=[STATIC],
        as_of=AS_OF,
    )


def point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


def road_result(
    window: Window = "departure",
    *,
    intersections: tuple[tuple[int, str, float], ...] = ((1001, "Piazza Vittoria", 1.2),),
    edges: tuple[tuple[str, str | None, float], ...] = (("1-2-0", "Riviera di Chiaia", 1.3),),
    closed: tuple[str, ...] = (),
) -> RoadResult:
    measures = [
        measure(("road", window, "veh_hours"), 4820.0, "veic·h"),
        measure(("road", window, "od_time.mean"), 38.4, "min"),
        measure(("road", window, "critical_edges.count"), len(edges), "n"),
    ] + [
        measure(("road", window, f"critical_intersection.{rank}.vc"), vc, "rapporto")
        for rank, (_node, _label, vc) in enumerate(intersections, start=1)
    ]
    layer = FeatureCollection(
        features=[
            Feature(
                id=str(node),
                geometry=point(14.2 + node / 1e6, 40.8),
                properties={"node": str(node)},
            )
            for node, _label, _vc in intersections
        ]
    )
    entering = [  # gli archi entranti negli incroci critici, con flusso dell'Evento
        (f"9-{node}-0", vc, True) for node, _label, vc in intersections
    ] + [(key, vc, False) for key, _name, vc in edges]
    edges_layer = FeatureCollection(
        features=[
            Feature(
                id=key,
                geometry=point(14.25, 40.83),
                properties={"edge_key": key, "vc": vc, "detour": detour, "closed": key in closed},
            )
            for key, vc, detour in entering
        ]
    )
    return RoadResult(
        event_id="match_2027",
        level="mid",
        window=window,
        applied=(),
        metrics=RoadMetrics(
            window=window,
            measures=tuple(measures),
            layers={"critical_intersections": layer, "edges_vc": edges_layer},
            critical_edges=tuple(CriticalEdge(key, name, vc, 120.0) for key, name, vc in edges),
            critical_intersections=tuple(
                CriticalIntersection(rank, node, vc, f"9-{node}-0", label)
                for rank, (node, label, vc) in enumerate(intersections, start=1)
            ),
        ),
    )


def transit_result(
    window: Window = "departure",
    *,
    trips: dict[str, int] | None = None,
    loads: dict[str, float] | None = None,
    stops: tuple[tuple[str, str, float, bool, bool], ...] = (
        ("2116", "Riviera di Chiaia", 1.6, True, False),
    ),
    itineraries: dict[str, str] | None = None,
) -> TransitResult:
    trips = {"metro_line_1": 6, "metro_line_6": 0, "funicular": 18} if trips is None else trips
    loads = {"metro_line_1": 2.7, "metro_line_6": 0.0, "funicular": 0.5} if loads is None else loads
    measures = [
        measure(
            ("transit", window, f"trips_in_window.{c}"), n, "n", "estimate", "engine.transit v1"
        )
        for c, n in trips.items()
    ]
    measures += [
        measure(
            ("transit", window, f"max_section_load.{c}"),
            v,
            "rapporto",
            "estimate",
            "engine.transit v1",
        )
        for c, v in loads.items()
    ]
    measures += [
        measure(("transit", window, "stops_overloaded"), 26, "n", "estimate", "engine.transit v1")
    ]
    measures += [
        measure(
            ("transit", window, f"itinerary_used.{zone}"),
            text,
            "testo",
            "estimate",
            "engine.transit v1",
        )
        for zone, text in (itineraries or {"vomero": "funicolare, poi a piedi"}).items()
    ]
    features = [
        Feature(
            id=stop_id,
            geometry=point(14.23, 40.83),
            properties={
                "stop_id": stop_id,
                "name": name,
                "load_ratio": ratio,
                "overloaded": over,
                "closed": closed,
            },
        )
        for stop_id, name, ratio, over, closed in stops
    ]
    return TransitResult(
        event_id="match_2027",
        level="mid",
        window=window,
        applied=(),
        metrics=TransitMetrics(
            window=window,
            measures=tuple(measures),
            layers={"stops": FeatureCollection(features=features)},
            sections=(
                SectionRow("4955", "metro_line_1", "MUNICIPIO", "TOLEDO", 3, 7500.0, 20500.0, 2.73),
            ),
        ),
    )


# --- gli input dell'LLM, costruiti come li costruisce il runner ---------------------------------


def config_with(**sections: Any) -> AgentsConfig:
    data = CONFIG.model_dump()
    for name, changes in sections.items():
        data[name] = {**data[name], **changes}
    return AgentsConfig.model_validate(data)


def traffic_agent_tools() -> AgentTools:
    return traffic_tools(
        {"departure": road_result()}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG
    )


def transit_agent_tools() -> AgentTools:
    return transit_tools(
        {"departure": transit_result()}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG
    )


def event_demand_agent_tools() -> AgentTools:
    def pax(name: str, value: float) -> Measured:
        return measure(("event", *name.split(".")), value, "pax")

    return AgentTools(
        agent="event_demand",
        tools_called=list(EVENT_DEMAND_TOOLS),
        measures=[
            pax("attendance", 45000),
            pax("departure.persons_in_band", 18000.0),
            pax("departure.car_persons", 11250.0),
            pax("departure.transit_persons", 4500.0),
            pax("departure.walk_persons", 2250.0),
        ],
        context={
            "event": "Napoli–Juventus 2027",
            "date": "2027-08-27",
            "arrival_window": "12:00–15:00",
            "departure_window": "18:00–21:00",
            "closures": ["Via Caracciolo"],
        },
    )


def traffic() -> dict[str, Any]:
    return analysis_input(traffic_agent_tools(), CATALOG).payload


def transit() -> dict[str, Any]:
    return analysis_input(transit_agent_tools(), CATALOG).payload


def event_demand() -> dict[str, Any]:
    payload = analysis_input(event_demand_agent_tools(), CATALOG).payload
    payload.pop("signals")  # come fa il runner: Event & Demand non ha criticità
    return payload


def candidate(identifier: str, target: str = "Piazza Vittoria") -> PlanCandidate:
    recommendation = Recommendation(
        measure_type="traffic_post",
        target="1001",
        department="municipal_police",
        window="departure",
        rationale="Incrocio saturo.",
        evidence_ids=[EVIDENCE],
    )
    return PlanCandidate(identifier, recommendation, target, "critical")


def plan() -> dict[str, Any]:
    resources = [
        ResourceBalance(
            department="municipal_police",
            window="departure",
            resource="patrols",
            total=6,
            used=5,
            remaining=1,
        )
    ]
    measures = [measure(("road", "departure", "veh_hours"), 4820.0, "veic·h")]
    return plan_input(
        [candidate("c1"), candidate("c2", "Piazza Sannazaro")], resources, measures, 2
    )


def replan() -> dict[str, Any]:
    rejected = make_operation(
        "act_2",
        state="REJECTED",
        reject_code="UNAVAILABLE",
        reject_reason="Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, 6 già impegnate",
    )
    alternatives = alternative_ids(
        [
            Alternative("signal_plan_change", "traffic_control", "1001", "Piazza Vittoria"),
            Alternative("detour_signage", "traffic_control", "1-2-0", "Archi a monte"),
        ]
    )
    return replan_input(
        rejected, alternatives, [measure(("road", "departure", "veh_hours"), 4820.0, "veic·h")]
    )


def notice() -> dict[str, Any]:
    accepted = [make_operation("act_1", state="ACCEPTED")]
    return notice_input(accepted, [], {"arrival": "12:00–15:00", "departure": "18:00–21:00"})


def demand(window: Window = "departure") -> Demand:
    """Una domanda di prova: una zona, mille persone nella fascia."""
    zone = ZoneDemand("z1", "near", 1000.0, 400.0, 500.0, 100.0, 180.0, 90.0)
    return Demand(
        window=window,
        level="mid",
        attendance=150000,
        band_start=dt.time(21, 0),
        band_end=dt.time(22, 0),
        band_share=0.4,
        persons=1000.0,
        zones=(zone,),
        flows=(),
        car_occupancy=2.2,
        inputs=("zone di prova",),
        assumptions=("occupazione 2,2",),
    )
