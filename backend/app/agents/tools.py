from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime

from pydantic import Field, JsonValue

from app.engine import STATIC_MODEL_ASSUMPTION, unique
from app.engine.demand import Demand
from app.engine.metrics import CriticalEdge
from app.engine.run import RoadResult
from app.engine.transit_metrics import OVERLOAD
from app.engine.transit_run import TransitResult
from app.models.agents import AgentName, Severity
from app.models.agents_config import AgentsConfig, Thresholds
from app.models.api import Feature
from app.models.base import WINDOWS, FrozenModel, Slug, Window
from app.models.catalog import TargetKind
from app.models.event import Event
from app.models.geo import GeoPoint
from app.models.provenance import Measured, MeasuredId, make_measured, measured_id
from app.models.run import AttendanceLevel

ROAD_SOURCE = "engine.metrics v1"  # la fonte dei numeri stradali del motore (`engine/metrics.py`)
TRANSIT_SOURCE = "engine.transit v1"
DEMAND_SOURCE = "engine.demand v1"

EVENT_DEMAND_TOOLS = ["create_event_context", "build_demand"]
TRAFFIC_TOOLS = [
    "apply_closures",
    "assign_traffic",
    "find_congested_edges",
    "find_critical_intersections",
    "od_times",
]
TRANSIT_TOOLS = [
    "get_stops_near",
    "get_trips_in_window",
    "estimate_loads",
    "find_alternative_connections",
]


def _present[R](results: Mapping[Window, R]) -> Iterator[tuple[Window, R]]:
    """Le finestre che hanno un risultato, nell'ordine canonico (arrivo, poi deflusso)."""
    for window in WINDOWS:
        if (result := results.get(window)) is not None:
            yield window, result


class ToolError(ValueError):
    """Un risultato del motore che non ha ciò che gli strumenti si aspettano (un id mancante)."""


class Signal(FrozenModel):
    """Una criticità trovata dagli strumenti: l'unico materiale da cui nascono i finding."""

    trigger: Slug  # un trigger di `catalog.yaml`
    target: str  # incrocio (id del nodo), archi (`u-v-k`), linea (classe o `route_id`), fermata
    target_kind: TargetKind
    target_label: str = Field(min_length=1)
    window: Window
    severity: Severity
    evidence_ids: list[MeasuredId] = Field(min_length=1)
    location: GeoPoint | None = None
    # ciò che una misura chiede oltre al bersaglio, per tipo di misura (04 6.1): il cambio di
    # piano semaforico vuole l'arco da favorire. Lo sanno gli strumenti, che hanno il motore.
    measure_params: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)


class AgentTools(FrozenModel):
    """Tutto ciò che un agente riceve dagli strumenti."""

    agent: AgentName
    tools_called: list[str]
    measures: list[Measured]
    signals: list[Signal] = Field(default_factory=list)
    # fatti che non sono numeri misurati (nomi, itinerari): l'LLM li legge, non li cita
    context: dict[str, JsonValue] = Field(default_factory=dict)

    def measure(self, measured_id_: str) -> Measured | None:
        return next((m for m in self.measures if m.id == measured_id_), None)


def severity_of(value: float, thresholds: Thresholds) -> Severity:
    if value >= thresholds.critical_at:
        return "critical"
    if value >= thresholds.warning_at:
        return "warning"
    return "info"


def _by_suffix(measures: Sequence[Measured], suffix: str) -> Measured:
    for measured in measures:
        if measured.id.endswith(f".{suffix}"):
            return measured
    raise ToolError(f"il motore non ha prodotto la metrica '{suffix}'")


def _point(feature: Feature | None) -> GeoPoint | None:
    """Il punto di una feature GeoJSON `Point` (coordinate: [lon, lat])."""
    geometry = feature.geometry if feature else None
    if not geometry or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    lon, lat = coordinates[0], coordinates[1]
    if not isinstance(lon, int | float) or not isinstance(lat, int | float):
        return None
    return GeoPoint(lat=float(lat), lon=float(lon))


def _feature(layer: Mapping[str, object] | object, feature_id: str) -> Feature | None:
    features = getattr(layer, "features", [])
    return next((f for f in features if str(f.id) == feature_id), None)


# --- Event & Demand ----------------------------------------------------------------------------


def attendance_measured(event: Event, level: AttendanceLevel, run_id: str) -> Measured:
    """L'affluenza dell'Evento per il livello del run, come `Measured` (sempre SIMULATO: è
    un'ipotesi di scenario). L'interfaccia ne ricostruisce una uguale (`attendanceMeasured`, in
    `frontend/src/features/metrics/attendance.ts`) per la card, prima che l'iterazione 0 sia
    salvata: un test del frontend verifica che le due coincidano, partendo da quella delle
    fixture."""
    note = (event.attendance.source_ref or "").strip()
    return make_measured(
        id=measured_id(run_id, "it0", "event", "attendance"),
        value=getattr(event.attendance, level),
        unit="pax",
        kind="simulated",
        source=f"Evento {event.id} (revisione {event.revision})",
        method=f"affluenza del livello {level} indicata nell'Evento, ipotesi di scenario",
        inputs=[f"event {event.id} rev {event.revision}", f"livello di affluenza {level}"],
        assumptions=[f"fonte indicata nell'Evento: {note}"] if note else [],
        as_of=event.updated_at,
    )


def event_demand_tools(
    event: Event,
    level: AttendanceLevel,
    demands: Mapping[Window, Demand],
    *,
    run_id: str,
    as_of: datetime,
) -> AgentTools:
    """`create_event_context` e `build_demand`: l'affluenza dell'Evento (un'ipotesi di scenario) e
    le persone che la domanda manda in auto, sui mezzi pubblici e a piedi, per finestra."""
    measures = [attendance_measured(event, level, run_id)]
    for window, demand in _present(demands):
        shares = (
            ("persons_in_band", demand.persons, "persone nella fascia di picco"),
            ("car_persons", demand.car_persons, "persone che arrivano in auto"),
            ("transit_persons", demand.transit_persons, "persone sui mezzi pubblici"),
            ("walk_persons", demand.walk_persons, "persone a piedi"),
        )
        for name, value, what in shares:
            measures.append(
                make_measured(
                    id=measured_id(run_id, "it0", "event", window, name),
                    value=value,
                    unit="pax",
                    kind="simulated",
                    source=DEMAND_SOURCE,
                    method=f"{what}, dalla ripartizione modale della domanda",
                    inputs=list(demand.inputs),
                    assumptions=unique(STATIC_MODEL_ASSUMPTION, *demand.assumptions),
                    as_of=as_of,
                )
            )
    context: dict[str, JsonValue] = {
        "event": event.name,
        "date": event.date.isoformat(),
        "attendance_level": level,
        "arrival_window": event.window_span("arrival"),
        "departure_window": event.window_span("departure"),
        "closures": [closure.label for closure in event.closures],
        "transit_disruptions": [item.label for item in event.transit_disruptions],
    }
    return AgentTools(
        agent="event_demand",
        tools_called=list(EVENT_DEMAND_TOOLS),
        measures=measures,
        context=context,
    )


# --- Traffic -----------------------------------------------------------------------------------


def traffic_tools(
    results: Mapping[Window, RoadResult],
    *,
    run_id: str,
    iteration: int,
    as_of: datetime,
    config: AgentsConfig,
) -> AgentTools:
    """`apply_closures`, `assign_traffic`, `find_congested_edges`, `find_critical_intersections`,
    `od_times`: le metriche stradali del motore, gli incroci critici (bersagli di un presidio) e gli
    archi più saturi (bersagli di una deviazione), per finestra."""
    measures: list[Measured] = []
    signals: list[Signal] = []
    for window, result in _present(results):
        window_measures = list(result.metrics.measures)
        measures += window_measures
        layer = result.metrics.layers.get("critical_intersections")
        for item in result.metrics.critical_intersections:
            evidence = _by_suffix(window_measures, f"critical_intersection.{item.rank}.vc")
            signals.append(
                Signal(
                    trigger="critical_intersection",
                    target=str(item.node),
                    target_kind="intersection",
                    target_label=item.label,
                    window=window,
                    severity=severity_of(item.vc, config.severity.road),
                    evidence_ids=[evidence.id],
                    location=_point(_feature(layer, str(item.node))),
                    measure_params={"signal_plan_change": {"favored_edge_key": item.edge_key}},
                )
            )
        edges = result.metrics.critical_edges[: config.tools.top_congested_edges]
        for edge in edges:
            derived = _edge_measure(edge, window, run_id, iteration, window_measures, as_of)
            measures.append(derived)
            signals.append(
                Signal(
                    trigger="saturated_path",
                    target=edge.edge_key,
                    target_kind="edges",
                    target_label=edge.name or edge.edge_key,
                    window=window,
                    severity=severity_of(edge.vc, config.severity.road),
                    evidence_ids=[derived.id],
                    location=_point(_feature(result.metrics.layers.get("edges_vc"), edge.edge_key)),
                )
            )
    return AgentTools(
        agent="traffic",
        tools_called=list(TRAFFIC_TOOLS),
        measures=measures,
        signals=signals,
    )


def _edge_measure(
    edge: CriticalEdge,
    window: Window,
    run_id: str,
    iteration: int,
    window_measures: Sequence[Measured],
    as_of: datetime,
) -> Measured:
    """Il v/c di un arco, con la provenienza dei numeri stradali della stessa finestra."""
    base = _by_suffix(window_measures, "veh_hours")  # stessi input e assunzioni del motore
    return make_measured(
        id=measured_id(run_id, f"it{iteration}", "road", window, "edge_vc", edge.edge_key),
        value=edge.vc,
        unit="rapporto",
        kind="simulated",
        source=ROAD_SOURCE,
        method="rapporto flusso/capacità dell'arco, tra i più saturi della finestra",
        inputs=[*base.inputs, f"arco {edge.edge_key}"],
        assumptions=base.assumptions,
        as_of=as_of,
    )


# --- Transit -----------------------------------------------------------------------------------


def transit_tools(
    results: Mapping[Window, TransitResult],
    *,
    run_id: str,
    iteration: int,
    as_of: datetime,
    config: AgentsConfig,
) -> AgentTools:
    """`get_stops_near`, `get_trips_in_window`, `estimate_loads`, `find_alternative_connections`: le
    metriche del trasporto pubblico del motore, le linee senza corse o sature e le fermate più
    cariche, per finestra."""
    labels = config.labels.route_classes
    measures: list[Measured] = []
    signals: list[Signal] = []
    itineraries: dict[str, JsonValue] = {}
    for window, result in _present(results):
        window_measures = list(result.metrics.measures)
        measures += window_measures
        for route_class in labels:
            trips = _optional(window_measures, f"trips_in_window.{route_class}")
            if trips is not None and trips.value == 0:
                signals.append(
                    Signal(
                        trigger="line_no_service_in_window",
                        target=route_class,
                        target_kind="route",
                        target_label=labels[route_class],
                        window=window,
                        severity="warning",
                        evidence_ids=[trips.id],
                    )
                )
            load = _optional(window_measures, f"max_section_load.{route_class}")
            if load is not None and isinstance(load.value, int | float) and load.value > OVERLOAD:
                signals.append(
                    Signal(
                        trigger="section_overloaded",
                        target=route_class,
                        target_kind="route",
                        target_label=labels[route_class],
                        window=window,
                        severity=severity_of(float(load.value), config.severity.transit),
                        evidence_ids=[load.id],
                    )
                )
        stops_layer = result.metrics.layers.get("stops")
        loaded = sorted(
            (
                feature
                for feature in getattr(stops_layer, "features", [])
                if feature.properties.get("overloaded") is True
                and feature.properties.get("closed") is not True
            ),
            key=lambda feature: (-_ratio(feature), str(feature.id)),
        )
        for feature in loaded[: config.tools.top_overloaded_stops]:
            stop_id = str(feature.properties.get("stop_id") or feature.id)
            ratio = _ratio(feature)
            derived = make_measured(
                id=measured_id(run_id, f"it{iteration}", "transit", window, "stop_load", stop_id),
                value=ratio,
                unit="rapporto",
                kind="estimate",
                source=TRANSIT_SOURCE,
                method="passeggeri/ora ÷ capacità della fermata, tra le più cariche della finestra",
                inputs=[*_inputs_of(window_measures), f"fermata {stop_id}"],
                assumptions=_assumptions_of(window_measures),
                as_of=as_of,
            )
            measures.append(derived)
            unsafe = ratio >= config.severity.stop_unsafe_load
            signals.append(
                Signal(
                    trigger="stop_overloaded_unsafe" if unsafe else "stop_overloaded",
                    target=stop_id,
                    target_kind="stop",
                    target_label=str(feature.properties.get("name") or stop_id),
                    window=window,
                    severity="critical" if unsafe else severity_of(ratio, config.severity.transit),
                    evidence_ids=[derived.id],
                    location=_point(feature),
                )
            )
        for measured in window_measures:
            marker = f".transit.{window}.itinerary_used."
            if marker in measured.id and isinstance(measured.value, str):
                itineraries[f"{window}:{measured.id.split(marker, 1)[1]}"] = measured.value
    return AgentTools(
        agent="transit",
        tools_called=list(TRANSIT_TOOLS),
        measures=measures,
        signals=signals,
        context={"itineraries": itineraries},
    )


def _ratio(feature: Feature) -> float:
    value = feature.properties.get("load_ratio")
    return float(value) if isinstance(value, int | float) else 0.0


def _optional(measures: Sequence[Measured], suffix: str) -> Measured | None:
    return next((m for m in measures if m.id.endswith(f".{suffix}")), None)


def _inputs_of(measures: Sequence[Measured]) -> list[str]:
    return list(measures[0].inputs) if measures else ["motore del trasporto pubblico"]


def _assumptions_of(measures: Sequence[Measured]) -> list[str]:
    return list(measures[0].assumptions) if measures else [STATIC_MODEL_ASSUMPTION]
