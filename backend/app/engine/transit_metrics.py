from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import get_args

import pandas as pd

from app.engine import STATIC_MODEL_ASSUMPTION, unique
from app.engine.demand import Demand
from app.engine.transit import ResolvedItinerary, TransitNetwork
from app.engine.transit_loads import SectionLoad, StopLoad, TransitLoads, ZoneAssignment
from app.engine.transit_measures import TransitMeasures
from app.engine.transit_supply import SectionKey
from app.geo import COORD_DECIMALS, circle_polygon, geojson_point
from app.models.api import Feature, FeatureCollection
from app.models.base import Window
from app.models.config import RailKind
from app.models.event import Event
from app.models.provenance import Kind, Measured, make_measured, measured_id

SOURCE = "engine.transit v1"
OVERLOAD = 1.0  # carico = passeggeri / capacità: oltre 1 la domanda supera l'offerta
RAIL_KINDS: tuple[RailKind, ...] = get_args(RailKind)


@dataclass(frozen=True, slots=True)
class SectionRow:
    """Una tratta con passeggeri, per chi stampa o esporta i carichi."""

    route_id: str
    route_class: RailKind
    from_name: str
    to_name: str
    trips: int  # corse nella fascia
    capacity_pax_h: float
    pax_h: float
    load_ratio: float | None
    by_zone: tuple[tuple[str, float], ...] = ()  # (zona, pax/h): chi riempie la tratta


@dataclass(frozen=True)
class TransitMetrics:
    window: Window
    measures: tuple[Measured, ...]
    layers: Mapping[str, FeatureCollection]  # stops, sections, event_area
    sections: tuple[SectionRow, ...]  # le tratte con passeggeri: per classe, dal carico più alto


def _overloaded(ratio: float | None) -> bool:
    return ratio is not None and ratio > OVERLOAD


FIRST_ITINERARY_METHOD = (
    "ogni zona viaggia tutta sul suo primo itinerario disponibile, senza ripartirsi tra "
    "itinerari né essere limitata dalla capacità"
)


def _fill_text(top: SectionRow, loads: TransitLoads, network: TransitNetwork) -> str:
    """Chi riempie la tratta più carica, per zona: passeggeri/h, quota e itinerario scelto. È
    un input del massimo: il numero alto dipende da quali zone ci passano."""
    chosen = {zone.zone_id: zone.itinerary for zone in loads.zones}
    parts = []
    for zone_id, pax_h in top.by_zone:
        number, total = chosen.get(zone_id), len(network.itineraries.get(zone_id, ()))
        parts.append(
            f"{zone_id} {pax_h:.0f} pax/h ({pax_h / top.pax_h * 100:.0f} %, "
            f"itinerario {number} di {total})"
        )
    return (
        f"passeggeri sulla tratta più carica ({top.pax_h:.0f} pax/h su {top.capacity_pax_h:.0f} "
        f"di capacità, {top.trips} corse nella fascia), per zona: {'; '.join(parts)}"
    )


def _section_rows(loads: TransitLoads) -> tuple[SectionRow, ...]:
    rows = [
        SectionRow(
            load.section.route_id,
            load.section.route_class,
            load.section.from_name,
            load.section.to_name,
            load.section.trips,
            load.section.capacity_pax_h,
            load.pax_h,
            load.load_ratio,
            load.by_zone,
        )
        for load in loads.sections.values()
    ]
    return tuple(
        sorted(
            rows,
            key=lambda r: (
                RAIL_KINDS.index(r.route_class),
                -(r.load_ratio or 0.0),
                r.route_id,
                r.from_name,
                r.to_name,
            ),
        )
    )


# --- itinerari ---------------------------------------------------------------------------------


def _itinerary_text(
    zone: ZoneAssignment, itinerary: ResolvedItinerary | None, window: Window
) -> str:
    """Come viaggiano le persone di una zona, in italiano e senza numeri (quelli sono nelle
    metriche). Nel deflusso le tratte si percorrono al contrario."""
    if zone.mode == "bus":
        return "autobus"
    if zone.mode == "unserved":
        return "non servita (nessun autobus nelle fermate vicine)"
    if itinerary is None or zone.itinerary is None:  # il piano non esiste: non può succedere
        raise ValueError(f"zona {zone.zone_id}: itinerario {zone.itinerary} non risolto")
    if zone.mode == "walk":
        return f"a piedi (itinerario {zone.itinerary})"
    legs = list(reversed(itinerary.legs)) if window == "departure" else list(itinerary.legs)
    parts = [
        f"{leg.alight.name} → {leg.board.name}"
        if window == "departure"
        else f"{leg.board.name} → {leg.alight.name}"
        for leg in legs
    ]
    steps = [f"{part} ({leg.route_class})" for part, leg in zip(parts, legs, strict=True)]
    if itinerary.egress_walk:
        steps.append("poi a piedi")
    return f"itinerario {zone.itinerary}: " + ", ".join(steps)


# --- layer -------------------------------------------------------------------------------------


def _stops_layer(loads: TransitLoads) -> FeatureCollection:
    def feature(item: StopLoad) -> Feature:
        stop = item.stop
        return Feature(
            id=stop.stop_id,
            geometry=geojson_point(stop.lat, stop.lon),
            properties={
                "stop_id": stop.stop_id,
                "name": stop.name,
                "load_ratio": item.load_ratio,
                "overloaded": _overloaded(item.load_ratio),
                "closed": item.closed,
                "pax_h": item.pax_h,
                "capacity_pax_h": stop.capacity_pax_h,
            },
        )

    return FeatureCollection(features=[feature(item) for item in loads.stops])


def _station_points(network: TransitNetwork) -> pd.DataFrame:
    return network.feed.stops.set_index("stop_id")[["lat", "lon"]]


def _sections_layer(network: TransitNetwork, loads: TransitLoads) -> FeatureCollection:
    points = _station_points(network)

    def centre(stop_ids: frozenset[str]) -> list[float]:
        found = points.loc[sorted(stop_ids)]
        return [round(float(found["lon"].mean()), COORD_DECIMALS),
                round(float(found["lat"].mean()), COORD_DECIMALS)]  # fmt: skip

    def feature(key: SectionKey, section_load: SectionLoad | None) -> Feature:
        section = loads.supply.sections[key]
        pax_h = section_load.pax_h if section_load else 0.0
        ratio = section_load.load_ratio if section_load else None
        if section_load is None and section.capacity_pax_h > 0:
            ratio = 0.0
        return Feature(
            id=":".join(key),
            geometry={
                "type": "LineString",
                "coordinates": [centre(section.from_stop_ids), centre(section.to_stop_ids)],
            },
            properties={
                "route_id": section.route_id,
                "route_class": section.route_class,
                "label": f"{section.from_name} → {section.to_name}",
                "trips": section.trips,
                "capacity_pax_h": section.capacity_pax_h,
                "pax_h": pax_h,
                "load_ratio": ratio,
                "overloaded": _overloaded(ratio),
            },
        )

    return FeatureCollection(
        features=[feature(key, loads.sections.get(key)) for key in sorted(loads.supply.sections)]
    )


def _area_layer(event: Event) -> FeatureCollection:
    centre = event.area_center
    return FeatureCollection(
        features=[
            Feature(
                id="event_area",
                geometry={
                    "type": "Polygon",
                    "coordinates": [circle_polygon(centre.lat, centre.lon, event.area_radius_m)],
                },
                properties={"label": centre.label, "radius_m": event.area_radius_m},
            )
        ]
    )


# --- metriche ----------------------------------------------------------------------------------


def transit_metrics(
    network: TransitNetwork,
    loads: TransitLoads,
    event: Event,
    demand: Demand,
    *,
    measures: TransitMeasures | None = None,
    id_prefix: Sequence[str],
    as_of: datetime,
) -> TransitMetrics:
    """Metriche e layer di una finestra e di un'iterazione.

    `loads` sono i carichi di `assign_transit`, `demand` la domanda da cui vengono e `measures` le
    misure TPL applicate (`apply_transit_measures`; le sue corse aggiunte rendono `simulated` le
    corse della loro classe). `id_prefix` apre gli id dei `Measured` e `as_of` è il loro istante
    (dato da chi chiama: la funzione non legge l'orologio).
    """
    window = loads.window
    service = loads.supply.service
    feed = network.feed
    inputs = (
        *demand.inputs,
        f"feed GTFS {feed.directory.name}: validità {feed.valid_from:%d/%m/%Y}–"
        f"{feed.valid_to:%d/%m/%Y}, giorno di servizio {service.used:%d/%m/%Y}",
    )
    common = unique(
        STATIC_MODEL_ASSUMPTION,
        *loads.assumptions,
        *(measures.assumptions if measures else ()),
        *demand.assumptions,
    )

    def measure(
        parts: Sequence[str],
        value: float | int | str,
        unit: str,
        kind: Kind,
        method: str,
        extra: Sequence[str] = (),
        more_inputs: Sequence[str] = (),
    ) -> Measured:
        return make_measured(
            id=measured_id(*id_prefix, "transit", window, *parts),
            value=value,
            unit=unit,
            kind=kind,
            source=SOURCE,
            method=method,
            inputs=(*inputs, *more_inputs),
            assumptions=unique(*common, *extra),
            as_of=as_of,
        )

    rows = _section_rows(loads)
    out: list[Measured] = [
        measure(
            ("stops_overloaded",),
            sum(1 for item in loads.stops if _overloaded(item.load_ratio)),
            "n",
            "estimate",
            f"fermate vicine all'area con passeggeri/capacità > {OVERLOAD:g} "
            "(una fermata chiusa non ha un carico)",
        ),
        measure(
            ("sections_overloaded",),
            sum(1 for row in rows if _overloaded(row.load_ratio)),
            "n",
            "estimate",
            f"tratte di metro e funicolare con passeggeri/capacità > {OVERLOAD:g}",
        ),
    ]

    for kind in RAIL_KINDS:
        loaded = [row for row in rows if row.route_class == kind and row.load_ratio is not None]
        top = max(loaded, key=lambda row: row.load_ratio or 0.0, default=None)
        out.append(
            measure(
                ("max_section_load", kind),
                (top.load_ratio or 0.0) if top else 0.0,
                "rapporto",
                "estimate",
                f"massimo di passeggeri/capacità tra le tratte di {kind}"
                + (f"; {FIRST_ITINERARY_METHOD}" if top else ""),
                (
                    f"tratta più carica: {top.from_name} → {top.to_name} (linea {top.route_id})"
                    if top
                    else f"nessuna tratta di {kind} ha passeggeri",
                ),
                (_fill_text(top, loads, network),) if top else (),
            )
        )

    added = {
        network.classes.of(str(route_id))
        for route_id in (measures.extra.trips["route_id"] if measures and measures.extra else ())
    }
    for kind in RAIL_KINDS:
        out.append(
            measure(
                ("trips_in_window", kind),
                loads.supply.trips_by_class[kind],
                "n",
                "simulated" if kind in added else loads.supply.kind,
                f"corse di {kind} che partono dal primo capolinea nella fascia di picco "
                "(due direzioni)",
            )
        )

    for zone in loads.zones:
        itineraries = network.itineraries.get(zone.zone_id, ())
        itinerary = itineraries[zone.itinerary - 1] if zone.itinerary is not None else None
        out.append(
            measure(
                ("itinerary_used", zone.zone_id),
                _itinerary_text(zone, itinerary, window),
                "testo",
                "estimate",
                "primo itinerario disponibile nella fascia tra quelli di engine.yaml; se nessuno "
                "lo è, autobus",
                (
                    f"zona {zone.zone_id}: {zone.persons:.0f} persone TPL nella fascia di picco",
                    *zone.skipped,
                ),
            )
        )

    out.append(
        measure(
            ("walk_people",),
            loads.walk_persons,
            "pax",
            "estimate",
            "persone a piedi nella fascia di picco: modo «a piedi» della ripartizione modale più "
            "gli itinerari senza tratte",
        )
    )

    layers = {
        "stops": _stops_layer(loads),
        "sections": _sections_layer(network, loads),
        "event_area": _area_layer(event),
    }
    return TransitMetrics(window=window, measures=tuple(out), layers=layers, sections=rows)
