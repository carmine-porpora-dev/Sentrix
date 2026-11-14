from collections.abc import Collection, Sequence
from typing import Any

import networkx as nx
import pandas as pd
from pydantic import JsonValue

from app.data.gtfs import GtfsFeed, RouteClasses
from app.data.resolvers import (
    ResolveError,
    edge_coordinates,
    edge_key,
    nearest_node,
    osm_name_parts,
    resolve_closure,
    resolve_stop,
)
from app.engine.demand import effective_demand_inputs
from app.geo import COORD_DECIMALS, geojson_point
from app.models.api import Feature, FeatureCollection
from app.models.api_config import NetworkConfig
from app.models.config import EngineConfig
from app.models.event import Event
from app.models.geo import GeoPoint

Bbox = tuple[float, float, float, float]  # ovest, sud, est, nord


def _classes(highway: Any) -> list[str]:
    """Le classi OSM di un arco (una o più), senza `_link` (`primary_link` → `primary`)."""
    values = highway if isinstance(highway, list) else [highway]
    return [str(value).removesuffix("_link") for value in values if value]


def _is_major(highway: Any, major: Collection[str]) -> bool:
    return any(name in major for name in _classes(highway))


def _bounds(graph: nx.MultiDiGraph, u: int, v: int, data: dict[str, Any]) -> Bbox:
    geometry = data.get("geometry")
    if geometry is not None:
        west, south, east, north = geometry.bounds
        return float(west), float(south), float(east), float(north)
    a, b = graph.nodes[u], graph.nodes[v]
    xs, ys = sorted((float(a["x"]), float(b["x"]))), sorted((float(a["y"]), float(b["y"])))
    return xs[0], ys[0], xs[1], ys[1]


def _overlaps(box: Bbox, other: Bbox) -> bool:
    return box[0] <= other[2] and box[2] >= other[0] and box[1] <= other[3] and box[3] >= other[1]


def _line(coordinates: list[list[float]]) -> dict[str, JsonValue]:
    return {"type": "LineString", "coordinates": coordinates}  # type: ignore[dict-item]


# --- strade ------------------------------------------------------------------------------------


def _opposite(
    graph: nx.MultiDiGraph, edge: tuple[int, int, int], taken: set[tuple[int, int, int]]
) -> tuple[int, int, int] | None:
    """L'altro senso di marcia di `edge`: stessi nomi (anche in altro ordine), stessa classe e
    lunghezza. Se c'è e non è già stato abbinato lo segna in `taken`. Due archi paralleli tra gli
    stessi nodi con nomi diversi sono due strade, non i due sensi di una."""
    u, v, k = edge
    if u == v or not graph.has_edge(v, u):
        return None
    data = graph.edges[u, v, k]
    for other in sorted(graph[v][u]):
        candidate = (v, u, int(other))
        back = graph.edges[candidate]
        if (
            candidate not in taken
            and set(osm_name_parts(back.get("name"))) == set(osm_name_parts(data.get("name")))
            and _classes(back.get("highway")) == _classes(data.get("highway"))
            and round(float(back["length_m"])) == round(float(data["length_m"]))
        ):
            taken.add(candidate)
            return candidate
    return None


def network_edges(graph: nx.MultiDiGraph, bbox: Bbox, config: NetworkConfig) -> FeatureCollection:
    """Gli archi che toccano `bbox`: sempre quelli delle classi `major_classes`, tutti se l'area è
    piccola (`detail_max_span_deg`), al massimo `max_features` (prima le strade maggiori).

    Una feature per **strada**, non per senso di marcia: `edge_key` è un senso e `reverse_key`, se
    c'è, l'altro (chiudere una strada chiude entrambi). Chi la sceglie con un clic ha già le due
    chiavi."""
    west, south, east, north = bbox
    detail = max(east - west, north - south) <= config.detail_max_span_deg
    major = set(config.major_classes)
    picked: list[tuple[bool, tuple[int, int, int]]] = []
    for u, v, k, data in graph.edges(keys=True, data=True):
        is_major = _is_major(data.get("highway"), major)
        if (detail or is_major) and _overlaps(bbox, _bounds(graph, u, v, data)):
            picked.append((not is_major, (u, v, k)))
    features: list[Feature] = []
    paired: set[tuple[int, int, int]] = set()
    for _, (u, v, k) in sorted(picked):
        if (u, v, k) in paired:
            continue
        paired.add((u, v, k))
        data = graph.edges[u, v, k]
        back = _opposite(graph, (u, v, k), paired)
        key = edge_key(u, v, k)
        features.append(
            Feature(
                id=key,
                geometry=_line(edge_coordinates(graph, (u, v, k), COORD_DECIMALS)),
                properties={
                    "edge_key": key,
                    "reverse_key": None if back is None else edge_key(*back),
                    "name": "; ".join(osm_name_parts(data.get("name"))),
                    "highway": ", ".join(_classes(data.get("highway"))),
                    "length_m": round(float(data["length_m"])),
                },
            )
        )
        if len(features) >= config.max_features:
            break
    return FeatureCollection(features=features)


# --- trasporto pubblico ------------------------------------------------------------------------


def _route_names(routes: pd.DataFrame, column: str, fallback: dict[str, str]) -> dict[str, str]:
    """route_id → il valore di `column` (facoltativa nel GTFS), o `fallback` se manca o è vuota."""
    ids = [str(route_id) for route_id in routes["route_id"]]
    if column not in routes:
        return {route_id: fallback.get(route_id, route_id) for route_id in ids}
    return {
        route_id: str(name).strip() if pd.notna(name) and str(name).strip() else fallback[route_id]
        for route_id, name in zip(ids, routes[column], strict=True)
    }


def _short_names(routes: pd.DataFrame) -> dict[str, str]:
    ids = {str(route_id): str(route_id) for route_id in routes["route_id"]}
    return _route_names(routes, "route_short_name", ids)


def _routes_served(feed: GtfsFeed, stop_ids: Sequence[str]) -> dict[str, list[str]]:
    """Per ogni fermata, i nomi (brevi) delle linee che vi passano."""
    at = feed.stop_times[feed.stop_times["stop_id"].isin(list(stop_ids))][["trip_id", "stop_id"]]
    merged = at.merge(feed.trips[["trip_id", "route_id"]], on="trip_id")
    names = _short_names(feed.routes)
    served: dict[str, set[str]] = {}
    for stop_id, route_id in zip(merged["stop_id"], merged["route_id"], strict=True):
        served.setdefault(str(stop_id), set()).add(names.get(str(route_id), str(route_id)))
    return {stop: sorted(found) for stop, found in served.items()}


def transit_stops(feed: GtfsFeed, bbox: Bbox, config: NetworkConfig) -> FeatureCollection:
    """Le fermate del feed dentro `bbox` (la posizione è un dato reale), con le linee servite."""
    west, south, east, north = bbox
    stops = feed.stops
    inside = stops[
        (stops["lon"] >= west)
        & (stops["lon"] <= east)
        & (stops["lat"] >= south)
        & (stops["lat"] <= north)
    ].head(config.max_features)
    served = _routes_served(feed, [str(s) for s in inside["stop_id"]]) if len(inside) else {}
    features = [
        Feature(
            id=str(row.stop_id),
            geometry=geojson_point(float(row.lat), float(row.lon)),  # type: ignore[arg-type]
            properties={
                "stop_id": str(row.stop_id),
                "name": str(row.stop_name).strip(),
                "routes": list(served.get(str(row.stop_id), [])),
                "kind": "real",
            },
        )
        for row in inside.itertuples()
    ]
    return FeatureCollection(features=features)


def transit_lines(
    feed: GtfsFeed, classes: RouteClasses, route_classes: Collection[str]
) -> FeatureCollection:
    """Le linee di metro e funicolari: per ognuna la corsa con più fermate, unite in ordine."""
    wanted = {
        route_id: kind
        for kind in route_classes
        for route_id in sorted(classes.by_class.get(kind, frozenset()))  # type: ignore[call-overload]
    }
    trips = feed.trips[feed.trips["route_id"].isin(list(wanted))][["trip_id", "route_id"]]
    times = feed.stop_times[feed.stop_times["trip_id"].isin(list(trips["trip_id"]))]
    sizes = times.groupby("trip_id", observed=True).size()
    coords = feed.stops.set_index("stop_id")[["lon", "lat"]]
    short = _short_names(feed.routes)
    labels = _route_names(feed.routes, "route_long_name", short)
    features: list[Feature] = []
    for route_id, group in trips.groupby("route_id", sort=True):
        longest = sizes.reindex(group["trip_id"]).idxmax()
        stops = times[times["trip_id"] == longest].sort_values("seq")["stop_id"]
        path = [
            [
                round(float(coords.at[s, "lon"]), COORD_DECIMALS),  # type: ignore[arg-type]
                round(float(coords.at[s, "lat"]), COORD_DECIMALS),  # type: ignore[arg-type]
            ]
            for s in stops
            if s in coords.index
        ]
        if len(path) < 2:
            continue
        features.append(
            Feature(
                id=str(route_id),
                geometry=_line(path),
                properties={
                    "route_id": str(route_id),
                    "route_class": wanted[str(route_id)],
                    "label": labels[str(route_id)],
                    "kind": "line",
                },
            )
        )
    return FeatureCollection(features=features)


# --- anteprima di un Evento ---------------------------------------------------------------------


def _snapped(point: GeoPoint, graph: nx.MultiDiGraph, **properties: JsonValue) -> Feature:
    node, distance = nearest_node(point, graph)
    return Feature(
        geometry=geojson_point(point.lat, point.lon),
        properties={**properties, "node": node, "distance_m": round(distance)},
    )


def event_preview(
    event: Event, graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig
) -> FeatureCollection:
    """Ciò che il risolutore trova per l'Evento: le strade chiuse (una linea per arco), le fermate
    interrotte, il centro dell'area e i punti di arrivo in auto, ognuno col nodo a cui si aggancia.
    Una chiusura o una fermata che non si risolve non compare (il run la segnalerebbe)."""
    features = [
        _snapped(
            event.area_center,
            graph,
            kind="area_center",
            label=event.area_center.label or event.name,
        )
    ]
    for closure in event.closures:
        try:
            keys = resolve_closure(closure, graph)
        except ResolveError:
            continue
        for key in keys:
            u, v, k = (int(part) for part in key.split("-"))
            data = graph.edges[u, v, k]
            features.append(
                Feature(
                    id=key,
                    geometry=_line(edge_coordinates(graph, (u, v, k), COORD_DECIMALS)),
                    properties={
                        "kind": "closure",
                        "edge_key": key,
                        "label": closure.label,
                        "name": "; ".join(osm_name_parts(data.get("name"))),
                        "length_m": round(float(data["length_m"])),
                    },
                )
            )
    for disruption in event.transit_disruptions:
        try:
            ids = disruption.stop_ids or resolve_stop(disruption.stop_name, stops)
        except ResolveError:
            continue
        for stop_id in ids:
            found = stops[stops["stop_id"] == stop_id]
            if found.empty:
                continue
            row = found.iloc[0]
            features.append(
                Feature(
                    id=stop_id,
                    geometry=geojson_point(float(row["lat"]), float(row["lon"])),
                    properties={
                        "kind": "stop",
                        "stop_id": stop_id,
                        "label": disruption.label,
                        "name": str(row["stop_name"]).strip(),
                    },
                )
            )
    for destination in effective_demand_inputs(event, config).car_destinations:
        label = f"Arrivo auto: {destination.point.label or 'senza etichetta'}"
        features.append(_snapped(destination.point, graph, kind="car_destination", label=label))
    return FeatureCollection(features=features)
