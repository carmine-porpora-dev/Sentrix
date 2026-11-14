from collections.abc import Collection, Mapping
from dataclasses import dataclass

import pandas as pd

from app.data.gtfs import GtfsFeed, RouteClasses, classify_routes, stops_served_by_routes
from app.data.resolvers import ResolveError, resolve_stop
from app.models.base import Window
from app.models.config import Itinerary, RailKind, TransitConfig
from app.models.event import Event


class TransitConfigError(ValueError):
    """Gli itinerari di engine.yaml non si accordano con il feed; il messaggio li elenca tutti."""


@dataclass(frozen=True, slots=True)
class Station:
    """Una stazione per una classe di linea: i suoi `stop_id` (uno per senso)."""

    name: str  # come scritto in engine.yaml
    stop_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ResolvedLeg:
    route_class: RailKind
    board: Station  # dove si sale nell'arrivo (e si scende nel deflusso)
    alight: Station  # dove si scende nell'arrivo (e si sale nel deflusso)


@dataclass(frozen=True, slots=True)
class ResolvedItinerary:
    legs: tuple[ResolvedLeg, ...]  # vuoto = solo a piedi
    egress_walk: bool


def _connects(
    feed: GtfsFeed, route_ids: Collection[str], first: Collection[str], second: Collection[str]
) -> bool:
    """Se almeno una corsa delle linee passa da una fermata di `first` e poi da una di `second`."""
    trip_ids = feed.trips.loc[feed.trips["route_id"].isin(list(route_ids)), "trip_id"]
    times = feed.stop_times[feed.stop_times["trip_id"].isin(trip_ids)]
    earliest = (
        times[times["stop_id"].isin(list(first))].groupby("trip_id", observed=True)["seq"].min()
    )
    latest = (
        times[times["stop_id"].isin(list(second))].groupby("trip_id", observed=True)["seq"].max()
    )
    both = pd.concat([earliest, latest], axis=1, keys=["first", "second"]).dropna()
    return bool((both["first"] < both["second"]).any())


def resolve_itineraries(
    feed: GtfsFeed, classes: RouteClasses, config: TransitConfig
) -> dict[str, tuple[ResolvedItinerary, ...]]:
    """Gli itinerari di `config` con le fermate risolte sul feed, per zona e in ordine.

    `TransitConfigError`, con **tutti** i problemi, se: una fermata non esiste nel feed; esiste ma
    non è servita dalla classe della tratta; nessuna corsa va dall'una all'altra in una delle due
    direzioni (l'arrivo le percorre come scritte, il deflusso al contrario).
    """
    errors: list[str] = []
    served: dict[RailKind, set[str]] = {}
    # per (classe, nome): la stazione, o il motivo per cui non si risolve (da riferire a ogni punto)
    stations: dict[tuple[RailKind, str], Station | str] = {}

    def lookup(kind: RailKind, name: str) -> Station | str:
        try:
            candidates = resolve_stop(name, feed.stops)
        except ResolveError:
            return f"nessuna fermata chiamata «{name}» nel feed"
        if kind not in served:
            served[kind] = stops_served_by_routes(classes.ids(kind), feed.stop_times, feed.trips)
        on_line = frozenset(stop_id for stop_id in candidates if stop_id in served[kind])
        if not on_line:
            return f"«{name}» è nel feed ({len(candidates)} fermate) ma nessuna è servita da {kind}"
        return Station(name, on_line)

    def station(kind: RailKind, name: str, where: str) -> Station | None:
        key = (kind, name.strip().casefold())
        if key not in stations:
            stations[key] = lookup(kind, name)
        found = stations[key]
        if isinstance(found, str):
            errors.append(f"{where}: {found}")
            return None
        return found

    def resolve(zone: str, number: int, itinerary: Itinerary) -> ResolvedItinerary | None:
        legs: list[ResolvedLeg] = []
        for position, leg in enumerate(itinerary.legs, start=1):
            where = f"{zone}, itinerario {number}, tratta {position} ({leg.route_class})"
            board = station(leg.route_class, leg.from_stop_name, where)
            alight = station(leg.route_class, leg.to_stop_name, where)
            if board is None or alight is None:
                continue
            ids = classes.ids(leg.route_class)
            for first, second, direction in (
                (board, alight, f"da «{board.name}» a «{alight.name}» (arrivo)"),
                (alight, board, f"da «{alight.name}» a «{board.name}» (deflusso)"),
            ):
                if not _connects(feed, ids, first.stop_ids, second.stop_ids):
                    errors.append(f"{where}: nessuna corsa va {direction}")
            legs.append(ResolvedLeg(leg.route_class, board, alight))
        return ResolvedItinerary(tuple(legs), itinerary.egress_walk)

    resolved: dict[str, tuple[ResolvedItinerary, ...]] = {}
    for zone, itineraries in config.itineraries.items():
        items = [resolve(zone, n, it) for n, it in enumerate(itineraries, start=1)]
        resolved[zone] = tuple(item for item in items if item is not None)
    if errors:
        raise TransitConfigError(
            "Itinerari di engine.yaml (transit.itineraries) non risolti sul feed GTFS:\n  - "
            + "\n  - ".join(errors)
        )
    return resolved


@dataclass(frozen=True)
class TransitNetwork:
    """Ciò che il motore TPL costruisce una volta sola dal feed e da engine.yaml: la
    classificazione delle linee e gli itinerari risolti."""

    feed: GtfsFeed
    classes: RouteClasses
    itineraries: Mapping[str, tuple[ResolvedItinerary, ...]]


def load_transit_network(feed: GtfsFeed, config: TransitConfig) -> TransitNetwork:
    """Classifica le linee e risolve gli itinerari: è il «caricamento» di 03 2, quello che segnala
    tutti gli errori (`GtfsError` per le linee, `TransitConfigError` per gli itinerari)."""
    classes = classify_routes(feed, config.route_classification)
    return TransitNetwork(feed, classes, resolve_itineraries(feed, classes, config))


class DisruptionError(ValueError):
    """Un'interruzione dell'Evento che non si riferisce a fermate del feed."""


def disrupted_stops(feed: GtfsFeed, event: Event, window: Window) -> frozenset[str]:
    """Gli `stop_id` resi indisponibili dalle interruzioni dell'Evento attive in `window` (03 3.3).

    Una interruzione vale per la sua finestra o per `both`. Usa gli `stop_ids` già risolti; se non
    ci sono (un Evento creato a mano) li cerca per nome, e quel nome può avere più fermate: le
    chiude tutte. `DisruptionError` se un `stop_id` non è nel feed o il nome non corrisponde a
    nessuna fermata (un'interruzione ignorata in silenzio non cambierebbe nessun numero)."""
    known = set(feed.stops["stop_id"])
    closed: set[str] = set()
    for disruption in event.transit_disruptions:
        if disruption.window not in (window, "both"):
            continue
        try:
            ids = disruption.stop_ids or resolve_stop(disruption.stop_name, feed.stops)
        except ResolveError as error:
            raise DisruptionError(f"Interruzione «{disruption.label}»: {error}") from error
        unknown = sorted(set(ids) - known)
        if unknown:
            raise DisruptionError(
                f"Interruzione «{disruption.label}»: fermate che il feed non ha: "
                f"{', '.join(unknown)}"
            )
        closed.update(ids)
    return frozenset(closed)
