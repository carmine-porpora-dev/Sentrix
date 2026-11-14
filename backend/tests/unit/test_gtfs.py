from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.data.gtfs import (
    SURFACE_ROUTE_TYPES,
    GtfsError,
    classify_routes,
    clear_feed_cache,
    load_feed,
    service_day,
    stops_served_by_routes,
)
from app.models.config import EngineConfig, RouteClassification
from tests.support import GTFS_FIXTURE, write_gtfs

ROUTES = [{"route_id": "R1", "route_type": "1"}]
TRIPS = [{"route_id": "R1", "service_id": "WK", "trip_id": "T1"}]
STOPS = [{"stop_id": "S1", "stop_name": "UNO", "stop_lat": "40.83", "stop_lon": "14.23"}]
TIMES = [
    {
        "trip_id": "T1",
        "arrival_time": "08:00:00",
        "departure_time": "08:00:00",
        "stop_id": "S1",
        "stop_sequence": "1",
    }
]
DATES = [{"service_id": "WK", "date": "20261109", "exception_type": "1"}]


@pytest.fixture(autouse=True)
def fresh_cache() -> None:
    clear_feed_cache()


def feed_in(tmp_path: Path, **changes: Any) -> Path:
    """Un feed minimo valido (solo calendar_dates.txt, come quello di ANM), con le tabelle
    sostituite da `changes`; `None` toglie il file."""
    tables: dict[str, Any] = {
        "routes": ROUTES,
        "trips": TRIPS,
        "stops": STOPS,
        "stop_times": TIMES,
        "calendar_dates": DATES,
    }
    tables.update(changes)
    return write_gtfs(tmp_path / "feed", **{k: v for k, v in tables.items() if v is not None})


# --- lettura --------------------------------------------------------------------------------------


def test_carica_il_mini_feed() -> None:
    feed = load_feed(GTFS_FIXTURE)
    assert len(feed.stops) == 6 and len(feed.routes) == 6 and len(feed.trips) == 16
    assert len(feed.stop_times) == 31
    assert list(feed.stop_times.columns) == ["trip_id", "stop_id", "seq", "arr_s", "dep_s"]
    arconi = feed.stops[feed.stops["stop_id"] == "S3"].iloc[0]
    assert (arconi["stop_name"], arconi["lat"], arconi["lon"]) == ("ARCO MIRELLI", 40.8313, 14.2304)


def test_gli_orari_sono_secondi_dalla_mezzanotte() -> None:
    times = load_feed(GTFS_FIXTURE).stop_times
    row = times[(times["trip_id"] == "L1_C") & (times["seq"] == 2)].iloc[0]
    assert (row["arr_s"], row["dep_s"]) == (23 * 3600, 23 * 3600)
    first = times[(times["trip_id"] == "L1_A") & (times["seq"] == 1)].iloc[0]
    assert first["dep_s"] == 6 * 3600  # la riga di sequenza 1 non è la prima del file


def test_il_calendario_unisce_calendar_e_calendar_dates() -> None:
    dates = load_feed(GTFS_FIXTURE).service_dates
    assert dates[date(2025, 4, 24)] == frozenset({"WK"})  # giovedì
    assert dates[date(2025, 4, 26)] == frozenset({"SAT"})
    # 25/04/2025 è un venerdì: l'eccezione toglie WK e aggiunge SAT
    assert dates[date(2025, 4, 25)] == frozenset({"SAT"})
    assert dates[date(2025, 4, 27)] == frozenset({"SUN"})
    assert (load_feed(GTFS_FIXTURE).valid_from, load_feed(GTFS_FIXTURE).valid_to) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )


def test_feed_con_solo_calendar_dates(tmp_path: Path) -> None:
    """Come il feed ANM reale: nessun calendar.txt."""
    dates = [
        {"service_id": "A", "date": "20261114", "exception_type": "1"},
        {"service_id": "B", "date": "20261114", "exception_type": "1"},
        {"service_id": "A", "date": "20261115", "exception_type": "1"},
        {"service_id": "A", "date": "20261115", "exception_type": "2"},  # tolto lo stesso giorno
    ]
    feed = load_feed(feed_in(tmp_path, calendar_dates=dates))
    assert dict(feed.service_dates) == {date(2026, 11, 14): frozenset({"A", "B"})}


def test_la_lettura_a_blocchi_da_lo_stesso_risultato(monkeypatch: pytest.MonkeyPatch) -> None:
    whole = load_feed(GTFS_FIXTURE).stop_times
    clear_feed_cache()
    monkeypatch.setattr("app.data.gtfs.STOP_TIMES_CHUNK", 4)  # 31 righe in 8 blocchi
    chunked = load_feed(GTFS_FIXTURE).stop_times
    assert chunked.equals(whole)
    assert len(chunked) == 31


def test_il_feed_si_legge_una_volta_per_processo(tmp_path: Path) -> None:
    directory = feed_in(tmp_path)
    first = load_feed(directory)
    assert load_feed(directory) is first
    clear_feed_cache()
    assert load_feed(directory) is not first


def test_orario_mancante_si_completa_con_l_altro_e_oltre_le_24_ore(tmp_path: Path) -> None:
    def row(arrival: str, departure: str, sequence: int) -> dict[str, str]:
        return {**TIMES[0], "arrival_time": arrival, "departure_time": departure,
                "stop_sequence": str(sequence)}  # fmt: skip

    rows = [row("", "08:00:30", 1), row("25:30:00", "", 2), row("", "", 3)]
    times = load_feed(feed_in(tmp_path, stop_times=rows)).stop_times
    assert times["arr_s"].tolist()[:2] == [8 * 3600 + 30, 25 * 3600 + 30 * 60]
    assert times["dep_s"].tolist()[:2] == [8 * 3600 + 30, 25 * 3600 + 30 * 60]
    assert times["arr_s"].isna().tolist() == [False, False, True]  # senza nessun orario: NaN


# --- errori ---------------------------------------------------------------------------------------


def test_cartella_mancante_dice_cosa_fare(tmp_path: Path) -> None:
    with pytest.raises(GtfsError, match=r"Manca il feed GTFS .*nowhere.*make data"):
        load_feed(tmp_path / "nowhere")


@pytest.mark.parametrize("missing", ["stops", "routes", "trips", "stop_times"])
def test_file_obbligatorio_mancante(tmp_path: Path, missing: str) -> None:
    with pytest.raises(GtfsError, match=f"manca {missing}.txt"):
        load_feed(feed_in(tmp_path, **{missing: None}))


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("routes", "route_type"),
        ("trips", "service_id"),
        ("stops", "stop_lon"),
        ("stop_times", "arrival_time"),
        ("stop_times", "stop_sequence"),
    ],
)
def test_colonna_obbligatoria_mancante(tmp_path: Path, table: str, column: str) -> None:
    rows = {"routes": ROUTES, "trips": TRIPS, "stops": STOPS, "stop_times": TIMES}[table]
    without = [{k: v for k, v in row.items() if k != column} for row in rows]
    with pytest.raises(GtfsError, match=f"{table}.txt: mancano le colonne {column}"):
        load_feed(feed_in(tmp_path, **{table: without}))


def test_senza_calendario(tmp_path: Path) -> None:
    with pytest.raises(GtfsError, match="mancano sia calendar.txt sia calendar_dates.txt"):
        load_feed(feed_in(tmp_path, calendar_dates=None))


def test_calendario_vuoto(tmp_path: Path) -> None:
    removed = [{"service_id": "WK", "date": "20261109", "exception_type": "2"}]
    with pytest.raises(GtfsError, match="nessun giorno con servizio"):
        load_feed(feed_in(tmp_path, calendar_dates=removed))


def test_una_data_non_valida_non_sparisce_in_silenzio(tmp_path: Path) -> None:
    dates = [*DATES, {"service_id": "WK", "date": "2026-11-10", "exception_type": "1"}]
    with pytest.raises(GtfsError, match="1 date non valide"):
        load_feed(feed_in(tmp_path, calendar_dates=dates))


def test_fermata_senza_coordinate(tmp_path: Path) -> None:
    stops = [{"stop_id": "S1", "stop_name": "UNO", "stop_lat": "", "stop_lon": "14.2"}]
    with pytest.raises(GtfsError, match="fermate senza coordinate valide"):
        load_feed(feed_in(tmp_path, stops=stops))


def test_una_fermata_che_stops_non_ha(tmp_path: Path) -> None:
    rows = [{**TIMES[0], "stop_id": "S9"}, {**TIMES[0], "stop_id": "S1", "stop_sequence": "2"}]
    with pytest.raises(GtfsError, match="cita fermate che stops.txt non ha: S9"):
        load_feed(feed_in(tmp_path, stop_times=rows))


def test_sequenza_non_valida(tmp_path: Path) -> None:
    rows = [{**TIMES[0], "stop_sequence": "primo"}]
    with pytest.raises(GtfsError, match="senza stop_sequence valido"):
        load_feed(feed_in(tmp_path, stop_times=rows))


# --- giorno di servizio e orario tipo -------------------------------------------------------------


def saturdays(**patterns: list[date]) -> dict[date, frozenset[str]]:
    """Calendario di prova: ogni argomento è un servizio (A, B…) con le date in cui è attivo."""
    out: dict[date, set[str]] = {}
    for service, days in patterns.items():
        for day in days:
            out.setdefault(day, set()).add(service)
    return {day: frozenset(ids) for day, ids in out.items()}


def test_una_data_coperta_dal_feed_si_usa_com_e() -> None:
    calendar = saturdays(A=[date(2026, 11, 14)], B=[date(2026, 11, 14), date(2026, 11, 21)])
    day = service_day(calendar, date(2026, 11, 14))
    assert (day.requested, day.used, day.covered) == (date(2026, 11, 14),) * 2 + (True,)
    assert day.services == frozenset({"A", "B"})
    assert day.assumption is None


def test_fuori_dal_feed_l_orario_tipo_e_il_servizio_piu_frequente() -> None:
    sat = [date(2026, 11, d) for d in (14, 21, 28)] + [date(2026, 12, d) for d in (5, 12, 19, 26)]
    calendar = saturdays(
        A=sat[:2],  # 14 e 21 novembre
        B=sat[2:6],  # 28 novembre, 5, 12 e 19 dicembre: il più frequente
        H=[sat[6]],  # 26 dicembre: festività, servizio raro, e anche l'ultimo sabato
    )
    day = service_day(calendar, date(2027, 7, 10))  # sabato fuori dal feed
    assert (day.used, day.covered, day.services) == (date(2026, 12, 19), False, frozenset({"B"}))
    assert day.assumption == (
        "orario tipo del 19/12/2026 (sabato) applicato alla data dell'evento (10/07/2027): "
        "il feed non la copre"
    )


def test_a_parita_di_frequenza_vince_il_servizio_piu_recente() -> None:
    calendar = saturdays(
        A=[date(2026, 11, 14), date(2026, 11, 21)], B=[date(2026, 12, 5), date(2026, 12, 12)]
    )
    assert service_day(calendar, date(2027, 1, 2)).used == date(2026, 12, 12)  # fmt: skip


def test_ogni_giorno_della_settimana_ha_il_suo_orario_tipo() -> None:
    """Il venerdì non è un giorno feriale qualunque: nel feed ANM ha più corse della metro."""
    calendar = saturdays(
        MON=[date(2026, 11, 9), date(2026, 11, 16)],
        FRI=[date(2026, 11, 13), date(2026, 11, 20)],
    )
    assert service_day(calendar, date(2027, 3, 1)).services == frozenset({"MON"})  # un lunedì
    assert service_day(calendar, date(2027, 3, 5)).services == frozenset({"FRI"})  # un venerdì


def test_un_giorno_della_settimana_che_il_feed_non_ha() -> None:
    calendar = saturdays(A=[date(2026, 11, 14)])
    with pytest.raises(GtfsError, match="nessun domenica.*14|nessun domenica"):
        service_day(calendar, date(2027, 7, 11))  # una domenica


def test_un_giorno_dentro_il_feed_ma_senza_servizio_usa_l_orario_tipo() -> None:
    calendar = saturdays(A=[date(2026, 11, 14), date(2026, 11, 28)])  # niente sabato 21
    day = service_day(calendar, date(2026, 11, 21))
    assert (day.covered, day.used) == (False, date(2026, 11, 28))


# --- linee ----------------------------------------------------------------------------------------


def classification(**ids: list[str]) -> RouteClassification:
    config = EngineConfig.from_yaml().transit.route_classification
    return config.model_copy(
        update={
            name: type(getattr(config, name))(route_ids=route_ids)
            for name, route_ids in ids.items()
        }
    )


def test_classificazione_delle_linee_del_mini_feed() -> None:
    feed = load_feed(GTFS_FIXTURE)
    classes = classify_routes(
        feed, classification(metro_line_1=["R1"], metro_line_6=["R2"], funicular=["R3"])
    )
    assert classes.ids("metro_line_1") == frozenset({"R1"})
    assert classes.ids("metro_line_6") == frozenset({"R2"})
    assert classes.ids("funicular") == frozenset({"R3"})
    # bus = ogni altra linea di superficie: R4 (autobus) e R6 (filobus); non R5 (metro L2)
    assert classes.ids("bus") == frozenset({"R4", "R6"})
    assert [classes.of(r) for r in ("R1", "R2", "R3", "R4", "R5", "R6", "R9")] == [
        "metro_line_1", "metro_line_6", "funicular", "bus", None, "bus", None,
    ]  # fmt: skip


def test_una_linea_di_superficie_classificata_non_e_anche_bus() -> None:
    """Se engine.yaml mette un autobus (R4) tra le funicolari, per il motore è una funicolare."""
    feed = load_feed(GTFS_FIXTURE)
    classes = classify_routes(
        feed, classification(metro_line_1=["R1"], metro_line_6=["R2"], funicular=["R3", "R4"])
    )
    assert classes.ids("funicular") == frozenset({"R3", "R4"})
    assert classes.ids("bus") == frozenset({"R6"})
    assert classes.of("R4") == "funicular"


def test_fermate_servite_dalle_linee() -> None:
    feed = load_feed(GTFS_FIXTURE)
    served = stops_served_by_routes
    assert served(["R3"], feed.stop_times, feed.trips) == {"S6", "S2"}  # funicolare di Chiaia
    assert served(["R2"], feed.stop_times, feed.trips) == {"S3", "S1"}  # L6
    assert served(["R2", "R3"], feed.stop_times, feed.trips) == {"S1", "S2", "S3", "S6"}
    assert served([], feed.stop_times, feed.trips) == set()
    assert served(["R_che_non_c_e"], feed.stop_times, feed.trips) == set()


def test_i_tipi_di_superficie_sono_tram_autobus_e_filobus() -> None:
    assert {"0", "3", "11"} == SURFACE_ROUTE_TYPES


def test_un_route_id_di_config_che_il_feed_non_ha(tmp_path: Path) -> None:
    feed = load_feed(GTFS_FIXTURE)
    with pytest.raises(GtfsError) as error:
        classify_routes(
            feed, classification(metro_line_1=["R1", "X9"], metro_line_6=["R2"], funicular=["Y8"])
        )
    message = str(error.value)
    assert "funicular: Y8" in message and "metro_line_1: X9" in message
    assert "metro_line_6" not in message
    assert "Rilancia `scripts.data_report`" in message
