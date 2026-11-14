from typing import Any

import pytest

from app.data.gtfs import GtfsFeed, RouteClasses, clear_feed_cache, load_feed
from app.engine.transit import ResolvedLeg, Station, TransitConfigError, resolve_itineraries
from app.models.config import EngineConfig, Itinerary, TransitConfig
from tests.support import write_gtfs

ROUTES = [
    {"route_id": "R1", "route_type": "1"},
    {"route_id": "R2", "route_type": "1"},
    {"route_id": "R5", "route_type": "1"},
    {"route_id": "R9", "route_type": "1"},
    {"route_id": "R3", "route_type": "7"},
    {"route_id": "R7", "route_type": "7"},
    {"route_id": "R4", "route_type": "3"},
]
NAMES = {
    "a1": "ALFA", "a2": "ALFA", "b1": "BETA ", "b2": "BETA ", "g1": "GAMMA", "g2": "GAMMA",
    "m1": "BETA", "m2": "EPSILON", "p1": "PIU", "p2": "QUA",
    "n1": "ANELLO A", "n2": "ANELLO B", "n3": "ANELLO A",
    "bus1": "ALFA", "bus2": "DELTA",
    "f1": "FUNI SU", "f2": "FUNI GIU", "x1": "ALTRA SU", "x2": "ALTRA GIU",
}  # fmt: skip
# (corsa, linea, fermate nell'ordine)
TRIPS = [
    ("T1", "R1", ["a1", "b1", "g1"]), ("T2", "R1", ["g2", "b2", "a2"]),
    ("T3", "R2", ["m1", "m2"]), ("T3b", "R2", ["m2", "m1"]),
    ("T7", "R5", ["p1", "p2"]),
    ("T10", "R9", ["n1", "n2", "n3"]),
    ("T4", "R4", ["bus1", "bus2"]),
    ("T5", "R3", ["f1", "f2"]), ("T6", "R3", ["f2", "f1"]),
    ("T8", "R7", ["x1", "x2"]), ("T9", "R7", ["x2", "x1"]),
]  # fmt: skip


@pytest.fixture(scope="module")
def feed(tmp_path_factory: pytest.TempPathFactory) -> GtfsFeed:
    clear_feed_cache()
    times = [
        {
            "trip_id": trip,
            "arrival_time": f"08:{n:02d}:00",
            "departure_time": f"08:{n:02d}:00",
            "stop_id": stop,
            "stop_sequence": str(n + 1),
        }
        for trip, _, stops in TRIPS
        for n, stop in enumerate(stops)
    ]
    directory = write_gtfs(
        tmp_path_factory.mktemp("transit") / "feed",
        routes=ROUTES,
        trips=[{"route_id": r, "service_id": "WK", "trip_id": t} for t, r, _ in TRIPS],
        stops=[
            {"stop_id": i, "stop_name": n, "stop_lat": "40.83", "stop_lon": "14.23"}
            for i, n in NAMES.items()
        ],
        stop_times=times,
        calendar_dates=[{"service_id": "WK", "date": "20261109", "exception_type": "1"}],
    )
    return load_feed(directory)


@pytest.fixture(scope="module")
def classes() -> RouteClasses:
    return RouteClasses(
        {
            "metro_line_1": frozenset({"R1", "R9"}),
            "metro_line_6": frozenset({"R2", "R5"}),
            "funicular": frozenset({"R3", "R7"}),
            "bus": frozenset({"R4"}),
        }
    )


def transit_with(itineraries: dict[str, list[dict[str, Any]]]) -> TransitConfig:
    base = EngineConfig.from_yaml().transit
    parsed = {
        zone: [Itinerary.model_validate(item) for item in items]
        for zone, items in itineraries.items()
    }
    return base.model_copy(update={"itineraries": parsed})


def leg(kind: str, start: str, end: str) -> dict[str, str]:
    return {"route_class": kind, "from_stop_name": start, "to_stop_name": end}


# --- risoluzione ----------------------------------------------------------------------------------


def test_la_stazione_e_l_insieme_delle_fermate_della_classe_con_quel_nome(
    feed: GtfsFeed, classes: RouteClasses
) -> None:
    config = transit_with(
        {"z": [{"legs": [leg("metro_line_1", "Alfa", "Gamma")], "egress_walk": False}]}
    )
    [itinerary] = resolve_itineraries(feed, classes, config)["z"]
    [resolved] = itinerary.legs
    # ALFA c'è anche tra gli autobus (bus1): non è una fermata della L1
    assert resolved == ResolvedLeg(
        "metro_line_1",
        Station("Alfa", frozenset({"a1", "a2"})),
        Station("Gamma", frozenset({"g1", "g2"})),
    )
    assert itinerary.egress_walk is False


def test_il_nome_si_trova_anche_con_maiuscole_e_spazi_diversi(
    feed: GtfsFeed, classes: RouteClasses
) -> None:
    """Nel feed è «BETA » con lo spazio finale; in engine.yaml «beta»."""
    config = transit_with(
        {"z": [{"legs": [leg("metro_line_1", "alfa", "beta")], "egress_walk": True}]}
    )
    [itinerary] = resolve_itineraries(feed, classes, config)["z"]
    assert itinerary.legs[0].alight.stop_ids == frozenset({"b1", "b2"})


def test_l_interscambio_ha_fermate_diverse_con_lo_stesso_nome(
    feed: GtfsFeed, classes: RouteClasses
) -> None:
    legs = [leg("metro_line_1", "Alfa", "Beta"), leg("metro_line_6", "Beta", "Epsilon")]
    config = transit_with({"z": [{"legs": legs, "egress_walk": False}]})
    [itinerary] = resolve_itineraries(feed, classes, config)["z"]
    first, second = itinerary.legs
    assert first.alight.stop_ids == frozenset({"b1", "b2"})  # BETA della L1
    assert second.board.stop_ids == frozenset({"m1"})  # BETA della L6


def test_una_corsa_che_passa_due_volte_dalla_stazione_collega_comunque(
    feed: GtfsFeed, classes: RouteClasses
) -> None:
    """ANELLO A → ANELLO B si fa (n1 poi n2) e ANELLO B → ANELLO A pure (n2 poi n3)."""
    config = transit_with(
        {"z": [{"legs": [leg("metro_line_1", "Anello a", "Anello b")], "egress_walk": False}]}
    )
    [itinerary] = resolve_itineraries(feed, classes, config)["z"]
    assert itinerary.legs[0].board.stop_ids == frozenset({"n1", "n3"})


def test_ordine_zone_senza_itinerari_e_solo_a_piedi(feed: GtfsFeed, classes: RouteClasses) -> None:
    funicular = {"legs": [leg("funicular", "Funi su", "Funi giu")], "egress_walk": True}
    config = transit_with(
        {
            "prima": [funicular, {"legs": [], "egress_walk": True}],
            "vuota": [],
            "seconda": [{"legs": [leg("metro_line_1", "Alfa", "Gamma")], "egress_walk": False}],
        }
    )
    resolved = resolve_itineraries(feed, classes, config)
    assert list(resolved) == ["prima", "vuota", "seconda"]
    assert resolved["vuota"] == ()
    assert [len(item.legs) for item in resolved["prima"]] == [1, 0]
    assert [item.egress_walk for item in resolved["prima"]] == [True, True]
    assert resolved["seconda"][0].legs[0].route_class == "metro_line_1"


def test_gli_itinerari_di_engine_yaml_non_si_risolvono_su_un_feed_che_non_e_il_suo(
    feed: GtfsFeed, classes: RouteClasses
) -> None:
    with pytest.raises(TransitConfigError, match="Piscinola"):
        resolve_itineraries(feed, classes, EngineConfig.from_yaml().transit)


# --- errori ---------------------------------------------------------------------------------------


def errors_of(feed: GtfsFeed, classes: RouteClasses, itineraries: dict[str, Any]) -> list[str]:
    with pytest.raises(TransitConfigError) as info:
        resolve_itineraries(feed, classes, transit_with(itineraries))
    header, *lines = str(info.value).split("\n  - ")
    assert header == "Itinerari di engine.yaml (transit.itineraries) non risolti sul feed GTFS:"
    return lines


def test_fermata_che_il_feed_non_ha(feed: GtfsFeed, classes: RouteClasses) -> None:
    config = {"z": [{"legs": [leg("metro_line_1", "Atlantide", "Gamma")], "egress_walk": False}]}
    assert errors_of(feed, classes, config) == [
        "z, itinerario 1, tratta 1 (metro_line_1): nessuna fermata chiamata «Atlantide» nel feed"
    ]


def test_fermata_che_esiste_ma_non_e_della_classe(feed: GtfsFeed, classes: RouteClasses) -> None:
    config = {"z": [{"legs": [leg("metro_line_1", "Alfa", "Delta")], "egress_walk": False}]}
    assert errors_of(feed, classes, config) == [
        "z, itinerario 1, tratta 1 (metro_line_1): «Delta» è nel feed (1 fermate) ma nessuna è "
        "servita da metro_line_1"
    ]


def test_nessuna_corsa_collega_le_due_fermate(feed: GtfsFeed, classes: RouteClasses) -> None:
    """Due funicolari della stessa classe: i nomi si risolvono, ma nessuna corsa li unisce."""
    config = {"z": [{"legs": [leg("funicular", "Funi su", "Altra giu")], "egress_walk": True}]}
    assert errors_of(feed, classes, config) == [
        "z, itinerario 1, tratta 1 (funicular): nessuna corsa va da «Funi su» a «Altra giu» "
        "(arrivo)",
        "z, itinerario 1, tratta 1 (funicular): nessuna corsa va da «Altra giu» a «Funi su» "
        "(deflusso)",
    ]


def test_una_sola_direzione_basta_a_dare_errore(feed: GtfsFeed, classes: RouteClasses) -> None:
    """PIU → QUA c'è solo in andata: il deflusso (QUA → PIU) non è percorribile."""
    config = {"z": [{"legs": [leg("metro_line_6", "Piu", "Qua")], "egress_walk": False}]}
    assert errors_of(feed, classes, config) == [
        "z, itinerario 1, tratta 1 (metro_line_6): nessuna corsa va da «Qua» a «Piu» (deflusso)"
    ]


def test_gli_errori_si_riportano_tutti_insieme_e_in_ogni_punto(
    feed: GtfsFeed, classes: RouteClasses
) -> None:
    config = {
        "uno": [
            {"legs": [leg("metro_line_1", "Atlantide", "Gamma")], "egress_walk": False},
            {"legs": [leg("metro_line_1", "Alfa", "Delta")], "egress_walk": False},
        ],
        "due": [{"legs": [leg("metro_line_1", "Atlantide", "Alfa")], "egress_walk": True}],
    }
    assert errors_of(feed, classes, config) == [
        "uno, itinerario 1, tratta 1 (metro_line_1): nessuna fermata chiamata «Atlantide» nel feed",
        "uno, itinerario 2, tratta 1 (metro_line_1): «Delta» è nel feed (1 fermate) ma nessuna è "
        "servita da metro_line_1",
        "due, itinerario 1, tratta 1 (metro_line_1): nessuna fermata chiamata «Atlantide» nel feed",
    ]


# --- la rete TPL caricata -------------------------------------------------------------------------


def test_load_transit_network_classifica_e_risolve(feed: GtfsFeed) -> None:
    from app.engine.transit import load_transit_network
    from app.models.config import RouteClassification

    classification = RouteClassification.model_validate(
        {
            "metro_line_1": {"route_ids": ["R1"]},
            "metro_line_6": {"route_ids": ["R2"]},
            "funicular": {"route_ids": ["R3", "R7"]},
        }
    )
    config = transit_with(
        {"z": [{"legs": [leg("metro_line_1", "Alfa", "Gamma")], "egress_walk": False}]}
    ).model_copy(update={"route_classification": classification})
    network = load_transit_network(feed, config)
    assert network.feed is feed
    assert network.classes.ids("bus") == frozenset({"R4"})
    assert network.classes.ids("metro_line_1") == frozenset({"R1"})
    assert network.itineraries["z"][0].legs[0].alight.stop_ids == frozenset({"g1", "g2"})


def test_load_transit_network_segnala_le_linee_che_il_feed_non_ha(feed: GtfsFeed) -> None:
    from app.data.gtfs import GtfsError
    from app.engine.transit import load_transit_network

    with pytest.raises(GtfsError, match="route_id di engine.yaml"):
        load_transit_network(feed, EngineConfig.from_yaml().transit)  # le linee ANM, non queste
