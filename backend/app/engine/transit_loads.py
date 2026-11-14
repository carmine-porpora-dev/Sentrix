from collections import defaultdict, deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from typing import Literal

from app.data.gtfs import service_day
from app.engine import unique
from app.engine.demand import Demand
from app.engine.transit import ResolvedItinerary, ResolvedLeg, TransitNetwork, disrupted_stops
from app.engine.transit_supply import (
    ExtraTrips,
    NearStop,
    SectionKey,
    SectionSupply,
    TransitSupply,
    build_supply,
    near_stops,
)
from app.geo import haversine_m
from app.models.base import Window
from app.models.config import TransitConfig
from app.models.event import Event

ZoneMode = Literal["itinerary", "walk", "bus", "unserved"]


@dataclass(frozen=True, slots=True)
class ZoneAssignment:
    """Come viaggiano le persone TPL di una zona."""

    zone_id: str
    persons: float  # nella fascia di picco
    pax_h: float
    mode: ZoneMode  # itinerario con tratte, a piedi, bus, non servite
    itinerary: int | None  # numero (da 1) tra gli itinerari della zona; None se bus o non servite
    skipped: tuple[str, ...] = ()  # perché gli itinerari prima di quello scelto non c'erano


@dataclass(frozen=True, slots=True)
class SectionLoad:
    section: SectionSupply
    pax_h: float
    load_ratio: float | None  # passeggeri / capacità; None se la capacità è 0
    by_zone: tuple[tuple[str, float], ...] = ()  # (zona, pax/h) dal più alto: chi riempie la tratta


@dataclass(frozen=True, slots=True)
class StopLoad:
    stop: NearStop
    pax_h: float  # in discesa (arrivo) o in salita (deflusso): itinerari e bus
    bus_pax_h: float  # la parte arrivata con la domanda bus
    load_ratio: float | None  # passeggeri / capacità offerta dalla fermata; None se è 0 o è chiusa
    closed: bool = False  # indisponibile: interruzione o fermata sospesa


@dataclass(frozen=True)
class TransitLoads:
    window: Window
    supply: TransitSupply
    zones: tuple[ZoneAssignment, ...]  # le zone con domanda TPL, nell'ordine della domanda
    sections: Mapping[SectionKey, SectionLoad]  # solo le tratte con passeggeri
    stops: tuple[StopLoad, ...]  # tutte le fermate vicine all'area, dalla più vicina
    bus_persons: float
    walk_persons: float  # modo «a piedi» + itinerari senza tratte
    unserved_persons: float
    closed_stops: frozenset[str]  # gli stop_id indisponibili in questa fascia
    assumptions: tuple[str, ...]


# --- percorsi degli itinerari sulle tratte --------------------------------------------------------


def leg_path(supply: TransitSupply, leg: ResolvedLeg, reverse: bool) -> list[SectionKey] | None:
    """Le tratte da percorrere per andare da una stazione all'altra di `leg` (nell'arrivo da
    `board` ad `alight`, nel deflusso al contrario), o `None` se la linea non le collega in quel
    senso. In una linea a rami, il primo percorso più corto."""
    start, end = (leg.alight, leg.board) if reverse else (leg.board, leg.alight)
    keys = sorted(k for k, s in supply.sections.items() if s.route_class == leg.route_class)
    outgoing: defaultdict[tuple[str, str], list[SectionKey]] = defaultdict(list)
    for key in keys:
        outgoing[(key[0], key[1])].append(key)
    queue = deque([key] for key in keys if supply.sections[key].from_stop_ids & start.stop_ids)
    seen = {path[0] for path in queue}
    while queue:
        path = queue.popleft()
        last = path[-1]
        if supply.sections[last].to_stop_ids & end.stop_ids:
            return path
        for following in outgoing[(last[0], last[2])]:
            if following not in seen:
                seen.add(following)
                queue.append([*path, following])
    return None


@dataclass(frozen=True, slots=True)
class _Plan:
    number: int  # numero (da 1) dell'itinerario scelto
    paths: tuple[tuple[SectionKey, ...], ...]  # un percorso per tratta, nell'ordine di viaggio
    access: frozenset[str] | None  # banchine dal lato dell'area; None se tutto a piedi


def _plan(
    number: int,
    itinerary: ResolvedItinerary,
    supply: TransitSupply,
    reverse: bool,
    closed: frozenset[str],
) -> _Plan | str:
    """Il piano di un itinerario se è disponibile nella fascia, altrimenti il motivo (in italiano).

    Disponibile: nessuna fermata di salita o discesa è indisponibile; ogni tratta ha un percorso e
    ogni tratta del percorso ha almeno una corsa."""
    legs = list(reversed(itinerary.legs)) if reverse else list(itinerary.legs)
    for leg in legs:
        for end in (leg.board, leg.alight):
            if end.stop_ids & closed:
                return f"itinerario {number}: fermata indisponibile ({end.name})"
    paths: list[tuple[SectionKey, ...]] = []
    for leg in legs:
        path = leg_path(supply, leg, reverse)
        if path is None or any(supply.sections[key].trips == 0 for key in path):
            return f"itinerario {number}: senza corse nella fascia ({leg.route_class})"
        paths.append(tuple(path))
    if not paths:
        return _Plan(number, (), None)
    # il lato dell'area: dove si scende nell'arrivo (ultima tratta), dove si sale nel deflusso
    # (la prima del viaggio, cioè la più vicina all'area)
    near_area = (
        supply.sections[paths[0][0]].from_stop_ids
        if reverse
        else (supply.sections[paths[-1][-1]].to_stop_ids)
    )
    return _Plan(number, tuple(paths), near_area)


# --- assegnazione ---------------------------------------------------------------------------------


def _ratio(pax_h: float, capacity_pax_h: float) -> float | None:
    return pax_h / capacity_pax_h if capacity_pax_h > 0 else None


def _bus_shares(
    near: tuple[NearStop, ...], bus_pax_h: float, closed: frozenset[str], config: TransitConfig
) -> dict[str, float] | None:
    """La domanda bus sulle fermate vicine con autobus, in proporzione alla capacità bus. La quota
    di una fermata chiusa va alle fermate aperte con autobus entro `redistribution_radius_m` a
    piedi (linea d'aria × `walk_detour_factor`), sempre in proporzione alla capacità; se non ce
    n'è nessuna, a tutte le aperte. `None` se nessuna fermata aperta ha autobus."""
    with_bus = [stop for stop in near if stop.bus_capacity_pax_h > 0]
    open_stops = [stop for stop in with_bus if stop.stop_id not in closed]
    if not open_stops:
        return None
    total = sum(stop.bus_capacity_pax_h for stop in with_bus)
    shares: dict[str, float] = {}

    def give(share: float, to: list[NearStop]) -> None:
        capacity = sum(stop.bus_capacity_pax_h for stop in to)
        for stop in to:
            shares[stop.stop_id] = shares.get(stop.stop_id, 0.0) + (
                share * stop.bus_capacity_pax_h / capacity
            )

    for stop in with_bus:
        share = bus_pax_h * stop.bus_capacity_pax_h / total
        if stop.stop_id not in closed:
            shares[stop.stop_id] = shares.get(stop.stop_id, 0.0) + share
            continue
        walking = [
            other
            for other in open_stops
            if haversine_m(stop.lat, stop.lon, (other.lat, other.lon)) * config.walk_detour_factor
            <= config.redistribution_radius_m
        ]
        give(share, walking or open_stops)
    return shares


def assign_transit(
    network: TransitNetwork,
    config: TransitConfig,
    event: Event,
    demand: Demand,
    slice_minutes: int,
    suspended: Collection[str] = (),
    extra: ExtraTrips | None = None,
) -> TransitLoads:
    """I carichi TPL della fascia di picco di `demand` (finestra e livello di affluenza inclusi).

    Le fermate indisponibili sono quelle delle interruzioni dell'Evento attive nella finestra più
    `suspended` (gli `stop_id` sospesi da una misura); `extra` sono le corse aggiunte dalle misure
    (`transit_measures`)."""
    feed = network.feed
    service = service_day(feed.service_dates, event.date)
    supply = build_supply(
        feed,
        network.classes,
        config,
        service,
        demand.band_start,
        demand.band_end,
        slice_minutes,
        extra,
    )
    near = near_stops(
        feed, network.classes, config, service, demand.band_start, demand.band_end,
        slice_minutes, event.area_center, extra,
    )  # fmt: skip
    closed = disrupted_stops(feed, event, demand.window) | frozenset(suspended)
    reverse = demand.window == "departure"
    to_pax_h = 60 / slice_minutes

    zones: list[ZoneAssignment] = []
    section_pax: defaultdict[SectionKey, float] = defaultdict(float)
    section_zones: defaultdict[SectionKey, defaultdict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    stop_pax: defaultdict[str, float] = defaultdict(float)
    bus_persons = walk_persons = 0.0
    for zone in demand.zones:
        if zone.transit_persons <= 0:
            continue
        persons, pax_h = zone.transit_persons, zone.transit_persons * to_pax_h
        skipped: list[str] = []
        plan: _Plan | None = None
        for number, itinerary in enumerate(network.itineraries.get(zone.zone_id, ()), start=1):
            found = _plan(number, itinerary, supply, reverse, closed)
            if isinstance(found, str):
                skipped.append(found)
            else:
                plan = found
                break
        if plan is None:
            zones.append(ZoneAssignment(zone.zone_id, persons, pax_h, "bus", None, tuple(skipped)))
            bus_persons += persons
        elif plan.access is None:
            mode = ZoneAssignment(zone.zone_id, persons, pax_h, "walk", plan.number, tuple(skipped))
            zones.append(mode)
            walk_persons += persons
        else:
            zones.append(
                ZoneAssignment(
                    zone.zone_id, persons, pax_h, "itinerary", plan.number, tuple(skipped)
                )
            )
            for path in plan.paths:
                for key in path:
                    section_pax[key] += pax_h
                    section_zones[key][zone.zone_id] += pax_h
            for stop_id in sorted(plan.access):
                stop_pax[stop_id] += pax_h / len(plan.access)

    # la domanda bus: sulle fermate vicine aperte con autobus
    bus_shares = _bus_shares(near, bus_persons * to_pax_h, closed, config) if bus_persons else {}
    unserved_persons = 0.0
    if bus_shares is None:
        unserved_persons, bus_persons, bus_shares = bus_persons, 0.0, {}
        zones = [replace(z, mode="unserved") if z.mode == "bus" else z for z in zones]
    for stop_id, share in bus_shares.items():
        stop_pax[stop_id] += share

    stops = tuple(
        StopLoad(
            stop,
            stop_pax[stop.stop_id],
            bus_shares.get(stop.stop_id, 0.0),
            None if stop.stop_id in closed else _ratio(stop_pax[stop.stop_id], stop.capacity_pax_h),
            stop.stop_id in closed,
        )
        for stop in near
    )
    sections = {
        key: SectionLoad(
            supply.sections[key],
            pax_h,
            _ratio(pax_h, supply.sections[key].capacity_pax_h),
            tuple(sorted(section_zones[key].items(), key=lambda item: (-item[1], item[0]))),
        )
        for key, pax_h in sorted(section_pax.items())
    }
    return TransitLoads(
        window=demand.window,
        supply=supply,
        zones=tuple(zones),
        sections=sections,
        stops=stops,
        bus_persons=bus_persons,
        walk_persons=demand.walk_persons + walk_persons,
        unserved_persons=unserved_persons,
        closed_stops=closed,
        assumptions=unique(
            *supply.assumptions,
            *_assumptions(config, slice_minutes, unserved_persons > 0, bool(closed)),
        ),
    )


def _assumptions(
    config: TransitConfig, slice_minutes: int, unserved: bool, closures: bool
) -> list[str]:
    items = [
        "domanda TPL = persone della fascia di picco riportate a passeggeri/ora "
        f"(× 60/{slice_minutes})",
        "itinerario per zona: il primo disponibile nella fascia (ogni tratta del percorso ha "
        "almeno una corsa); altrimenti la domanda va sul bus",
        f"fermate vicine = entro {config.stop_radius_m:g} m dal centro dell'area evento; domanda "
        "bus ripartita sulle fermate con corse di autobus in proporzione alla capacità offerta "
        f"(bus: {config.vehicle_capacity['bus']} pax per corsa, "
        f"{config.vehicle_capacity_sources['bus']})",
        "i passeggeri sono sommati a ogni tratta del percorso senza distinguere le corse; "
        "i pedoni (modo «a piedi» e itinerari senza tratte) sono solo contati",
    ]
    if closures:
        items.append(
            "fermata indisponibile (interruzione o sospensione): gli itinerari che la usano per "
            "salire o scendere non sono disponibili e le corse continuano a transitare; la quota "
            f"bus di una fermata chiusa passa alle fermate aperte con autobus entro "
            f"{config.redistribution_radius_m:g} m a piedi (linea d'aria × "
            f"{config.walk_detour_factor:g}), in proporzione alla capacità"
        )
    if unserved:
        items.append(
            "nessuna fermata vicina ha corse di autobus nella fascia: domanda bus non servita"
        )
    return items
