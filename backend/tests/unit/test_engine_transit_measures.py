import datetime as dt
from datetime import date
from typing import Any

import pandas as pd
import pytest

from app.data.gtfs import GtfsFeed, RouteClasses, ServiceDay, clear_feed_cache, load_feed
from app.engine.demand import Demand, ZoneDemand
from app.engine.measures import MeasureError
from app.engine.transit import ResolvedItinerary, ResolvedLeg, Station, TransitNetwork
from app.engine.transit_loads import TransitLoads, assign_transit
from app.engine.transit_measures import TransitMeasures, apply_transit_measures
from app.engine.transit_supply import build_supply
from app.models.base import Window
from app.models.config import EngineConfig, TransitConfig
from tests.support import make_event, write_gtfs
from tests.transit_world import req

BAND = (dt.time(8, 15), dt.time(8, 45))
SLICE = 30
DAY = date(2026, 12, 19)
SERVICE = ServiceDay(DAY, DAY, frozenset({"WK"}), covered=True)


def hhmm(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 3600 + int(minutes) * 60


def clock(seconds: float) -> str:
    return f"{int(seconds // 3600):02d}:{int(seconds % 3600 // 60):02d}"


def trip_rows(trip: str, stops: list[str], start: str, step: int = 300) -> list[dict[str, str]]:
    """Una corsa con le fermate a `step` secondi una dall'altra."""
    out = []
    for n, stop in enumerate(stops):
        seconds = hhmm(start) + n * step
        text = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:00"
        out.append(
            {"trip_id": trip, "arrival_time": text, "departure_time": text,
             "stop_id": stop, "stop_sequence": str(n + 1)}
        )  # fmt: skip
    return out


FORWARD = [
    f"{h:02d}:{m:02d}" for h, m in ((7, 0), (7, 10), (7, 20), (7, 30), (7, 40), (7, 50), (8, 0))
]
BACKWARD = ["07:00", "07:12", "07:24", "07:36", "07:48"]
SLOW = 420  # secondi tra le fermate dell'ultima corsa dell'andata
SCHEDULE: list[tuple[str, str, list[str], str, int, str]] = [
    # (corsa, linea, fermate, partenza, secondi tra una fermata e l'altra, servizio)
    *(
        (f"A{i}", "RS", ["m1", "m2"], t, SLOW if t == "08:00" else 300, "WK")
        for i, t in enumerate(FORWARD)
    ),
    *((f"R{i}", "RS", ["q1", "q2"], t, 300, "WK") for i, t in enumerate(BACKWARD)),
    ("SU", "RS", ["m1", "m2"], "08:50", 300, "SUN"),
    ("F0", "RF", ["f1", "f2"], "06:00", 300, "WK"),
    ("F1", "RF", ["f1", "f2"], "07:00", 300, "WK"),
    ("F2", "RF", ["f1", "f2"], "09:00", 300, "WK"),
    ("G0", "RG", ["g1", "g2"], "06:00", 300, "WK"),
    ("Z0", "RZ", ["z1", "z2"], "07:00", 300, "WK"),
    ("Z1", "RZ", ["z1", "z2"], "07:00", 300, "WK"),
    ("BA", "RB", ["u1", "u2"], "08:20", 300, "WK"),
]  # fmt: skip


@pytest.fixture(scope="module")
def feed(tmp_path_factory: pytest.TempPathFactory) -> GtfsFeed:
    clear_feed_cache()
    stops = {
        "m1": ("UNO", 40.90), "m2": ("DUE", 40.8330), "q1": ("DUE", 40.8330), "q2": ("UNO", 40.90),
        "f1": ("SU", 40.90), "f2": ("GIU", 40.90), "g1": ("PRIMO", 40.90), "g2": ("SECONDO", 40.90),
        "z1": ("ZETA UNO", 40.90), "z2": ("ZETA DUE", 40.90),
        "u1": ("BUS UNO", 40.8325), "u2": ("BUS DUE", 40.8310),
    }  # fmt: skip
    directory = write_gtfs(
        tmp_path_factory.mktemp("tpl") / "feed",
        routes=[
            {"route_id": "RS", "route_type": "1"},
            {"route_id": "RF", "route_type": "7"},
            {"route_id": "RG", "route_type": "7"},
            {"route_id": "RZ", "route_type": "7"},
            {"route_id": "RB", "route_type": "3"},
            {"route_id": "RX", "route_type": "1"},
        ],
        trips=[{"route_id": r, "service_id": sv, "trip_id": t} for t, r, _, _, _, sv in SCHEDULE],
        stops=[
            {"stop_id": i, "stop_name": n, "stop_lat": str(lat), "stop_lon": "14.2350"}
            for i, (n, lat) in stops.items()
        ],
        stop_times=[
            row for t, _, s, start, step, _ in SCHEDULE for row in trip_rows(t, s, start, step)
        ],
        calendar_dates=[
            {"service_id": "WK", "date": "20261219", "exception_type": "1"},
            {"service_id": "SUN", "date": "20261220", "exception_type": "1"},
        ],
    )
    return load_feed(directory)


CLASSES = RouteClasses(
    {
        "metro_line_1": frozenset(),
        "metro_line_6": frozenset({"RS"}),
        "funicular": frozenset({"RF", "RG", "RZ"}),
        "bus": frozenset({"RB"}),
    }
)
UNO, DUE = Station("UNO", frozenset({"m1", "q2"})), Station("DUE", frozenset({"m2", "q1"}))
L6_LEG = ResolvedLeg("metro_line_6", UNO, DUE)


@pytest.fixture(scope="module")
def config() -> TransitConfig:
    return EngineConfig.from_yaml().transit


@pytest.fixture(scope="module")
def network(feed: GtfsFeed) -> TransitNetwork:
    return TransitNetwork(feed, CLASSES, {"z": (ResolvedItinerary((L6_LEG,), False),)})


def apply(
    network: TransitNetwork, config: TransitConfig, *requests: Any, window: Window = "arrival"
) -> TransitMeasures:
    return apply_transit_measures(network, config, SERVICE, window, *BAND, list(requests))


def added(measures: TransitMeasures) -> pd.DataFrame:
    assert measures.extra is not None
    return measures.extra.stop_times


# --- extend_hours ---------------------------------------------------------------------------------


def test_extend_hours_continua_l_orario_con_l_intervallo_dell_ultima_ora(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(
        network, config, req("act_1", "extend_hours", "metro_line_6", payload={"until": "09:00"})
    )
    assert measures.applied == ("act_1",)
    rows = added(measures).sort_values(["trip_id", "seq"])
    firsts = rows.groupby("trip_id").head(1)
    starts = sorted(clock(s) for s in firsts["dep_s"])
    # andata: ultima 08:00, intervallo 10 min → 08:10 … 09:00 (6); ritorno: ultima 07:48, intervallo
    # 12 min → 08:00, 08:12, 08:24, 08:36, 08:48, 09:00 (6); fino a `until` incluso
    assert starts == sorted(
        ["08:10", "08:20", "08:30", "08:40", "08:50", "09:00",
         "08:00", "08:12", "08:24", "08:36", "08:48", "09:00"]
    )  # fmt: skip
    assert measures.extra is not None and len(measures.extra.trips) == 12


def test_le_corse_aggiunte_copiano_fermate_e_tempi_relativi_della_ultima_corsa(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(
        network, config, req("act_1", "extend_hours", "RS", payload={"until": "08:10"})
    )
    assert measures.extra is not None
    [trip] = [t for t in measures.extra.trips["trip_id"] if t.endswith(":0")][:1]
    rows = added(measures)
    rows = rows[rows["trip_id"] == trip].sort_values("seq")
    assert list(rows["stop_id"]) == ["m1", "m2"]  # le stesse fermate
    assert list(rows["seq"]) == [1, 2]
    # parte alle 08:10 e arriva a m2 dopo 7 minuti, come l'ultima corsa programmata (non 5 come
    # le altre)
    assert list(rows["dep_s"]) == [hhmm("08:10"), hhmm("08:17")]
    assert list(rows["arr_s"]) == [hhmm("08:10"), hhmm("08:17")]
    assert set(measures.extra.trips.columns) == {"trip_id", "route_id"}
    assert set(measures.extra.trips["route_id"]) == {"RS"}


def test_senza_until_vale_l_orario_di_engine_yaml(
    network: TransitNetwork, config: TransitConfig
) -> None:
    """Fino alle 23:59: andata 08:10, 08:20 … (95 corse), ritorno 08:00, 08:12 … (80 corse)."""
    measures = apply(network, config, req("act_1", "extend_hours", "metro_line_6"))
    assert str(config.extend_hours_default_end) == "23:59:00"
    assert len(added(measures).groupby("trip_id")) == 95 + 80
    assert "fino alle 23:59" in measures.assumptions[1]


def test_il_bersaglio_puo_essere_la_classe_o_il_route_id(
    network: TransitNetwork, config: TransitConfig
) -> None:
    by_class = apply(
        network, config, req("a", "extend_hours", "metro_line_6", payload={"until": "08:30"})
    )
    by_route = apply(network, config, req("a", "extend_hours", "RS", payload={"until": "08:30"}))
    assert added(by_class).equals(added(by_route))


def test_senza_corse_nell_ultima_ora_l_intervallo_e_la_media_del_giorno(
    network: TransitNetwork, config: TransitConfig
) -> None:
    """RF ha corse alle 06:00, 07:00 e 09:00: nell'ultima ora c'è solo la 09:00, quindi l'intervallo
    è (09:00 − 06:00) / 2 = 90 minuti: 10:30 e 12:00."""
    measures = apply(network, config, req("a", "extend_hours", "RF", payload={"until": "12:00"}))
    firsts = added(measures).sort_values(["trip_id", "seq"]).groupby("trip_id").head(1)
    assert sorted(clock(s) for s in firsts["dep_s"]) == ["10:30", "12:00"]


def test_una_classe_senza_linee_non_aggiunge_niente(
    network: TransitNetwork, config: TransitConfig
) -> None:
    """La L1 non c'è in questo feed: il bersaglio è valido (è una classe) e non cambia niente."""
    measures = apply(network, config, req("a", "extend_hours", "metro_line_1"))
    assert measures.extra is None and measures.applied == ("a",)


def test_una_linea_con_una_sola_corsa_non_si_puo_prolungare(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(network, config, req("a", "extend_hours", "RG", payload={"until": "12:00"}))
    assert measures.extra is None and measures.applied == ("a",)
    assert "una sola corsa" in measures.assumptions[1]
    assert "nessuna corsa aggiunta" in measures.assumptions[1]


def test_until_prima_dell_ultima_corsa_non_aggiunge_niente(
    network: TransitNetwork, config: TransitConfig
) -> None:
    assert (
        apply(network, config, req("a", "extend_hours", "RS", payload={"until": "07:30"})).extra
        is None
    )


def test_corse_alla_stessa_ora_hanno_intervallo_nullo_e_non_si_prolungano(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(network, config, req("a", "extend_hours", "RZ", payload={"until": "12:00"}))
    assert measures.extra is None
    assert "intervallo nullo" in measures.assumptions[1]


def test_le_corse_di_un_altro_servizio_non_contano_per_l_ultima_corsa(
    network: TransitNetwork, config: TransitConfig
) -> None:
    """La corsa «SUN» delle 08:50 non è del giorno: l'ultima dell'andata resta quella delle 08:00
    (si aggiunge la 08:10, e al ritorno la 08:00; la 08:12 è oltre `until`)."""
    measures = apply(network, config, req("a", "extend_hours", "RS", payload={"until": "08:11"}))
    firsts = added(measures).sort_values(["trip_id", "seq"]).groupby("trip_id").head(1)
    assert sorted(clock(s) for s in firsts["dep_s"]) == ["08:00", "08:10"]


# --- add_runs -------------------------------------------------------------------------------------


def test_add_runs_distribuisce_le_corse_uniformemente_nella_fascia_per_ogni_senso(
    network: TransitNetwork, config: TransitConfig
) -> None:
    """n = 2 nella fascia 08:15–08:45: al centro di due metà da 15 minuti, 08:22:30 e 08:37:30."""
    measures = apply(network, config, req("a", "add_runs", "metro_line_6", payload={"n": 2}))
    rows = added(measures).sort_values(["trip_id", "seq"])
    firsts = rows.groupby("trip_id").head(1)
    assert sorted(firsts["dep_s"]) == [
        hhmm("08:22") + 30,
        hhmm("08:22") + 30,
        hhmm("08:37") + 30,
        hhmm("08:37") + 30,
    ]
    assert len(firsts) == 4  # 2 per senso
    # i tempi relativi vengono dalla corsa più vicina all'inizio della fascia: all'andata quella
    # delle 08:00 (7 minuti), al ritorno quella delle 07:48 (5 minuti)
    second = rows[rows["seq"] == 2]
    assert sorted(second["dep_s"].to_numpy() - firsts["dep_s"].to_numpy()) == [300, 300, 420, 420]


def test_add_runs_si_distribuisce_nella_fascia_data_non_in_una_di_30_minuti(
    network: TransitNetwork, config: TransitConfig
) -> None:
    short = (dt.time(8, 15), dt.time(8, 35))  # 1.200 s: due metà da 10 minuti → 08:20 e 08:30
    measures = apply_transit_measures(
        network, config, SERVICE, "arrival", *short, [req("a", "add_runs", "RB", payload={"n": 2})]
    )
    firsts = added(measures).sort_values(["trip_id", "seq"]).groupby("trip_id").head(1)
    assert sorted(clock(s) for s in firsts["dep_s"]) == ["08:20", "08:30"]


def test_senza_n_vale_il_valore_di_engine_yaml(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(network, config, req("a", "add_runs", "RS"))
    assert config.add_runs_default == 4
    assert len(added(measures).groupby("trip_id")) == 4 * 2


def test_add_runs_su_una_linea_di_autobus(network: TransitNetwork, config: TransitConfig) -> None:
    measures = apply(network, config, req("a", "add_runs", "RB", payload={"n": 3}))
    assert len(added(measures).groupby("trip_id")) == 3  # una sola direzione
    assert set(measures.extra.trips["route_id"]) == {"RB"}  # type: ignore[union-attr]


def test_add_runs_sulla_classe_bus_chiede_un_route_id(
    network: TransitNetwork, config: TransitConfig
) -> None:
    with pytest.raises(MeasureError, match="la classe bus ha troppe linee"):
        apply(network, config, req("a", "add_runs", "bus"))


# --- stop_suspension e bus_detour -----------------------------------------------------------------


def test_stop_suspension_sospende_la_fermata(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(
        network, config, req("a", "stop_suspension", "u2"), req("b", "stop_suspension", "m2")
    )
    assert measures.suspended == frozenset({"u2", "m2"})
    assert measures.extra is None and measures.applied == ("a", "b")
    assert any("stop_suspension u2" in a for a in measures.assumptions)


def test_stop_suspension_su_una_fermata_che_il_feed_non_ha(
    network: TransitNetwork, config: TransitConfig
) -> None:
    with pytest.raises(
        MeasureError, match="b \\(stop_suspension\\): la fermata 'zz' non è nel feed"
    ):
        apply(network, config, req("b", "stop_suspension", "zz"))


def test_bus_detour_e_solo_una_segnalazione(network: TransitNetwork, config: TransitConfig) -> None:
    detour = req("a", "bus_detour", "RB", payload={"avoid_edge_keys": ["1-2-0", "3-4-0"]})
    measures = apply(network, config, detour)
    assert [(d.action_id, d.route_id, d.avoid_edge_keys) for d in measures.detours] == [
        ("a", "RB", ("1-2-0", "3-4-0"))
    ]
    assert (
        measures.extra is None and measures.suspended == frozenset() and measures.applied == ("a",)
    )
    assert any("nessun effetto numerico" in a for a in measures.assumptions)


@pytest.mark.parametrize(
    ("target", "payload", "fragment"),
    [
        ("RQ", {"avoid_edge_keys": ["1-2-0"]}, "la linea 'RQ' non è nel feed"),
        ("RB", {}, "serve payload\\['avoid_edge_keys'\\]"),
        ("RB", {"avoid_edge_keys": []}, "serve payload\\['avoid_edge_keys'\\]"),
        ("RB", {"avoid_edge_keys": [3]}, "serve payload\\['avoid_edge_keys'\\]"),
        ("RB", {"avoid_edge_keys": ["strada"]}, "a\\) \\(bus_detour\\)|bus_detour"),
    ],
)
def test_bus_detour_non_valido(
    network: TransitNetwork,
    config: TransitConfig,
    target: str,
    payload: dict[str, Any],
    fragment: str,
) -> None:
    with pytest.raises(MeasureError, match=fragment):
        apply(network, config, req("a", "bus_detour", target, payload=payload))


# --- regole comuni --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "target", "payload", "fragment"),
    [
        ("extend_hours", "Linea 6", {}, "non è una classe"),
        ("extend_hours", "RX", {}, "non è una classe"),  # una linea che il modello non considera
        ("extend_hours", "bus", {}, "la classe bus ha troppe linee"),
        ("extend_hours", "RS", {"until": "tardi"}, "non è un orario HH:MM"),
        ("extend_hours", "RS", {"until": "25:99"}, "non è un orario HH:MM"),
        ("add_runs", "RS", {"n": 0}, "payload\\['n'\\] deve essere un intero ≥ 1"),
        ("add_runs", "RS", {"n": "due"}, "payload\\['n'\\] deve essere un intero ≥ 1"),
        ("add_runs", "RS", {"n": True}, "payload\\['n'\\] deve essere un intero ≥ 1"),
        ("add_runs", "RS", {"n": 2.5}, "payload\\['n'\\] deve essere un intero ≥ 1"),
    ],
)
def test_bersagli_e_payload_non_validi(
    network: TransitNetwork,
    config: TransitConfig,
    kind: str,
    target: str,
    payload: dict[str, Any],
    fragment: str,
) -> None:
    with pytest.raises(MeasureError, match=fragment):
        apply(network, config, req("a", kind, target, payload=payload))


def test_una_richiesta_non_accettata_e_un_errore(
    network: TransitNetwork, config: TransitConfig
) -> None:
    with pytest.raises(MeasureError, match="b \\(stop_suspension\\): la richiesta è RECEIVED"):
        apply(network, config, req("b", "stop_suspension", "u1", state="RECEIVED"))


def test_una_richiesta_di_un_altra_finestra_si_convalida_ma_non_si_applica(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(network, config, req("a", "stop_suspension", "u1", window="departure"))
    assert measures.applied == () and measures.suspended == frozenset()
    with pytest.raises(MeasureError, match="la fermata 'zz'"):
        apply(network, config, req("a", "stop_suspension", "zz", window="arrival"))
    with pytest.raises(
        MeasureError, match="non accettata"
    ):  # convalidata anche se è di un'altra finestra
        apply(network, config, req("a", "stop_suspension", "u1", window="departure", state="SENT"))


def test_le_misure_stradali_e_senza_effetto_si_ignorano(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(
        network, config, req("a", "close_road", "1-2-0"), req("b", "citizen_notice", "avviso"),
        req("c", "traffic_post", "123"),
    )  # fmt: skip
    assert measures == TransitMeasures(None, frozenset(), (), (), measures.assumptions)


def test_un_tipo_sconosciuto_e_un_errore(network: TransitNetwork, config: TransitConfig) -> None:
    with pytest.raises(MeasureError, match="tipo di misura sconosciuto"):
        apply(network, config, req("a", "teletrasporto", "u1"))


def test_si_applicano_nell_ordine_iterazione_e_action_id(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(
        network, config,
        req("z", "stop_suspension", "u1", iteration=1),
        req("b", "stop_suspension", "u2", iteration=2),
        req("a", "stop_suspension", "m2", iteration=2),
    )  # fmt: skip
    assert measures.applied == ("z", "a", "b")


def test_stesse_misure_stesso_risultato(network: TransitNetwork, config: TransitConfig) -> None:
    requests = [
        req("a", "extend_hours", "RS", payload={"until": "09:00"}),
        req("b", "add_runs", "RB"),
    ]
    first, second = apply(network, config, *requests), apply(network, config, *requests)
    assert added(first).equals(added(second))
    assert first.extra.trips.equals(second.extra.trips)  # type: ignore[union-attr]
    assert first.assumptions == second.assumptions
    ids = list(first.extra.trips["trip_id"])  # type: ignore[union-attr]
    assert len(set(ids)) == len(ids) and all(i.startswith(("a:", "b:")) for i in ids)


# --- l'effetto sull'offerta e sui carichi ---------------------------------------------------------


def zone(zone_id: str, transit: float) -> ZoneDemand:
    return ZoneDemand(
        zone_id=zone_id, zone_type="near", persons=transit, car_persons=0.0,
        transit_persons=transit, walk_persons=0.0, car_vehicles=0.0, car_veh_per_hour=0.0,
    )  # fmt: skip


def demand_of(*zones: ZoneDemand) -> Demand:
    return Demand(
        window="arrival", level="mid", attendance=0, band_start=BAND[0], band_end=BAND[1],
        band_share=0.3, persons=0.0, zones=zones, flows=(), car_occupancy=2.2,
        inputs=("prova",), assumptions=(),
    )  # fmt: skip


def loads(
    network: TransitNetwork, config: TransitConfig, measures: TransitMeasures | None = None
) -> TransitLoads:
    event = make_event(date=DAY.isoformat())
    return assign_transit(
        network, config, event, demand_of(zone("z", 300)), SLICE,
        suspended=measures.suspended if measures else (),
        extra=measures.extra if measures else None,
    )  # fmt: skip


def test_senza_misure_la_l6_e_ferma_e_la_zona_va_sul_bus(
    network: TransitNetwork, config: TransitConfig
) -> None:
    base = loads(network, config)
    assert base.supply.trips_by_class["metro_line_6"] == 0
    assert [(z.mode, z.skipped) for z in base.zones] == [
        ("bus", ("itinerario 1: senza corse nella fascia (metro_line_6)",))
    ]


def test_extend_hours_rende_di_nuovo_disponibile_l_itinerario_e_da_capacita_alla_tratta(
    network: TransitNetwork, config: TransitConfig
) -> None:
    """Fino alle 09:00 nella fascia 08:15–08:45: andata 08:20, 08:30, 08:40 (3), ritorno 08:24,
    08:36 (2). UNO → DUE ha 3 corse × 290 × 2 = 1.740 pax/h; 300 persone = 600 pax/h."""
    measures = apply(
        network, config, req("a", "extend_hours", "metro_line_6", payload={"until": "09:00"})
    )
    result = loads(network, config, measures)
    assert result.supply.trips_by_class["metro_line_6"] == 5
    assert [(z.mode, z.itinerary) for z in result.zones] == [("itinerary", 1)]
    section = result.sections[("RS", "UNO", "DUE")]
    assert (section.section.trips, section.section.capacity_pax_h) == (3, 1740)
    assert section.pax_h == 600 and section.load_ratio == pytest.approx(600 / 1740)


def test_add_runs_aumenta_le_corse_di_una_tratta(
    network: TransitNetwork, config: TransitConfig
) -> None:
    measures = apply(network, config, req("a", "add_runs", "metro_line_6", payload={"n": 2}))
    result = loads(network, config, measures)
    assert result.sections[("RS", "UNO", "DUE")].section.trips == 2
    assert result.sections[("RS", "UNO", "DUE")].section.capacity_pax_h == 2 * 290 * 2
    assert result.supply.trips_by_class["metro_line_6"] == 4


def test_add_runs_su_un_autobus_aumenta_la_capacita_della_fermata_vicina(
    network: TransitNetwork, config: TransitConfig
) -> None:
    before = loads(network, config)
    after = loads(
        network, config, apply(network, config, req("a", "add_runs", "RB", payload={"n": 3}))
    )
    u1_before = next(s for s in before.stops if s.stop.stop_id == "u1")
    u1_after = next(s for s in after.stops if s.stop.stop_id == "u1")
    assert (u1_before.stop.trips, u1_after.stop.trips) == (1, 4)  # BA 08:20 + 3 corse aggiunte
    assert u1_after.stop.bus_capacity_pax_h == 4 * 90 * 2
    assert u1_after.load_ratio is not None and u1_before.load_ratio is not None
    assert u1_after.load_ratio < u1_before.load_ratio


def test_una_fermata_sospesa_da_una_misura_blocca_l_itinerario(
    network: TransitNetwork, config: TransitConfig
) -> None:
    both = apply(
        network, config,
        req("a", "extend_hours", "metro_line_6", payload={"until": "09:00"}),
        req("b", "stop_suspension", "m2"),
    )  # fmt: skip
    result = loads(network, config, both)
    assert result.closed_stops == frozenset({"m2"})
    assert by_mode(result) == {"z": "bus"}  # L6 ripristinata, ma la discesa (DUE) è sospesa
    assert result.zones[0].skipped == ("itinerario 1: fermata indisponibile (DUE)",)


def by_mode(loads: TransitLoads) -> dict[str, str]:
    return {z.zone_id: z.mode for z in loads.zones}


def test_l_offerta_senza_extra_non_cambia(feed: GtfsFeed, config: TransitConfig) -> None:
    plain = build_supply(feed, CLASSES, config, SERVICE, *BAND, SLICE)
    assert build_supply(feed, CLASSES, config, SERVICE, *BAND, SLICE, None) == plain
