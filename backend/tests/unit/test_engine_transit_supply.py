import datetime as dt
from datetime import date
from typing import Any

import pytest

from app.data.gtfs import GtfsFeed, RouteClasses, ServiceDay, clear_feed_cache, load_feed
from app.engine.transit_supply import SectionSupply, build_supply
from app.models.config import EngineConfig, TransitConfig
from tests.support import write_gtfs

BAND = (dt.time(8, 15), dt.time(8, 45))
WK = frozenset({"WK"})
DAY = ServiceDay(date(2027, 7, 10), date(2026, 12, 19), WK, covered=False)

ROUTES = [
    {"route_id": "RL", "route_type": "1"},
    {"route_id": "RS", "route_type": "1"},
    {"route_id": "RF1", "route_type": "7"},
    {"route_id": "RF3", "route_type": "7"},
    {"route_id": "RK", "route_type": "7"},
    {"route_id": "RD", "route_type": "7"},
    {"route_id": "RB", "route_type": "3"},
]
STOPS = {
    "a1": "ALFA", "a2": "ALFA", "b1": "BETA ", "b2": "BETA ", "g1": "GAMMA", "g2": "GAMMA",
    "c1": "C.SO V. EMANUELE", "c3": "C.SO V. EMANUELE", "p1": "SU", "q1": "GIU",
    "s1": "UNO", "s2": "DUE", "u1": "BUS UNO", "u2": "BUS DUE",
    "k1": "K UNO", "k2": "K DUE", "k3": "K TRE", "k4": "K QUATTRO",
    "d1": "D UNO", "d2": "D UNO", "d3": "D DUE",
}  # fmt: skip
# (corsa, linea, servizio, [(fermata, "HH:MM")])
TRIPS = [
    ("T1", "RL", "WK", [("a1", "08:00"), ("b1", "08:05"), ("g1", "08:10")]),
    ("T2", "RL", "WK", [("a1", "08:20"), ("b1", "08:25"), ("g1", "08:30")]),
    ("T3", "RL", "WK", [("a1", "08:40"), ("b1", "08:45"), ("g1", "08:50")]),
    ("T5", "RL", "WK", [("a1", "08:25"), ("b1", "08:30")]),
    ("T4", "RL", "WK", [("g2", "08:30"), ("b2", "08:35"), ("a2", "08:40")]),
    ("T6", "RL", "WK", [("a1", "08:15"), ("b1", "08:20"), ("g1", "08:25")]),
    ("T8", "RL", "WK", [("a1", "08:45"), ("b1", "08:50")]),
    ("T7", "RL", "SUN", [("a1", "08:20"), ("b1", "08:25"), ("g1", "08:30")]),
    ("F1", "RF1", "WK", [("p1", "08:20"), ("c1", "08:22"), ("q1", "08:24")]),
    ("F3", "RF3", "WK", [("c3", "08:21"), ("p1", "08:23")]),
    ("FX", "RF1", "WK", [("p1", "08:30"), ("q1", "08:34")]),
    ("FY", "RF1", "WK", [("p1", "08:00"), ("q1", "08:04")]),
    ("Ka", "RK", "WK", [("k1", "08:20"), ("k2", "08:25"), ("k3", "08:30")]),
    ("Kb", "RK", "WK", [("k1", "08:25"), ("k2", "08:30"), ("k4", "08:35")]),
    ("TD", "RD", "WK", [("d1", "08:20"), ("d2", "08:21"), ("d3", "08:22")]),
    ("L6", "RS", "SUN", [("s1", "08:20"), ("s2", "08:30")]),
    ("BUS", "RB", "WK", [("u1", "08:20"), ("u2", "08:30")]),
]  # fmt: skip

CLASSES = RouteClasses(
    {
        "metro_line_1": frozenset({"RL"}),
        "metro_line_6": frozenset({"RS"}),
        "funicular": frozenset({"RF1", "RF3", "RK", "RD"}),
        "bus": frozenset({"RB"}),
    }
)


@pytest.fixture(scope="module")
def feed(tmp_path_factory: pytest.TempPathFactory) -> GtfsFeed:
    clear_feed_cache()
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
    directory = write_gtfs(
        tmp_path_factory.mktemp("supply") / "feed",
        routes=ROUTES,
        trips=[{"route_id": r, "service_id": s, "trip_id": t} for t, r, s, _ in TRIPS],
        stops=[
            {"stop_id": i, "stop_name": n, "stop_lat": "40.83", "stop_lon": "14.23"}
            for i, n in STOPS.items()
        ],
        stop_times=list(reversed(times)),  # alla rinfusa: l'ordine lo dà stop_sequence
        calendar_dates=[
            {"service_id": s, "date": "20261219", "exception_type": "1"} for s in ("WK", "SUN")
        ],
    )
    return load_feed(directory)


@pytest.fixture(scope="module")
def config() -> TransitConfig:
    return EngineConfig.from_yaml().transit


def supply_of(
    feed: GtfsFeed,
    config: TransitConfig,
    *,
    service: ServiceDay = DAY,
    band: tuple[dt.time, dt.time] = BAND,
    slice_minutes: int = 30,
) -> Any:
    return build_supply(feed, CLASSES, config, service, *band, slice_minutes)


def section(supply: Any, route: str, start: str, end: str) -> SectionSupply:
    found: SectionSupply = supply.sections[(route, start, end)]
    return found


# --- corse e capacità per tratta ------------------------------------------------------------------


def test_le_corse_di_ogni_tratta_nella_fascia(feed: GtfsFeed, config: TransitConfig) -> None:
    supply = supply_of(feed, config)
    # ALFA → BETA: T2 (08:20), T3 (08:40), T5 (08:25), T6 (08:15 = inizio fascia, incluso);
    # T1 (08:00) è fuori e T7 è di un servizio non attivo
    assert section(supply, "RL", "ALFA", "BETA").trips == 4
    # BETA → GAMMA parte da BETA: T2 (08:25) sì, T3 (08:45 = fine, esclusa) no, T6 (08:20) sì
    assert section(supply, "RL", "BETA", "GAMMA").trips == 2
    # ritorno: T4 parte da GAMMA alle 08:30 e da BETA alle 08:35
    assert section(supply, "RL", "GAMMA", "BETA").trips == 1
    assert section(supply, "RL", "BETA", "ALFA").trips == 1


def test_la_capacita_e_corse_per_veicolo_riportata_a_pax_h(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    assert config.vehicle_capacity["metro_line_1"] == 1250
    supply = supply_of(feed, config)
    assert section(supply, "RL", "ALFA", "BETA").capacity_pax_h == 4 * 1250 * 60 / 30  # 10.000
    assert section(supply, "RL", "BETA", "GAMMA").capacity_pax_h == 2 * 1250 * 2
    assert section(supply, "RF1", "SU", "C SO V EMANUELE").capacity_pax_h == 2 * 250 * 2


def test_la_capacita_usa_la_fascia_intera_anche_se_quella_data_e_piu_corta(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """Con `slice_minutes` 60 le stesse 4 corse valgono la metà dei pax/h."""
    supply = supply_of(feed, config, slice_minutes=60)
    assert section(supply, "RL", "ALFA", "BETA").capacity_pax_h == 4 * 1250


def test_le_banchine_di_una_tratta_sono_quelle_del_suo_senso_di_marcia(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """ALFA ha un id per senso (a1 all'andata, a2 al ritorno): ALFA → BETA usa a1 e b1, il senso
    opposto b2 e a2. Le stazioni si riconoscono per nome, le banchine no."""
    supply = supply_of(feed, config)
    forward = section(supply, "RL", "ALFA", "BETA")
    assert (forward.from_stop_ids, forward.to_stop_ids) == (frozenset({"a1"}), frozenset({"b1"}))
    backward = section(supply, "RL", "BETA", "ALFA")
    assert (backward.from_stop_ids, backward.to_stop_ids) == (frozenset({"b2"}), frozenset({"a2"}))
    # il nome viene dal feed, con lo spazio in fondo; la chiave è normalizzata
    assert (forward.from_name, forward.to_name) == ("ALFA", "BETA ")
    assert (forward.route_class, forward.route_id) == ("metro_line_1", "RL")


def test_le_banchine_di_una_tratta_coperta_da_una_diretta_sono_quelle_della_corsa_completa(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """FX (diretta) salta c1, ma le tratte SU → C.SO e C.SO → GIU hanno le banchine di F1."""
    supply = supply_of(feed, config)
    first = section(supply, "RF1", "SU", "C SO V EMANUELE")
    assert (first.from_stop_ids, first.to_stop_ids) == (frozenset({"p1"}), frozenset({"c1"}))
    second = section(supply, "RF1", "C SO V EMANUELE", "GIU")
    assert (second.from_stop_ids, second.to_stop_ids) == (frozenset({"c1"}), frozenset({"q1"}))


def test_il_giro_corto_conta_solo_fin_dove_arriva(feed: GtfsFeed, config: TransitConfig) -> None:
    """T5 finisce a BETA: carica ALFA → BETA e non BETA → GAMMA."""
    supply = supply_of(feed, config, band=(dt.time(8, 25), dt.time(8, 26)))
    assert section(supply, "RL", "ALFA", "BETA").trips == 1  # T5 alle 08:25
    assert section(supply, "RL", "BETA", "GAMMA").trips == 1  # T2 alle 08:25, non T5


def test_funicolari_diverse_con_una_fermata_dallo_stesso_nome_restano_separate(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    supply = supply_of(feed, config)
    assert ("RF1", "C SO V EMANUELE", "GIU") in supply.sections
    assert ("RF3", "C SO V EMANUELE", "SU") in supply.sections
    assert section(supply, "RF1", "C SO V EMANUELE", "GIU").from_stop_ids == frozenset({"c1"})
    assert section(supply, "RF3", "C SO V EMANUELE", "SU").from_stop_ids == frozenset({"c3"})
    assert section(supply, "RF3", "C SO V EMANUELE", "SU").route_class == "funicular"


def test_una_corsa_diretta_copre_le_tratte_che_salta(feed: GtfsFeed, config: TransitConfig) -> None:
    """FX va da SU a GIU senza fermarsi a C.SO V. EMANUELE: copre SU → C.SO e C.SO → GIU, con
    l'ora di partenza da SU (08:30). Insieme a F1 (08:20) fanno 2 corse per tratta. FY, della
    stessa forma ma alle 08:00, è fuori fascia."""
    supply = supply_of(feed, config)
    assert section(supply, "RF1", "SU", "C SO V EMANUELE").trips == 2
    assert section(supply, "RF1", "C SO V EMANUELE", "GIU").trips == 2
    # la diretta non crea una tratta SU → GIU: le tratte sono quelle del percorso più lungo
    assert ("RF1", "SU", "GIU") not in supply.sections


def test_una_linea_con_due_rami_ha_le_tratte_di_entrambi(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    supply = supply_of(feed, config)
    assert section(supply, "RK", "K UNO", "K DUE").trips == 2  # Ka e Kb
    assert section(supply, "RK", "K DUE", "K TRE").trips == 1  # solo Ka
    assert section(supply, "RK", "K DUE", "K QUATTRO").trips == 1  # solo Kb


def test_due_banchine_di_seguito_con_lo_stesso_nome_sono_una_stazione(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """TD ferma a d1 e d2, entrambe «D UNO»: nessuna tratta da D UNO a se stessa."""
    supply = supply_of(feed, config)
    assert ("RD", "D UNO", "D UNO") not in supply.sections
    assert [k for k in supply.sections if k[0] == "RD"] == [("RD", "D UNO", "D DUE")]
    only = section(supply, "RD", "D UNO", "D DUE")
    assert only.trips == 1  # d2 → d3 alle 08:21
    assert only.from_stop_ids == frozenset({"d1", "d2"})


def test_tratte_senza_corse_nella_fascia_ci_sono_con_zero(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    supply = supply_of(feed, config, band=(dt.time(12, 0), dt.time(12, 30)))
    zero = section(supply, "RL", "ALFA", "BETA")
    assert (zero.trips, zero.capacity_pax_h) == (0, 0.0)
    assert len([s for s in supply.sections.values() if s.route_class == "metro_line_1"]) == 4


def test_una_linea_senza_servizio_quel_giorno_non_ha_tratte(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    supply = supply_of(feed, config)
    assert not [s for s in supply.sections.values() if s.route_class == "metro_line_6"]
    assert supply.trips_by_class["metro_line_6"] == 0


def test_gli_autobus_non_hanno_tratte(feed: GtfsFeed, config: TransitConfig) -> None:
    supply = supply_of(feed, config)
    assert {s.route_id for s in supply.sections.values()} == {"RL", "RF1", "RF3", "RK", "RD"}


def test_un_altro_servizio_cambia_le_corse(feed: GtfsFeed, config: TransitConfig) -> None:
    sunday = ServiceDay(date(2027, 7, 11), date(2026, 12, 19), frozenset({"SUN"}), covered=False)
    supply = supply_of(feed, config, service=sunday)
    assert section(supply, "RL", "ALFA", "BETA").trips == 1  # solo T7
    assert section(supply, "RS", "UNO", "DUE").trips == 1  # la L6 c'è, solo con SUN
    assert supply.trips_by_class["metro_line_6"] == 1


# --- corse per linea ------------------------------------------------------------------------------


def test_le_corse_di_una_linea_partono_dal_primo_capolinea_nelle_due_direzioni(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    supply = supply_of(feed, config)
    # partenze dal primo capolinea nella fascia: T2 08:20, T3 08:40, T5 08:25, T6 08:15, T4 08:30
    # (T1 08:00 prima, T8 08:45 = fine, esclusa)
    assert supply.trips_by_class["metro_line_1"] == 5
    # F1 08:20, F3 08:21, FX 08:30, Ka 08:20, Kb 08:25, TD 08:20 (FY, 08:00, è prima della fascia)
    assert supply.trips_by_class["funicular"] == 6
    assert supply.trips_by_class["metro_line_6"] == 0


def test_le_corse_di_una_linea_si_contano_dal_capolinea_non_da_ogni_fermata(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    """Fascia 08:21–08:26: dal capolinea parte solo T5 (08:25), che finisce a BETA; da BETA verso
    GAMMA passa T2 (08:25), partita prima. Le due cose sono corse diverse e si contano a parte."""
    supply = supply_of(feed, config, band=(dt.time(8, 21), dt.time(8, 26)))
    assert supply.trips_by_class["metro_line_1"] == 1  # T5
    assert section(supply, "RL", "BETA", "GAMMA").trips == 1  # T2, non T5
    assert section(supply, "RL", "ALFA", "BETA").trips == 1  # T5


def test_stesso_input_stesso_risultato_in_ordine_di_chiave(
    feed: GtfsFeed, config: TransitConfig
) -> None:
    first, second = supply_of(feed, config), supply_of(feed, config)
    assert first.sections == second.sections and first.trips_by_class == second.trips_by_class
    assert list(first.sections) == sorted(first.sections)


# --- provenienza ----------------------------------------------------------------------------------


def test_kind_e_assunzioni(feed: GtfsFeed, config: TransitConfig) -> None:
    estimated = supply_of(feed, config)
    assert estimated.kind == "estimate"
    assert any("non una previsione" in a for a in estimated.assumptions)
    assert "GTFS statico: orario programmato, non tracking in tempo reale" in estimated.assumptions
    assert (
        "orario tipo del 19/12/2026 (sabato) applicato alla data dell'evento (10/07/2027): "
        "il feed non la copre"
    ) in estimated.assumptions
    capacity_note = estimated.assumptions[-1]
    assert "metro_line_1 1250 pax per corsa (dato ANM (ago 2024))" in capacity_note
    assert "funicular 250 pax per corsa" in capacity_note and "su 30 minuti" in capacity_note

    covered = ServiceDay(date(2026, 12, 19), date(2026, 12, 19), WK, covered=True)
    real = supply_of(feed, config, service=covered)
    assert real.kind == "real"
    assert "orario del feed per il 19/12/2026 (la data dell'evento è coperta)" in real.assumptions
    assert not any("orario tipo" in a for a in real.assumptions)
