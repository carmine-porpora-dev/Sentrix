import re
import unicodedata
from collections.abc import Hashable, Iterable, Sequence
from functools import cache
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from app.geo import METERS_PER_DEGREE, haversine_m
from app.models.event import Closure
from app.models.geo import GeoPoint

# OSMnx unisce con ";" i nomi di segmenti diversi fusi in un solo arco in fase di semplificazione.
OSM_NAME_SEPARATOR = ";"


class ResolveError(Exception):
    """Un nome o un punto non corrisponde a niente (o a troppo poco) nei dati."""


# --- nomi ---------------------------------------------------------------------------------------


@cache
def normalize_name(text: str) -> str:
    """Maiuscolo, senza accenti né punteggiatura: "MEDAGLIE D'ORO " -> "MEDAGLIE D ORO"."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", ascii_text.upper()).split())


def match_keys[K: Hashable](query: str, names_by_key: Iterable[tuple[K, Iterable[str]]]) -> list[K]:
    """Le chiavi con almeno un nome che corrisponde a `query` (regola nella docstring del modulo),
    nell'ordine in cui arrivano."""
    wanted = normalize_name(query)
    words = set(wanted.split())
    if not words:
        return []
    exact: list[K] = []
    partial: list[K] = []
    for key, names in names_by_key:
        normalized = [normalize_name(name) for name in names]
        if wanted in normalized:
            exact.append(key)
        elif any(words <= set(name.split()) for name in normalized):
            partial.append(key)
    return exact or partial


def osm_name_parts(name: Any) -> list[str]:
    """I nomi di un arco OSM: `None` → nessuno, "A; B" → ["A", "B"]."""
    if not isinstance(name, str):
        return []
    return [part.strip() for part in name.split(OSM_NAME_SEPARATOR) if part.strip()]


# --- chiusure -----------------------------------------------------------------------------------


def edge_key(u: int, v: int, k: int) -> str:
    return f"{u}-{v}-{k}"


def parse_edge_key(key: str) -> tuple[int, int, int]:
    """L'inverso di `edge_key`: "12-34-0" → (12, 34, 0). `ValueError` se non ha la forma u-v-k."""
    parts = key.split("-")
    if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts):
        raise ValueError(f"chiave arco non valida (attesa 'u-v-k'): {key!r}")
    u, v, k = (int(part) for part in parts)
    return u, v, k


def edge_point(
    graph: nx.MultiDiGraph, key: tuple[int, int, int], fraction: float
) -> tuple[float, float]:
    """(lon, lat) del punto a `fraction` (da 0 a 1) del percorso dell'arco, da u a v: sulla
    geometria se l'arco è curvo, altrimenti sulla retta tra i due nodi. 0,5 è il punto medio."""
    u, v, k = key
    geometry = graph.edges[u, v, k].get("geometry")
    if geometry is not None:
        point = geometry.interpolate(fraction, normalized=True)
        return float(point.x), float(point.y)
    a, b = graph.nodes[u], graph.nodes[v]
    return (
        (1 - fraction) * float(a["x"]) + fraction * float(b["x"]),
        (1 - fraction) * float(a["y"]) + fraction * float(b["y"]),
    )


def edge_coordinates(
    graph: nx.MultiDiGraph, key: tuple[int, int, int], decimals: int
) -> list[list[float]]:
    """Le coordinate [lon, lat] dell'arco per GeoJSON, arrotondate a `decimals` decimali: la
    geometria se l'arco è curvo, altrimenti la retta tra i due nodi."""
    u, v, k = key
    geometry = graph.edges[u, v, k].get("geometry")
    if geometry is not None:
        pairs = [(float(x), float(y)) for x, y in geometry.coords]
    else:
        pairs = [(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"])) for n in (u, v)]
    return [[round(x, decimals), round(y, decimals)] for x, y in pairs]


def edges_named(
    graph: nx.MultiDiGraph, street: str
) -> list[tuple[tuple[int, int, int], dict[str, Any]]]:
    """Gli archi della strada `street` (regola dei nomi), in ordine di chiave, con gli attributi."""
    by_key = {(u, v, k): d for u, v, k, d in graph.edges(keys=True, data=True)}
    keys = match_keys(street, ((key, osm_name_parts(d.get("name"))) for key, d in by_key.items()))
    return [(key, by_key[key]) for key in sorted(keys)]


def resolve_closure(closure: Closure, graph: nx.MultiDiGraph) -> list[str]:
    """Le chiavi "u-v-k" degli archi chiusi.

    * Se la chiusura ha già `edge_keys` (risolte o scelte a mano sulla mappa) sono quelle: si
      controlla soltanto che esistano nel grafo.
    * Altrimenti, per ogni nome in `street_names`, gli archi con quel nome; con `bbox` (ovest, sud,
      est, nord) restano quelli il cui PUNTO MEDIO cade dentro. Ogni nome deve trovare almeno un
      arco: un nome sbagliato non passa inosservato solo perché un altro ha trovato qualcosa.
    """
    if closure.edge_keys:
        missing = [key for key in closure.edge_keys if not _edge_exists(graph, key)]
        if missing:
            raise ResolveError(
                f"Chiusura «{closure.label}»: archi non presenti nel grafo: {', '.join(missing)}"
            )
        return list(closure.edge_keys)

    found: set[tuple[int, int, int]] = set()
    for street in closure.street_names:
        named = edges_named(graph, street)
        if not named:
            raise ResolveError(f"Chiusura «{closure.label}»: nessun arco chiamato «{street}»")
        inside = [
            key
            for key, data in named
            if closure.bbox is None or _inside(closure.bbox, edge_point(graph, key, 0.5))
        ]
        if not inside:
            raise ResolveError(
                f"Chiusura «{closure.label}»: {len(named)} archi chiamati «{street}», "
                f"nessuno con il punto medio dentro il bbox {list(closure.bbox or ())}"
            )
        found.update(inside)
    return [edge_key(*key) for key in sorted(found)]


def _inside(bbox: tuple[float, float, float, float], point: tuple[float, float]) -> bool:
    west, south, east, north = bbox
    lon, lat = point
    return west <= lon <= east and south <= lat <= north


def _edge_exists(graph: nx.MultiDiGraph, key: str) -> bool:
    return bool(graph.has_edge(*parse_edge_key(key)))


# --- punti --------------------------------------------------------------------------------------


def nearest_node(point: GeoPoint, graph: nx.MultiDiGraph) -> tuple[int, float]:
    """(id del nodo, distanza in metri) del nodo stradale più vicino. A parità vince l'id minore."""
    ids = np.array(sorted(graph.nodes), dtype=np.int64)
    lats = np.array([graph.nodes[n]["y"] for n in ids], dtype=float)
    lons = np.array([graph.nodes[n]["x"] for n in ids], dtype=float)
    distances = haversine_m(lats, lons, (point.lat, point.lon))
    best = int(np.argmin(distances))
    return int(ids[best]), float(distances[best])


def resolve_point(point: GeoPoint, graph: nx.MultiDiGraph, *, max_distance_m: float) -> int:
    """Il nodo stradale più vicino a `point`; errore se è oltre `max_distance_m`
    (`node_snap_max_distance_m` di engine.yaml)."""
    node, distance = nearest_node(point, graph)
    if distance > max_distance_m:
        raise ResolveError(
            f"Il punto ({point.lat:.5f}, {point.lon:.5f}) dista {distance:.0f} m dal nodo "
            f"stradale più vicino (massimo {max_distance_m:.0f} m)"
        )
    return node


def nearest_edges(
    points: Sequence[GeoPoint], graph: nx.MultiDiGraph
) -> list[tuple[tuple[int, int, int], float]]:
    """Per ogni punto, (chiave dell'arco più vicino, distanza in metri dalla sua linea).

    La distanza è dal punto al segmento più vicino della geometria dell'arco, calcolata su una
    proiezione piana locale (metri per grado: 111 195 in latitudine, per il coseno in longitudine):
    esatta a meno di centimetri sulle distanze di una città. A parità vince la chiave minore."""
    keys: list[tuple[int, int, int]] = []
    segments: list[list[float]] = []  # lon1, lat1, lon2, lat2
    owners: list[int] = []
    for key in sorted(graph.edges(keys=True)):
        geometry = graph.edges[key].get("geometry")
        if geometry is not None:
            coords = [(float(x), float(y)) for x, y in geometry.coords]
        else:
            coords = [(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"])) for n in key[:2]]
        for (x1, y1), (x2, y2) in zip(coords, coords[1:], strict=False):
            segments.append([x1, y1, x2, y2])
            owners.append(len(keys))
        keys.append(key)
    seg = np.array(segments, dtype=float)
    owner = np.array(owners, dtype=int)
    result = []
    for point in points:
        scale = np.cos(np.radians(point.lat))
        ax, ay = (
            (seg[:, 0] - point.lon) * scale * METERS_PER_DEGREE,
            (seg[:, 1] - point.lat) * METERS_PER_DEGREE,
        )
        bx, by = (
            (seg[:, 2] - point.lon) * scale * METERS_PER_DEGREE,
            (seg[:, 3] - point.lat) * METERS_PER_DEGREE,
        )
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(length_sq > 0, -(ax * dx + ay * dy) / length_sq, 0.0)
        t = np.clip(t, 0.0, 1.0)
        distance = np.hypot(ax + t * dx, ay + t * dy)
        best = int(np.argmin(distance))  # il primo minimo: le chiavi sono già in ordine
        result.append((keys[int(owner[best])], float(distance[best])))
    return result


# --- fermate ------------------------------------------------------------------------------------


def match_stops(target: str, stops: pd.DataFrame) -> pd.DataFrame:
    """Le righe di `stops` (tabella `stops.txt` del GTFS) il cui nome corrisponde a `target`."""
    names = ((i, [str(n)] if pd.notna(n) else []) for i, n in enumerate(stops["stop_name"]))
    return stops.iloc[match_keys(target, names)]


def resolve_stop(name: str, stops: pd.DataFrame) -> list[str]:
    """Gli `stop_id` delle fermate che si chiamano `name`, nell'ordine della tabella. Errore se
    nessuna."""
    found = match_stops(name, stops)
    if found.empty:
        raise ResolveError(f"Nessuna fermata chiamata «{name}»")
    return [str(stop_id) for stop_id in found["stop_id"]]
