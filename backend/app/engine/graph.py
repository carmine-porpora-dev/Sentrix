import math
from collections import Counter
from pathlib import Path
from typing import Any, Literal

import networkx as nx

from app.data.osm_graph import load_osm_graph
from app.data.resolvers import edge_key
from app.models.config import EngineConfig, RoadDefault
from app.models.edge_overrides import EdgeOverrides

# Da dove viene un valore. Il terzo caso non è nella spec 02 2 (che ne prevede due) ma è
# necessario: una correzione manuale non è né un dato OSM né un valore di riserva.
AttributeSource = Literal["osm", "default", "override"]


class GraphError(ValueError):
    """La rete o le sue correzioni non sono utilizzabili."""


def road_params(config: EngineConfig, highway: object) -> RoadDefault:
    """I valori di riserva della classe `highway`; la riga `default` se è assente o non prevista."""
    if isinstance(highway, str) and highway in config.road_defaults:
        return config.road_defaults[highway]
    return config.road_defaults["default"]


def osm_lanes_per_direction(data: dict[str, Any]) -> int | None:
    """Le corsie per senso di marcia dal tag OSM `lanes` di un arco (vedi la docstring del modulo);
    `None` se OSM non le dà."""
    lanes = data.get("lanes")
    if lanes is None or data.get("oneway") is True:
        return lanes
    return max(1, lanes // 2)


def _resolve[T](override: T | None, osm: T | None, default: T) -> tuple[T, AttributeSource]:
    if override is not None:
        return override, "override"
    if osm is not None:
        return osm, "osm"
    return default, "default"


def build_road_graph(
    raw: nx.MultiDiGraph, config: EngineConfig, overrides: EdgeOverrides | None = None
) -> nx.MultiDiGraph:
    """Una copia di `raw` con gli attributi del motore su ogni arco. `raw` non viene toccato.

    `GraphError` se una correzione riguarda un arco che non esiste o se un arco ha una lunghezza
    (`length_m`) assente, non finita o non positiva: il tempo a flusso libero non sarebbe definito.
    """
    corrections = {item.edge_key: item for item in (overrides.overrides if overrides else ())}
    existing = {edge_key(u, v, k) for u, v, k in raw.edges(keys=True)}
    unknown = sorted(set(corrections) - existing)
    if unknown:
        raise GraphError(f"Correzioni manuali su archi che non esistono nel grafo: {unknown}")

    graph = raw.copy()
    for u, v, k, data in graph.edges(keys=True, data=True):
        key = edge_key(u, v, k)
        length = data.get("length_m")
        if not isinstance(length, int | float) or not math.isfinite(length) or length <= 0:
            raise GraphError(f"Arco {key}: lunghezza `length_m` non valida ({length!r})")

        params = road_params(config, data.get("highway"))
        correction = corrections.get(key)
        lanes, lanes_source = _resolve(
            correction.lanes if correction else None, osm_lanes_per_direction(data), params.lanes
        )
        speed, speed_source = _resolve(
            correction.speed_kmh if correction else None,
            data.get("maxspeed_kmh"),
            params.speed_kmh,
        )
        data["lanes"] = lanes
        data["lanes_source"] = lanes_source
        data["speed_kmh"] = float(speed)
        data["speed_source"] = speed_source
        data["t0_min"] = length / (speed / 3.6) / 60
        data["capacity_vph"] = lanes * params.capacity_per_lane
    return graph


_SOURCE_LABELS: dict[AttributeSource, str] = {
    "osm": "OSM",
    "default": "valore di riserva della classe",
    "override": "correzione manuale",
}


def describe_sources(graph: nx.MultiDiGraph) -> str:
    """Da dove vengono corsie e velocità degli archi di `graph` (uscito da `build_road_graph`):
    una riga per le assunzioni di ogni metrica (02 2), perché un valore di riserva è una stima."""
    edges = [data for *_, data in graph.edges(data=True)]
    parts = []
    for name, field in (("corsie per senso", "lanes_source"), ("velocità", "speed_source")):
        counts = Counter(data[field] for data in edges)
        listed = ", ".join(f"{counts[src]} da {label}" for src, label in _SOURCE_LABELS.items())
        parts.append(f"{name}: {listed}")
    return f"rete di {len(edges)} archi; " + "; ".join(parts)


# --- caricamento da file, una volta per processo --------------------------------------------------


def require_graph_file(path: Path) -> None:
    """`GraphError` con l'indicazione di cosa fare se il file del grafo non c'è."""
    if not path.is_file():
        raise GraphError(f"Manca il grafo stradale {path}: esegui `make data`.")


_CACHE: dict[tuple[str, str, str], nx.MultiDiGraph] = {}


def load_road_graph(
    path: Path, config: EngineConfig, overrides: EdgeOverrides | None = None
) -> nx.MultiDiGraph:
    """La rete del motore da `path` (graph_drive.graphml), costruita una sola volta per processo
    per ogni combinazione di file, configurazione e correzioni. L'oggetto restituito è condiviso:
    non va modificato (vedi la docstring del modulo)."""
    require_graph_file(path)
    cache_key = (
        str(path.resolve()),
        config.content_hash(),
        overrides.content_hash() if overrides else "",
    )
    if cache_key not in _CACHE:
        _CACHE[cache_key] = build_road_graph(load_osm_graph(path), config, overrides)
    return _CACHE[cache_key]


def clear_road_graph_cache() -> None:
    """Svuota la cache di `load_road_graph` (per i test e per chi sostituisce il file)."""
    _CACHE.clear()
