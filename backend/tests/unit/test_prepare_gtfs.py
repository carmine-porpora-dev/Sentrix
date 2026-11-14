import json
import shutil
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.data.gtfs import read_table, services_by_date, to_seconds
from scripts import prepare_gtfs
from scripts.prepare_gtfs import (
    FeedError,
    check_zip,
    format_seconds,
    pick_reference_day,
    validate_feed,
)
from tests.support import FeedServer, make_zip

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mini_gtfs"
TODAY_VALID = date(2025, 6, 2)  # lunedì, dentro la validità del feed di prova (2025)
TODAY_EXPIRED = date(2026, 11, 7)


def line(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(entry for entry in result["lines_of_interest"] if entry["name"] == name)


def copy_fixture(tmp_path: Path, *, drop: tuple[str, ...] = ()) -> Path:
    target = tmp_path / "feed"
    shutil.copytree(FIXTURE, target)
    for name in drop:
        (target / name).unlink()
    return target


# --- Orari -----------------------------------------------------------------------------


def test_to_seconds_accetta_ore_oltre_24_e_scarta_il_resto() -> None:
    series = pd.Series(["06:00:00", "25:30:00", " 7:05:09", "", None, "abc", "12:5:00"])
    seconds = to_seconds(series).tolist()
    assert seconds[0] == 6 * 3600
    assert seconds[1] == 25 * 3600 + 30 * 60
    assert seconds[2] == 7 * 3600 + 5 * 60 + 9
    assert all(pd.isna(v) for v in seconds[3:])


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "00:00"),
        (21600, "06:00"),
        (91800, "25:30"),
        (45359, "12:35"),
        (23 * 3600 + 59 * 60 + 59, "23:59"),
    ],
)
def test_format_seconds(seconds: int, text: str) -> None:
    assert format_seconds(seconds) == text


# --- Calendario ------------------------------------------------------------------------


def test_services_by_date_applica_le_eccezioni() -> None:
    calendar, dates = read_table(FIXTURE, "calendar.txt"), read_table(FIXTURE, "calendar_dates.txt")
    by_date, invalid = services_by_date(calendar, dates)
    assert invalid == 0
    assert by_date[date(2025, 6, 6)] == {"WK"}  # venerdì normale
    assert by_date[date(2025, 6, 7)] == {"SAT"}
    assert by_date[date(2025, 6, 8)] == {"SUN"}
    assert by_date[date(2025, 4, 25)] == {"SAT"}  # WK tolto, SAT aggiunto
    assert date(2024, 12, 31) not in by_date and date(2026, 1, 1) not in by_date


def test_services_by_date_solo_calendar_dates_e_date_non_valide() -> None:
    dates = pd.DataFrame(
        {
            "service_id": ["A", "A", "B", "C"],
            "date": ["20261113", "20261114", "20261114", "31/12"],
            "exception_type": ["1", "1", "1", "1"],
        }
    )
    by_date, invalid = services_by_date(None, dates)
    assert by_date == {date(2026, 11, 13): {"A"}, date(2026, 11, 14): {"A", "B"}}
    assert invalid == 1


def test_services_by_date_una_rimozione_che_svuota_il_giorno_lo_elimina() -> None:
    dates = pd.DataFrame(
        {"service_id": ["A", "A"], "date": ["20261113", "20261113"], "exception_type": ["1", "2"]}
    )
    assert services_by_date(None, dates) == ({}, 0)


def test_pick_reference_day() -> None:
    fridays = [date(2025, 1, 3), date(2025, 6, 6), date(2025, 12, 26)]
    assert pick_reference_day(fridays, 4, date(2025, 6, 6)) == (
        date(2025, 6, 6),
        False,
    )  # oggi incluso
    assert pick_reference_day(fridays, 4, date(2025, 6, 7)) == (date(2025, 12, 26), False)
    assert pick_reference_day(fridays, 4, date(2026, 1, 1)) == (date(2025, 12, 26), True)  # scaduto
    assert pick_reference_day(fridays, 5, date(2025, 6, 1)) is None  # nessun sabato


# --- Validazione sul mini-GTFS ---------------------------------------------------------


def test_validazione_feed_valido() -> None:
    result = validate_feed(FIXTURE, TODAY_VALID)
    assert result["errors"] == [] and result["warnings"] == []
    assert result["files"]["has_calendar"] and result["files"]["has_calendar_dates"]
    assert result["files"]["has_feed_info"] and result["files"]["missing_required"] == []
    assert result["feed_info"]["feed_version"] == "test-1"
    assert result["counts"] == {"routes": 6, "trips": 16, "stops": 6, "stop_times": 31}
    assert result["route_type_counts"] == {"1": 3, "7": 1, "3": 1, "11": 1}
    cal = result["calendar"]
    assert (cal["valid_from"], cal["valid_to"]) == ("2025-01-01", "2025-12-31")
    assert cal["expired"] is False and cal["starts_in_future"] is False
    assert cal["reference_days"] == {
        "friday": {"date": "2025-06-06", "from_expired_feed": False},
        "saturday": {"date": "2025-06-07", "from_expired_feed": False},
    }


def test_linea_1_venerdi_e_sabato() -> None:
    l1 = line(validate_feed(FIXTURE, TODAY_VALID), "Linea 1")
    assert l1["found"] and [r["route_id"] for r in l1["routes"]] == ["R1"]  # non la L2 delle FS
    assert l1["days"]["friday"] == {
        "date": "2025-06-06",
        "trips": 5,  # A, B, C, D, E
        "trips_without_times": 1,  # L1_X non ha stop_times
        "first_start": "06:00",
        "last_start": "25:30",  # oltre la mezzanotte
        "last_end": "25:45",
        "trips_21_23": 2,  # 21:30 e 22:45; 23:00 è fuori (fine esclusa)
        "trips_12_18": 0,
    }
    assert l1["days"]["saturday"] == {
        "date": "2025-06-07",
        "trips": 3,
        "trips_without_times": 0,
        "first_start": "07:00",
        "last_start": "18:00",
        "last_end": "18:10",
        "trips_21_23": 0,
        "trips_12_18": 1,  # 12:00 incluso, 18:00 escluso
    }


def test_ultimo_arrivo_usa_la_sequenza_non_l_ordine_del_file() -> None:
    # In stop_times.txt la fermata con stop_sequence 3 di L1_A (06:10) è scritta per prima.
    friday = line(validate_feed(FIXTURE, TODAY_VALID), "Linea 1")["days"]["friday"]
    assert friday["first_start"] == "06:00"  # non 06:10


def test_linea_6_chiude_presto() -> None:
    l6 = line(validate_feed(FIXTURE, TODAY_VALID), "Linea 6")
    assert l6["days"]["friday"] == {
        "date": "2025-06-06",
        "trips": 2,
        "trips_without_times": 0,
        "first_start": "07:23",
        "last_start": "15:50",
        "last_end": "16:10",
        "trips_21_23": 0,
        "trips_12_18": 1,
    }
    assert l6["days"]["saturday"]["trips"] == 1 and l6["days"]["saturday"]["last_end"] == "08:20"


def test_funicolare_cercata_per_tipo_e_nome() -> None:
    result = validate_feed(FIXTURE, TODAY_VALID)
    chiaia = line(result, "Funicolare di Chiaia")
    # R3 è tipo 7; R4 'ASCENSORE CHIAIA' è un bus (tipo 3): non è la funicolare.
    assert [r["route_id"] for r in chiaia["routes"]] == ["R3"]
    assert chiaia["days"]["friday"]["trips"] == 2
    assert chiaia["days"]["friday"]["trips_21_23"] == 1  # 22:00
    assert chiaia["days"]["friday"]["last_end"] == "22:06"
    assert chiaia["days"]["saturday"]["trips"] == 0
    assert chiaia["days"]["saturday"]["first_start"] is None  # nessuna corsa il sabato
    for missing in ("Funicolare Centrale", "Funicolare di Montesanto", "Funicolare di Mergellina"):
        entry = line(result, missing)
        assert entry["found"] is False and entry["routes"] == [] and entry["days"] == {}


def test_fermate_entro_800_m_da_rotonda_diaz() -> None:
    near = validate_feed(FIXTURE, TODAY_VALID)["stops_near_rotonda_diaz"]
    assert near["radius_m"] == 800 and near["center"] == [40.8320, 14.2350]
    stops = near["stops"]
    # Distanze con formula indipendente: 0, 112.46, 394.77, 475.83 m. S4 (1535 m) e S5 sono fuori.
    assert [(s["stop_id"], s["distance_m"]) for s in stops] == [
        ("S1", 0),
        ("S2", 112),
        ("S3", 395),
        ("S6", 476),
    ]
    assert [s["lines"] for s in stops] == [
        ["L1", "L6"],
        ["CHIAIA", "F1", "L1"],
        ["L1", "L6"],  # L1 solo come terza fermata di L1_A
        ["CHIAIA", "F1"],
    ]
    assert stops[2]["stop_name"] == "ARCO MIRELLI"


def test_calendario_scaduto_usa_l_ultimo_giorno_valido() -> None:
    cal = validate_feed(FIXTURE, TODAY_EXPIRED)["calendar"]
    assert cal["expired"] is True and cal["starts_in_future"] is False
    assert cal["reference_days"] == {
        "friday": {"date": "2025-12-26", "from_expired_feed": True},
        "saturday": {"date": "2025-12-27", "from_expired_feed": True},
    }


def test_calendario_non_ancora_in_vigore() -> None:
    result = validate_feed(FIXTURE, date(2024, 12, 1))
    assert result["calendar"]["starts_in_future"] is True and result["calendar"]["expired"] is False
    assert result["calendar"]["reference_days"]["friday"]["date"] == "2025-01-03"


def test_venerdi_festivo_usa_l_orario_del_sabato() -> None:
    # 2025-04-25 è venerdì ma calendar_dates toglie WK e aggiunge SAT.
    result = validate_feed(FIXTURE, date(2025, 4, 20))
    assert result["calendar"]["reference_days"]["friday"]["date"] == "2025-04-25"
    assert line(result, "Linea 1")["days"]["friday"]["trips"] == 3  # le corse del sabato


def test_feed_senza_calendar_txt_come_quello_reale_anm(tmp_path: Path) -> None:
    feed = copy_fixture(tmp_path, drop=("calendar.txt", "feed_info.txt"))
    (feed / "calendar_dates.txt").write_text(
        "service_id,date,exception_type\nWK,20261109,1\nWK,20261113,1\nSAT,20261114,1\nSAT,20261121,1\n"
    )
    result = validate_feed(feed, date(2026, 11, 7))
    assert result["errors"] == [] and result["feed_info"] is None
    assert result["files"]["has_calendar"] is False and result["files"]["has_feed_info"] is False
    cal = result["calendar"]
    assert (cal["valid_from"], cal["valid_to"], cal["service_dates"]) == (
        "2026-11-09",
        "2026-11-21",
        4,
    )
    assert cal["starts_in_future"] is True and cal["expired"] is False
    assert cal["reference_days"]["friday"]["date"] == "2026-11-13"
    assert cal["reference_days"]["saturday"]["date"] == "2026-11-14"
    l1 = line(result, "Linea 1")["days"]
    assert (l1["friday"]["trips"], l1["saturday"]["trips"]) == (5, 3)


def test_json_senza_nan_per_i_campi_vuoti() -> None:
    result = validate_feed(FIXTURE, TODAY_VALID)
    text = json.dumps(result, allow_nan=False)  # solleva ValueError se c'è un NaN
    route = next(r for r in result["routes"] if r["route_id"] == "R6")
    assert route["long_name"] is None and route["short_name"] == "201"
    assert '"nan"' not in text.lower()


# --- Feed non valido -------------------------------------------------------------------


def test_file_obbligatorio_mancante(tmp_path: Path) -> None:
    result = validate_feed(copy_fixture(tmp_path, drop=("trips.txt",)), TODAY_VALID)
    assert any("trips.txt" in e for e in result["errors"])
    assert result["files"]["missing_required"] == ["trips.txt"]
    assert "calendar" not in result  # niente analisi su un feed inutilizzabile


def test_nessun_calendario(tmp_path: Path) -> None:
    result = validate_feed(
        copy_fixture(tmp_path, drop=("calendar.txt", "calendar_dates.txt")), TODAY_VALID
    )
    assert any("calendario" in e for e in result["errors"])


def test_colonna_obbligatoria_mancante(tmp_path: Path) -> None:
    feed = copy_fixture(tmp_path)
    (feed / "stops.txt").write_text("stop_id,stop_name,stop_lon\nS1,X,14.2\n")
    result = validate_feed(feed, TODAY_VALID)
    assert any("stops.txt" in e and "stop_lat" in e for e in result["errors"])


def test_orari_malformati_producono_un_avviso(tmp_path: Path) -> None:
    feed = copy_fixture(tmp_path)
    with (feed / "stop_times.txt").open("a") as handle:
        handle.write("L1_A,xx,yy,S1,9\n")
    result = validate_feed(feed, TODAY_VALID)
    assert any("1 orari di partenza" in w for w in result["warnings"])


def test_calendario_senza_giorni_con_servizio(tmp_path: Path) -> None:
    feed = copy_fixture(tmp_path, drop=("calendar.txt",))
    (feed / "calendar_dates.txt").write_text("service_id,date,exception_type\nWK,20250425,2\n")
    assert any("nessun giorno" in e for e in validate_feed(feed, TODAY_VALID)["errors"])


def test_bom_nei_file_viene_ignorato(tmp_path: Path) -> None:
    feed = copy_fixture(tmp_path)
    stops = feed / "stops.txt"
    stops.write_bytes(b"\xef\xbb\xbf" + stops.read_bytes())
    assert validate_feed(feed, TODAY_VALID)["errors"] == []


# --- Zip -------------------------------------------------------------------------------


def test_check_zip_valido(tmp_path: Path) -> None:
    check_zip(make_zip(FIXTURE, tmp_path / "ok.zip"))


def test_check_zip_non_e_uno_zip(tmp_path: Path) -> None:
    junk = tmp_path / "junk.zip"
    junk.write_text("<html>pagina di errore</html>")
    with pytest.raises(FeedError, match="corrotto o non valido"):
        check_zip(junk)


@pytest.mark.parametrize("name", ["../evil.txt", "/tmp/evil.txt", "a/../../evil.txt"])
def test_check_zip_percorsi_non_sicuri(tmp_path: Path, name: str) -> None:
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr(name, "x")
    with pytest.raises(FeedError, match="percorso non sicuro"):
        check_zip(bad)


def test_check_zip_troppo_grande(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prepare_gtfs, "MAX_UNZIPPED_BYTES", 100)
    with pytest.raises(FeedError, match="supera 100 byte"):
        check_zip(make_zip(FIXTURE, tmp_path / "big.zip"))


# --- Flusso completo -------------------------------------------------------------------


def copy_zip_download(source: Path) -> tuple[Any, list[str]]:
    calls: list[str] = []

    def fake(url: str, target: Path) -> dict[str, str]:
        calls.append(url)
        shutil.copy(source, target)
        return {"Content-Type": "application/zip"}

    return fake, calls


def test_prepare_flusso_completo_e_idempotenza(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = make_zip(FIXTURE, tmp_path / "src.zip")
    fake, calls = copy_zip_download(source)
    data = tmp_path / "data"

    assert (
        prepare_gtfs.prepare(
            data, "https://esempio.it/f.zip", force=False, today=date(2025, 6, 2), download=fake
        )
        == 0
    )
    gtfs = data / "gtfs"
    assert (gtfs / "anm_20250602.zip").is_file() and (gtfs / "anm_20250602.zip.meta.json").is_file()
    assert (gtfs / "anm" / "stops.txt").is_file()
    assert not list(gtfs.glob("*incoming*")) and not list(gtfs.glob("*.part"))
    meta = json.loads((gtfs / "anm_20250602.zip.meta.json").read_text())
    assert set(meta) == {"source_url", "fetched_at", "license", "sha256", "notes"}
    assert meta["source_url"] == "https://esempio.it/f.zip" and "IODL 2.0" in meta["license"]
    assert not list(gtfs.glob("*validation*"))  # la validazione si stampa, non si salva
    first_run = capsys.readouterr().out
    assert "Calendario: 2025-01-01 -> 2025-12-31" in first_run and "SCADUTO" not in first_run
    assert calls == ["https://esempio.it/f.zip"]

    # Seconda esecuzione, giorno diverso: il download è saltato ma la validazione si rifà.
    assert (
        prepare_gtfs.prepare(
            data, "https://esempio.it/f.zip", force=False, today=date(2026, 11, 7), download=fake
        )
        == 0
    )
    assert len(calls) == 1
    second_run = capsys.readouterr().out
    assert "download saltato" in second_run
    assert "ATTENZIONE: calendario SCADUTO" in second_run  # riconvalidato con il nuovo "oggi"

    # --force: riscarica e sostituisce la cartella estratta (nessun file vecchio residuo).
    (gtfs / "anm" / "residuo.txt").write_text("vecchio")
    assert (
        prepare_gtfs.prepare(
            data, "https://esempio.it/f.zip", force=True, today=date(2026, 11, 7), download=fake
        )
        == 0
    )
    assert len(calls) == 2
    assert not (gtfs / "anm" / "residuo.txt").exists()
    assert (gtfs / "anm_20261107.zip").is_file()


def test_prepare_zip_corrotto_non_distrugge_i_dati_buoni(
    server: FeedServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert (
        prepare_gtfs.prepare(data, f"{server.url}/feed.zip", force=False, today=date(2025, 6, 2))
        == 0
    )
    gtfs = data / "gtfs"
    before = {p.name: p.read_bytes() for p in gtfs.glob("*") if p.is_file()}

    assert (
        prepare_gtfs.prepare(data, f"{server.url}/garbage", force=True, today=date(2025, 6, 2)) == 1
    )
    assert "corrotto o non valido" in capsys.readouterr().err
    after = {p.name: p.read_bytes() for p in gtfs.glob("*") if p.is_file()}
    assert after == before  # zip, meta e validazione invariati
    assert (gtfs / "anm" / "stops.txt").is_file()
    assert not list(gtfs.glob("*incoming*"))


def test_prepare_404_esce_con_1_e_scrive_su_stderr(
    server: FeedServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert prepare_gtfs.prepare(tmp_path, f"{server.url}/manca", force=False) == 1
    assert "HTTP 404" in capsys.readouterr().err
    assert not (tmp_path / "gtfs" / "anm").exists()


def test_prepare_feed_inutilizzabile_esce_con_1_e_dice_perche(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    feed = copy_fixture(tmp_path, drop=("trips.txt",))
    fake, _ = copy_zip_download(make_zip(feed, tmp_path / "broken.zip"))
    data = tmp_path / "data"
    assert (
        prepare_gtfs.prepare(
            data, "https://esempio.it/f.zip", force=False, today=date(2025, 6, 2), download=fake
        )
        == 1
    )
    assert "ERRORE: File obbligatori mancanti: trips.txt" in capsys.readouterr().out
    assert (data / "gtfs" / "anm_20250602.zip").is_file()  # il feed scaricato resta per ispezione


def test_main_con_url_file_locale(tmp_path: Path) -> None:
    source = make_zip(FIXTURE, tmp_path / "local.zip")
    assert prepare_gtfs.main(["--data-dir", str(tmp_path / "d"), "--url", source.as_uri()]) == 0
    assert (tmp_path / "d" / "gtfs" / "anm" / "stops.txt").is_file()


def test_riepilogo_a_video_linea_senza_corse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nel mini-GTFS la funicolare di Chiaia non ha corse il sabato: niente "None-None".
    fake, _ = copy_zip_download(make_zip(FIXTURE, tmp_path / "src.zip"))
    prepare_gtfs.prepare(
        tmp_path / "d", "https://esempio.it/f.zip", force=False, today=TODAY_VALID, download=fake
    )
    out = capsys.readouterr().out
    assert "None" not in out
    assert "Funicolare di Chiaia       sat 2025-06-07:   0 corse, nessuna corsa," in out
