import dataclasses
import datetime as dt
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.data.gtfs import GtfsFeed, clear_feed_cache, load_feed, service_day
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.demand import Demand
from app.engine.transit import ResolvedItinerary, ResolvedLeg, TransitNetwork
from app.engine.transit_loads import SectionLoad, assign_transit
from app.engine.transit_measures import apply_transit_measures
from app.engine.transit_metrics import TransitMetrics, _section_rows, transit_metrics
from app.engine.transit_supply import SectionSupply
from app.geo import haversine_m
from app.models.config import EngineConfig, TransitConfig
from app.models.provenance import Measured
from tests.support import make_event
from tests.transit_world import (
    BAND,
    BETA_L1,
    CLASSES,
    GAMMA,
    L1_ALFA_BETA,
    L1_ALFA_GAMMA,
    L6_BETA_EPSILON,
    S6_DAY,
    SLICE,
    WK_DAY,
    demand_of,
    disruption,
    itinerary,
    req,
    write_world_feed,
    zone,
)

AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
PREFIX = ("run1", "it0")


@pytest.fixture(scope="module")
def feed(tmp_path_factory: pytest.TempPathFactory) -> GtfsFeed:
    clear_feed_cache()
    return load_feed(write_world_feed(tmp_path_factory.mktemp("metrics") / "feed"))


@pytest.fixture(scope="module")
def config() -> TransitConfig:
    return EngineConfig.from_yaml().transit


def metrics_of(
    feed: GtfsFeed,
    config: TransitConfig,
    itineraries: dict[str, list[ResolvedItinerary]],
    demand: Demand,
    day: date = WK_DAY,
    *,
    disruptions: list[dict[str, Any]] | None = None,
    requests: tuple[Any, ...] = (),
    network_feed: GtfsFeed | None = None,
) -> TransitMetrics:
    """Le metriche di `transit_metrics` sul pipeline vero: misure → carichi → metriche."""
    network = TransitNetwork(feed, CLASSES, {z: tuple(i) for z, i in itineraries.items()})
    event = make_event(date=day.isoformat(), transit_disruptions=disruptions or [])
    service = service_day(feed.service_dates, event.date)
    applied = apply_transit_measures(
        network, config, service, demand.window, demand.band_start, demand.band_end, requests
    )
    loads = assign_transit(network, config, event, demand, SLICE, applied.suspended, applied.extra)
    shown = dataclasses.replace(network, feed=network_feed or feed)
    return transit_metrics(
        shown, loads, event, demand, measures=applied, id_prefix=PREFIX, as_of=AS_OF
    )


def named(metrics: TransitMetrics) -> dict[str, Measured]:
    """Le metriche per nome: l'id senza `m.run1.it0.transit.<finestra>.`."""
    marker = f".transit.{metrics.window}."
    return {m.id.split(marker, 1)[1]: m for m in metrics.measures}


ITIN_L1 = {"z": [itinerary(L1_ALFA_GAMMA)]}
DEMAND_3000 = demand_of(zone("z", 3000, walk=200))
KINDS = ("metro_line_1", "metro_line_6", "funicular")


# --- id e valori ----------------------------------------------------------------------------------


def test_gli_id_sono_quelli_della_specifica(feed: GtfsFeed, config: TransitConfig) -> None:
    got = metrics_of(feed, config, ITIN_L1, DEMAND_3000)
    assert [m.id for m in got.measures] == [
        f"m.run1.it0.transit.arrival.{name}"
        for name in (
            "stops_overloaded",
            "sections_overloaded",
            *(f"max_section_load.{kind}" for kind in KINDS),
            *(f"trips_in_window.{kind}" for kind in KINDS),
            "itinerary_used.z",
            "walk_people",
        )
    ]


def test_i_valori_dell_arrivo_sono_quelli_calcolati_a_mano(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    got = named(metrics_of(feed, config, ITIN_L1, DEMAND_3000))
    # solo g1 (6000 pax/h su 5000 = 1,2) e solo BETA → GAMMA (6000 su 5000) superano 1
    assert (got["stops_overloaded"].value, got["stops_overloaded"].unit) == (1, "n")
    assert (got["sections_overloaded"].value, got["sections_overloaded"].unit) == (1, "n")
    top = got["max_section_load.metro_line_1"]
    assert (top.value, top.unit) == (pytest.approx(1.2), "rapporto")
    assert "tratta più carica: BETA → GAMMA (linea RL)" in top.assumptions
    for kind in ("metro_line_6", "funicular"):
        empty = got[f"max_section_load.{kind}"]
        assert empty.value == 0.0 and f"nessuna tratta di {kind} ha passeggeri" in empty.assumptions
    # corse dal primo capolinea nella fascia, due direzioni: L1 3 + 2; L6 non ha servizio il 19/12;
    # funicolare TD 08:20 e TE 08:30
    assert [got[f"trips_in_window.{kind}"].value for kind in KINDS] == [5, 0, 2]
    assert all(got[f"trips_in_window.{kind}"].unit == "n" for kind in KINDS)
    assert (got["walk_people"].value, got["walk_people"].unit) == (200, "pax")


def test_il_massimo_dice_chi_riempie_la_tratta_e_l_ipotesi_che_lo_alza(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    got = named(metrics_of(feed, config, ITIN_L1, DEMAND_3000))
    top = got["max_section_load.metro_line_1"]
    # le ipotesi che alzano il numero stanno nel metodo e negli input (in cima al tooltip)
    assert top.method.startswith("massimo di passeggeri/capacità tra le tratte di metro_line_1; ")
    assert "primo itinerario disponibile, senza ripartirsi tra itinerari" in top.method
    assert "né essere limitata dalla capacità" in top.method
    assert top.inputs[-1] == (
        "passeggeri sulla tratta più carica (6000 pax/h su 5000 di capacità, 2 corse nella "
        "fascia), per zona: z 6000 pax/h (100 %, itinerario 1 di 1)"
    )
    # una classe senza passeggeri non ha né l'ipotesi né l'elenco
    empty = got["max_section_load.metro_line_6"]
    assert empty.method == "massimo di passeggeri/capacità tra le tratte di metro_line_6"
    assert empty.inputs == got["walk_people"].inputs


def test_il_massimo_elenca_le_zone_dalla_piu_carica_con_la_quota_e_l_itinerario(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    both = {
        "x": [itinerary(L1_ALFA_GAMMA), itinerary(L1_ALFA_BETA)],
        "y": [itinerary(L6_BETA_EPSILON), itinerary(L1_ALFA_GAMMA), itinerary(L1_ALFA_BETA)],
    }
    got = named(metrics_of(feed, config, both, demand_of(zone("x", 1000), zone("y", 2000))))
    top = got["max_section_load.metro_line_1"]
    # y non può prendere la L6 (nessuna corsa il 19/12): usa il suo secondo itinerario
    assert top.inputs[-1].endswith(
        "per zona: y 4000 pax/h (67 %, itinerario 2 di 3); x 2000 pax/h (33 %, itinerario 1 di 2)"
    )


def test_senza_domanda_tpl_ci_sono_le_metriche_della_rete_e_nessun_itinerario(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    got = named(metrics_of(feed, config, ITIN_L1, demand_of(zone("z", 0, walk=50))))
    assert not [name for name in got if name.startswith("itinerary_used")]
    assert got["stops_overloaded"].value == 0 and got["sections_overloaded"].value == 0
    assert all(got[f"max_section_load.{kind}"].value == 0.0 for kind in KINDS)
    assert got["walk_people"].value == 50
    assert got["trips_in_window.metro_line_1"].value == 5


def test_un_carico_di_esattamente_uno_non_e_sovraccarico(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """2500 persone = 5000 pax/h: BETA → GAMMA e la banchina g1 hanno 5000 pax/h di capacità."""
    got = metrics_of(feed, config, ITIN_L1, demand_of(zone("z", 2500)))
    values = named(got)
    assert values["max_section_load.metro_line_1"].value == pytest.approx(1.0)
    assert values["sections_overloaded"].value == 0 and values["stops_overloaded"].value == 0
    g1 = next(f for f in got.layers["stops"].features if f.id == "g1")
    assert (
        g1.properties["load_ratio"] == pytest.approx(1.0) and g1.properties["overloaded"] is False
    )
    line = next(f for f in got.layers["sections"].features if f.id == "RL:BETA:GAMMA")
    assert line.properties["overloaded"] is False


# --- kind e provenienza ---------------------------------------------------------------------------


def test_kind_delle_metriche(feed: GtfsFeed, config: TransitConfig) -> None:
    got = named(metrics_of(feed, config, ITIN_L1, DEMAND_3000))
    # la data è nel feed: le corse sono reali; i carichi sono stime
    assert {name: m.kind for name, m in got.items() if name.startswith("trips_in_window")} == {
        f"trips_in_window.{kind}": "real" for kind in KINDS
    }
    assert {m.kind for name, m in got.items() if not name.startswith("trips_in_window")} == {
        "estimate"
    }


def test_con_l_orario_tipo_le_corse_sono_una_stima(feed: GtfsFeed, config: TransitConfig) -> None:
    """Il 9/1/2027 (un sabato) il feed non c'è: vale l'orario tipo del sabato 19/12/2026."""
    got = named(metrics_of(feed, config, ITIN_L1, DEMAND_3000, day=date(2027, 1, 9)))
    trips = got["trips_in_window.metro_line_1"]
    assert (trips.kind, trips.value) == ("estimate", 5)
    assert any("orario tipo del 19/12/2026" in a for a in trips.assumptions)
    # il giorno di servizio è quello del feed, non la data dell'Evento
    assert all(any("giorno di servizio 19/12/2026" in i for i in x.inputs) for x in got.values())


def test_le_corse_aggiunte_da_una_misura_sono_simulate_solo_per_la_loro_classe(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """add_runs n=2 sulla L1: 2 percorsi (andata e ritorno) × 2 corse nella fascia → 5 + 4."""
    request = req("a1", "add_runs", "metro_line_1", payload={"n": 2})
    got = named(metrics_of(feed, config, ITIN_L1, DEMAND_3000, requests=(request,)))
    assert (
        got["trips_in_window.metro_line_1"].kind,
        got["trips_in_window.metro_line_1"].value,
    ) == (
        "simulated",
        9,
    )
    assert got["trips_in_window.funicular"].kind == "real"
    assert got["trips_in_window.metro_line_6"].kind == "real"
    # più corse: la capacità sale e il carico massimo scende sotto 1,2
    assert float(got["max_section_load.metro_line_1"].value) < 1.2
    assert any("add_runs metro_line_1" in a for a in got["sections_overloaded"].assumptions)


def test_ogni_misura_ha_provenienza_completa(feed: GtfsFeed, config: TransitConfig) -> None:
    got = metrics_of(feed, config, ITIN_L1, DEMAND_3000)
    ids = [m.id for m in got.measures]
    assert len(ids) == len(set(ids))
    for m in got.measures:
        assert m.source == "engine.transit v1"
        assert m.as_of == AS_OF
        assert m.method.strip()
        assert STATIC_MODEL_ASSUMPTION in m.assumptions
        assert len(m.assumptions) == len(set(m.assumptions))
        assert "prova" in m.inputs  # gli input della domanda
        assert any(i.startswith("feed GTFS feed: validità 19/12/2026–20/12/2026") for i in m.inputs)
        assert any("giorno di servizio 19/12/2026" in i for i in m.inputs)


def test_le_assunzioni_di_domanda_e_carichi_arrivano_a_ogni_misura(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    demand = dataclasses.replace(DEMAND_3000, assumptions=("assunzione della domanda",))
    got = metrics_of(feed, config, ITIN_L1, demand)
    for m in got.measures:
        assert "assunzione della domanda" in m.assumptions
        assert any(
            a.startswith("domanda TPL = persone della fascia di picco") for a in m.assumptions
        )


# --- itinerari ------------------------------------------------------------------------------------


def test_l_itinerario_dell_arrivo_si_legge_da_salita_a_discesa(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    both = {"z": [itinerary(L1_ALFA_BETA, L6_BETA_EPSILON, walk=True)]}
    got = named(metrics_of(feed, config, both, demand_of(zone("z", 100)), day=S6_DAY))
    used = got["itinerary_used.z"]
    assert (used.unit, used.kind) == ("testo", "estimate")
    assert used.value == (
        "itinerario 1: ALFA → BETA (metro_line_1), BETA → EPSILON (metro_line_6), poi a piedi"
    )
    assert "zona z: 100 persone TPL nella fascia di picco" in used.assumptions


def test_nel_deflusso_l_itinerario_si_legge_al_contrario(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """Due tratte della L1 (ALFA → BETA, BETA → GAMMA): nel deflusso si parte da GAMMA."""
    legs = itinerary(L1_ALFA_BETA, ResolvedLeg("metro_line_1", BETA_L1, GAMMA))
    demand = demand_of(zone("z", 100), window="departure")
    got = named(metrics_of(feed, config, {"z": [legs]}, demand))
    assert got["itinerary_used.z"].value == (
        "itinerario 1: GAMMA → BETA (metro_line_1), BETA → ALFA (metro_line_1)"
    )


def test_senza_corse_di_ritorno_l_itinerario_del_deflusso_non_c_e(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """La L6 del mondo di prova ha corse solo da BETA a EPSILON: nel deflusso va sul bus."""
    both = {"z": [itinerary(L6_BETA_EPSILON)]}
    demand = demand_of(zone("z", 100), window="departure")
    used = named(metrics_of(feed, config, both, demand, day=S6_DAY))["itinerary_used.z"]
    assert used.value == "autobus"
    assert "itinerario 1: senza corse nella fascia (metro_line_6)" in used.assumptions


def test_gli_itinerari_scartati_sono_tra_le_assunzioni(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """Il 19/12 la L6 non ha corse: l'itinerario 1 manca e vale il 2."""
    both = {"z": [itinerary(L6_BETA_EPSILON), itinerary(L1_ALFA_BETA)]}
    used = named(metrics_of(feed, config, both, demand_of(zone("z", 100))))["itinerary_used.z"]
    assert used.value == "itinerario 2: ALFA → BETA (metro_line_1)"
    assert "itinerario 1: senza corse nella fascia (metro_line_6)" in used.assumptions


@pytest.mark.parametrize(
    ("itineraries", "band", "text"),
    [
        ({"z": [itinerary()]}, BAND, "a piedi (itinerario 1)"),
        ({"z": []}, BAND, "autobus"),
        ({"z": []}, (dt.time(12, 0), dt.time(12, 30)), "non servita (nessun autobus nelle fermate"),
    ],
)
def test_le_zone_a_piedi_sul_bus_o_non_servite(
    feed: GtfsFeed,
    config: TransitConfig,
    itineraries: dict[str, list[ResolvedItinerary]],
    band: tuple[dt.time, dt.time],
    text: str,
) -> None:
    got = named(metrics_of(feed, config, itineraries, demand_of(zone("z", 100), band=band)))
    assert got["itinerary_used.z"].value.startswith(text)  # type: ignore[union-attr]


def test_un_itinerario_a_piedi_conta_tra_i_pedoni(feed: GtfsFeed, config: TransitConfig) -> None:
    got = named(metrics_of(feed, config, {"z": [itinerary()]}, demand_of(zone("z", 100, walk=30))))
    assert got["walk_people"].value == 130


# --- fermate chiuse -------------------------------------------------------------------------------


def test_una_fermata_sospesa_toglie_l_itinerario_e_non_conta_tra_le_sovraccariche(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """g1 sospesa: l'itinerario non c'è, 3000 persone = 6000 pax/h vanno sul bus. u1 ha 360 pax/h
    di capacità e 6000 × 360/540 = 4000 pax/h, u2 180 e 2000: carico 11,1 per tutte e due."""
    request = req("s1", "stop_suspension", "g1")
    got = metrics_of(feed, config, ITIN_L1, DEMAND_3000, requests=(request,))
    values = named(got)
    assert values["stops_overloaded"].value == 2  # u1 e u2, non g1
    assert values["sections_overloaded"].value == 0
    used = values["itinerary_used.z"]
    assert used.value == "autobus"
    assert "itinerario 1: fermata indisponibile (GAMMA)" in used.assumptions
    assert any("stop_suspension g1" in a for a in used.assumptions)
    stops = {f.id: f.properties for f in got.layers["stops"].features}
    assert stops["g1"]["closed"] is True and stops["g1"]["load_ratio"] is None
    assert stops["g1"]["overloaded"] is False
    assert stops["u1"]["load_ratio"] == pytest.approx(4000 / 360)
    assert stops["u1"]["closed"] is False


def test_un_interruzione_dell_evento_vale_come_una_sospensione(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    got = metrics_of(feed, config, ITIN_L1, DEMAND_3000, disruptions=[disruption("GAMMA", "g1")])
    stops = {f.id: f.properties for f in got.layers["stops"].features}
    assert stops["g1"]["closed"] is True and stops["g2"]["closed"] is False


# --- layer ----------------------------------------------------------------------------------------


def test_il_layer_delle_fermate_ha_le_fermate_vicine_con_il_loro_carico(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    layer = metrics_of(feed, config, ITIN_L1, DEMAND_3000).layers["stops"]
    assert layer.type == "FeatureCollection"
    # entro 800 m dal centro: le due banchine di GAMMA, m2, u1, u2 e le due di D UNO
    assert {f.id for f in layer.features} == {"g1", "g2", "m2", "u1", "u2", "d5", "d6"}
    g1 = next(f for f in layer.features if f.id == "g1")
    assert g1.geometry == {"type": "Point", "coordinates": [14.235, 40.834]}
    assert g1.properties == {
        "stop_id": "g1",
        "name": "GAMMA",
        "load_ratio": pytest.approx(1.2),
        "overloaded": True,
        "closed": False,
        "pax_h": 6000,
        "capacity_pax_h": 5000,
    }
    g2 = next(f for f in layer.features if f.id == "g2")
    assert g2.properties["pax_h"] == 0 and g2.properties["load_ratio"] == 0.0
    # m2 non ha corse il 19/12: nessuna capacità, nessun rapporto
    m2 = next(f for f in layer.features if f.id == "m2")
    assert m2.properties["load_ratio"] is None and m2.properties["overloaded"] is False


def test_il_layer_delle_tratte_ha_tutte_le_tratte_di_metro_e_funicolare(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    layer = metrics_of(feed, config, ITIN_L1, DEMAND_3000).layers["sections"]
    by_id = {f.id: f for f in layer.features}
    assert set(by_id) == {
        "RL:ALFA:BETA",
        "RL:BETA:GAMMA",
        "RL:GAMMA:BETA",
        "RL:BETA:ALFA",
        "RD:D UNO:D DUE",
        "RD:D DUE:D UNO",
    }
    loaded = by_id["RL:BETA:GAMMA"]
    assert loaded.geometry == {
        "type": "LineString",
        "coordinates": [[14.3, 40.9], [14.235, 40.834]],
    }
    assert loaded.properties == {
        "route_id": "RL",
        "route_class": "metro_line_1",
        "label": "BETA → GAMMA",
        "trips": 2,
        "capacity_pax_h": 5000,
        "pax_h": 6000,
        "load_ratio": pytest.approx(1.2),
        "overloaded": True,
    }
    # una tratta senza passeggeri ma con corse ha carico 0, non assente
    idle = by_id["RL:GAMMA:BETA"].properties
    assert (idle["pax_h"], idle["load_ratio"], idle["overloaded"]) == (0, 0.0, False)


def test_una_tratta_senza_corse_ha_il_carico_nullo_non_zero(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """Nella fascia 08:36–08:45 ALFA → BETA ha una corsa (T3 da ALFA alle 08:40) e BETA → GAMMA
    nessuna (T2 parte da BETA alle 08:35, T3 alle 08:45 = fine, esclusa)."""
    band = (dt.time(8, 36), dt.time(8, 45))
    layer = metrics_of(feed, config, {}, demand_of(band=band)).layers["sections"]
    props = {f.id: f.properties for f in layer.features}
    assert props["RL:BETA:GAMMA"]["trips"] == 0 and props["RL:BETA:GAMMA"]["load_ratio"] is None
    assert props["RL:ALFA:BETA"]["trips"] == 1 and props["RL:ALFA:BETA"]["load_ratio"] == 0.0


def test_il_segmento_di_una_tratta_va_dal_centro_delle_banchine(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """D DUE → D UNO arriva alle banchine d5 e d6: il segmento finisce a metà tra le due."""
    stops = feed.stops.copy()
    stops.loc[stops["stop_id"] == "d6", ["lat", "lon"]] = [40.8334, 14.2364]
    moved = dataclasses.replace(feed, stops=stops)
    layer = metrics_of(feed, config, {}, demand_of(), network_feed=moved).layers["sections"]
    line = next(f for f in layer.features if f.id == "RD:D DUE:D UNO")
    assert line.geometry == {
        "type": "LineString",
        "coordinates": [[14.3, 40.9], [14.2362, 40.8332]],
    }


def test_l_area_dell_evento_e_un_cerchio_chiuso_del_raggio_giusto(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    area = metrics_of(feed, config, ITIN_L1, DEMAND_3000).layers["event_area"].features
    assert len(area) == 1 and area[0].id == "event_area"
    event = make_event()
    assert area[0].properties == {
        "label": event.area_center.label,
        "radius_m": event.area_radius_m,
    }
    geometry = area[0].geometry
    assert geometry is not None and geometry["type"] == "Polygon"
    ring = cast(list[list[float]], cast(list[Any], geometry["coordinates"])[0])
    assert ring[0] == ring[-1] and len(ring) == 49
    for lon, lat in ring:
        distance = float(haversine_m(lat, lon, (event.area_center.lat, event.area_center.lon)))
        assert distance == pytest.approx(event.area_radius_m, abs=1.0)


# --- le tratte con passeggeri ---------------------------------------------------------------------


def test_le_tratte_con_passeggeri_sono_per_classe_e_dal_carico_piu_alto(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """Un interscambio il 20/12: ALFA → BETA sulla L1 (0,8 con 3000 persone) e BETA → EPSILON
    sulla L6 (2 corse × 290 × 2 = 1160 pax/h): la classe viene prima del carico."""
    both = {"z": [itinerary(L1_ALFA_BETA, L6_BETA_EPSILON)]}
    rows = metrics_of(feed, config, both, demand_of(zone("z", 3000)), day=S6_DAY).sections
    assert [(r.route_class, r.from_name, r.to_name) for r in rows] == [
        ("metro_line_1", "ALFA", "BETA"),
        ("metro_line_6", "BETA", "EPSILON"),
    ]
    l1, l6 = rows
    assert (l1.pax_h, l1.capacity_pax_h, l1.trips) == (6000, 7500, 3)
    assert l1.load_ratio == pytest.approx(0.8)
    assert (l6.pax_h, l6.capacity_pax_h, l6.trips) == (6000, 1160, 2)
    assert l6.load_ratio == pytest.approx(6000 / 1160)


def test_a_pari_carico_le_tratte_sono_in_ordine_di_linea_e_di_stazione() -> None:
    def load(route_id: str, to_name: str) -> SectionLoad:
        section = SectionSupply(
            route_id, "funicular", "A", to_name, frozenset({"a"}), frozenset({"b"}), 2, 500.0
        )
        return SectionLoad(section, 250.0, 0.5)

    sections = {
        ("R2", "a", "z"): load("R2", "Z"),
        ("R1", "a", "z"): load("R1", "Z"),
        ("R1", "a", "b"): load("R1", "B"),
    }
    rows = _section_rows(SimpleNamespace(sections=sections))  # type: ignore[arg-type]
    assert [(r.route_id, r.to_name) for r in rows] == [("R1", "B"), ("R1", "Z"), ("R2", "Z")]


def test_nella_stessa_classe_prima_la_tratta_piu_carica(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    rows = metrics_of(feed, config, ITIN_L1, DEMAND_3000).sections
    assert [(r.from_name, r.to_name) for r in rows] == [("BETA", "GAMMA"), ("ALFA", "BETA")]
