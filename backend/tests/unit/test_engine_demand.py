import datetime as dt
from collections.abc import Iterable
from typing import Any

import networkx as nx
import pytest

from app.data.resolvers import ResolveError
from app.engine.demand import (
    Demand,
    build_demand,
    demand_measures,
    effective_demand_inputs,
    peak_band,
    triangular_share,
)
from app.models.config import EngineConfig
from app.models.event import TimeWindow
from app.models.geo import GeoPoint
from tests.support import make_event

NodeMap = dict[tuple[float, float], int]


def t(text: str) -> dt.time:
    return dt.time.fromisoformat(text)


def window(start: str, end: str, peak: str) -> TimeWindow:
    return TimeWindow.model_validate({"start": start, "end": end, "peak": peak})


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


def graph_with_nodes(points: Iterable[GeoPoint]) -> tuple[nx.MultiDiGraph, NodeMap]:
    """Un nodo esatto (id 1000+i) su ogni punto e, a circa 44 m, un nodo «esca» con id più basso:
    solo il più vicino, non il primo per id, è la risposta giusta."""
    graph: nx.MultiDiGraph = nx.MultiDiGraph()
    nodes: NodeMap = {}
    for i, point in enumerate(points):
        graph.add_node(10 + i, x=point.lon, y=point.lat + 0.0004)
        graph.add_node(1000 + i, x=point.lon, y=point.lat)
        nodes[(point.lat, point.lon)] = 1000 + i
    return graph, nodes


def default_points(config: EngineConfig) -> list[GeoPoint]:
    return [zone.centroid for zone in config.demand.zones] + [
        d.point for d in config.demand.car_destinations
    ]


@pytest.fixture(scope="module")
def world(config: EngineConfig) -> tuple[nx.MultiDiGraph, NodeMap]:
    return graph_with_nodes(default_points(config))


def node_of(nodes: NodeMap, point: GeoPoint) -> int:
    return nodes[(point.lat, point.lon)]


# --- profilo triangolare -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("win", "band", "expected"),
    [
        # picco al centro: 5/18 (vedi la docstring)
        (("12:00", "15:00", "13:30"), ("13:30", "14:00"), 5 / 18),
        # le fasce a fianco del picco e agli estremi: 1/18 + 1/6 + 5/18 = 1/2 (metà finestra)
        (("12:00", "15:00", "13:30"), ("12:00", "12:30"), 1 / 18),
        (("12:00", "15:00", "13:30"), ("12:30", "13:00"), 1 / 6),
        (("12:00", "15:00", "13:30"), ("13:00", "13:30"), 5 / 18),
        (("12:00", "15:00", "13:30"), ("14:30", "15:00"), 1 / 18),
        # picco all'inizio: densità massima 2/120 al min 0, 0,0125 al min 30 → 0,4375
        (("12:00", "14:00", "12:00"), ("12:00", "12:30"), 0.4375),
        # fascia troncata (15 minuti): triangolo di base 15 e altezza 2/120 → 0,125
        (("12:00", "14:00", "13:45"), ("13:45", "14:00"), 0.125),
        # Regate: arrivo 12-14 picco 13:30 → 1/4; deflusso 16-18 picco 16:30 → 5/12
        (("12:00", "14:00", "13:30"), ("13:30", "14:00"), 0.25),
        (("16:00", "18:00", "16:30"), ("16:30", "17:00"), 5 / 12),
        # Match: arrivo 16-19 picco 18:00 → 1/4; deflusso 21-23 picco 21:30 → 5/12
        (("16:00", "19:00", "18:00"), ("18:00", "18:30"), 0.25),
        (("21:00", "23:00", "21:30"), ("21:30", "22:00"), 5 / 12),
        # tutta la finestra = 1; fuori dalla finestra = 0; a cavallo vale solo la parte dentro
        (("12:00", "15:00", "13:30"), ("12:00", "15:00"), 1.0),
        (("12:00", "15:00", "13:30"), ("10:00", "11:00"), 0.0),
        (("12:00", "15:00", "13:30"), ("15:00", "16:00"), 0.0),
        (("12:00", "15:00", "13:30"), ("11:00", "13:30"), 0.5),
        (("12:00", "15:00", "13:30"), ("13:30", "23:00"), 0.5),
    ],
)
def test_quota_della_fascia_calcolata_a_mano(
    win: tuple[str, str, str], band: tuple[str, str], expected: float
) -> None:
    assert triangular_share(window(*win), t(band[0]), t(band[1])) == pytest.approx(
        expected, abs=1e-12
    )


def test_le_fasce_che_coprono_la_finestra_sommano_a_uno() -> None:
    w = window("12:00", "15:00", "13:40")  # picco non allineato alle fasce
    bounds = ["12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00"]
    shares = [triangular_share(w, t(a), t(b)) for a, b in zip(bounds, bounds[1:], strict=False)]
    assert sum(shares) == pytest.approx(1.0, abs=1e-12)
    assert all(share > 0 for share in shares)
    assert max(shares) == shares[3]  # la fascia 13:30-14:00 contiene il picco delle 13:40


def test_secondi_e_minuti_frazionari() -> None:
    w = window("12:00", "13:00", "12:30:30")
    # fascia 12:30:30-13:00: base 29,5 min; altezza della densità 2/60 al min 30,5
    assert triangular_share(w, t("12:30:30"), t("13:00")) == pytest.approx(1 - 30.5 / 60, abs=1e-12)


@pytest.mark.parametrize(
    ("win", "slice_minutes", "expected"),
    [
        (("12:00", "15:00", "13:30"), 30, ("13:30", "14:00")),
        (("12:00", "14:00", "13:45"), 30, ("13:45", "14:00")),  # troncata alla fine
        (("12:00", "15:00", "13:30"), 45, ("13:30", "14:15")),
        (("12:00", "15:00", "12:00"), 30, ("12:00", "12:30")),
        (("12:00", "14:00", "13:30"), 30, ("13:30", "14:00")),  # esattamente fino alla fine
        (("23:00", "23:59", "23:50"), 30, ("23:50", "23:59")),  # senza passare la mezzanotte
    ],
)
def test_fascia_di_picco(
    win: tuple[str, str, str], slice_minutes: int, expected: tuple[str, str]
) -> None:
    assert peak_band(window(*win), slice_minutes) == (t(expected[0]), t(expected[1]))


# --- domanda dell'Evento, valori di default ------------------------------------------------------

# (zona, persone, auto, TPL, piedi) per l'arrivo al livello mid: 100 persone per punto di peso
ARRIVAL_MID = [
    ("gate_east", 1200, 1200, 0, 0),  # road_gate 100/0/0
    ("gate_west", 800, 800, 0, 0),
    ("gate_metro_north", 800, 0, 800, 0),  # metro_gate 0/100/0
    ("central_station", 1200, 0, 960, 240),  # arrival_hub 0/80/20
    ("port", 400, 0, 320, 80),
    ("chiaia", 800, 160, 240, 400),  # near 20/30/50
    ("posillipo", 500, 100, 150, 250),
    ("san_ferdinando", 600, 120, 180, 300),
    ("vomero", 1000, 300, 600, 100),  # far 30/60/10
    ("arenella", 600, 180, 360, 60),
    ("centro_storico", 800, 240, 480, 80),
    ("fuorigrotta", 800, 240, 480, 80),
    ("bagnoli", 500, 150, 300, 50),
]
ZONES_WITH_CARS = [row[0] for row in ARRIVAL_MID if row[2] > 0]  # 10 zone


@pytest.fixture(scope="module")
def arrival(config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]) -> Demand:
    return build_demand(make_event(), "mid", "arrival", config, world[0])


def test_la_fascia_e_le_persone(arrival: Demand) -> None:
    assert (arrival.window, arrival.level, arrival.attendance) == ("arrival", "mid", 36000)
    assert (arrival.band_start, arrival.band_end) == (t("13:30"), t("14:00"))
    assert arrival.band_share == pytest.approx(5 / 18, abs=1e-12)
    assert arrival.persons == pytest.approx(10000, rel=1e-12)


@pytest.mark.parametrize(("zone_id", "persons", "car", "transit", "walk"), ARRIVAL_MID)
def test_persone_per_zona_e_per_modo(
    arrival: Demand, zone_id: str, persons: float, car: float, transit: float, walk: float
) -> None:
    zone = next(z for z in arrival.zones if z.zone_id == zone_id)
    assert zone.persons == pytest.approx(persons, rel=1e-12)
    assert zone.car_persons == pytest.approx(car, abs=1e-9)
    assert zone.transit_persons == pytest.approx(transit, abs=1e-9)
    assert zone.walk_persons == pytest.approx(walk, abs=1e-9)
    # veicoli = auto / 2,2; flusso orario = veicoli · 60/30
    assert zone.car_vehicles == pytest.approx(car / 2.2, abs=1e-9)
    assert zone.car_veh_per_hour == pytest.approx(car / 2.2 * 2, abs=1e-9)


def test_le_zone_sono_tutte_e_nell_ordine_della_configurazione(
    arrival: Demand, config: EngineConfig
) -> None:
    assert [z.zone_id for z in arrival.zones] == [z.id for z in config.demand.zones]
    assert [z.zone_type for z in arrival.zones] == [z.type for z in config.demand.zones]
    assert [z.zone_id for z in arrival.zones] == [row[0] for row in ARRIVAL_MID]


def test_conservazione_dei_modi(arrival: Demand) -> None:
    assert arrival.car_persons == pytest.approx(3490, rel=1e-12)
    assert arrival.transit_persons == pytest.approx(4870, rel=1e-12)
    assert arrival.walk_persons == pytest.approx(1640, rel=1e-12)
    total = arrival.car_persons + arrival.transit_persons + arrival.walk_persons
    assert total == pytest.approx(arrival.persons, rel=1e-12)
    assert sum(z.persons for z in arrival.zones) == pytest.approx(arrival.persons, rel=1e-12)
    for zone in arrival.zones:  # e in ogni zona
        parts = zone.car_persons + zone.transit_persons + zone.walk_persons
        assert parts == pytest.approx(zone.persons, rel=1e-12)


def test_flussi_auto_arrivo(
    arrival: Demand, config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    nodes = world[1]
    zones = {z.id: z for z in config.demand.zones}
    destinations = [node_of(nodes, d.point) for d in config.demand.car_destinations]
    # 10 zone con auto × 5 punti di arrivo (20 % ciascuno); mai da zone metro_gate o arrival_hub
    assert len(destinations) == 5 and len(arrival.flows) == 50
    assert {f.zone_id for f in arrival.flows} == set(ZONES_WITH_CARS)
    assert not {f.zone_id for f in arrival.flows} & {"gate_metro_north", "central_station", "port"}
    east = [f for f in arrival.flows if f.zone_id == "gate_east"]
    east_node = node_of(nodes, zones["gate_east"].centroid)
    assert [(f.origin_node, f.dest_node) for f in east] == [(east_node, d) for d in destinations]
    # 1200 auto-persone / 2,2 = 545,45 veicoli → 1090,9 veic/h, un quinto (218,18) per punto
    assert [f.veh_per_hour for f in east] == pytest.approx([1200 / 2.2 * 2 / 5] * 5, rel=1e-12)
    assert [f.destination_label for f in east] == [
        "Piazza Vittoria",
        "Piazza Sannazaro",
        "Corso Vittorio Emanuele (Via Tasso)",
        "Corso Vittorio Emanuele (Piazzetta Cariati)",
        "Piazza Municipio",
    ]
    assert sum(f.veh_per_hour for f in arrival.flows) == pytest.approx(3490 / 2.2 * 2, rel=1e-12)
    assert arrival.car_veh_per_hour == pytest.approx(3490 / 2.2 * 2, rel=1e-12)


def test_il_deflusso_e_l_inverso_dell_arrivo(
    arrival: Demand, config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    departure = build_demand(make_event(), "mid", "departure", config, world[0])
    # deflusso 18:00-21:00 picco 18:30, fascia 18:30-19:00: 3/10 di 36.000 = 10.800 persone
    assert (departure.band_start, departure.band_end) == (t("18:30"), t("19:00"))
    assert departure.band_share == pytest.approx(0.3, abs=1e-12)
    assert departure.persons == pytest.approx(10800, rel=1e-12)
    assert [(f.zone_id, f.dest_node, f.origin_node) for f in departure.flows] == [
        (f.zone_id, f.origin_node, f.dest_node) for f in arrival.flows
    ]
    for back, there in zip(departure.flows, arrival.flows, strict=True):
        assert back.veh_per_hour == pytest.approx(there.veh_per_hour * 1.08, rel=1e-12)


@pytest.mark.parametrize(("level", "persons"), [("low", 5000), ("mid", 10000), ("high", 20000)])
def test_il_livello_di_affluenza_scala_la_domanda(
    config: EngineConfig,
    world: tuple[nx.MultiDiGraph, NodeMap],
    level: Any,
    persons: float,
) -> None:
    demand = build_demand(make_event(), level, "arrival", config, world[0])
    assert demand.persons == pytest.approx(persons, rel=1e-12)
    assert demand.car_veh_per_hour == pytest.approx(persons * 0.349 / 2.2 * 2, rel=1e-12)


def test_senza_presenze_non_ci_sono_flussi(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    event = make_event(attendance={"low": 0, "mid": 0, "high": 0})
    demand = build_demand(event, "mid", "arrival", config, world[0])
    assert demand.persons == 0 and demand.flows == ()
    assert all(zone.persons == 0 and zone.car_veh_per_hour == 0 for zone in demand.zones)


def test_nessun_flusso_nullo_e_nessun_dato_non_finito(arrival: Demand) -> None:
    assert all(f.veh_per_hour > 0 for f in arrival.flows)


def test_il_risultato_e_deterministico_e_non_dipende_dall_ordine_dei_nodi(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    graph = world[0]
    first = build_demand(make_event(), "mid", "arrival", config, graph)
    assert build_demand(make_event(), "mid", "arrival", config, graph) == first
    shuffled: nx.MultiDiGraph = nx.MultiDiGraph()
    shuffled.add_nodes_from(reversed(list(graph.nodes(data=True))))
    assert build_demand(make_event(), "mid", "arrival", config, shuffled) == first


def test_un_punto_senza_nodi_vicini_e_un_errore(config: EngineConfig) -> None:
    far: nx.MultiDiGraph = nx.MultiDiGraph()
    far.add_node(1, x=0.0, y=0.0)
    with pytest.raises(ResolveError, match="dista .* dal nodo stradale più vicino"):
        build_demand(make_event(), "mid", "arrival", config, far)


# --- l'Evento sostituisce i default --------------------------------------------------------------

A = GeoPoint(lat=40.8300, lon=14.2300, label="A")
B = GeoPoint(lat=40.8400, lon=14.2500, label="B")
D1 = GeoPoint(lat=40.8350, lon=14.2400, label="D1")
D2 = GeoPoint(lat=40.8360, lon=14.2410, label="D2")
D3 = GeoPoint(lat=40.8370, lon=14.2420, label="D3")


def zone_dict(zone_id: str, kind: str, weight: float, point: GeoPoint) -> dict[str, Any]:
    return {
        "id": zone_id,
        "name": zone_id,
        "type": kind,
        "weight_pct": weight,
        "centroid": point.model_dump(),
    }


def test_zone_dell_evento(config: EngineConfig) -> None:
    event = make_event(
        zones_override=[zone_dict("z_a", "far", 60, A), zone_dict("z_b", "road_gate", 40, B)]
    )
    graph, nodes = graph_with_nodes([A, B, *(d.point for d in config.demand.car_destinations)])
    demand = build_demand(event, "mid", "arrival", config, graph)
    # 10.000 persone: z_a 6.000 (far: 30 % auto → 1.800), z_b 4.000 (road_gate: tutte in auto)
    assert [z.zone_id for z in demand.zones] == ["z_a", "z_b"]
    assert demand.zones[0].persons == pytest.approx(6000, rel=1e-12)
    assert demand.zones[0].car_persons == pytest.approx(1800, rel=1e-12)
    assert demand.zones[0].transit_persons == pytest.approx(3600, rel=1e-12)
    assert demand.zones[1].car_persons == pytest.approx(4000, rel=1e-12)
    assert {f.origin_node for f in demand.flows if f.zone_id == "z_b"} == {node_of(nodes, B)}
    assert "zone" in demand.assumptions[-1]


def test_ripartizione_modale_dell_evento_sostituisce_solo_i_tipi_citati(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    event = make_event(
        modal_split_override={"far": {"car_pct": 50, "transit_pct": 40, "walk_pct": 10}}
    )
    demand = build_demand(event, "mid", "arrival", config, world[0])
    by_zone = {z.zone_id: z for z in demand.zones}
    assert by_zone["vomero"].car_persons == pytest.approx(500, rel=1e-12)  # far: 50 % di 1.000
    assert by_zone["vomero"].transit_persons == pytest.approx(400, rel=1e-12)
    assert by_zone["chiaia"].car_persons == pytest.approx(160, rel=1e-12)  # near invariato
    assert by_zone["gate_east"].car_persons == pytest.approx(1200, rel=1e-12)


def test_punti_di_arrivo_dell_evento(config: EngineConfig) -> None:
    event = make_event(
        car_destinations=[
            {"point": D1.model_dump(), "share_pct": 20},
            {"point": D2.model_dump(), "share_pct": 30},
            {"point": D3.model_dump(), "share_pct": 50},
        ]
    )
    graph, nodes = graph_with_nodes([*(z.centroid for z in config.demand.zones), D1, D2, D3])
    demand = build_demand(event, "mid", "arrival", config, graph)
    east = [f for f in demand.flows if f.zone_id == "gate_east"]
    assert [f.dest_node for f in east] == [node_of(nodes, p) for p in (D1, D2, D3)]
    assert [f.veh_per_hour for f in east] == pytest.approx(
        [1200 / 2.2 * 2 * 0.2, 1200 / 2.2 * 2 * 0.3, 1200 / 2.2 * 2 * 0.5], rel=1e-12
    )
    assert len(demand.flows) == 30  # 10 zone con auto × 3 punti


def test_occupazione_auto_dell_evento(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    demand = build_demand(make_event(car_occupancy=4.0), "mid", "arrival", config, world[0])
    east = next(z for z in demand.zones if z.zone_id == "gate_east")
    assert demand.car_occupancy == 4.0
    assert east.car_vehicles == pytest.approx(1200 / 4.0, rel=1e-12)  # 300 veicoli
    assert east.car_veh_per_hour == pytest.approx(600, rel=1e-12)
    assert east.car_persons == pytest.approx(1200, rel=1e-12)  # le persone non cambiano


def test_impostazioni_effettive(config: EngineConfig) -> None:
    plain = effective_demand_inputs(make_event(), config)
    assert plain.zones == tuple(config.demand.zones)
    assert plain.modal_split == config.demand.modal_split_by_type
    assert plain.car_destinations == tuple(config.demand.car_destinations)
    assert plain.car_occupancy == 2.2 and plain.overridden == ()
    event = make_event(
        car_occupancy=3.0,
        modal_split_override={"near": {"car_pct": 0, "transit_pct": 50, "walk_pct": 50}},
    )
    mixed = effective_demand_inputs(event, config)
    assert mixed.car_occupancy == 3.0
    assert mixed.modal_split["near"].car_pct == 0
    assert mixed.modal_split["far"] == config.demand.modal_split_by_type["far"]
    assert mixed.overridden == ("ripartizione modale", "occupazione auto")
    assert dict(plain.modal_split) == dict(config.demand.modal_split_by_type)  # i default intatti


def test_pesi_e_quote_che_non_sommano_a_100_si_normalizzano(config: EngineConfig) -> None:
    """La validazione ammette 100 ± 0,5; la conservazione deve valere comunque."""
    event = make_event(
        zones_override=[zone_dict("z_a", "far", 49.8, A), zone_dict("z_b", "near", 49.8, B)],
        modal_split_override={
            "far": {"car_pct": 20, "transit_pct": 30, "walk_pct": 49.8},
            "near": {"car_pct": 49.9, "transit_pct": 25, "walk_pct": 25},
        },
        car_destinations=[
            {"point": D1.model_dump(), "share_pct": 49.8},
            {"point": D2.model_dump(), "share_pct": 49.8},
        ],
    )
    graph, _ = graph_with_nodes([A, B, D1, D2])
    demand = build_demand(event, "mid", "arrival", config, graph)
    assert sum(z.persons for z in demand.zones) == pytest.approx(10000, rel=1e-12)
    for zone in demand.zones:
        parts = zone.car_persons + zone.transit_persons + zone.walk_persons
        assert parts == pytest.approx(zone.persons, rel=1e-12)
    # z_a: 5.000 persone, auto 20/99,8 → 1.002,004 ; z_b: 5.000, auto 49,9/99,9
    assert demand.zones[0].car_persons == pytest.approx(5000 * 20 / 99.8, rel=1e-12)
    assert demand.zones[1].car_persons == pytest.approx(5000 * 49.9 / 99.9, rel=1e-12)
    assert sum(f.veh_per_hour for f in demand.flows) == pytest.approx(
        demand.car_veh_per_hour, rel=1e-12
    )


# --- provenienza ---------------------------------------------------------------------------------

AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


def test_i_measured_della_domanda(arrival: Demand) -> None:
    measures = demand_measures(arrival, ("run1", "it0"), AS_OF)
    by_id = {m.id: m for m in measures}
    assert len(measures) == len(by_id) == 5 + 13 * 5  # ids univoci
    assert all(m.id.startswith("m.run1.it0.demand.arrival.") for m in measures)
    assert all(m.kind == "estimate" for m in measures)
    assert all(m.source == "engine.demand v1" for m in measures)
    assert all(m.method == "profilo triangolare + ripartizione per tipo zona" for m in measures)
    persons = by_id["m.run1.it0.demand.arrival.persons"]
    assert (persons.unit, persons.as_of) == ("pax", AS_OF)
    assert persons.value == pytest.approx(10000, rel=1e-12)
    assert by_id["m.run1.it0.demand.arrival.car_persons"].value == pytest.approx(3490, rel=1e-12)
    assert by_id["m.run1.it0.demand.arrival.transit_persons"].value == pytest.approx(4870)
    assert by_id["m.run1.it0.demand.arrival.walk_persons"].value == pytest.approx(1640)
    rate = by_id["m.run1.it0.demand.arrival.car_veh_per_hour"]
    assert (rate.unit, rate.value) == ("veic/h", pytest.approx(3490 / 2.2 * 2))
    east = by_id["m.run1.it0.demand.arrival.zone.gate_east.car_veh_per_hour"]
    assert (east.unit, east.value) == ("veic/h", pytest.approx(1200 / 2.2 * 2))
    assert by_id["m.run1.it0.demand.arrival.zone.port.transit_persons"].value == pytest.approx(320)


def test_provenienza_e_assunzioni(arrival: Demand) -> None:
    measure = demand_measures(arrival, ("run1", "it0"), AS_OF)[0]
    assert measure.inputs[0] == "event test_event rev 1"
    assert measure.inputs[1].startswith("engine.yaml sha:") and len(measure.inputs[1]) == 24
    assert "livello di affluenza mid: 36000 persone" in measure.inputs
    assert any("non una previsione" in a for a in measure.assumptions)  # principio 6
    assert any("triangolare tra 12:00 e 15:00, moda alle 13:30" in a for a in measure.assumptions)
    assert any("occupazione auto 2.2" in a for a in measure.assumptions)
    assert any("parcheggi non modellati" in a for a in measure.assumptions)
    assert not any("troncata" in a for a in measure.assumptions)
    assert not any("al posto di quelle di default" in a for a in measure.assumptions)


def test_la_fascia_troncata_e_dichiarata(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    event = make_event(departure={"start": "18:00", "end": "18:50", "peak": "18:40"})
    demand = build_demand(event, "mid", "departure", config, world[0])
    assert (demand.band_start, demand.band_end) == (t("18:40"), t("18:50"))
    # CDF(b) - CDF(c) = 1 - 40/50 = 0,2: il triangolo di base 10 min e altezza 2/50
    assert demand.band_share == pytest.approx(0.2, abs=1e-12)
    assert any(
        "fascia troncata alla fine della finestra (10 minuti)" in a for a in demand.assumptions
    )
    # il flusso orario resta calcolato sui 30 minuti di una fascia intera (02 3)
    assert demand.car_veh_per_hour == pytest.approx(7200 * 0.349 / 2.2 * 2, rel=1e-12)


def test_le_sostituzioni_dell_evento_sono_dichiarate(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    demand = build_demand(make_event(car_occupancy=3.0), "mid", "arrival", config, world[0])
    assert any(
        a == "impostazioni dell'evento al posto di quelle di default: occupazione auto"
        for a in demand.assumptions
    )


# --- i parametri vengono dalla configurazione ----------------------------------------------------


def test_la_durata_della_fascia_viene_dalla_configurazione(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    short = config.model_copy(update={"time_slice_minutes": 15})
    demand = build_demand(make_event(), "mid", "arrival", short, world[0])
    # fascia 13:30-13:45: CDF(13:45) = 1 - 75²/(180·90) = 0,65278 → quota 0,15278 = 11/72
    assert (demand.band_start, demand.band_end) == (t("13:30"), t("13:45"))
    assert demand.band_share == pytest.approx(11 / 72, abs=1e-12)
    assert demand.persons == pytest.approx(5500, rel=1e-12)
    # gate_east: 5.500 · 12 % = 660 auto-persone → 300 veicoli → ×(60/15) = 1.200 veic/h
    east = next(z for z in demand.zones if z.zone_id == "gate_east")
    assert east.car_vehicles == pytest.approx(300, rel=1e-12)
    assert east.car_veh_per_hour == pytest.approx(1200, rel=1e-12)


def test_l_occupazione_di_default_viene_dalla_configurazione(
    config: EngineConfig, world: tuple[nx.MultiDiGraph, NodeMap]
) -> None:
    other = config.model_copy(update={"car_occupancy_default": 1.1})
    demand = build_demand(make_event(), "mid", "arrival", other, world[0])
    east = next(z for z in demand.zones if z.zone_id == "gate_east")
    assert demand.car_occupancy == 1.1
    assert east.car_vehicles == pytest.approx(1200 / 1.1, rel=1e-12)


def test_la_distanza_di_aggancio_viene_dalla_configurazione(config: EngineConfig) -> None:
    decoys_only: nx.MultiDiGraph = nx.MultiDiGraph()
    for i, point in enumerate(default_points(config)):
        decoys_only.add_node(i, x=point.lon, y=point.lat + 0.0004)  # ~44 m dal punto
    near = config.model_copy(update={"node_snap_max_distance_m": 100})
    far = config.model_copy(update={"node_snap_max_distance_m": 10})
    assert build_demand(make_event(), "mid", "arrival", near, decoys_only).flows
    with pytest.raises(ResolveError, match="massimo 10 m"):
        build_demand(make_event(), "mid", "arrival", far, decoys_only)


@pytest.mark.parametrize(("zone_id", "persons", "car", "transit", "walk"), ARRIVAL_MID)
def test_i_measured_di_ogni_zona_hanno_i_valori_della_zona(
    arrival: Demand, zone_id: str, persons: float, car: float, transit: float, walk: float
) -> None:
    by_id = {m.id: m for m in demand_measures(arrival, ("run1", "it0"), AS_OF)}
    base = f"m.run1.it0.demand.arrival.zone.{zone_id}"
    assert by_id[f"{base}.persons"].value == pytest.approx(persons, rel=1e-12)
    assert by_id[f"{base}.car_persons"].value == pytest.approx(car, abs=1e-9)
    assert by_id[f"{base}.transit_persons"].value == pytest.approx(transit, abs=1e-9)
    assert by_id[f"{base}.walk_persons"].value == pytest.approx(walk, abs=1e-9)
    assert by_id[f"{base}.car_veh_per_hour"].value == pytest.approx(car / 2.2 * 2, abs=1e-9)
    assert {by_id[f"{base}.{q}"].unit for q in ("persons", "car_persons")} == {"pax"}
    assert by_id[f"{base}.car_veh_per_hour"].unit == "veic/h"
