import heapq
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import networkx as nx

from app.data.resolvers import edge_key
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.demand import OdFlow
from app.engine.graph import GraphError
from app.models.config import EngineConfig


def bpr_time(t0_min: float, volume: float, capacity: float, alpha: float, beta: float) -> float:
    """Tempo di percorrenza BPR in minuti: `t0 × (1 + α (v/c)^β)`."""
    return t0_min * (1.0 + alpha * (volume / capacity) ** beta)


@dataclass(frozen=True, slots=True)
class EdgeLoad:
    """Il carico finale di un arco aperto."""

    v_event: float  # veic/h dovuti all'evento
    v_background: float  # veic/h di fondo
    capacity_vph: float
    v_total: float  # fondo + evento
    vc: float  # v_total / capacity_vph
    t_min: float  # tempo di percorrenza BPR, minuti
    cost_min: float  # t_min × perceived_factor: il costo con cui si sceglie il cammino


@dataclass(frozen=True, slots=True)
class Assignment:
    steps: int
    seed: int  # registrato anche se il motore è deterministico
    edges: Mapping[str, EdgeLoad]  # per chiave "u-v-k"; solo archi aperti, in ordine di chiave
    unassigned: tuple[OdFlow, ...]  # coppie senza percorso
    demand_veh_per_hour: float  # totale richiesto
    assigned_veh_per_hour: float  # totale assegnato; assegnato + non assegnato = richiesto
    assumptions: tuple[str, ...]

    @property
    def unassigned_veh_per_hour(self) -> float:
        return sum(flow.veh_per_hour for flow in self.unassigned)


# --- rete di instradamento ------------------------------------------------------------------------


@dataclass(slots=True)
class _Network:
    """La rete come array paralleli (più veloce di un grafo per il Dijkstra ripetuto).

    Nodi e archi sono indicizzati in ordine di id e di chiave `(u, v, k)`: l'indice di un arco è il
    suo posto nella chiave, quindi «chiave minore» e «indice minore» sono la stessa cosa.
    """

    node_index: dict[int, int]
    keys: list[tuple[int, int, int]]
    tail: list[int]
    head: list[int]
    t0: list[float]
    capacity: list[float]
    background: list[float]
    perceived: list[float]
    outgoing: list[list[int]]  # per nodo, gli archi uscenti instradabili (senza anelli)


def _build_network(graph: nx.MultiDiGraph, background: Mapping[str, float]) -> _Network:
    node_index = {node: i for i, node in enumerate(sorted(graph.nodes))}
    net = _Network(
        node_index=node_index,
        keys=[],
        tail=[],
        head=[],
        t0=[],
        capacity=[],
        background=[],
        perceived=[],
        outgoing=[[] for _ in node_index],
    )
    for u, v, k in sorted(graph.edges(keys=True)):
        key = edge_key(u, v, k)
        data = graph.edges[u, v, k]
        t0, capacity = data.get("t0_min"), data.get("capacity_vph")
        if t0 is None or capacity is None:
            raise GraphError(
                f"Arco {key}: mancano `t0_min` o `capacity_vph` (usa engine.graph.build_road_graph)"
            )
        if capacity < 0:
            raise GraphError(f"Arco {key}: capacità negativa ({capacity})")
        if capacity == 0:  # chiuso: fuori dall'instradamento e dai risultati
            continue
        if key not in background:
            raise GraphError(f"Arco {key}: manca il traffico di fondo (engine.background)")
        perceived = data.get("perceived_factor", 1.0)
        if not perceived > 0:
            raise GraphError(f"Arco {key}: perceived_factor non positivo ({perceived})")
        edge = len(net.keys)
        net.keys.append((u, v, k))
        net.tail.append(node_index[u])
        net.head.append(node_index[v])
        net.t0.append(float(t0))
        net.capacity.append(float(capacity))
        net.background.append(float(background[key]))
        net.perceived.append(float(perceived))
        if u != v:
            net.outgoing[node_index[u]].append(edge)
    return net


def _dijkstra(net: _Network, cost: Sequence[float], source: int, targets: set[int]) -> list[int]:
    """Gli archi predecessori dell'albero dei cammini minimi da `source` (-1 = non raggiunto o
    origine), fermandosi quando i `targets` sono stati tutti raggiunti.

    A parità di costo il predecessore di un nodo è l'arco entrante con l'indice minore (02 5).
    """
    count = len(net.outgoing)
    dist = [math.inf] * count
    pred = [-1] * count
    done = [False] * count
    dist[source] = 0.0
    heap: list[tuple[float, int]] = [(0.0, source)]
    remaining = set(targets)
    while heap:
        d, node = heapq.heappop(heap)
        if done[node]:
            continue
        done[node] = True
        remaining.discard(node)
        if not remaining:
            break
        for edge in net.outgoing[node]:
            head = net.head[edge]
            if done[head]:
                continue
            candidate = d + cost[edge]
            if candidate < dist[head]:
                dist[head] = candidate
                pred[head] = edge
                heapq.heappush(heap, (candidate, head))
            elif candidate == dist[head] and edge < pred[head]:
                pred[head] = edge
    return pred


def _path(net: _Network, pred: Sequence[int], target: int) -> list[int]:
    """Gli archi del cammino minimo che arriva a `target` (da `_dijkstra`), dall'ultimo al primo;
    vuoto se `target` è l'origine o non è raggiunto."""
    edges: list[int] = []
    edge = pred[target]
    while edge != -1:
        edges.append(edge)
        edge = pred[net.tail[edge]]
    return edges


# --- assegnazione ---------------------------------------------------------------------------------


def assign(
    graph: nx.MultiDiGraph,
    background: Mapping[str, float],
    flows: Sequence[OdFlow],
    config: EngineConfig,
) -> Assignment:
    """Carica `flows` sulla rete `graph` (con le misure già applicate) sopra il `background`.

    `background` è quello della rete di BASE (`build_background`): una chiave mancante per un arco
    aperto è un errore (`GraphError`). Un arco con `capacity_vph` 0 è chiuso. Il risultato contiene
    solo gli archi aperti.
    """
    net = _build_network(graph, background)
    alpha, beta = config.bpr.alpha, config.bpr.beta
    steps, step_share = config.assignment.steps, config.assignment.step_share

    ordered = sorted(
        flows, key=lambda f: (f.origin_node, f.dest_node, f.zone_id, f.destination_label or "")
    )
    node_index = net.node_index
    unassigned: set[int] = {
        i
        for i, flow in enumerate(ordered)
        if flow.origin_node not in node_index or flow.dest_node not in node_index
    }
    by_origin: dict[int, list[int]] = {}
    for i, flow in enumerate(ordered):
        if i not in unassigned:
            by_origin.setdefault(node_index[flow.origin_node], []).append(i)

    count = len(net.keys)
    event = [0.0] * count
    for _ in range(steps):
        cost = [
            bpr_time(net.t0[e], net.background[e] + event[e], net.capacity[e], alpha, beta)
            * net.perceived[e]
            for e in range(count)
        ]
        for origin, members in by_origin.items():
            live = [i for i in members if i not in unassigned]
            targets = {node_index[ordered[i].dest_node] for i in live}
            pred = _dijkstra(net, cost, origin, targets)
            for i in live:
                flow = ordered[i]
                target = node_index[flow.dest_node]
                if target == origin:  # origine = destinazione: niente rete da caricare
                    continue
                if pred[target] == -1:
                    unassigned.add(i)
                    continue
                quota = step_share * flow.veh_per_hour
                for edge in _path(net, pred, target):
                    event[edge] += quota

    edges: dict[str, EdgeLoad] = {}
    for e, (u, v, k) in enumerate(net.keys):
        total = net.background[e] + event[e]
        time = bpr_time(net.t0[e], total, net.capacity[e], alpha, beta)
        edges[edge_key(u, v, k)] = EdgeLoad(
            v_event=event[e],
            v_background=net.background[e],
            capacity_vph=net.capacity[e],
            v_total=total,
            vc=total / net.capacity[e],
            t_min=time,
            cost_min=time * net.perceived[e],
        )

    lost = tuple(ordered[i] for i in sorted(unassigned))
    demand = sum(flow.veh_per_hour for flow in ordered)
    missing = sum(flow.veh_per_hour for flow in lost)
    assumptions = [
        STATIC_MODEL_ASSUMPTION,
        f"assegnazione incrementale in {steps} passi da {step_share * 100:g} %, tutto o niente per "
        f"coppia O/D sul cammino a costo minimo; costo = tempo BPR t0 (1 + {alpha:g} (v/c)^"
        f"{beta:g}) × fattore di percezione; non è un equilibrio d'utente",
        "archi chiusi (capacità 0) esclusi dall'instradamento",
    ]
    if lost:
        assumptions.append(
            f"{len(lost)} coppie O/D senza percorso non assegnate ({missing:.0f} veic/h)"
        )
    return Assignment(
        steps=steps,
        seed=config.seed,
        edges=edges,
        unassigned=lost,
        demand_veh_per_hour=demand,
        assigned_veh_per_hour=demand - missing,
        assumptions=tuple(assumptions),
    )


# --- cammini minimi sui carichi finali ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Route:
    """Un cammino tra due nodi: gli archi dall'origine alla destinazione."""

    edges: tuple[str, ...]  # chiavi "u-v-k"; vuoto se origine = destinazione
    time_min: float  # somma dei tempi reali `t_min`
    length_m: float


class Router:
    """Cammini minimi per COSTO (`cost_min`, che include il fattore di percezione) sui carichi di
    un'assegnazione, con lo stesso Dijkstra deterministico di `assign`. Il tempo e la lunghezza
    riportati sono quelli reali del cammino scelto. Serve alle metriche (tempi O/D, deviazioni).

    `loads` sono gli `Assignment.edges` e `graph` la rete su cui sono stati calcolati: gli archi
    chiusi (capacità 0) non sono instradabili né in `loads`.
    """

    def __init__(self, graph: nx.MultiDiGraph, loads: Mapping[str, EdgeLoad]) -> None:
        self._net = _build_network(graph, {key: load.v_background for key, load in loads.items()})
        self._loads = loads
        self._length = {
            edge_key(*key): float(graph.edges[key].get("length_m", 0.0)) for key in self._net.keys
        }
        self._cost = [loads[edge_key(*key)].cost_min for key in self._net.keys]

    def routes(self, pairs: Iterable[tuple[int, int]]) -> dict[tuple[int, int], Route | None]:
        """Il cammino di ogni coppia (origine, destinazione); `None` se non c'è (o se un nodo non
        è nella rete). Una sola ricerca per origine."""
        net = self._net
        wanted = sorted(set(pairs))
        result: dict[tuple[int, int], Route | None] = dict.fromkeys(wanted)
        by_origin: dict[int, list[int]] = {}
        for origin, dest in wanted:
            if origin in net.node_index and dest in net.node_index:
                by_origin.setdefault(net.node_index[origin], []).append(net.node_index[dest])
        index_to_node = {index: node for node, index in net.node_index.items()}
        for source, targets in by_origin.items():
            pred = _dijkstra(net, self._cost, source, set(targets))
            for target in targets:
                if target != source and pred[target] == -1:
                    continue
                path = [edge_key(*net.keys[edge]) for edge in reversed(_path(net, pred, target))]
                result[(index_to_node[source], index_to_node[target])] = Route(
                    edges=tuple(path),
                    time_min=sum(self._loads[key].t_min for key in path),
                    length_m=sum(self._length[key] for key in path),
                )
        return result
