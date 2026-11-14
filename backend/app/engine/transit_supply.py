import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import groupby
from typing import get_args

import pandas as pd

from app.clock import seconds_of
from app.data.gtfs import GtfsFeed, RouteClasses, ServiceDay
from app.data.resolvers import normalize_name
from app.engine import STATIC_MODEL_ASSUMPTION
from app.geo import haversine_m
from app.models.config import RailKind, TransitConfig
from app.models.geo import GeoPoint
from app.models.provenance import Kind

# (route_id, stazione di partenza, stazione di arrivo): i nomi sono normalizzati.
SectionKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class SectionSupply:
    """L'offerta di una tratta nella fascia."""

    route_id: str
    route_class: RailKind
    from_name: str  # come nel feed (della prima fermata trovata), per mostrarlo
    to_name: str
    from_stop_ids: frozenset[str]  # le banchine (stop_id) nel senso di marcia della tratta
    to_stop_ids: frozenset[str]
    trips: int  # corse che partono dalla stazione iniziale nella fascia
    capacity_pax_h: float  # corse × capacità del veicolo × 60 / slice_minutes


@dataclass(frozen=True)
class TransitSupply:
    service: ServiceDay
    band_start: dt.time
    band_end: dt.time
    slice_minutes: int
    sections: Mapping[SectionKey, SectionSupply]  # tutte le tratte del giorno, anche senza corse
    trips_by_class: Mapping[RailKind, int]  # per linea: partenza dal primo capolinea, due direzioni
    assumptions: tuple[str, ...]

    @property
    def kind(self) -> Kind:
        """`real` se il feed copre la data dell'Evento, altrimenti `estimate` (orario tipo)."""
        return "real" if self.service.covered else "estimate"


@dataclass(frozen=True)
class ExtraTrips:
    """Corse aggiunte da una misura (`extend_hours`, `add_runs`), come righe di `trips` e di
    `stop_times` nelle stesse colonne di `GtfsFeed`; contano come corse del giorno di servizio."""

    trips: pd.DataFrame  # trip_id, route_id
    stop_times: pd.DataFrame  # trip_id, stop_id, seq, arr_s, dep_s


def _is_subsequence(small: tuple[str, ...], big: tuple[str, ...]) -> bool:
    remaining = iter(big)
    return all(item in remaining for item in small)


def _trip_runs(times: pd.DataFrame) -> dict[str, list[tuple[str, frozenset[str]]]]:
    """Per corsa, le stazioni nell'ordine, ciascuna con gli `stop_id` usati. Due fermate di fila
    con lo stesso nome (due banchine) sono una stazione sola."""
    runs: dict[str, list[tuple[str, frozenset[str]]]] = {}
    for trip_id, group in times.groupby("trip_id", sort=False):
        pairs = zip(map(str, group["key"]), map(str, group["stop_id"]), strict=True)
        runs[str(trip_id)] = [
            (key, frozenset(stop for _, stop in run))
            for key, run in groupby(pairs, key=lambda item: item[0])
        ]
    return runs


def _maximal_patterns(
    runs: Mapping[str, list[tuple[str, frozenset[str]]]], trip_route: Mapping[str, str]
) -> dict[str, list[tuple[str, ...]]]:
    """Per ogni linea, i percorsi (sequenze di stazioni) delle sue corse che non sono un
    sottoinsieme ordinato di un altro, dal più lungo (a parità, in ordine alfabetico)."""
    by_route: defaultdict[str, set[tuple[str, ...]]] = defaultdict(set)
    for trip_id, stations in runs.items():
        by_route[trip_route[trip_id]].add(tuple(key for key, _ in stations))
    result: dict[str, list[tuple[str, ...]]] = {}
    for route_id, found in by_route.items():
        maximal: list[tuple[str, ...]] = []
        for pattern in sorted(found, key=lambda p: (-len(p), p)):
            if not any(_is_subsequence(pattern, longer) for longer in maximal):
                maximal.append(pattern)
        result[route_id] = maximal
    return result


def _chain_stop_ids(
    runs: Mapping[str, list[tuple[str, frozenset[str]]]],
    trip_route: Mapping[str, str],
    patterns: Mapping[str, list[tuple[str, ...]]],
) -> dict[tuple[str, int], list[frozenset[str]]]:
    """Per ogni percorso massimale (linea, numero d'ordine), gli `stop_id` di ogni posizione: quelli
    usati dalle corse che fanno proprio quel percorso, cioè le banchine del suo senso di marcia."""
    ids: dict[tuple[str, int], list[set[str]]] = {}
    for trip_id, stations in runs.items():
        route_id = trip_route[trip_id]
        pattern = tuple(key for key, _ in stations)
        if pattern not in patterns[route_id]:
            continue  # una corsa che salta stazioni: le banchine le dà quella completa
        slots = ids.setdefault(
            (route_id, patterns[route_id].index(pattern)), [set() for _ in pattern]
        )
        for slot, (_, stops) in zip(slots, stations, strict=True):
            slot |= stops
    return {chain: [frozenset(slot) for slot in slots] for chain, slots in ids.items()}


def _covered(
    chains: list[tuple[str, ...]], route_id: str, from_key: str, to_key: str
) -> list[SectionKey]:
    """Le tratte della linea tra `from_key` e `to_key`, nel primo percorso massimale che li contiene
    in quest'ordine. Ogni coppia di fermate consecutive di una corsa ne ha uno, perché il percorso
    della corsa è un sottoinsieme ordinato di un percorso massimale; due banchine con lo stesso
    nome (`from_key == to_key`) non coprono nessuna tratta."""
    for chain in chains:
        if from_key in chain and to_key in chain:
            start, end = chain.index(from_key), chain.index(to_key)
            if start < end:
                return [(route_id, chain[n], chain[n + 1]) for n in range(start, end)]
    return []


def build_supply(
    feed: GtfsFeed,
    classes: RouteClasses,
    config: TransitConfig,
    service: ServiceDay,
    band_start: dt.time,
    band_end: dt.time,
    slice_minutes: int,
    extra: ExtraTrips | None = None,
) -> TransitSupply:
    """L'offerta di metro e funicolari nella fascia `[band_start, band_end)` del giorno `service`.

    `slice_minutes` è la lunghezza di una fascia intera (`time_slice_minutes`): serve a riportare
    le corse a pax/h, anche se la fascia è stata troncata a fine finestra. `extra` sono le corse
    aggiunte da una misura (quelle di linee non metro o funicolare non entrano).
    """
    start_s, end_s = seconds_of(band_start), seconds_of(band_end)
    route_class: dict[str, RailKind] = {
        route_id: kind for kind in get_args(RailKind) for route_id in sorted(classes.ids(kind))
    }

    trips = feed.trips[
        feed.trips["route_id"].isin(list(route_class))
        & feed.trips["service_id"].isin(list(service.services))
    ]
    trip_route = dict(zip(trips["trip_id"], trips["route_id"], strict=True))
    times = feed.stop_times[feed.stop_times["trip_id"].isin(list(trip_route))].copy()
    times["trip_id"] = times["trip_id"].astype(str)
    times["stop_id"] = times["stop_id"].astype(str)
    if extra is not None:
        added = extra.trips[extra.trips["route_id"].isin(list(route_class))]
        trip_route.update(zip(added["trip_id"], added["route_id"], strict=True))
        times = pd.concat(
            [times, extra.stop_times[extra.stop_times["trip_id"].isin(list(added["trip_id"]))]],
            ignore_index=True,
        )
    times = times.sort_values(["trip_id", "seq"], kind="stable")

    stop_name = feed.stops.set_index("stop_id")["stop_name"]
    key_of = stop_name.map(normalize_name)

    # coppie di fermate consecutive di una corsa, con la stazione (nome normalizzato) di ciascuna
    times["next_stop"] = times.groupby("trip_id", sort=False)["stop_id"].shift(-1)
    times["route_id"] = times["trip_id"].map(trip_route)
    times["key"] = times["stop_id"].map(key_of)
    runs = _trip_runs(times)
    patterns = _maximal_patterns(runs, trip_route)
    chain_ids = _chain_stop_ids(runs, trip_route, patterns)

    pairs = times[times["next_stop"].notna()].copy()
    pairs["to_key"] = pairs["next_stop"].map(key_of)
    pairs["in_band"] = (pairs["dep_s"] >= start_s) & (pairs["dep_s"] < end_s)

    # le corse nella fascia di ogni tratta: ogni coppia (x → y) di una corsa copre le tratte della
    # linea tra x e y
    in_band: defaultdict[SectionKey, int] = defaultdict(int)
    for (route_id, from_key, to_key), group in pairs.groupby(
        ["route_id", "key", "to_key"], sort=True
    ):
        count = int(group["in_band"].sum())
        for section_key in _covered(
            patterns[str(route_id)], str(route_id), str(from_key), str(to_key)
        ):
            in_band[section_key] += count

    sections: dict[SectionKey, SectionSupply] = {}
    for route_id, chains in sorted(patterns.items()):
        kind = route_class[route_id]
        for number, chain in enumerate(chains):
            ids = chain_ids[(route_id, number)]
            for n, (from_key, to_key) in enumerate(zip(chain, chain[1:], strict=False)):
                key = (route_id, from_key, to_key)
                if key in sections:
                    continue
                count = in_band[key]
                sections[key] = SectionSupply(
                    route_id=route_id,
                    route_class=kind,
                    from_name=str(stop_name[min(ids[n])]),
                    to_name=str(stop_name[min(ids[n + 1])]),
                    from_stop_ids=ids[n],
                    to_stop_ids=ids[n + 1],
                    trips=count,
                    capacity_pax_h=count * config.vehicle_capacity[kind] * 60 / slice_minutes,
                )
    sections = dict(sorted(sections.items()))

    # le corse di una linea: ora di partenza dal primo capolinea (00 2.2)
    firsts = times.groupby("trip_id", sort=False).head(1)
    starts = firsts[(firsts["dep_s"] >= start_s) & (firsts["dep_s"] < end_s)]
    counts = starts["trip_id"].map(trip_route).map(route_class).value_counts()
    trips_by_class: dict[RailKind, int] = {
        kind: int(counts.get(kind, 0)) for kind in get_args(RailKind)
    }
    return TransitSupply(
        service=service,
        band_start=band_start,
        band_end=band_end,
        slice_minutes=slice_minutes,
        sections=sections,
        trips_by_class=trips_by_class,
        assumptions=_assumptions(config, service, slice_minutes),
    )


def _assumptions(config: TransitConfig, service: ServiceDay, slice_minutes: int) -> tuple[str, ...]:
    capacities = "; ".join(
        f"{kind} {config.vehicle_capacity[kind]} pax per corsa "
        f"({config.vehicle_capacity_sources[kind]})"
        for kind in get_args(RailKind)
    )
    items = [
        STATIC_MODEL_ASSUMPTION,
        "GTFS statico: orario programmato, non tracking in tempo reale",
        service.assumption
        or f"orario del feed per il {service.used:%d/%m/%Y} (la data dell'evento è coperta)",
        f"capacità di una tratta = corse nella fascia × capacità del veicolo, su {slice_minutes} "
        f"minuti riportata a pax/h ({capacities})",
    ]
    return tuple(items)


# --- fermate vicine all'area evento ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NearStop:
    """Una fermata del feed entro `stop_radius_m` dall'area evento, con ciò che vi si offre."""

    stop_id: str
    name: str
    lat: float
    lon: float
    distance_m: float
    trips: int  # corse di ogni linea che vi fermano nella fascia
    capacity_pax_h: float  # Σ corse per classe × capacità del veicolo × 60 / slice_minutes
    bus_capacity_pax_h: float  # la parte delle sole linee bus


def near_stops(
    feed: GtfsFeed,
    classes: RouteClasses,
    config: TransitConfig,
    service: ServiceDay,
    band_start: dt.time,
    band_end: dt.time,
    slice_minutes: int,
    center: GeoPoint,
    extra: ExtraTrips | None = None,
) -> tuple[NearStop, ...]:
    """Le fermate entro `config.stop_radius_m` da `center` (03 3.2), dalla più vicina, con le
    corse che vi fermano nella fascia (partenza dalla fermata in `[band_start, band_end)`) e la
    capacità che ne deriva. Contano le linee di tutte le classi; le linee che il modello non
    considera (la metro L2) no."""
    distance = haversine_m(feed.stops["lat"], feed.stops["lon"], (center.lat, center.lon))
    stops = feed.stops.assign(distance_m=distance)
    stops = stops[stops["distance_m"] <= config.stop_radius_m].sort_values(
        ["distance_m", "stop_id"]
    )

    start_s, end_s = seconds_of(band_start), seconds_of(band_end)
    trips = feed.trips[feed.trips["service_id"].isin(list(service.services))]
    calls = feed.stop_times[feed.stop_times["stop_id"].isin(list(stops["stop_id"]))].copy()
    calls["trip_id"] = calls["trip_id"].astype(str)
    calls["stop_id"] = calls["stop_id"].astype(str)
    trip_routes = trips[["trip_id", "route_id"]]
    if extra is not None:
        calls = pd.concat(
            [calls, extra.stop_times[extra.stop_times["stop_id"].isin(list(stops["stop_id"]))]],
            ignore_index=True,
        )
        trip_routes = pd.concat([trip_routes, extra.trips[["trip_id", "route_id"]]])
    calls = calls[(calls["dep_s"] >= start_s) & (calls["dep_s"] < end_s)]
    calls = calls.merge(trip_routes, on="trip_id")
    calls["kind"] = calls["route_id"].map(classes.of)
    counts = calls.dropna(subset=["kind"]).groupby(["stop_id", "kind"]).size()

    result = []
    for row in stops.to_dict("records"):
        stop_id = str(row["stop_id"])
        by_kind = {kind: int(counts.get((stop_id, kind), 0)) for kind in config.vehicle_capacity}
        capacity = {
            kind: n * config.vehicle_capacity[kind] * 60 / slice_minutes
            for kind, n in by_kind.items()
        }
        result.append(
            NearStop(
                stop_id=stop_id,
                name=str(row["stop_name"]),
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                distance_m=float(row["distance_m"]),
                trips=sum(by_kind.values()),
                capacity_pax_h=sum(capacity.values()),
                bus_capacity_pax_h=capacity["bus"],
            )
        )
    return tuple(result)
