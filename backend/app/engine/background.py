from collections.abc import Collection, Mapping
from dataclasses import dataclass

import networkx as nx

from app.data.resolvers import edge_key
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.graph import GraphError
from app.models.base import Window
from app.models.event import Event


@dataclass(frozen=True, slots=True)
class Background:
    window: Window
    share: float  # quota della capacità occupata dal fondo (da 0 a 1)
    volumes: Mapping[str, float]  # veic/h per arco "u-v-k": uno per ogni arco della rete
    closed: frozenset[str]  # gli archi a fondo 0 perché chiusi
    assumptions: tuple[str, ...]


def build_background(
    graph: nx.MultiDiGraph,
    event: Event,
    window: Window,
    closed: Collection[str] = (),
) -> Background:
    """Il traffico di fondo di ogni arco di `graph` nella fascia di picco di `window`.

    `closed` sono le chiavi "u-v-k" degli archi chiusi (chiusure dell'Evento e misure
    `close_road`). `GraphError` se una non esiste nel grafo o se un arco non ha `capacity_vph`
    (la rete non è passata da `build_road_graph`).
    """
    share = event.background.peak_share(window)
    closed_keys = frozenset(closed)

    volumes: dict[str, float] = {}
    for u, v, k, data in graph.edges(keys=True, data=True):
        key = edge_key(u, v, k)
        capacity = data.get("capacity_vph")
        if capacity is None:
            raise GraphError(
                f"Arco {key}: manca `capacity_vph` (usa engine.graph.build_road_graph)"
            )
        volumes[key] = 0.0 if key in closed_keys else share * capacity

    unknown = sorted(key for key in closed_keys if key not in volumes)
    if unknown:
        raise GraphError(f"Archi chiusi che non esistono nel grafo: {unknown}")

    assumptions = [
        STATIC_MODEL_ASSUMPTION,
        f"traffico di fondo = {share * 100:g} % della capacità di ogni arco nella fascia di "
        f"picco ({window}), uguale per tutte le classi di strada; calcolato sulla capacità di "
        "base, prima di chiusure e misure",
    ]
    if closed_keys:
        assumptions.append(
            "il traffico di fondo degli archi chiusi non è redistribuito "
            f"({len(closed_keys)} archi a zero)"
        )
    return Background(
        window=window,
        share=share,
        volumes=volumes,
        closed=closed_keys,
        assumptions=tuple(assumptions),
    )
