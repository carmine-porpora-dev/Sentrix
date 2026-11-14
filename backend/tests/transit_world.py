import datetime as dt
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.data.gtfs import GtfsFeed, RouteClasses
from app.engine.demand import Demand, ZoneDemand
from app.engine.transit import ResolvedItinerary, ResolvedLeg, Station, TransitNetwork
from app.engine.transit_loads import TransitLoads, assign_transit
from app.models.config import TransitConfig
from app.models.geo import GeoPoint
from tests.support import make_event, make_request, write_gtfs

BAND = (dt.time(8, 15), dt.time(8, 45))
SLICE = 30

ROUTES = [
    {"route_id": "RL", "route_type": "1"},
    {"route_id": "RS", "route_type": "1"},
    {"route_id": "RB", "route_type": "3"},
    {"route_id": "RD", "route_type": "7"},
    {"route_id": "RX", "route_type": "1"},
]
# stop_id: (nome, lat, lon)
FAR = (40.90, 14.30)
STOPS = {
    "a1": ("ALFA", *FAR), "a2": ("ALFA", *FAR), "b1": ("BETA", *FAR), "b2": ("BETA", *FAR),
    "g1": ("GAMMA", 40.8340, 14.2350), "g2": ("GAMMA", 40.8340, 14.2350),
    "m1": ("BETA", *FAR), "m2": ("EPSILON", 40.8330, 14.2350),
    "u1": ("BUS UNO", 40.8325, 14.2350), "u2": ("BUS DUE", 40.8310, 14.2350),
    "u3": ("BUS TRE", *FAR),
    "d1": ("D UNO", *FAR), "d3": ("D DUE", *FAR), "d4": ("D DUE", *FAR),
    "d5": ("D UNO", 40.8330, 14.2360), "d6": ("D UNO", 40.8330, 14.2360),
}  # fmt: skip
# (corsa, linea, servizio, [(fermata, "HH:MM")])
TRIPS = [
    ("T1", "RL", "WK", [("a1", "08:20"), ("b1", "08:25"), ("g1", "08:30")]),
    ("T2", "RL", "WK", [("a1", "08:30"), ("b1", "08:35"), ("g1", "08:40")]),
    ("T3", "RL", "WK", [("a1", "08:40"), ("b1", "08:45"), ("g1", "08:50")]),
    ("T4", "RL", "WK", [("g2", "08:20"), ("b2", "08:25"), ("a2", "08:30")]),
    ("T5", "RL", "WK", [("g2", "08:35"), ("b2", "08:40"), ("a2", "08:45")]),
    ("S6a", "RS", "S6", [("m1", "08:20"), ("m2", "08:30")]),
    ("S6b", "RS", "S6", [("m1", "08:40"), ("m2", "08:50")]),
    ("BA", "RB", "WK", [("u1", "08:20"), ("u2", "08:24")]),
    ("BB", "RB", "WK", [("u1", "08:35"), ("u3", "08:40")]),
    ("TD", "RD", "WK", [("d1", "08:20"), ("d3", "08:25")]),
    ("TE", "RD", "WK", [("d4", "08:30"), ("d5", "08:31"), ("d6", "08:32")]),
    ("X1", "RX", "WK", [("u1", "08:22"), ("u2", "08:26")]),
]  # fmt: skip
WK_DAY, S6_DAY = date(2026, 12, 19), date(2026, 12, 20)

CLASSES = RouteClasses(
    {
        "metro_line_1": frozenset({"RL"}),
        "metro_line_6": frozenset({"RS"}),
        "funicular": frozenset({"RD"}),
        "bus": frozenset({"RB"}),
    }
)


def station(name: str, *ids: str) -> Station:
    return Station(name, frozenset(ids))


ALFA, BETA_L1, GAMMA = (
    station("ALFA", "a1", "a2"),
    station("BETA", "b1", "b2"),
    station("GAMMA", "g1", "g2"),
)
BETA_L6, EPSILON = station("BETA", "m1"), station("EPSILON", "m2")
D_UNO, D_DUE = station("D UNO", "d1", "d5", "d6"), station("D DUE", "d3", "d4")
L1_ALFA_GAMMA = ResolvedLeg("metro_line_1", ALFA, GAMMA)
L1_ALFA_BETA = ResolvedLeg("metro_line_1", ALFA, BETA_L1)
L6_BETA_EPSILON = ResolvedLeg("metro_line_6", BETA_L6, EPSILON)


def itinerary(*legs: ResolvedLeg, walk: bool = False) -> ResolvedItinerary:
    return ResolvedItinerary(tuple(legs), walk)


def write_world_feed(directory: Path) -> Path:
    """Scrive il feed del mondo di prova in `directory` e la restituisce."""
    times = [
        {
            "trip_id": trip,
            "arrival_time": f"{hhmm}:00",
            "departure_time": f"{hhmm}:00",
            "stop_id": stop,
            "stop_sequence": str(n + 1),
        }
        for trip, _, _, stops in TRIPS
        for n, (stop, hhmm) in enumerate(stops)
    ]
    return write_gtfs(
        directory,
        routes=ROUTES,
        trips=[{"route_id": r, "service_id": s, "trip_id": t} for t, r, s, _ in TRIPS],
        stops=[
            {"stop_id": i, "stop_name": n, "stop_lat": str(lat), "stop_lon": str(lon)}
            for i, (n, lat, lon) in STOPS.items()
        ],
        stop_times=times,
        calendar_dates=[
            {"service_id": "WK", "date": "20261219", "exception_type": "1"},
            {"service_id": "WK", "date": "20261220", "exception_type": "1"},
            {"service_id": "S6", "date": "20261220", "exception_type": "1"},
        ],
    )


def zone(zone_id: str, transit: float, walk: float = 0.0) -> ZoneDemand:
    return ZoneDemand(
        zone_id=zone_id, zone_type="near", persons=transit + walk, car_persons=0.0,
        transit_persons=transit, walk_persons=walk, car_vehicles=0.0, car_veh_per_hour=0.0,
    )  # fmt: skip


def demand_of(
    *zones: ZoneDemand, window: str = "arrival", band: tuple[dt.time, dt.time] = BAND
) -> Demand:
    return Demand(
        window=window,  # type: ignore[arg-type]
        level="mid", attendance=0, band_start=band[0], band_end=band[1], band_share=0.3,
        persons=0.0, zones=zones, flows=(), car_occupancy=2.2, inputs=("prova",), assumptions=(),
    )  # fmt: skip


def disruption(name: str, *ids: str, window: str = "both") -> dict[str, Any]:
    return {"label": f"{name} chiusa", "stop_name": name, "stop_ids": list(ids), "window": window}


# --- un feed costruito dagli itinerari di engine.yaml ---------------------------------------------

HEADWAY_MIN = 10  # una corsa ogni 10 minuti per senso, da WORLD_FIRST_H a WORLD_LAST_H
WORLD_FIRST_H, WORLD_LAST_H = 5, 24
RAIL_ROUTE_TYPE = {"metro_line_1": "1", "metro_line_6": "1", "funicular": "7"}


def write_feed_for_itineraries(
    directory: Path, transit: TransitConfig, day: date, center: GeoPoint
) -> Path:
    """Un feed GTFS in cui ogni itinerario di `transit` si risolve: per ogni tratta
    (classe, salita, discesa) due fermate per stazione (una per senso) entro 300 m da `center` e una
    corsa diretta per senso ogni `HEADWAY_MIN` minuti dalle 05:00 alle 24:00 il giorno `day`. In
    più una linea bus con due fermate. I tempi sono finti: servono a far girare la riga di comando e
    i test di integrazione sugli stessi nomi di `engine.yaml`, non a rappresentare la rete."""
    legs = sorted(
        {
            (leg.route_class, leg.from_stop_name, leg.to_stop_name)
            for itineraries in transit.itineraries.values()
            for itinerary in itineraries
            for leg in itinerary.legs
        }
    )
    stations = sorted({(kind, name) for kind, a, b in legs for name in (a, b)})
    route_of = {
        kind: getattr(transit.route_classification, kind).route_ids[0] for kind in RAIL_ROUTE_TYPE
    }
    stops: list[dict[str, Any]] = []
    for number, (kind, name) in enumerate(stations):
        for side in ("a", "b"):
            stops.append(
                {
                    "stop_id": f"{kind}:{name}:{side}",
                    "stop_name": name,
                    "stop_lat": str(round(center.lat + 0.0005 + 0.00005 * number, 6)),
                    "stop_lon": str(round(center.lon + 0.0005, 6)),
                }
            )
    for stop_id, name, lat in (
        ("bus1", "Bus uno", center.lat),
        ("bus2", "Bus due", center.lat + 0.001),
    ):
        stops.append(
            {
                "stop_id": stop_id,
                "stop_name": name,
                "stop_lat": str(lat),
                "stop_lon": str(center.lon),
            }
        )
    rides = [(route_of[kind], f"{kind}:{a}:a", f"{kind}:{b}:a") for kind, a, b in legs]
    rides += [(route_of[kind], f"{kind}:{b}:b", f"{kind}:{a}:b") for kind, a, b in legs]
    rides.append(("BUS", "bus1", "bus2"))
    trips: list[dict[str, Any]] = []
    times: list[dict[str, Any]] = []
    for ride, (route, first, second) in enumerate(rides):
        for minute in range(WORLD_FIRST_H * 60, WORLD_LAST_H * 60, HEADWAY_MIN):
            trip_id = f"t{ride}-{minute}"
            trips.append({"route_id": route, "service_id": "WK", "trip_id": trip_id})
            for seq, (stop, offset) in enumerate(((first, 0), (second, 3)), start=1):
                clock = f"{(minute + offset) // 60:02d}:{(minute + offset) % 60:02d}:00"
                times.append(
                    {
                        "trip_id": trip_id,
                        "arrival_time": clock,
                        "departure_time": clock,
                        "stop_id": stop,
                        "stop_sequence": str(seq),
                    }
                )
    return write_gtfs(
        directory,
        routes=[
            *(
                {"route_id": route, "route_type": route_type}
                for kind, route_type in RAIL_ROUTE_TYPE.items()
                for route in getattr(transit.route_classification, kind).route_ids
            ),
            {"route_id": "BUS", "route_type": "3"},
        ],
        trips=trips,
        stops=stops,
        stop_times=times,
        calendar_dates=[
            {"service_id": "WK", "date": f"{day:%Y%m%d}", "exception_type": "1"},
        ],
    )


def req(action_id: str, kind: str, target: str, **changes: Any) -> Any:
    """Una richiesta TPL accettata: arrivo, iterazione 1 (`changes` modifica i campi)."""
    fields: dict[str, Any] = {
        "type": kind, "target": target, "window": "arrival", "state": "ACCEPTED", "iteration": 1,
    }  # fmt: skip
    return make_request(action_id, **{**fields, **changes})


def run_loads(
    feed: GtfsFeed,
    config: TransitConfig,
    itineraries: dict[str, list[ResolvedItinerary]],
    demand: Demand,
    day: date = WK_DAY,
    *,
    disruptions: list[dict[str, Any]] | None = None,
    suspended: tuple[str, ...] = (),
    classes: RouteClasses = CLASSES,
) -> TransitLoads:
    """I carichi TPL di `demand` nel mondo di prova (`disruptions` = interruzioni dell'Evento)."""
    network = TransitNetwork(feed, classes, {z: tuple(i) for z, i in itineraries.items()})
    event = make_event(date=day.isoformat(), transit_disruptions=disruptions or [])
    return assign_transit(network, config, event, demand, SLICE, suspended)


def determinism_probe(directory: Path) -> str:
    """L'impronta (sha256) del risultato di uno scenario del mondo di prova con interruzioni, una
    sospensione e corse aggiunte: due processi con `PYTHONHASHSEED` diversi devono darla uguale.
    Scrive il feed in `directory`."""
    import datetime as _dt
    import hashlib

    from app.data.gtfs import clear_feed_cache, load_feed
    from app.engine.transit_run import TransitEngine
    from app.models.config import EngineConfig

    clear_feed_cache()
    feed = load_feed(write_world_feed(directory / "feed"))
    itineraries = {
        "a": (itinerary(ResolvedLeg("metro_line_1", ALFA, GAMMA)),),
        "b": (itinerary(ResolvedLeg("funicular", D_DUE, D_UNO), walk=True), itinerary()),
        "c": (),
    }
    network = TransitNetwork(feed, CLASSES, itineraries)
    event = make_event(
        date=WK_DAY.isoformat(), transit_disruptions=[disruption("BETA", "b1", "b2")]
    )
    demand = demand_of(zone("a", 900, walk=40), zone("b", 300), zone("c", 500))
    requests = [
        req("m1", "add_runs", "metro_line_1", payload={"n": 2}),
        req("m2", "stop_suspension", "u1"),
    ]
    result = TransitEngine(network, EngineConfig.from_yaml()).run(
        event,
        demand,
        requests,
        id_prefix=("probe", "it1"),
        as_of=_dt.datetime(2026, 11, 9, 12, 0, tzinfo=_dt.UTC),
    )
    return hashlib.sha256(result.model_dump_json().encode()).hexdigest()


def assert_persons_conserved(loads: TransitLoads, demand: Demand) -> dict[str, float]:
    """Tutta la domanda TPL della fascia finisce da qualche parte, una volta sola (03 5): ogni zona
    con domanda compare una volta; itinerario + a piedi + bus + non servite = domanda; la domanda
    bus, anche redistribuita dalle fermate chiuse, arriva tutta sulle fermate aperte. Restituisce le
    persone per modo (`itinerary`, `walk`, `bus`, `unserved`)."""
    to_pax_h = 60 / SLICE
    by_mode = {"itinerary": 0.0, "walk": 0.0, "bus": 0.0, "unserved": 0.0}
    for assigned in loads.zones:
        by_mode[assigned.mode] += assigned.persons
    wanted = sorted(z.zone_id for z in demand.zones if z.transit_persons > 0)
    assert sorted(z.zone_id for z in loads.zones) == wanted
    assert sum(by_mode.values()) == pytest.approx(demand.transit_persons)
    assert loads.bus_persons == pytest.approx(by_mode["bus"])
    assert loads.unserved_persons == pytest.approx(by_mode["unserved"])
    assert loads.walk_persons == pytest.approx(demand.walk_persons + by_mode["walk"])
    assert sum(s.bus_pax_h for s in loads.stops) == pytest.approx(loads.bus_persons * to_pax_h)
    for stop in loads.stops:
        assert stop.pax_h >= stop.bus_pax_h >= 0
        if stop.closed:
            assert stop.pax_h == 0 and stop.load_ratio is None
    return by_mode


def real_transit_fingerprint() -> str:
    """L'impronta (sha256) dei risultati TPL dei due preset sui dati veri di `DATA_DIR` (livello
    mid, entrambe le finestre, con `extend_hours` sulla L6 nell'arrivo): due processi con
    `PYTHONHASHSEED` diversi devono darla uguale. `as_of` è fisso."""
    import datetime as _dt
    import hashlib

    from app.data.gtfs import load_feed
    from app.data.paths import DataPaths, default_data_dir
    from app.data.seeds import read_seed_events
    from app.engine.demand import build_demand
    from app.engine.graph import load_road_graph
    from app.engine.transit import load_transit_network
    from app.engine.transit_run import TransitEngine
    from app.models.config import EngineConfig
    from app.models.edge_overrides import EdgeOverrides

    paths, config = DataPaths(default_data_dir()), EngineConfig.from_yaml()
    graph = load_road_graph(paths.osm_graph, config, EdgeOverrides.from_yaml())
    network = load_transit_network(load_feed(paths.gtfs_feed), config.transit)
    engine = TransitEngine(network, config)
    extend = req("e1", "extend_hours", "metro_line_6")
    digest = hashlib.sha256()
    for event in read_seed_events():
        for window in ("arrival", "departure"):
            demand = build_demand(event, "mid", window, config, graph)
            requests = [extend] if window == "arrival" else []
            result = engine.run(
                event,
                demand,
                requests,
                id_prefix=("fp", "it1"),
                as_of=_dt.datetime(2026, 11, 9, 12, 0, tzinfo=_dt.UTC),
            )
            digest.update(result.model_dump_json().encode())
    return digest.hexdigest()
