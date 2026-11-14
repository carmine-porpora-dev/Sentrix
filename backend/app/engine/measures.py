from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import networkx as nx

from app.data.resolvers import edge_key, parse_edge_key, resolve_closure
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.assign import EdgeLoad
from app.models.base import Window
from app.models.config import EngineConfig, MeasureEffects
from app.models.event import Event
from app.models.operations import ACTIVE_STATES, OperationRequest

# Stati di una richiesta che valgono come «misura accettata» (04 3).
ROAD_TYPES = frozenset({"close_road", "traffic_post", "signal_plan_change", "detour_signage"})
# Misure che esistono ma non agiscono sulla rete stradale (le gestisce il motore TPL o nessuno).
NON_ROAD_TYPES = frozenset(
    {
        "bus_detour",
        "stop_suspension",
        "add_runs",
        "extend_hours",
        "crowd_control_post",
        "citizen_notice",
    }
)

EdgeTuple = tuple[int, int, int]


class MeasureError(ValueError):
    """Una misura o una chiusura non si può applicare alla rete."""


@dataclass(frozen=True, slots=True)
class RoadNetwork:
    """La rete su cui assegnare il traffico di una finestra e di un'iterazione."""

    graph: nx.MultiDiGraph  # copia della rete di base con chiusure e misure
    closed: frozenset[str]  # chiavi degli archi con capacità 0: servono a `build_background`
    applied: tuple[str, ...]  # action_id delle misure che hanno cambiato la rete, nell'ordine
    assumptions: tuple[str, ...]


def favored_edge_key(graph: nx.MultiDiGraph, node: int, loads: Mapping[str, EdgeLoad]) -> str:
    """L'arco entrante nell'incrocio `node` con il v/c più alto in `loads` (l'iterazione
    precedente); a parità, la chiave minore. Sarà la `payload["favored_edge_key"]` di una richiesta
    `signal_plan_change`. Solo gli archi aperti hanno un carico: `MeasureError` se non ce n'è."""
    candidates = [
        (-loads[key].vc, (u, v, k), key)
        for u, v, k in graph.in_edges(node, keys=True)
        if (key := edge_key(u, v, k)) in loads
    ]
    if not candidates:
        raise MeasureError(f"L'incrocio {node} non ha archi entranti aperti con un carico")
    return min(candidates)[2]


def _check_config(config: EngineConfig) -> None:
    """I valori sono di engine.yaml; la `scope` descrive a che archi si applicano e il codice sa
    applicarne una sola per tipo: se il file ne dichiara un'altra, meglio dirlo che ignorarlo."""
    effects = config.measure_effects
    expected = {
        "traffic_post": (effects.traffic_post.scope, "incoming_edges"),
        "signal_plan_change": (
            effects.signal_plan_change.scope,
            "incoming_edges_favored_direction",
        ),
    }
    for name, (found, supported) in expected.items():
        if found != supported:
            raise MeasureError(
                f"engine.yaml: measure_effects.{name}.scope è '{found}', "
                f"ma il motore sa applicare solo '{supported}'"
            )


def _scale(graph: nx.MultiDiGraph, key: EdgeTuple, attribute: str, factor: float) -> None:
    data = graph.edges[key]
    data[attribute] = data.get(attribute, 1.0) * factor


def _node(request: OperationRequest, graph: nx.MultiDiGraph) -> int:
    try:
        node = int(request.target)
    except ValueError:
        raise MeasureError(
            f"{request.action_id} ({request.type}): il bersaglio '{request.target}' non è un "
            "id di nodo"
        ) from None
    if node not in graph:
        raise MeasureError(
            f"{request.action_id} ({request.type}): l'incrocio {node} non esiste nella rete"
        )
    return node


def _edges(request: OperationRequest, graph: nx.MultiDiGraph) -> list[EdgeTuple]:
    """Le chiavi del bersaglio, senza doppioni e in ordine di chiave."""
    found: set[EdgeTuple] = set()
    for part in request.target.split(","):
        try:
            key = parse_edge_key(part.strip())
        except ValueError as error:
            raise MeasureError(f"{request.action_id} ({request.type}): {error}") from None
        if not graph.has_edge(*key):
            raise MeasureError(
                f"{request.action_id} ({request.type}): l'arco {part.strip()} non esiste nella rete"
            )
        found.add(key)
    return sorted(found)


def check_requests(requests: Sequence[OperationRequest]) -> None:
    """Il chiamante passa solo misure accettate di tipi del catalogo: altrimenti `MeasureError`. Lo
    usano il motore stradale e quello del trasporto pubblico."""
    for request in requests:
        if request.state not in ACTIVE_STATES:
            raise MeasureError(
                f"{request.action_id} ({request.type}): la richiesta è {request.state}, "
                "non accettata"
            )
        if request.type not in ROAD_TYPES | NON_ROAD_TYPES:
            raise MeasureError(f"{request.action_id}: tipo di misura sconosciuto '{request.type}'")


def _apply_event_closures(
    graph: nx.MultiDiGraph, base: nx.MultiDiGraph, event: Event, effects: MeasureEffects
) -> str | None:
    """Applica a `graph` (una copia) le chiusure dell'Evento; la riga delle assunzioni, o `None`
    se l'Evento non ne ha. Gli archi si contano una volta sola anche se stanno in più chiusure."""
    closed: set[EdgeTuple] = set()
    reduced: set[EdgeTuple] = set()
    for closure in event.closures:
        keys = [parse_edge_key(key) for key in resolve_closure(closure, base)]
        factor = (
            effects.close_road.capacity_factor
            if closure.mode == "closed"
            else closure.capacity_factor
        )
        for key in sorted(keys):
            _scale(graph, key, "capacity_vph", factor)
        (closed if closure.mode == "closed" else reduced).update(keys)
    if not (closed or reduced):
        return None
    return (
        f"chiusure dell'evento: {len(closed)} archi chiusi, "
        f"{len(reduced - closed)} a capacità ridotta"
    )


def target_edges(request: OperationRequest, graph: nx.MultiDiGraph) -> list[EdgeTuple]:
    """Gli archi che una misura stradale tocca, nell'ordine in cui `apply_measures` li scala: gli
    entranti dell'incrocio (`traffic_post`), l'arco favorito (`signal_plan_change`), gli archi
    indicati (`close_road`, `detour_signage`). `MeasureError` se il bersaglio non esiste."""
    if request.type == "traffic_post":
        return sorted(graph.in_edges(_node(request, graph), keys=True))
    if request.type == "signal_plan_change":
        return [_favored(request, graph, _node(request, graph))]
    return _edges(request, graph)


def _apply_request(
    graph: nx.MultiDiGraph, request: OperationRequest, effects: MeasureEffects
) -> None:
    """Applica a `graph` (una copia) una misura stradale accettata."""
    if request.type == "close_road":
        attribute, factor = "capacity_vph", effects.close_road.capacity_factor
    elif request.type == "traffic_post":
        attribute, factor = "capacity_vph", effects.traffic_post.capacity_factor
    elif request.type == "signal_plan_change":
        attribute, factor = "capacity_vph", effects.signal_plan_change.capacity_factor
    else:  # detour_signage
        attribute, factor = "perceived_factor", effects.detour_signage.perceived_time_factor
    for key in target_edges(request, graph):
        _scale(graph, key, attribute, factor)


def _request_assumptions(counts: Mapping[str, int], effects: MeasureEffects) -> list[str]:
    descriptions = {
        "close_road": "archi chiusi",
        "traffic_post": f"capacità × {effects.traffic_post.capacity_factor:g} sugli archi entranti",
        "signal_plan_change": f"capacità × {effects.signal_plan_change.capacity_factor:g} "
        "sull'arco entrante favorito",
        "detour_signage": f"costo percepito × {effects.detour_signage.perceived_time_factor:g} "
        "sugli archi indicati, tempo reale invariato",
    }
    return [f"{counts[kind]} × {kind}: {descriptions[kind]}" for kind in sorted(counts)]


def apply_measures(
    base: nx.MultiDiGraph,
    event: Event,
    window: Window,
    requests: Sequence[OperationRequest],
    config: EngineConfig,
) -> RoadNetwork:
    """La rete di `base` con le chiusure di `event` e le misure accettate di `window`.

    `base` non viene modificata. `MeasureError` per una richiesta non accettata, di tipo ignoto o
    con un bersaglio che non esiste (e per un `engine.yaml` che il motore non sa applicare);
    `ResolveError` se una chiusura dell'Evento non si risolve.
    """
    _check_config(config)
    effects = config.measure_effects
    ordered = sorted(requests, key=lambda r: (r.iteration, r.action_id))
    check_requests(ordered)

    graph = base.copy()
    assumptions = [STATIC_MODEL_ASSUMPTION]
    closures = _apply_event_closures(graph, base, event, effects)
    if closures is not None:
        assumptions.append(closures)

    applied: list[str] = []
    counts: dict[str, int] = {}
    for request in ordered:
        if request.type not in ROAD_TYPES or request.window != window:
            continue
        _apply_request(graph, request, effects)
        applied.append(request.action_id)
        counts[request.type] = counts.get(request.type, 0) + 1
    assumptions += _request_assumptions(counts, effects)

    closed = frozenset(
        edge_key(u, v, k)
        for u, v, k, data in graph.edges(keys=True, data=True)
        if data["capacity_vph"] == 0
    )
    return RoadNetwork(
        graph=graph, closed=closed, applied=tuple(applied), assumptions=tuple(assumptions)
    )


def _favored(request: OperationRequest, graph: nx.MultiDiGraph, node: int) -> EdgeTuple:
    raw = request.payload.get("favored_edge_key")
    if not isinstance(raw, str):
        raise MeasureError(
            f"{request.action_id} (signal_plan_change): manca payload['favored_edge_key']"
        )
    try:
        u, v, k = parse_edge_key(raw)
    except ValueError as error:
        raise MeasureError(f"{request.action_id} (signal_plan_change): {error}") from None
    if v != node or not graph.has_edge(u, v, k):
        raise MeasureError(
            f"{request.action_id} (signal_plan_change): '{raw}' non è un arco entrante "
            f"nell'incrocio {node}"
        )
    return (u, v, k)
