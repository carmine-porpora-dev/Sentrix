from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import networkx as nx
from pydantic import JsonValue

from app.data.resolvers import (
    edge_coordinates,
    osm_name_parts,
    parse_edge_key,
    resolve_closure,
    resolve_point,
)
from app.engine import STATIC_MODEL_ASSUMPTION, unique
from app.engine.assign import Assignment, Route, Router, assign
from app.engine.background import Background, build_background
from app.engine.demand import Demand, effective_demand_inputs
from app.engine.graph import describe_sources
from app.engine.measures import RoadNetwork
from app.geo import COORD_DECIMALS, geojson_point
from app.models.api import Feature, FeatureCollection
from app.models.base import Window
from app.models.config import EngineConfig, ODEndpoint
from app.models.event import Event
from app.models.geo import GeoPoint
from app.models.provenance import Measured, make_measured, measured_id

SOURCE = "engine.metrics v1"


class MetricsError(ValueError):
    """Le metriche non si possono calcolare con questi input."""


@dataclass(frozen=True, slots=True)
class CriticalEdge:
    edge_key: str
    name: str | None
    vc: float
    length_m: float


@dataclass(frozen=True, slots=True)
class CriticalIntersection:
    rank: int  # 1 = la più critica
    node: int
    vc: float  # il massimo v/c degli archi entranti sui cammini deviati
    edge_key: str  # l'arco entrante che lo raggiunge (candidato a `favored_edge_key`)
    label: str


@dataclass(frozen=True)
class RoadMetrics:
    window: Window
    measures: tuple[Measured, ...]
    layers: Mapping[str, FeatureCollection]  # edges_vc, closures, critical_intersections
    critical_edges: tuple[CriticalEdge, ...]  # per l'export CSV, dal v/c più alto
    critical_intersections: tuple[CriticalIntersection, ...]


def build_reference(
    base: nx.MultiDiGraph, event: Event, window: Window, config: EngineConfig
) -> Assignment:
    """R: solo il traffico di fondo, nessun evento, nessuna chiusura, sulla rete di base."""
    return assign(base, build_background(base, event, window).volumes, [], config)


def _endpoint_node(
    endpoint: ODEndpoint,
    zones: Mapping[str, GeoPoint],
    base: nx.MultiDiGraph,
    config: EngineConfig,
    pair_id: str,
) -> int:
    if endpoint.zone is not None:
        if endpoint.zone not in zones:
            raise MetricsError(
                f"coppia O/D '{pair_id}': la zona '{endpoint.zone}' non è tra le zone dell'evento"
            )
        point = zones[endpoint.zone]
    else:
        assert endpoint.point is not None  # ODEndpoint ne garantisce esattamente uno
        point = endpoint.point
    return resolve_point(point, base, max_distance_m=config.node_snap_max_distance_m)


def od_pair_nodes(
    event: Event, base: nx.MultiDiGraph, config: EngineConfig
) -> dict[str, tuple[int, int]]:
    """Origine e destinazione, come nodi della rete, di ogni coppia O/D di `engine.yaml`.

    Un estremo `zone` è il centroide di una zona effettiva dell'Evento (`MetricsError` se non c'è);
    un estremo `point` vale per sé. `ResolveError` se un punto dista troppo da ogni nodo.
    """
    zones = {zone.id: zone.centroid for zone in effective_demand_inputs(event, config).zones}
    return {
        pair.id: (
            _endpoint_node(pair.origin, zones, base, config, pair.id),
            _endpoint_node(pair.destination, zones, base, config, pair.id),
        )
        for pair in config.demand.od_pairs
    }


# --- archi, deviazioni e incroci ------------------------------------------------------------------


def _edge_name(base: nx.MultiDiGraph, edge: tuple[int, int, int]) -> str | None:
    name = base.edges[edge].get("name")
    return name if isinstance(name, str) else None


def _edge_length_m(base: nx.MultiDiGraph, edge: tuple[int, int, int]) -> float:
    return float(base.edges[edge]["length_m"])


def _edge_feature(base: nx.MultiDiGraph, key: str, properties: dict[str, JsonValue]) -> Feature:
    """Un arco come `Feature` GeoJSON (LineString); l'id è la chiave dell'arco."""
    coordinates = edge_coordinates(base, parse_edge_key(key), COORD_DECIMALS)
    geometry: dict[str, JsonValue] = {
        "type": "LineString",
        "coordinates": [list(c) for c in coordinates],
    }
    return Feature(id=key, geometry=geometry, properties=properties)


def _node_label(base: nx.MultiDiGraph, node: int) -> str:
    names = sorted(
        {
            part
            for edges in (
                base.in_edges(node, keys=True, data=True),
                base.out_edges(node, keys=True, data=True),
            )
            for *_, data in edges
            for part in osm_name_parts(data.get("name"))
        }
    )
    return " / ".join(names[:2]) if names else f"Incrocio {node}"


def _critical_edges(
    base: nx.MultiDiGraph, assignment: Assignment, threshold: float
) -> list[CriticalEdge]:
    """Gli archi aperti con v/c oltre `threshold`, dal più carico (a parità, per chiave)."""
    critical = []
    for key, load in assignment.edges.items():
        if load.vc > threshold:
            edge = parse_edge_key(key)
            critical.append(
                CriticalEdge(key, _edge_name(base, edge), load.vc, _edge_length_m(base, edge))
            )
    critical.sort(key=lambda c: (-c.vc, parse_edge_key(c.edge_key)))
    return critical


def _deviations(
    event_pairs: Sequence[tuple[int, int]],
    final: Mapping[tuple[int, int], Route | None],
    ref: Mapping[tuple[int, int], Route | None],
    assignment: Assignment,
) -> tuple[list[tuple[Route, Route]], set[str]]:
    """Le coppie dell'evento che cambiano cammino rispetto a R (cammino finale, cammino in R) e gli
    archi «deviati»: sul cammino finale, non su quello di R, con flusso dell'evento."""
    changed: list[tuple[Route, Route]] = []
    diverted: set[str] = set()
    for nodes in event_pairs:
        route, route_ref = final[nodes], ref[nodes]
        if route is None or route_ref is None or route.edges == route_ref.edges:
            continue
        changed.append((route, route_ref))
        diverted.update(
            key
            for key in route.edges
            if key not in route_ref.edges and assignment.edges[key].v_event > 0
        )
    return changed, diverted


def _critical_intersections(
    base: nx.MultiDiGraph, assignment: Assignment, diverted: set[str], top_n: int
) -> list[CriticalIntersection]:
    """I primi `top_n` nodi per il massimo v/c dei loro archi entranti deviati (a parità, il nodo
    con id minore), ciascuno con l'arco che raggiunge il massimo."""
    worst: dict[int, tuple[float, str]] = {}  # nodo → (v/c più alto degli archi entranti, chiave)
    for key in sorted(diverted, key=parse_edge_key):
        node = parse_edge_key(key)[1]
        vc = assignment.edges[key].vc
        if node not in worst or vc > worst[node][0]:
            worst[node] = (vc, key)
    ranked = sorted(worst.items(), key=lambda item: (-item[1][0], item[0]))
    return [
        CriticalIntersection(rank, node, vc, key, _node_label(base, node))
        for rank, (node, (vc, key)) in enumerate(ranked[:top_n], start=1)
    ]


class _Emit(Protocol):
    """Il costruttore dei `Measured` di `road_metrics`: id, fonte, input e assunzioni sono già
    fissati; restano il nome, il valore, l'unità, la formula e le assunzioni specifiche."""

    def __call__(
        self,
        parts: Sequence[str],
        value: float,
        unit: str,
        method: str,
        extra: Sequence[str] = (),
    ) -> Measured: ...


def _od_time_measures(
    measure: _Emit,
    config: EngineConfig,
    od_nodes: Mapping[str, tuple[int, int]],
    final: Mapping[tuple[int, int], Route | None],
    ref: Mapping[tuple[int, int], Route | None],
) -> list[Measured]:
    """Per ogni coppia O/D con un cammino: il tempo finale e quello in R; poi la media semplice
    (le coppie senza cammino sono escluse e dichiarate; nessuna media se non ce n'è nessuna)."""
    out: list[Measured] = []
    times: list[float] = []
    missing: list[str] = []
    for pair in config.demand.od_pairs:
        route, route_ref = final[od_nodes[pair.id]], ref[od_nodes[pair.id]]
        if route is None:
            missing.append(pair.id)
            continue
        times.append(route.time_min)
        out.append(
            measure(
                ("od_time", pair.id),
                route.time_min,
                "min",
                "cammino a costo minimo sui carichi finali: somma dei tempi reali degli archi",
                ("archi chiusi esclusi dall'instradamento",),
            )
        )
        if route_ref is not None:
            out.append(
                measure(
                    ("od_time_ref", pair.id),
                    route_ref.time_min,
                    "min",
                    "come od_time, nel riferimento R (solo traffico di fondo, nessuna chiusura)",
                )
            )
    if times:
        note = (
            (f"coppie senza percorso escluse dalla media: {', '.join(missing)}",) if missing else ()
        )
        out.append(
            measure(
                ("od_time", "mean"),
                sum(times) / len(times),
                "min",
                f"media semplice dei tempi O/D di {len(times)} coppie",
                note,
            )
        )
    return out


def _detour_measure(
    measure: _Emit, changed: Sequence[tuple[Route, Route]], pair_count: int
) -> Measured:
    """La lunghezza media della deviazione (con segno) sulle coppie che cambiano cammino; 0 se
    nessuna cambia, e lo dice un'assunzione."""
    extra_km = (
        sum(route.length_m - route_ref.length_m for route, route_ref in changed)
        / len(changed)
        / 1000
        if changed
        else 0.0
    )
    return measure(
        ("detour_extra_km",),
        extra_km,
        "km",
        "media di (cammino finale − cammino in R) sulle coppie O/D dell'evento che cambiano "
        "percorso",
        (
            (f"{len(changed)} coppie su {pair_count} cambiano percorso",)
            if changed
            else ("nessuna coppia O/D cambia percorso: 0 per definizione",)
        ),
    )


# --- metriche -------------------------------------------------------------------------------------


def road_metrics(
    base: nx.MultiDiGraph,
    network: RoadNetwork,
    assignment: Assignment,
    reference: Assignment,
    demand: Demand,
    event: Event,
    config: EngineConfig,
    *,
    background: Background,
    id_prefix: Sequence[str],
    as_of: datetime,
) -> RoadMetrics:
    """Metriche e layer di una finestra e di un'iterazione.

    `base` è la rete di base, `network` quella con chiusure e misure (`apply_measures`),
    `assignment` il suo carico, `reference` quello di R (`build_reference`), `demand` la domanda
    e `background` il traffico di fondo della stessa finestra. `id_prefix` apre gli id dei
    `Measured` e `as_of` è il loro istante (dato da chi chiama: la funzione non legge l'orologio).
    Le assunzioni di tutti questi input finiscono in ogni `Measured`.
    """
    window = demand.window
    threshold = config.metrics.vc_critical_threshold
    slice_minutes = config.time_slice_minutes
    inputs = (*demand.inputs, f"rete stradale: {len(assignment.edges)} archi aperti")
    common = unique(
        STATIC_MODEL_ASSUMPTION,
        *assignment.assumptions,
        *network.assumptions,
        *demand.assumptions,
        *background.assumptions,
        describe_sources(base),
    )

    def measure(
        parts: Sequence[str], value: float, unit: str, method: str, extra: Sequence[str] = ()
    ) -> Measured:
        return make_measured(
            id=measured_id(*id_prefix, "road", window, *parts),
            value=value,
            unit=unit,
            kind="simulated",
            source=SOURCE,
            method=method,
            inputs=inputs,
            assumptions=[*common, *extra],
            as_of=as_of,
        )

    # --- coppie O/D delle metriche e coppie dell'evento, tutte con una sola ricerca per origine
    od_nodes = od_pair_nodes(event, base, config)
    event_pairs = sorted({(f.origin_node, f.dest_node) for f in demand.flows})
    wanted = [*od_nodes.values(), *event_pairs]
    final = Router(network.graph, assignment.edges).routes(wanted)
    ref = Router(base, reference.edges).routes(wanted)

    out: list[Measured] = []

    # --- ore-veicolo
    veh_hours = sum(
        load.v_total * load.t_min / 60 * (slice_minutes / 60) for load in assignment.edges.values()
    )
    out.append(
        measure(
            ("veh_hours",),
            veh_hours,
            "veic·h",
            f"Σ archi (v_totale × t_min / 60) × ({slice_minutes}/60), fascia di picco",
        )
    )

    # --- tempi O/D
    out += _od_time_measures(measure, config, od_nodes, final, ref)

    # --- archi critici
    critical = _critical_edges(base, assignment, threshold)
    out.append(
        measure(
            ("critical_edges", "count"), len(critical), "n", f"archi aperti con v/c > {threshold:g}"
        )
    )
    out.append(
        measure(
            ("critical_edges", "km"),
            sum(c.length_m for c in critical) / 1000,
            "km",
            f"lunghezza degli archi aperti con v/c > {threshold:g}",
        )
    )

    # --- deviazioni, coppie non assegnate e incroci critici
    changed, diverted = _deviations(event_pairs, final, ref, assignment)
    out.append(_detour_measure(measure, changed, len(event_pairs)))
    out.append(
        measure(
            ("unassigned_pairs",),
            len(assignment.unassigned),
            "n",
            "coppie O/D della domanda senza percorso nella rete",
        )
    )
    intersections = _critical_intersections(
        base, assignment, diverted, config.metrics.critical_intersections_top_n
    )
    for item in intersections:
        out.append(
            measure(
                ("critical_intersection", str(item.rank), "vc"),
                item.vc,
                "rapporto",
                "massimo v/c degli archi entranti nell'incrocio sui cammini deviati",
                (f"incrocio {item.node} ({item.label}), arco {item.edge_key}",),
            )
        )

    # --- layer
    layers = {
        "edges_vc": _edges_layer(base, network, assignment, diverted, window, config),
        "closures": _closures_layer(base, event),
        "critical_intersections": _intersections_layer(base, intersections, id_prefix, window),
    }
    return RoadMetrics(
        window=window,
        measures=tuple(out),
        layers=layers,
        critical_edges=tuple(critical),
        critical_intersections=tuple(intersections),
    )


# --- layer GeoJSON --------------------------------------------------------------------------------


def _vc_class(vc: float, config: EngineConfig) -> int:
    """0–3: quante soglie di `metrics.vc_classes` il v/c raggiunge (`vc >= soglia`)."""
    return sum(1 for limit in config.metrics.vc_classes if vc >= limit)


def _edges_layer(
    base: nx.MultiDiGraph,
    network: RoadNetwork,
    assignment: Assignment,
    diverted: set[str],
    window: Window,
    config: EngineConfig,
) -> FeatureCollection:
    first_class = config.metrics.vc_classes[0]

    def feature(key: str, vc: float, closed: bool) -> Feature:
        edge = parse_edge_key(key)
        return _edge_feature(
            base,
            key,
            {
                "edge_key": key,
                "name": _edge_name(base, edge),
                "length_m": _edge_length_m(base, edge),
                "vc": vc,
                "vc_class": _vc_class(vc, config),
                "closed": closed,
                "detour": key in diverted,
                "window": window,
            },
        )

    features = [
        feature(key, load.vc, False)
        for key, load in assignment.edges.items()
        if load.vc >= first_class or load.v_event > 0
    ]
    features += [feature(key, 0.0, True) for key in sorted(network.closed, key=parse_edge_key)]
    return FeatureCollection(features=features)


def _closures_layer(base: nx.MultiDiGraph, event: Event) -> FeatureCollection:
    features: list[Feature] = []
    seen: set[str] = set()
    for closure in event.closures:
        for key in sorted(resolve_closure(closure, base), key=parse_edge_key):
            if key in seen:  # un arco in più chiusure: vale la prima
                continue
            seen.add(key)
            properties: dict[str, JsonValue] = {
                "edge_key": key,
                "label": closure.label,
                "length_m": _edge_length_m(base, parse_edge_key(key)),
                "mode": closure.mode,
            }
            if closure.mode == "capacity_reduction":
                properties["capacity_factor"] = closure.capacity_factor
            features.append(_edge_feature(base, key, properties))
    return FeatureCollection(features=features)


def _intersections_layer(
    base: nx.MultiDiGraph,
    intersections: Sequence[CriticalIntersection],
    id_prefix: Sequence[str],
    window: Window,
) -> FeatureCollection:
    features = []
    for item in intersections:
        data = base.nodes[item.node]
        features.append(
            Feature(
                id=str(item.node),
                geometry=geojson_point(float(data["y"]), float(data["x"])),
                properties={
                    "node": str(item.node),
                    "label": item.label,
                    "rank": item.rank,
                    "vc": item.vc,
                    "window": window,
                    "evidence_id": measured_id(
                        *id_prefix, "road", window, "critical_intersection", str(item.rank), "vc"
                    ),
                },
            )
        )
    return FeatureCollection(features=features)
