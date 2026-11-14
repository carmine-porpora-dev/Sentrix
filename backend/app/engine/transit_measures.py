import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args

import pandas as pd

from app.clock import SECONDS_PER_HOUR, format_hhmm, seconds_of
from app.data.gtfs import GtfsFeed, ServiceDay
from app.data.resolvers import parse_edge_key
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.measures import MeasureError, check_requests
from app.engine.transit import TransitNetwork
from app.engine.transit_supply import ExtraTrips
from app.models.base import Window
from app.models.config import RailKind, TransitConfig
from app.models.operations import OperationRequest

TPL_TYPES = frozenset({"extend_hours", "add_runs", "stop_suspension", "bus_detour"})


@dataclass(frozen=True, slots=True)
class BusDetour:
    action_id: str
    route_id: str
    avoid_edge_keys: tuple[str, ...]


@dataclass(frozen=True)
class TransitMeasures:
    """Gli effetti delle misure TPL accettate di una finestra."""

    extra: ExtraTrips | None  # le corse aggiunte
    suspended: frozenset[str]  # le fermate sospese
    detours: tuple[BusDetour, ...]  # le deviazioni segnalate
    applied: tuple[str, ...]  # action_id applicati, nell'ordine (iterazione, action_id)
    assumptions: tuple[str, ...]


# (ora di partenza, arrivi e partenze alle fermate, relativi alla partenza), in secondi
_Trip = tuple[float, tuple[float, ...], tuple[float, ...]]


@dataclass(frozen=True)
class _Pattern:
    """Le corse di una linea con le stesse fermate (un senso di marcia) nel giorno di servizio."""

    route_id: str
    stops: tuple[str, ...]
    trips: tuple[_Trip, ...]  # in ordine di partenza

    @property
    def starts(self) -> list[float]:
        return [trip[0] for trip in self.trips]


def _patterns(feed: GtfsFeed, route_ids: Sequence[str], service: ServiceDay) -> list[_Pattern]:
    trips = feed.trips[
        feed.trips["route_id"].isin(list(route_ids))
        & feed.trips["service_id"].isin(list(service.services))
    ]
    route_of = dict(zip(trips["trip_id"], trips["route_id"], strict=True))
    times = feed.stop_times[feed.stop_times["trip_id"].isin(list(route_of))].copy()
    times["trip_id"] = times["trip_id"].astype(str)
    times["stop_id"] = times["stop_id"].astype(str)
    times = times.sort_values(["trip_id", "seq"], kind="stable")
    groups: defaultdict[tuple[str, tuple[str, ...]], list[_Trip]] = defaultdict(list)
    for trip_id, group in times.groupby("trip_id", sort=True):
        arrivals, departures = list(group["arr_s"]), list(group["dep_s"])
        start = float(departures[0])
        groups[(route_of[str(trip_id)], tuple(group["stop_id"]))].append(
            (
                start,
                tuple(float(a) - start for a in arrivals),
                tuple(float(d) - start for d in departures),
            )
        )
    return [
        _Pattern(route_id, stops, tuple(sorted(found, key=lambda trip: trip[0])))
        for (route_id, stops), found in sorted(groups.items())
    ]


def _routes_of(network: TransitNetwork, request: OperationRequest) -> list[str]:
    """Le linee del bersaglio: una classe di metro o funicolari, oppure un `route_id` che il
    modello considera."""
    target = request.target.strip()
    where = f"{request.action_id} ({request.type})"
    for kind in get_args(RailKind):
        if target == kind:
            return sorted(network.classes.ids(kind))
    if target == "bus":
        raise MeasureError(f"{where}: la classe bus ha troppe linee, indica un route_id")
    if network.classes.of(target) is None:
        raise MeasureError(
            f"{where}: il bersaglio '{target}' non è una classe (metro_line_1, metro_line_6, "
            "funicular) né un route_id che il modello considera"
        )
    return [target]


def _trip_rows(pattern: _Pattern, template: int, start: float, trip_id: str) -> pd.DataFrame:
    _, arrivals, departures = pattern.trips[template]
    return pd.DataFrame(
        {
            "trip_id": trip_id,
            "stop_id": list(pattern.stops),
            "seq": range(1, len(pattern.stops) + 1),
            "arr_s": [start + a for a in arrivals],
            "dep_s": [start + d for d in departures],
        }
    )


def _payload_int(request: OperationRequest, key: str, default: int) -> int:
    value = request.payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MeasureError(
            f"{request.action_id} ({request.type}): payload['{key}'] deve essere un intero ≥ 1"
        )
    return value


def _extend(
    pattern_set: list[_Pattern], until_s: int, request: OperationRequest
) -> tuple[list[tuple[_Pattern, int, float]], list[str]]:
    """Per ogni percorso, le ore di partenza delle corse da aggiungere dopo l'ultima programmata."""
    out: list[tuple[_Pattern, int, float]] = []
    notes: list[str] = []
    for pattern in pattern_set:
        starts = pattern.starts
        last = starts[-1]
        recent = [t for t in starts if t >= last - SECONDS_PER_HOUR]
        if len(recent) >= 2:
            interval = (last - recent[0]) / (len(recent) - 1)
        elif len(starts) >= 2:
            interval = (last - starts[0]) / (len(starts) - 1)
        else:
            notes.append(f"linea {pattern.route_id}: una sola corsa, intervallo non determinabile")
            continue
        if interval <= 0:
            notes.append(f"linea {pattern.route_id}: corse alla stessa ora, intervallo nullo")
            continue
        k = 1
        while last + k * interval <= until_s:
            out.append((pattern, len(starts) - 1, last + k * interval))
            k += 1
    return out, notes


def apply_transit_measures(
    network: TransitNetwork,
    config: TransitConfig,
    service: ServiceDay,
    window: Window,
    band_start: dt.time,
    band_end: dt.time,
    requests: Sequence[OperationRequest],
) -> TransitMeasures:
    """Le misure TPL accettate di `window` (03 3.4), nell'ordine (iterazione, action_id).

    `MeasureError` per una richiesta non accettata, di tipo ignoto o con un bersaglio o un
    `payload` non validi. Le corse aggiunte dipendono dal giorno di servizio e dalla fascia."""
    ordered = sorted(requests, key=lambda r: (r.iteration, r.action_id))
    check_requests(ordered)
    feed = network.feed
    known_stops = set(feed.stops["stop_id"])
    known_routes = set(feed.routes["route_id"])
    start_s, end_s = seconds_of(band_start), seconds_of(band_end)

    added_trips: list[pd.DataFrame] = []
    added_ids: list[dict[str, str]] = []
    suspended: set[str] = set()
    detours: list[BusDetour] = []
    applied: list[str] = []
    assumptions = [STATIC_MODEL_ASSUMPTION]

    for request in ordered:
        if request.type not in TPL_TYPES or request.window != window:
            continue
        where = f"{request.action_id} ({request.type})"
        if request.type == "stop_suspension":
            if request.target not in known_stops:
                raise MeasureError(f"{where}: la fermata '{request.target}' non è nel feed")
            suspended.add(request.target)
            assumptions.append(
                f"stop_suspension {request.target}: fermata indisponibile come in un'interruzione "
                "(gli itinerari che la usano saltano, le corse continuano a transitare)"
            )
        elif request.type == "bus_detour":
            if request.target not in known_routes:
                raise MeasureError(f"{where}: la linea '{request.target}' non è nel feed")
            keys = request.payload.get("avoid_edge_keys")
            if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
                raise MeasureError(f"{where}: serve payload['avoid_edge_keys'], una lista di archi")
            for key in keys:
                try:
                    parse_edge_key(str(key))
                except ValueError as error:
                    raise MeasureError(f"{where}: {error}") from None
            detours.append(BusDetour(request.action_id, request.target, tuple(map(str, keys))))
            assumptions.append(
                f"bus_detour {request.target}: segnalazione nel piano, nessun effetto numerico "
                "nell'MVP"
            )
        else:
            routes = _routes_of(network, request)
            patterns = _patterns(feed, routes, service)
            if request.type == "extend_hours":
                until = request.payload.get("until")
                try:
                    until_time = (
                        config.extend_hours_default_end
                        if until is None
                        else dt.time.fromisoformat(str(until))
                    )
                except ValueError:
                    raise MeasureError(f"{where}: payload['until'] non è un orario HH:MM") from None
                plans, notes = _extend(patterns, seconds_of(until_time), request)
                starts = [t for _, _, t in plans]
                what = (
                    f"{len(plans)} corse aggiunte tra le {format_hhmm(min(starts))} e le "
                    f"{format_hhmm(max(starts))}"
                    if plans
                    else "nessuna corsa aggiunta"
                )
                assumptions.append(
                    f"extend_hours {request.target} fino alle {until_time:%H:%M}: {what}, con "
                    "l'intervallo medio dell'ultima ora programmata di ogni percorso"
                    + (f" ({'; '.join(notes)})" if notes else "")
                )
            else:
                n = _payload_int(request, "n", config.add_runs_default)
                length = end_s - start_s
                plans = []
                for pattern in patterns:
                    template = min(
                        range(len(pattern.trips)),
                        key=lambda i: (abs(pattern.trips[i][0] - start_s), pattern.trips[i][0]),
                    )
                    plans += [
                        (pattern, template, start_s + (k + 0.5) * length / n) for k in range(n)
                    ]
                assumptions.append(
                    f"add_runs {request.target}: {n} corse per percorso (per senso), distribuite "
                    f"in modo uniforme nella fascia, {len(plans)} in tutto"
                )
            for number, (pattern, template, start) in enumerate(plans):
                trip_id = f"{request.action_id}:{pattern.route_id}:{number}"
                added_trips.append(_trip_rows(pattern, template, start, trip_id))
                added_ids.append({"trip_id": trip_id, "route_id": pattern.route_id})
        applied.append(request.action_id)

    extra = (
        ExtraTrips(pd.DataFrame(added_ids), pd.concat(added_trips, ignore_index=True))
        if added_trips
        else None
    )
    return TransitMeasures(
        extra=extra,
        suspended=frozenset(suspended),
        detours=tuple(detours),
        applied=tuple(applied),
        assumptions=tuple(assumptions),
    )
