import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import networkx as nx

from app.data.resolvers import resolve_point
from app.engine import STATIC_MODEL_ASSUMPTION
from app.models.base import Window
from app.models.config import CarDestination, EngineConfig
from app.models.demand import ModalSplit, Zone, ZoneType
from app.models.event import Event, TimeWindow
from app.models.geo import GeoPoint
from app.models.provenance import Measured, make_measured, measured_id
from app.models.run import AttendanceLevel

SOURCE = "engine.demand v1"
METHOD = "profilo triangolare + ripartizione per tipo zona"


# --- profilo triangolare --------------------------------------------------------------------------


def _minutes(t: dt.time) -> float:
    return t.hour * 60 + t.minute + t.second / 60 + t.microsecond / 60_000_000


def _triangular_cdf(a: float, c: float, b: float, x: float) -> float:
    """Frazione della domanda arrivata entro `x`: inizio `a`, moda `c`, fine `b` (a ≤ c < b)."""
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    if x <= c:  # a < x ≤ c, quindi c > a
        return (x - a) ** 2 / ((b - a) * (c - a))
    return 1.0 - (b - x) ** 2 / ((b - a) * (b - c))


def triangular_share(window: TimeWindow, start: dt.time, end: dt.time) -> float:
    """La quota della domanda della finestra (da 0 a 1) che cade in `[start, end)`."""
    a, c, b = _minutes(window.start), _minutes(window.peak), _minutes(window.end)
    return _triangular_cdf(a, c, b, _minutes(end)) - _triangular_cdf(a, c, b, _minutes(start))


def peak_band(window: TimeWindow, slice_minutes: int) -> tuple[dt.time, dt.time]:
    """La fascia di picco `[peak, peak + slice)`, troncata alla fine della finestra."""
    start = dt.datetime.combine(dt.date.min, window.peak)
    end = min(
        start + dt.timedelta(minutes=slice_minutes), dt.datetime.combine(dt.date.min, window.end)
    )
    return start.time(), end.time()


# --- impostazioni effettive -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DemandInputs:
    """Zone, ripartizioni, punti di arrivo e occupazione effettivi per un Evento."""

    zones: tuple[Zone, ...]
    modal_split: Mapping[ZoneType, ModalSplit]
    car_destinations: tuple[CarDestination, ...]
    car_occupancy: float
    overridden: tuple[str, ...]  # quali impostazioni l'Evento ha sostituito, per le assunzioni


def effective_demand_inputs(event: Event, config: EngineConfig) -> DemandInputs:
    """I default di `engine.yaml`, con le sostituzioni dell'Evento."""
    demand = config.demand
    overridden: list[str] = []
    zones = demand.zones
    if event.zones_override is not None:
        zones = event.zones_override
        overridden.append("zone")
    modal_split = dict(demand.modal_split_by_type)
    if event.modal_split_override is not None:
        modal_split.update(event.modal_split_override)
        overridden.append("ripartizione modale")
    destinations = demand.car_destinations
    if event.car_destinations is not None:
        destinations = event.car_destinations
        overridden.append("punti di arrivo auto")
    occupancy = config.car_occupancy_default
    if event.car_occupancy is not None:
        occupancy = event.car_occupancy
        overridden.append("occupazione auto")
    return DemandInputs(
        zones=tuple(zones),
        modal_split=modal_split,
        car_destinations=tuple(destinations),
        car_occupancy=occupancy,
        overridden=tuple(overridden),
    )


# --- risultato ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ZoneDemand:
    """Persone e auto di una zona nella fascia di picco."""

    zone_id: str
    zone_type: ZoneType
    persons: float
    car_persons: float
    transit_persons: float  # domanda TPL per il motore trasporto pubblico (03)
    walk_persons: float  # solo conteggio
    car_vehicles: float  # veicoli nella fascia
    car_veh_per_hour: float  # flusso orario equivalente


@dataclass(frozen=True, slots=True)
class OdFlow:
    """Flusso auto tra la zona e un punto di arrivo, già agganciato ai nodi stradali."""

    zone_id: str
    origin_node: int
    dest_node: int
    veh_per_hour: float
    destination_label: str | None


@dataclass(frozen=True, slots=True)
class Demand:
    window: Window
    level: AttendanceLevel
    attendance: int  # persone del livello, in tutta la finestra
    band_start: dt.time
    band_end: dt.time
    band_share: float  # quota dell'affluenza che cade nella fascia
    persons: float  # attendance × band_share
    zones: tuple[ZoneDemand, ...]
    flows: tuple[OdFlow, ...]  # solo flussi > 0, nell'ordine delle zone e dei punti di arrivo
    car_occupancy: float
    inputs: tuple[str, ...]
    assumptions: tuple[str, ...]

    @property
    def car_persons(self) -> float:
        return sum(zone.car_persons for zone in self.zones)

    @property
    def transit_persons(self) -> float:
        return sum(zone.transit_persons for zone in self.zones)

    @property
    def walk_persons(self) -> float:
        return sum(zone.walk_persons for zone in self.zones)

    @property
    def car_veh_per_hour(self) -> float:
        return sum(zone.car_veh_per_hour for zone in self.zones)


# --- calcolo --------------------------------------------------------------------------------------


def _zone_demand(
    zone: Zone, zone_persons: float, split: ModalSplit, car_occupancy: float, slice_minutes: int
) -> ZoneDemand:
    """Le persone della zona divise per modo (la ripartizione è normalizzata alla sua somma), le
    auto e il flusso orario equivalente."""
    split_total = split.car_pct + split.transit_pct + split.walk_pct
    car = zone_persons * split.car_pct / split_total
    vehicles = car / car_occupancy
    return ZoneDemand(
        zone_id=zone.id,
        zone_type=zone.type,
        persons=zone_persons,
        car_persons=car,
        transit_persons=zone_persons * split.transit_pct / split_total,
        walk_persons=zone_persons * split.walk_pct / split_total,
        car_vehicles=vehicles,
        car_veh_per_hour=vehicles * 60 / slice_minutes,
    )


def build_demand(
    event: Event,
    level: AttendanceLevel,
    window: Window,
    config: EngineConfig,
    graph: nx.MultiDiGraph,
) -> Demand:
    """La domanda dell'Evento nella fascia di picco di `window` al livello `level`.

    `graph` serve solo ad agganciare zone e punti di arrivo al nodo stradale più vicino
    (`ResolveError` se uno dista più di `node_snap_max_distance_m` da ogni nodo).
    """
    inputs = effective_demand_inputs(event, config)
    time_window = event.time_window(window)
    slice_minutes = config.time_slice_minutes
    band_start, band_end = peak_band(time_window, slice_minutes)
    band_share = triangular_share(time_window, band_start, band_end)
    attendance: int = getattr(event.attendance, level)
    persons = attendance * band_share

    def snap(point: GeoPoint) -> int:
        return resolve_point(point, graph, max_distance_m=config.node_snap_max_distance_m)

    total_weight = sum(zone.weight_pct for zone in inputs.zones)
    total_share = sum(destination.share_pct for destination in inputs.car_destinations)
    destinations = [(d, snap(d.point)) for d in inputs.car_destinations]

    zones: list[ZoneDemand] = []
    flows: list[OdFlow] = []
    for zone in inputs.zones:
        zone_demand = _zone_demand(
            zone,
            persons * zone.weight_pct / total_weight,
            inputs.modal_split[zone.type],
            inputs.car_occupancy,
            slice_minutes,
        )
        zones.append(zone_demand)
        rate = zone_demand.car_veh_per_hour
        if rate <= 0:
            continue
        zone_node = snap(zone.centroid)
        for destination, destination_node in destinations:
            origin, target = (
                (zone_node, destination_node)
                if window == "arrival"
                else (destination_node, zone_node)
            )
            flows.append(
                OdFlow(
                    zone_id=zone.id,
                    origin_node=origin,
                    dest_node=target,
                    veh_per_hour=rate * destination.share_pct / total_share,
                    destination_label=destination.point.label,
                )
            )

    return Demand(
        window=window,
        level=level,
        attendance=attendance,
        band_start=band_start,
        band_end=band_end,
        band_share=band_share,
        persons=persons,
        zones=tuple(zones),
        flows=tuple(flows),
        car_occupancy=inputs.car_occupancy,
        inputs=(
            f"event {event.id} rev {event.revision}",
            f"engine.yaml sha:{config.content_hash()[:8]}",
            f"livello di affluenza {level}: {attendance} persone",
            f"finestra {window} {time_window.start:%H:%M}-{time_window.end:%H:%M}, "
            f"picco {time_window.peak:%H:%M}",
        ),
        assumptions=_assumptions(inputs, time_window, band_start, band_end, slice_minutes),
    )


def _assumptions(
    inputs: DemandInputs,
    window: TimeWindow,
    band_start: dt.time,
    band_end: dt.time,
    slice_minutes: int,
) -> tuple[str, ...]:
    band_minutes = _minutes(band_end) - _minutes(band_start)
    items = [
        STATIC_MODEL_ASSUMPTION,
        f"profilo triangolare tra {window.start:%H:%M} e {window.end:%H:%M}, "
        f"moda alle {window.peak:%H:%M}; fascia di picco di {slice_minutes} minuti",
        "pesi delle zone, ripartizioni modali e quote dei punti di arrivo normalizzati alla "
        "loro somma",
        f"occupazione auto {inputs.car_occupancy:g} persone per veicolo",
        "parcheggi non modellati: le auto raggiungono direttamente i punti di arrivo",
    ]
    if band_minutes < slice_minutes:
        items.append(
            f"fascia troncata alla fine della finestra ({band_minutes:g} minuti): il flusso "
            f"orario è calcolato sui {slice_minutes} minuti di una fascia intera"
        )
    if inputs.overridden:
        items.append(
            "impostazioni dell'evento al posto di quelle di default: "
            + ", ".join(inputs.overridden)
        )
    return tuple(items)


# --- provenienza ----------------------------------------------------------------------------------


def demand_measures(demand: Demand, id_prefix: Sequence[str], as_of: dt.datetime) -> list[Measured]:
    """Le grandezze della domanda come `Measured` (kind=estimate), 02 3.9.

    `id_prefix` apre gli id (es. `("run42", "it0")`): `m.run42.it0.demand.arrival.persons`; `as_of`
    è il loro istante (dato da chi chiama: la funzione non legge l'orologio). Totali della fascia,
    per modo, e per zona (persone per modo, veicoli/ora).
    """
    base = (*id_prefix, "demand", demand.window)

    def measure(parts: Sequence[str], value: float, unit: str) -> Measured:
        return make_measured(
            id=measured_id(*base, *parts),
            value=value,
            unit=unit,
            kind="estimate",
            source=SOURCE,
            method=METHOD,
            inputs=demand.inputs,
            assumptions=demand.assumptions,
            as_of=as_of,
        )

    out = [
        measure(("persons",), demand.persons, "pax"),
        measure(("car_persons",), demand.car_persons, "pax"),
        measure(("transit_persons",), demand.transit_persons, "pax"),
        measure(("walk_persons",), demand.walk_persons, "pax"),
        measure(("car_veh_per_hour",), demand.car_veh_per_hour, "veic/h"),
    ]
    for zone in demand.zones:
        prefix = ("zone", zone.zone_id)
        out += [
            measure((*prefix, "persons"), zone.persons, "pax"),
            measure((*prefix, "car_persons"), zone.car_persons, "pax"),
            measure((*prefix, "transit_persons"), zone.transit_persons, "pax"),
            measure((*prefix, "walk_persons"), zone.walk_persons, "pax"),
            measure((*prefix, "car_veh_per_hour"), zone.car_veh_per_hour, "veic/h"),
        ]
    return out
