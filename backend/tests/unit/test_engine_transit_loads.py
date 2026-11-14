import datetime as dt
from datetime import date
from typing import Any

import pytest

from app.data.gtfs import GtfsFeed, RouteClasses, ServiceDay, clear_feed_cache, load_feed
from app.engine.transit import (
    DisruptionError,
    ResolvedLeg,
)
from app.engine.transit_loads import TransitLoads, leg_path
from app.engine.transit_supply import build_supply
from app.geo import haversine_m
from app.models.config import EngineConfig, TransitConfig
from tests.support import write_gtfs
from tests.transit_world import (
    BAND,
    CLASSES,
    D_DUE,
    D_UNO,
    L1_ALFA_BETA,
    L1_ALFA_GAMMA,
    L6_BETA_EPSILON,
    S6_DAY,
    SLICE,
    WK_DAY,
    demand_of,
    disruption,
    itinerary,
    station,
    write_world_feed,
    zone,
)
from tests.transit_world import (
    run_loads as run,
)


@pytest.fixture(scope="module")
def feed(tmp_path_factory: pytest.TempPathFactory) -> GtfsFeed:
    clear_feed_cache()
    return load_feed(write_world_feed(tmp_path_factory.mktemp("loads") / "feed"))


@pytest.fixture(scope="module")
def config() -> TransitConfig:
    return EngineConfig.from_yaml().transit


def by_zone(loads: TransitLoads) -> dict[str, Any]:
    return {z.zone_id: z for z in loads.zones}


def stop(loads: TransitLoads, stop_id: str) -> Any:
    return next(s for s in loads.stops if s.stop.stop_id == stop_id)


# --- itinerario, tratte e banchina ----------------------------------------------------------------


def test_un_itinerario_carica_ogni_tratta_e_la_banchina_dell_area(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand_of(zone("z", 1000)))
    assert by_zone(loads)["z"].mode == "itinerary" and by_zone(loads)["z"].itinerary == 1
    assert (by_zone(loads)["z"].persons, by_zone(loads)["z"].pax_h) == (1000, 2000)
    # ALFA → BETA 3 corse × 1.250 × 2 = 7.500; BETA → GAMMA 2 corse = 5.000
    first, second = loads.sections[("RL", "ALFA", "BETA")], loads.sections[("RL", "BETA", "GAMMA")]
    assert (first.pax_h, first.section.capacity_pax_h) == (2000, 7500)
    assert first.load_ratio == pytest.approx(2000 / 7500)
    assert (second.pax_h, second.section.capacity_pax_h) == (2000, 5000)
    assert second.load_ratio == pytest.approx(0.4)
    assert set(loads.sections) == {("RL", "ALFA", "BETA"), ("RL", "BETA", "GAMMA")}
    # si scende alla banchina g1 (andata): 2 corse chiamano a g1 nella fascia → 5.000 pax/h
    arrival = stop(loads, "g1")
    assert (arrival.pax_h, arrival.stop.capacity_pax_h) == (2000, 5000)
    assert arrival.load_ratio == pytest.approx(0.4)
    assert stop(loads, "g2").pax_h == 0  # l'altra banchina non riceve nessuno


def test_nel_deflusso_si_percorre_al_contrario_e_si_sale_dal_lato_dell_area(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    demand = demand_of(zone("z", 1000), window="departure")
    loads = run(feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand)
    assert set(loads.sections) == {("RL", "GAMMA", "BETA"), ("RL", "BETA", "ALFA")}
    assert loads.sections[("RL", "GAMMA", "BETA")].section.capacity_pax_h == 5000  # 2 corse
    # si sale alla banchina g2 (ritorno), 2 corse chiamano a g2 → 5.000 pax/h
    boarding = stop(loads, "g2")
    assert (boarding.pax_h, boarding.stop.capacity_pax_h) == (2000, 5000)
    assert stop(loads, "g1").pax_h == 0


def test_le_persone_di_piu_zone_si_sommano_sulla_stessa_tratta(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    both = {"x": [itinerary(L1_ALFA_BETA)], "y": [itinerary(L1_ALFA_GAMMA)]}
    loads = run(feed, config, both, demand_of(zone("x", 100), zone("y", 400)))
    assert loads.sections[("RL", "ALFA", "BETA")].pax_h == (100 + 400) * 2
    assert loads.sections[("RL", "BETA", "GAMMA")].pax_h == 400 * 2


def test_ogni_tratta_sa_da_quali_zone_viene_il_suo_carico(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    both = {"x": [itinerary(L1_ALFA_BETA)], "y": [itinerary(L1_ALFA_GAMMA)]}
    loads = run(feed, config, both, demand_of(zone("x", 100), zone("y", 400)))
    # dalla zona che porta più passeggeri; la somma delle zone è il carico della tratta
    assert loads.sections[("RL", "ALFA", "BETA")].by_zone == (("y", 800.0), ("x", 200.0))
    assert loads.sections[("RL", "BETA", "GAMMA")].by_zone == (("y", 800.0),)
    for load in loads.sections.values():
        assert sum(pax for _, pax in load.by_zone) == pytest.approx(load.pax_h)


def test_a_pari_passeggeri_le_zone_sono_in_ordine_di_nome(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    both = {"b": [itinerary(L1_ALFA_BETA)], "a": [itinerary(L1_ALFA_BETA)]}
    loads = run(feed, config, both, demand_of(zone("b", 100), zone("a", 100)))
    assert loads.sections[("RL", "ALFA", "BETA")].by_zone == (("a", 200.0), ("b", 200.0))


def test_un_interscambio_carica_le_tratte_di_tutte_e_due_le_linee(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    config_itin = {"z": [itinerary(L1_ALFA_BETA, L6_BETA_EPSILON)]}
    loads = run(feed, config, config_itin, demand_of(zone("z", 300)), day=S6_DAY)
    assert set(loads.sections) == {("RL", "ALFA", "BETA"), ("RS", "BETA", "EPSILON")}
    assert loads.sections[("RS", "BETA", "EPSILON")].pax_h == 600
    # L6: 2 corse × 290 × 2 = 1.160; si scende a m2 (vicino), dove chiama 1 corsa: 580 pax/h
    assert loads.sections[("RS", "BETA", "EPSILON")].section.capacity_pax_h == 1160
    last = stop(loads, "m2")
    assert (last.pax_h, last.stop.capacity_pax_h) == (600, 580)
    assert last.load_ratio == pytest.approx(600 / 580)


def test_piu_banchine_dal_lato_dell_area_si_dividono_i_passeggeri(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """TE arriva a D UNO fermandosi a d5 e d6 (due banchine): 100 persone = 200 pax/h, 100 e 100."""
    leg = ResolvedLeg("funicular", D_DUE, D_UNO)
    loads = run(feed, config, {"z": [itinerary(leg)]}, demand_of(zone("z", 100)))
    assert (stop(loads, "d5").pax_h, stop(loads, "d6").pax_h) == (100, 100)
    # d5 e d6 hanno una corsa ciascuna (08:31, 08:32) × 250 × 2
    assert stop(loads, "d5").stop.capacity_pax_h == 500
    assert stop(loads, "d5").load_ratio == pytest.approx(0.2)
    assert loads.sections[("RD", "D DUE", "D UNO")].pax_h == 200


def test_le_linee_che_il_modello_non_considera_non_danno_capacita(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """X1 (la L2) passa da u1 alle 08:22: u1 resta a 2 corse di autobus."""
    loads = run(feed, config, {}, demand_of(zone("z", 1)))
    assert stop(loads, "u1").stop.trips == 2


# --- disponibilità e ordine -----------------------------------------------------------------------


def test_si_sceglie_il_primo_itinerario_disponibile(feed: GtfsFeed, config: TransitConfig) -> None:
    """Il giorno 19/12 la L6 non ha corse: l'itinerario 1 (L6) non c'è, vale il 2."""
    both = [itinerary(L6_BETA_EPSILON), itinerary(L1_ALFA_BETA, walk=True)]
    loads = run(feed, config, {"z": both}, demand_of(zone("z", 100)))
    assert (by_zone(loads)["z"].mode, by_zone(loads)["z"].itinerary) == ("itinerary", 2)
    assert by_zone(loads)["z"].skipped == ("itinerario 1: senza corse nella fascia (metro_line_6)",)
    assert set(loads.sections) == {("RL", "ALFA", "BETA")}
    # il 20/12 la L6 c'è: vale il 1
    with_l6 = run(feed, config, {"z": both}, demand_of(zone("z", 100)), day=S6_DAY)
    assert by_zone(with_l6)["z"].itinerary == 1
    assert set(with_l6.sections) == {("RS", "BETA", "EPSILON")}


def test_una_tratta_senza_corse_nella_fascia_rende_indisponibile_l_itinerario(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """Nella fascia 08:36–08:45 ALFA → BETA ha una corsa (T3, da ALFA alle 08:40) ma BETA → GAMMA
    nessuna (T2 parte da BETA alle 08:35, T3 alle 08:45 = fine, esclusa): non basta che la linea
    abbia corse, deve averle ogni tratta del percorso."""
    band = (dt.time(8, 36), dt.time(8, 45))
    loads = run(
        feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand_of(zone("z", 100), band=band)
    )
    assert by_zone(loads)["z"].mode == "unserved"  # niente itinerario e niente bus in quella fascia


def test_la_zona_senza_itinerari_o_non_in_elenco_va_sul_bus(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(feed, config, {"vuota": []}, demand_of(zone("vuota", 100), zone("nuova", 50)))
    assert {z.mode for z in loads.zones} == {"bus"}
    assert all(z.itinerary is None for z in loads.zones)


# --- domanda bus ----------------------------------------------------------------------------------


def test_la_domanda_bus_si_ripartisce_in_proporzione_alla_capacita(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """300 persone = 600 pax/h. u1: 2 corse × 90 × 2 = 360; u2: 1 corsa = 180; u3 è lontana."""
    loads = run(feed, config, {}, demand_of(zone("z", 300)))
    assert loads.bus_persons == 300 and loads.unserved_persons == 0
    u1, u2 = stop(loads, "u1"), stop(loads, "u2")
    assert (u1.stop.capacity_pax_h, u2.stop.capacity_pax_h) == (360, 180)
    assert u1.pax_h == pytest.approx(600 * 360 / 540) and u1.bus_pax_h == u1.pax_h
    assert u2.pax_h == pytest.approx(600 * 180 / 540)
    assert u1.load_ratio == pytest.approx(u2.load_ratio or 0) == pytest.approx(600 / 540)
    assert "u3" not in {s.stop.stop_id for s in loads.stops}


def test_senza_corse_di_autobus_la_domanda_bus_non_e_servita(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    band = (dt.time(12, 0), dt.time(12, 30))
    loads = run(feed, config, {}, demand_of(zone("z", 300), band=band))
    assert (loads.bus_persons, loads.unserved_persons) == (0, 300)
    assert by_zone(loads)["z"].mode == "unserved"
    assert all(s.pax_h == 0 and s.load_ratio is None for s in loads.stops)
    assert any("domanda bus non servita" in a for a in loads.assumptions)


# --- fermate vicine -------------------------------------------------------------------------------


def test_il_raggio_delle_fermate_vicine_e_inclusivo(feed: GtfsFeed, config: TransitConfig) -> None:
    demand = demand_of(zone("z", 100))
    distance = stop(run(feed, config, {}, demand), "g1").stop.distance_m
    assert 200 < distance < 250  # 0,002° di latitudine
    exact = config.model_copy(update={"stop_radius_m": distance})
    just_under = config.model_copy(update={"stop_radius_m": distance - 1e-6})
    assert "g1" in {s.stop.stop_id for s in run(feed, exact, {}, demand).stops}
    assert "g1" not in {s.stop.stop_id for s in run(feed, just_under, {}, demand).stops}


def test_le_fermate_vicine_sono_in_ordine_di_distanza_con_la_loro_offerta(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(feed, config, {}, demand_of(zone("z", 100)))
    # m2 è vicina anche se quel giorno non ha corse (la L6 è del servizio S6): offerta 0
    assert [s.stop.stop_id for s in loads.stops] == ["u1", "m2", "u2", "d5", "d6", "g1", "g2"]
    assert [round(s.stop.distance_m) for s in loads.stops] == [56, 111, 111, 139, 139, 222, 222]
    assert [s.stop.trips for s in loads.stops] == [2, 0, 1, 1, 1, 2, 2]
    # il bus ha 90 posti, la funicolare 250, la metro 1.250: u1 2 corse × 90 × 2, g1 2 × 1.250 × 2
    assert [s.stop.capacity_pax_h for s in loads.stops] == [360, 0, 180, 500, 500, 5000, 5000]
    assert [s.stop.bus_capacity_pax_h for s in loads.stops] == [360, 0, 180, 0, 0, 0, 0]


# --- pedoni ---------------------------------------------------------------------------------------


def test_i_pedoni_sono_il_modo_a_piedi_piu_gli_itinerari_senza_tratte(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(
        feed,
        config,
        {"z": [itinerary(walk=True)]},
        demand_of(zone("z", 50, walk=10), zone("w", 0, 25)),
    )
    assert by_zone(loads)["z"].mode == "walk" and by_zone(loads)["z"].itinerary == 1
    assert loads.walk_persons == 10 + 25 + 50
    assert not loads.sections and all(s.pax_h == 0 for s in loads.stops)


def test_le_zone_senza_domanda_tpl_non_compaiono(feed: GtfsFeed, config: TransitConfig) -> None:
    loads = run(feed, config, {}, demand_of(zone("solo_piedi", 0, 40), zone("z", 20)))
    assert [z.zone_id for z in loads.zones] == ["z"]
    assert loads.walk_persons == 40


# --- conservazione e provenienza ------------------------------------------------------------------


@pytest.mark.parametrize("day", [WK_DAY, S6_DAY])
@pytest.mark.parametrize("window", ["arrival", "departure"])
def test_conservazione_dei_passeggeri(
    feed: GtfsFeed, config: TransitConfig, day: date, window: str
) -> None:
    """Itinerari + bus + a piedi + non serviti = domanda TPL; i passeggeri dei bus sulle fermate
    sono quelli dei bus; quelli in discesa/salita alle fermate vicine non superano gli itinerari."""
    itineraries = {
        "a": [itinerary(L1_ALFA_GAMMA)],
        "b": [itinerary(L6_BETA_EPSILON), itinerary(L1_ALFA_BETA, walk=True)],
        "c": [itinerary(L6_BETA_EPSILON), itinerary(walk=True)],
        "d": [],
    }
    zones = (
        zone("a", 1000),
        zone("b", 300),
        zone("c", 50),
        zone("d", 200),
        zone("e", 70),
        zone("f", 0, 9),
    )
    demand = demand_of(*zones, window=window)
    loads = run(feed, config, itineraries, demand, day=day)
    total = sum(z.persons for z in loads.zones)
    assert total == pytest.approx(demand.transit_persons) == pytest.approx(1620)
    by_mode: dict[str, float] = {}
    for z in loads.zones:
        by_mode[z.mode] = by_mode.get(z.mode, 0) + z.persons
        assert z.pax_h == pytest.approx(z.persons * 2)
    assert by_mode.get("bus", 0) == pytest.approx(loads.bus_persons)
    assert by_mode.get("unserved", 0) == pytest.approx(loads.unserved_persons)
    assert loads.walk_persons == pytest.approx(9 + by_mode.get("walk", 0))
    bus_on_stops = sum(s.bus_pax_h for s in loads.stops)
    assert bus_on_stops == pytest.approx(loads.bus_persons * 2)
    ridden = sum(z.pax_h for z in loads.zones if z.mode == "itinerary")
    assert sum(s.pax_h for s in loads.stops) <= ridden + bus_on_stops + 1e-9


def test_stessi_input_stesso_risultato(feed: GtfsFeed, config: TransitConfig) -> None:
    itineraries = {"a": [itinerary(L1_ALFA_GAMMA)], "b": []}
    demand = demand_of(zone("a", 100), zone("b", 100))
    first = run(feed, config, itineraries, demand)
    second = run(feed, config, itineraries, demand)
    assert first == second
    assert list(first.sections) == sorted(first.sections)
    assert [s.stop.distance_m for s in first.stops] == sorted(
        s.stop.distance_m for s in first.stops
    )


def test_assunzioni_e_offerta_di_origine(feed: GtfsFeed, config: TransitConfig) -> None:
    loads = run(feed, config, {}, demand_of(zone("z", 100)))
    assert loads.supply.kind == "real"  # il 19/12/2026 è dentro il feed
    assert loads.assumptions[: len(loads.supply.assumptions)] == loads.supply.assumptions
    text = " | ".join(loads.assumptions)
    assert "primo disponibile" in text and "entro 800 m" in text and "bus: 90 pax per corsa" in text


# --- percorsi -------------------------------------------------------------------------------------


def supply_of(feed: GtfsFeed, config: TransitConfig, day: date = S6_DAY) -> Any:
    service = ServiceDay(day, day, feed.service_dates[day], covered=True)
    return build_supply(feed, CLASSES, config, service, *BAND, SLICE)


def test_percorso_di_una_tratta(feed: GtfsFeed, config: TransitConfig) -> None:
    supply = supply_of(feed, config)
    assert leg_path(supply, L1_ALFA_GAMMA, reverse=False) == [
        ("RL", "ALFA", "BETA"),
        ("RL", "BETA", "GAMMA"),
    ]
    assert leg_path(supply, L1_ALFA_GAMMA, reverse=True) == [
        ("RL", "GAMMA", "BETA"),
        ("RL", "BETA", "ALFA"),
    ]
    assert leg_path(supply, L6_BETA_EPSILON, reverse=False) == [("RS", "BETA", "EPSILON")]


def test_nessun_percorso_se_la_linea_non_va_in_quel_senso_o_non_c_e(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    supply = supply_of(feed, config)
    assert leg_path(supply, L6_BETA_EPSILON, reverse=True) is None  # la L6 di prova è solo andata
    assert leg_path(supply_of(feed, config, WK_DAY), L6_BETA_EPSILON, reverse=False) is None


def test_il_percorso_resta_nella_classe_della_tratta() -> None:
    """Due linee di classi diverse con la stessa banchina: la tratta L6 non prende quella L1."""
    from app.engine.transit_supply import SectionSupply, TransitSupply

    def section_of(route: str, kind: Any) -> SectionSupply:
        return SectionSupply(route, kind, "A", "B", frozenset({"x"}), frozenset({"y"}), 1, 10.0)

    sections = {
        ("R1", "A", "B"): section_of("R1", "metro_line_1"),
        ("R2", "A", "B"): section_of("R2", "metro_line_6"),
    }
    supply = TransitSupply(
        ServiceDay(WK_DAY, WK_DAY, frozenset({"WK"}), covered=True), *BAND, SLICE, sections, {}, ()
    )
    leg = ResolvedLeg("metro_line_6", station("A", "x"), station("B", "y"))
    assert leg_path(supply, leg, reverse=False) == [("R2", "A", "B")]


# --- fermate indisponibili (03 3.3) --------------------------------------------------------------


def test_la_discesa_chiusa_rende_indisponibile_l_itinerario_e_si_passa_al_successivo(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    both = [itinerary(L1_ALFA_GAMMA), itinerary(L1_ALFA_BETA, walk=True)]
    loads = run(
        feed, config, {"z": both}, demand_of(zone("z", 100)),
        disruptions=[disruption("GAMMA", "g1", "g2")],
    )  # fmt: skip
    z = by_zone(loads)["z"]
    assert (z.mode, z.itinerary) == ("itinerary", 2)
    assert z.skipped == ("itinerario 1: fermata indisponibile (GAMMA)",)
    assert loads.closed_stops == frozenset({"g1", "g2"})
    assert set(loads.sections) == {("RL", "ALFA", "BETA")}


def test_anche_la_salita_chiusa_rende_indisponibile_l_itinerario(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(
        feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand_of(zone("z", 100)),
        disruptions=[disruption("ALFA", "a1", "a2")],
    )  # fmt: skip
    assert by_zone(loads)["z"].mode == "bus"
    assert by_zone(loads)["z"].skipped == ("itinerario 1: fermata indisponibile (ALFA)",)


def test_una_stazione_di_passaggio_chiusa_non_cambia_l_itinerario(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """BETA è tra ALFA e GAMMA: i treni continuano a transitare, le tratte restano cariche."""
    base = run(feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand_of(zone("z", 100)))
    closed = run(
        feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand_of(zone("z", 100)),
        disruptions=[disruption("BETA", "b1", "b2")],
    )  # fmt: skip
    assert by_zone(closed)["z"].mode == "itinerary" and by_zone(closed)["z"].skipped == ()
    assert closed.sections == base.sections
    assert closed.closed_stops == frozenset({"b1", "b2"})


@pytest.mark.parametrize(
    ("window", "arrival_closed", "departure_closed"),
    [("arrival", True, False), ("departure", False, True), ("both", True, True)],
)
def test_l_interruzione_vale_per_la_sua_finestra(
    feed: GtfsFeed,
    config: TransitConfig,
    window: str,
    arrival_closed: bool,
    departure_closed: bool,
) -> None:
    for win, expected in (("arrival", arrival_closed), ("departure", departure_closed)):
        loads = run(
            feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand_of(zone("z", 100), window=win),
            disruptions=[disruption("GAMMA", "g1", "g2", window=window)],
        )  # fmt: skip
        assert (by_zone(loads)["z"].mode == "bus") is expected, (window, win)
        assert (loads.closed_stops == frozenset({"g1", "g2"})) is expected


def test_senza_stop_ids_l_interruzione_si_cerca_per_nome_e_chiude_tutte_le_fermate(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """«BETA» è sulla L1 (b1, b2) e sulla L6 (m1): l'interscambio si chiude da entrambe."""
    legs = itinerary(L1_ALFA_BETA, L6_BETA_EPSILON)
    loads = run(
        feed, config, {"z": [legs]}, demand_of(zone("z", 100)), day=S6_DAY,
        disruptions=[disruption("beta")],
    )  # fmt: skip
    assert loads.closed_stops == frozenset({"b1", "b2", "m1"})
    assert by_zone(loads)["z"].mode == "bus"


def test_piu_interruzioni_si_sommano(feed: GtfsFeed, config: TransitConfig) -> None:
    loads = run(
        feed, config, {}, demand_of(zone("z", 100)),
        disruptions=[
            disruption("GAMMA", "g1", window="arrival"),
            disruption("ALFA", "a1", window="both"),
            disruption("BETA", "b1", window="departure"),
        ],
    )  # fmt: skip
    assert loads.closed_stops == frozenset({"g1", "a1"})  # la terza è del deflusso


def test_interruzione_con_una_fermata_che_il_feed_non_ha(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    with pytest.raises(
        DisruptionError, match="Interruzione «X chiusa».*fermate che il feed non ha: zz"
    ):
        run(feed, config, {}, demand_of(zone("z", 1)), disruptions=[disruption("X", "g1", "zz")])


def test_interruzione_con_un_nome_che_il_feed_non_ha(feed: GtfsFeed, config: TransitConfig) -> None:
    with pytest.raises(DisruptionError, match="Interruzione «Atlantide chiusa»"):
        run(feed, config, {}, demand_of(zone("z", 1)), disruptions=[disruption("Atlantide")])


def test_le_fermate_sospese_da_una_misura_si_aggiungono_alle_interruzioni(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(
        feed, config, {"z": [itinerary(L1_ALFA_GAMMA)]}, demand_of(zone("z", 100)),
        disruptions=[disruption("ALFA", "a1", window="departure")], suspended=("g1", "g2"),
    )  # fmt: skip
    assert loads.closed_stops == frozenset({"g1", "g2"})
    assert by_zone(loads)["z"].skipped == ("itinerario 1: fermata indisponibile (GAMMA)",)


def test_una_fermata_vicina_chiusa_e_segnata_e_non_ha_carico(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(feed, config, {}, demand_of(zone("z", 300)), suspended=("u2",))
    closed, open_ = stop(loads, "u2"), stop(loads, "u1")
    assert closed.closed and closed.pax_h == 0 and closed.load_ratio is None
    assert not open_.closed and open_.pax_h == pytest.approx(600) and open_.bus_pax_h == open_.pax_h
    assert any("fermata indisponibile" in a for a in loads.assumptions)
    assert not any(
        "fermata indisponibile" in a
        for a in run(feed, config, {}, demand_of(zone("z", 1))).assumptions
    )


def test_le_assunzioni_dei_carichi_restano_uguali_senza_fermate_chiuse(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    plain = run(feed, config, {}, demand_of(zone("z", 100)))
    assert plain.closed_stops == frozenset()
    assert all(not s.closed for s in plain.stops)
    assert all(z.skipped == () for z in plain.zones)


# --- la quota bus di una fermata chiusa -----------------------------------------------------------

# Solo autobus, tutte vicine all'area (raggio 800 m): c1 a 333 m a nord (2 corse), c2 a 389 m a nord
# (1 corsa), f1 a 667 m a sud (1 corsa). c1-c2 distano 56 m (72 a piedi); f1 è a 1.001 m da c1
# (1.301 a piedi): fuori dal raggio di redistribuzione di 1.000 m. Capacità bus: 360, 180, 180.
BUS_STOPS = {"c1": 40.8350, "c2": 40.8355, "f1": 40.8260}


@pytest.fixture(scope="module")
def bus_feed(tmp_path_factory: pytest.TempPathFactory) -> GtfsFeed:
    clear_feed_cache()
    trips = [
        ("BA", [("c1", "08:20"), ("c2", "08:24")]),
        ("BB", [("c1", "08:35"), ("f1", "08:40")]),
    ]
    directory = write_gtfs(
        tmp_path_factory.mktemp("busfeed") / "feed",
        routes=[{"route_id": "RB", "route_type": "3"}],
        trips=[{"route_id": "RB", "service_id": "WK", "trip_id": t} for t, _ in trips],
        stops=[
            {"stop_id": i, "stop_name": f"BUS {i}", "stop_lat": str(lat), "stop_lon": "14.2350"}
            for i, lat in BUS_STOPS.items()
        ],
        stop_times=[
            {
                "trip_id": t, "arrival_time": f"{hhmm}:00", "departure_time": f"{hhmm}:00",
                "stop_id": stop, "stop_sequence": str(n + 1),
            }
            for t, stops in trips
            for n, (stop, hhmm) in enumerate(stops)
        ],
        calendar_dates=[{"service_id": "WK", "date": "20261219", "exception_type": "1"}],
    )  # fmt: skip
    return load_feed(directory)


BUS_ONLY = RouteClasses(
    {k: frozenset() for k in ("metro_line_1", "metro_line_6", "funicular")}
    | {"bus": frozenset({"RB"})}
)


def bus_shares(
    bus_feed: GtfsFeed, config: TransitConfig, closed: tuple[str, ...]
) -> dict[str, float]:
    """360 persone = 720 pax/h, ripartiti 360 / 180 / 180 senza chiusure."""
    loads = run(bus_feed, config, {}, demand_of(zone("z", 360)), suspended=closed, classes=BUS_ONLY)
    assert loads.unserved_persons == 0 or not [s for s in loads.stops if not s.closed]
    return {s.stop.stop_id: s.bus_pax_h for s in loads.stops}


def test_senza_chiusure_la_quota_e_proporzionale_alla_capacita(
    bus_feed: GtfsFeed, config: TransitConfig
) -> None:
    assert bus_shares(bus_feed, config, ()) == pytest.approx({"c1": 360, "c2": 180, "f1": 180})


def test_la_quota_di_una_fermata_chiusa_passa_alle_vicine_entro_il_raggio(
    bus_feed: GtfsFeed, config: TransitConfig
) -> None:
    """c1 chiusa: i suoi 360 vanno a c2 (a 72 m a piedi), non a f1 (a 1.301 m). Una ripartizione
    su tutte le aperte darebbe 360 e 360."""
    assert bus_shares(bus_feed, config, ("c1",)) == pytest.approx({"c1": 0, "c2": 540, "f1": 180})
    # c2 chiusa: i suoi 180 vanno a c1
    assert bus_shares(bus_feed, config, ("c2",)) == pytest.approx({"c1": 540, "c2": 0, "f1": 180})


def test_senza_aperte_nel_raggio_la_quota_va_a_tutte_le_aperte(
    bus_feed: GtfsFeed, config: TransitConfig
) -> None:
    """c1 e c2 chiuse: per c1 non c'è nessuna aperta entro 1.000 m a piedi (c2 è chiusa, f1 troppo
    lontana), quindi tutto passa all'unica aperta."""
    assert bus_shares(bus_feed, config, ("c1", "c2")) == pytest.approx(
        {"c1": 0, "c2": 0, "f1": 720}
    )


def test_con_tutte_le_fermate_bus_chiuse_la_domanda_non_e_servita(
    bus_feed: GtfsFeed, config: TransitConfig
) -> None:
    loads = run(
        bus_feed,
        config,
        {},
        demand_of(zone("z", 360)),
        suspended=("c1", "c2", "f1"),
        classes=BUS_ONLY,
    )
    assert (loads.bus_persons, loads.unserved_persons) == (0, 360)
    assert by_zone(loads)["z"].mode == "unserved"
    assert all(s.pax_h == 0 for s in loads.stops)


def test_il_raggio_di_redistribuzione_viene_dalla_configurazione(
    bus_feed: GtfsFeed, config: TransitConfig
) -> None:
    """Con 1.400 m anche f1 (1.301 m a piedi) è raggiungibile da c1: 180/360 a c2 e 180/360 a f1."""
    wide = config.model_copy(update={"redistribution_radius_m": 1400})
    loads = run(bus_feed, wide, {}, demand_of(zone("z", 360)), suspended=("c1",), classes=BUS_ONLY)
    assert {s.stop.stop_id: s.bus_pax_h for s in loads.stops} == pytest.approx(
        {"c1": 0, "c2": 180 + 180, "f1": 180 + 180}
    )
    # e il fattore a piedi: con 1,0 la distanza c1–f1 è 1.001 m, ancora fuori da 1.000
    flat = config.model_copy(update={"walk_detour_factor": 1.0, "redistribution_radius_m": 1100})
    loads = run(bus_feed, flat, {}, demand_of(zone("z", 360)), suspended=("c1",), classes=BUS_ONLY)
    assert {s.stop.stop_id: s.bus_pax_h for s in loads.stops}["f1"] == pytest.approx(360)


def test_il_raggio_di_redistribuzione_e_inclusivo(
    bus_feed: GtfsFeed, config: TransitConfig
) -> None:
    """Se la distanza a piedi tra c1 e c2 è esattamente il raggio, c2 è raggiungibile."""
    stops = {
        s.stop.stop_id: s.stop
        for s in run(bus_feed, config, {}, demand_of(zone("z", 1)), classes=BUS_ONLY).stops
    }
    walking = (
        haversine_m(stops["c1"].lat, stops["c1"].lon, (stops["c2"].lat, stops["c2"].lon))
        * config.walk_detour_factor
    )
    exact = config.model_copy(update={"redistribution_radius_m": walking})
    loads = run(bus_feed, exact, {}, demand_of(zone("z", 360)), suspended=("c1",), classes=BUS_ONLY)
    assert {s.stop.stop_id: s.bus_pax_h for s in loads.stops} == pytest.approx(
        {"c1": 0, "c2": 540, "f1": 180}
    )


def test_il_fattore_a_piedi_allontana_le_fermate(bus_feed: GtfsFeed, config: TransitConfig) -> None:
    """c1–c2 sono a 56 m in linea d'aria e a 72 a piedi: con un raggio di 60 m non sono vicine, e la
    quota di c1 va a tutte le aperte (180 + 180 a testa)."""
    tight = config.model_copy(update={"redistribution_radius_m": 60})
    loads = run(bus_feed, tight, {}, demand_of(zone("z", 360)), suspended=("c1",), classes=BUS_ONLY)
    assert {s.stop.stop_id: s.bus_pax_h for s in loads.stops} == pytest.approx(
        {"c1": 0, "c2": 360, "f1": 360}
    )


def test_la_quota_si_divide_tra_le_fermate_vicine_in_proporzione_alla_capacita(
    bus_feed: GtfsFeed, config: TransitConfig
) -> None:
    """f1 chiusa, raggio 1.400 m: i suoi 180 vanno a c1 (360) e c2 (180) come 2 a 1: 120 e 60."""
    wide = config.model_copy(update={"redistribution_radius_m": 1400})
    loads = run(bus_feed, wide, {}, demand_of(zone("z", 360)), suspended=("f1",), classes=BUS_ONLY)
    assert {s.stop.stop_id: s.bus_pax_h for s in loads.stops} == pytest.approx(
        {"c1": 360 + 120, "c2": 180 + 60, "f1": 0}
    )


def test_conservazione_con_le_fermate_chiuse(feed: GtfsFeed, config: TransitConfig) -> None:
    itineraries = {
        "a": [itinerary(L1_ALFA_GAMMA), itinerary(L1_ALFA_BETA, walk=True)],
        "b": [itinerary(L6_BETA_EPSILON)],
        "c": [],
    }
    demand = demand_of(zone("a", 1000), zone("b", 300), zone("c", 200))
    loads = run(feed, config, itineraries, demand, day=S6_DAY, suspended=("u1", "g1", "g2"))
    assert sum(z.persons for z in loads.zones) == pytest.approx(1500)
    assert sum(s.bus_pax_h for s in loads.stops) == pytest.approx(loads.bus_persons * 2)
    assert stop(loads, "u1").pax_h == 0 and stop(loads, "u1").closed
