import json
import re
import shutil
import struct
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox
import pandas as pd
import pytest

from app.data.gtfs import read_table
from scripts import data_report
from scripts.common import write_meta
from scripts.data_report import (
    Issue,
    build_issues,
    build_report,
    interchange_m,
    load_gtfs,
    minutes_of,
    num,
    osm_stats,
    pct,
    read_pmtiles_header,
    route_type_lines,
    size_text,
    station_checks,
)
from scripts.prepare_osm import enrich_graph
from tests.support import GTFS_FIXTURE, make_zip

TODAY = date(2025, 6, 2)  # lunedì, dentro la validità del mini-GTFS (2025)
# Itinerari di prova coerenti con il mini-GTFS (le stazioni vere sono nel feed ANM, non qui).
FIXTURE_ITINERARIES = {
    "Linea 1": ("Rotonda Diaz", "Riviera di Chiaia"),
    "Linea 6": ("Rotonda Diaz", "Arco Mirelli"),
    "Funicolare di Chiaia": ("Chiaia funicolare",),
    "Funicolare di Mergellina": ("Mergellina",),  # linea assente dal mini-GTFS
}


# --- Costruzione di una cartella dati di prova -------------------------------------------------


def osm_graph(*, full_coverage: bool = False, with_streets: bool = True) -> "nx.MultiDiGraph[int]":
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph(crs="EPSG:4326")
    for node in (1, 2, 3, 4):
        graph.add_node(node, x=14.2 + node / 100, y=40.8 + node / 100, street_count=2)
    common: dict[str, Any] = {"oneway": False, "reversed": False}
    extra = {"lanes": "2", "maxspeed": "50"} if full_coverage else {}
    caracciolo = "Via Francesco Caracciolo" if with_streets else "Via Roma"
    doppio = "Viale Anton Dohrn; Via Francesco Caracciolo" if with_streets else "Via Napoli"
    graph.add_edge(1, 2, 0, osmid=1, highway="primary", name=caracciolo, length=1000.0,
                   **{"lanes": "2", "maxspeed": "50"}, **common)  # fmt: skip
    graph.add_edge(
        2, 3, 0, osmid=2, highway="residential", name=[doppio], length=500.0, **extra, **common
    )
    graph.add_edge(3, 4, 0, osmid=3, highway="residential", length=300.0, **extra, **common)
    enrich_graph(graph)
    return graph


def add_osm(data: Path, **kwargs: bool) -> Path:
    path = data / "osm" / "graph_drive.graphml"
    path.parent.mkdir(parents=True)
    ox.save_graphml(osm_graph(**kwargs), path)
    write_meta(path, source_url="https://overpass.test/interpreter",
               fetched_at="2026-11-07T10:00:00+01:00", license="ODbL", notes="prova")  # fmt: skip
    return path


def add_gtfs(data: Path) -> Path:
    gtfs = data / "gtfs"
    shutil.copytree(GTFS_FIXTURE, gtfs / "anm")
    zip_path = make_zip(GTFS_FIXTURE, gtfs / "anm_20250602.zip")
    write_meta(
        zip_path,
        source_url="https://anm.test/f.zip",
        fetched_at="2026-11-07T10:05:00+01:00",
        license="verificare",
        notes="prova",
    )
    return zip_path


def pmtiles_bytes(
    bounds: tuple[float, float, float, float] = (14.10, 40.78, 14.35, 40.92),
    min_zoom: int = 0,
    max_zoom: int = 15,
    tiles: int = 635,
) -> bytes:
    head = bytearray(127)
    head[:7] = b"PMTiles"
    head[7] = 3
    head[72:80] = struct.pack("<Q", tiles)
    head[99], head[100], head[101] = 1, min_zoom, max_zoom
    head[102:118] = struct.pack("<4i", *(round(v * 1e7) for v in bounds))
    return bytes(head) + b"dati-delle-tile"


def add_pmtiles(data: Path) -> Path:
    path = data / "tiles" / "napoli.pmtiles"
    path.parent.mkdir(parents=True)
    path.write_bytes(pmtiles_bytes())
    write_meta(path, source_url="https://build.protomaps.com/20261107.pmtiles",
               fetched_at="2026-11-07T10:10:00+01:00", license="OSM", notes="prova")  # fmt: skip
    return path


def probe_point(label: str, ok: bool = True) -> dict[str, Any]:
    summary = {"currentSpeed": 27, "freeFlowSpeed": 30, "confidence": 1, "frc": "FRC2",
               "geometry_points": 2, "geometry_length_m": 112.5}  # fmt: skip
    return {"id": label.lower().replace(" ", "_"), "label": label, "lat": 40.8, "lon": 14.2,
            "http_status": 200 if ok else 400, "ok": ok,
            "error": None if ok else "HTTP 400: nessuna strada",
            "summary": summary if ok else None, "raw": {} if ok else None}  # fmt: skip


def add_tomtom(data: Path, oks: tuple[bool, ...] = (True, True, True)) -> Path:
    path = data / "tomtom" / "probe_20261107T162753.json"
    path.parent.mkdir(parents=True)
    points = [probe_point(f"Punto {i}", ok) for i, ok in enumerate(oks, 1)]
    path.write_text(json.dumps({"fetched_at": "2026-11-07T16:27:53+01:00", "endpoint": "https://t.test/x",
                                "ok_points": sum(oks), "points": points}))  # fmt: skip
    write_meta(path, source_url="https://t.test/x", fetched_at="2026-11-07T16:27:53+01:00",
               license="TomTom", notes="prova")  # fmt: skip
    return path


def full_data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    add_osm(data), add_gtfs(data), add_pmtiles(data), add_tomtom(data)
    return data


@pytest.fixture
def itineraries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_report, "ITINERARY_STATIONS", FIXTURE_ITINERARIES)
    monkeypatch.setattr(
        data_report, "DEMO_DATE", date(2025, 6, 7)
    )  # un sabato coperto dal mini-GTFS


# --- Funzioni pure -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "decimals", "text"),
    [
        (13507, 0, "13.507"),
        (11.7, 1, "11,7"),
        (1603.1, 1, "1.603,1"),
        (0, 0, "0"),
        (1234567.891, 2, "1.234.567,89"),
    ],
)
def test_num_all_italiana(value: float, decimals: int, text: str) -> None:
    assert num(value, decimals) == text


def test_pct_size_minutes() -> None:
    assert pct(1, 8) == "12,5%" and pct(0, 5) == "0,0%" and pct(1, 0) == "-"
    assert (
        size_text(16_450) == "16 kB"
        and size_text(11_583_440) == "11,6 MB"
        and size_text(999_999) == "1.000 kB"
    )
    assert (
        minutes_of("25:30") == 25 * 60 + 30
        and minutes_of("07:23") == 443
        and minutes_of(None) is None
    )


def test_issue_rifiuta_livelli_sconosciuti() -> None:
    with pytest.raises(AssertionError):
        Issue("BOH", "x")


def test_route_type_lines() -> None:
    routes: list[dict[str, Any]] = [
        {
            "route_id": "1",
            "agency_id": "ANM",
            "short_name": "L1",
            "long_name": "METRO",
            "route_type": "1",
        },
        {
            "route_id": "2",
            "agency_id": "FS",
            "short_name": "L2",
            "long_name": None,
            "route_type": "1",
        },
        {
            "route_id": "3",
            "agency_id": "ANM",
            "short_name": None,
            "long_name": "FUNICOLARE X",
            "route_type": "7",
        },
        {
            "route_id": "4",
            "agency_id": "ANM",
            "short_name": "R7",
            "long_name": None,
            "route_type": "3",
        },
        {
            "route_id": "5",
            "agency_id": "ANM",
            "short_name": "140",
            "long_name": None,
            "route_type": "3",
        },
        {
            "route_id": "6",
            "agency_id": "ANM",
            "short_name": "9",
            "long_name": None,
            "route_type": "99",
        },
    ]
    lines = route_type_lines(routes)
    assert "- metro: L1, L2 (FS)" in lines  # l'agenzia compare solo se non è ANM
    assert "- funicolari: FUNICOLARE X" in lines  # senza nome breve, il lungo
    assert "- bus: 2 linee" in lines  # i bus solo contati
    assert "- tipo 99: 9" in lines  # tipo sconosciuto: nessun nome inventato
    assert lines[-1] == "- bus: 2 linee"  # i bus in fondo, i tipi rari prima


def test_read_pmtiles_header(tmp_path: Path) -> None:
    path = tmp_path / "t.pmtiles"
    path.write_bytes(
        pmtiles_bytes(bounds=(14.1, 40.78, 14.35, 40.92), min_zoom=2, max_zoom=14, tiles=77)
    )
    assert read_pmtiles_header(path) == {
        "version": 3, "tile_type": 1, "min_zoom": 2, "max_zoom": 14,
        "bounds": (14.1, 40.78, 14.35, 40.92), "tiles": 77,
    }  # fmt: skip


@pytest.mark.parametrize(
    "content", [b"", b"PMTiles", b"<html>" + b"x" * 200, b"PMTiles" + b"\x03" * 50]
)
def test_read_pmtiles_header_file_non_valido(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "t.pmtiles"
    path.write_bytes(content)
    assert read_pmtiles_header(path) is None


# --- OSM ---------------------------------------------------------------------------------------


def test_osm_stats() -> None:
    stats = osm_stats(osm_graph())
    assert (stats["nodes"], stats["edges"]) == (4, 3)
    assert stats["km"] == pytest.approx(1.8)
    assert (stats["lanes"], stats["speed"]) == (1, 1)  # solo il primo arco ha corsie e limite
    classes = dict(stats["classes"])
    assert classes["primary"] == {"edges": 1, "lanes": 1, "speed": 1, "km": 1.0}
    assert classes["residential"]["edges"] == 2 and classes["residential"]["km"] == pytest.approx(
        0.8
    )
    caracciolo, dohrn = (
        stats["streets"]["Via Francesco Caracciolo"],
        stats["streets"]["Viale Anton Dohrn"],
    )
    # L'arco col doppio nome conta in entrambe le strade.
    assert (caracciolo["edges"], caracciolo["km"]) == (2, pytest.approx(1.5))
    assert (dohrn["edges"], dohrn["km"]) == (1, pytest.approx(0.5))
    assert caracciolo["names"] == Counter(
        {"Via Francesco Caracciolo": 1, "Viale Anton Dohrn; Via Francesco Caracciolo": 1}
    )


# --- Fermate e stazioni ------------------------------------------------------------------------


def stops_table(*rows: tuple[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"stop_id": [r[0] for r in rows], "stop_name": [r[1] for r in rows],
         "stop_lat": ["40.0"] * len(rows), "stop_lon": ["14.0"] * len(rows)}
    )  # fmt: skip


def fixture_tables() -> dict[str, pd.DataFrame]:
    tables = {
        n: read_table(GTFS_FIXTURE, f"{n}.txt") for n in ("stops", "routes", "trips", "stop_times")
    }
    assert all(table is not None for table in tables.values())
    return tables  # type: ignore[return-value]


def test_station_checks_la_stazione_deve_stare_sulla_linea_giusta() -> None:
    tb = fixture_tables()
    checks = station_checks(
        tb["stops"], tb["stop_times"], tb["trips"],
        {"Linea 1": ["R1"], "Linea 6": ["R2"], "Funicolare di Chiaia": ["R3"]},
        {
            "Linea 1": ("Rotonda Diaz", "Arco Mirelli", "Mergellina"),
            "Linea 6": ("Riviera di Chiaia",),
            "Funicolare di Chiaia": ("Chiaia funicolare",),
            "Funicolare Centrale": ("Augusteo",),
        },
    )  # fmt: skip
    found = {(c["line"], c["station"]): [s["stop_id"] for s in c["stops"]] for c in checks}
    assert found[("Linea 1", "Rotonda Diaz")] == ["S1"]
    assert found[("Linea 1", "Arco Mirelli")] == ["S3"]  # S3 è la terza fermata di una corsa L1
    assert found[("Linea 1", "Mergellina")] == []  # S4 esiste ma la serve solo la L2 (FS)
    assert found[("Linea 6", "Riviera di Chiaia")] == []  # S2 esiste ma la L6 non ci passa
    assert found[("Funicolare di Chiaia", "Chiaia funicolare")] == ["S6"]
    centrale = next(c for c in checks if c["line"] == "Funicolare Centrale")
    assert centrale["line_found"] is False and centrale["stops"] == []
    first = next(c for c in checks if c["station"] == "Rotonda Diaz")["stops"][0]
    assert first == {"stop_id": "S1", "name": "ROTONDA DIAZ", "lat": 40.832, "lon": 14.235}


def test_interchange_m() -> None:
    def stop(stop_id: str, lat: float) -> dict[str, Any]:
        return {"stop_id": stop_id, "name": "MUNICIPIO", "lat": lat, "lon": 14.25}

    checks = [
        {
            "line": "Linea 1",
            "station": "Municipio",
            "stops": [stop("6329", 40.8400), stop("6330", 40.8401)],
        },
        {"line": "Linea 6", "station": "Municipio", "stops": [stop("6245", 40.84005)]},
    ]
    # La minima tra le coppie: 6329-6245 = 0.00005° = 5,6 m e 6330-6245 = 0.00005° = 5,6 m
    assert interchange_m(checks, "Municipio", "Linea 1", "Linea 6") == 6
    assert interchange_m(checks, "Municipio", "Linea 1", "Linea 9") is None
    same = [{"line": "Linea 1", "station": "X", "stops": [stop("1", 40.0)]},
            {"line": "Linea 6", "station": "X", "stops": [stop("1", 40.0)]}]  # fmt: skip
    assert (
        interchange_m(same, "X", "Linea 1", "Linea 6") is None
    )  # stessa fermata: nessun interscambio


# --- Caricamento GTFS -------------------------------------------------------------------------


def test_load_gtfs_sul_mini_feed(tmp_path: Path, itineraries: None) -> None:
    data = tmp_path / "data"
    add_gtfs(data)
    gtfs = load_gtfs(data, TODAY)
    assert gtfs is not None and gtfs["validation"]["errors"] == []
    assert gtfs["demo_covered"] is True
    assert gtfs["route_ids"] == {
        "Linea 1": ["R1"],
        "Linea 6": ["R2"],
        "Funicolare di Chiaia": ["R3"],
    }
    assert [a["stop_id"] for a in gtfs["arco"]] == ["S3"]
    assert gtfs["arco"][0]["metro"] is True and gtfs["arco"][0]["lines"] == ["L1", "L6"]
    assert gtfs["other_metro"] == ["L2 (FS)"]
    assert gtfs["file"]["sha256_ok"] is True and gtfs["zip"] == "anm_20250602.zip"


def test_load_gtfs_non_scaricato(tmp_path: Path) -> None:
    assert load_gtfs(tmp_path, TODAY) is None


# --- Report completo -------------------------------------------------------------------------


def issues_text(issues: list[Issue], level: str) -> str:
    return "\n".join(i.text for i in issues if i.level == level)


def test_report_completo(tmp_path: Path, itineraries: None) -> None:
    data = full_data_dir(tmp_path)
    text, incomplete = build_report(data, TODAY)
    assert incomplete is False
    for heading in (
        "# Report dati", "## Cosa devi decidere", "## Stato dei file", "## 1. Rete stradale",
        "## 2. Trasporto pubblico", "### Stazioni degli itinerari proposti", "### Arco Mirelli",
        "## 3. TomTom", "## 4. Base map", "## Verifiche non tecniche", "## Configurazione proposta",
    ):  # fmt: skip
        assert heading in text, heading
    assert "**In breve:**" in text and "Tutti i dati sono presenti e i checksum coincidono." in text
    assert "NON TROVATA" in text  # le funicolari assenti dal mini-GTFS
    assert not re.search(
        r"\b(nan|none|null)\b", text, re.IGNORECASE
    )  # nessun valore vuoto trapelato
    assert (
        "| sabato 2025-06-07 | 0 | nessuna corsa | 0 | 0 |" in text
    )  # funicolare senza corse il sabato
    assert '    metro_line_1: { route_ids: ["R1"] }' in text
    assert '    metro_line_6: { route_ids: ["R2"] }' in text
    assert '    funicular: { route_ids: ["R3"] }' in text
    assert "Build Protomaps usata: **2026-11-07**" in text and "Zoom 0–15" in text
    assert "- bus: 1 linee" in text and "- metro: L1, L2 (FS), L6" in text
    assert "| Punto 1 | dati | 27 / 30 km/h | 90,0% | 1 | FRC2 | 112 m |" in text
    # Il file della sonda è piccolo: kB, non "0,0 MB".
    assert "| Sonda TomTom | presente |" in text and " kB |" in text and "0,0 MB" not in text


def test_decisioni_nel_mini_feed(tmp_path: Path, itineraries: None) -> None:
    data = full_data_dir(tmp_path)
    gtfs, osm = load_gtfs(data, TODAY), data_report.load_osm(data)
    issues = build_issues(osm, gtfs, data_report.load_tomtom(data), data_report.load_pmtiles(data))
    decisioni, note = issues_text(issues, "DECISIONE"), issues_text(issues, "NOTA")
    assert "Orario tipo (Q5)" in decisioni and "dal 2025-01-01 al 2025-12-31" in decisioni
    assert "include la demo" in decisioni
    # Il sabato la L6 del mini-GTFS finisce alle 08:00 e la L1 alle 18:00: prima delle 21:30.
    assert (
        "Linea 6: nessuna corsa dopo le 21:30 il sabato (ultima partenza 08:00, ultimo arrivo 08:20"
        in decisioni
    )
    assert "Linea 1: nessuna corsa dopo le 21:30 il sabato (ultima partenza 18:00" in decisioni
    assert (
        "Funicolare di Chiaia: nessuna corsa dopo" not in decisioni
    )  # nessuna corsa il sabato: nulla da dire
    assert "«Funicolare Centrale» NON è nel feed" in decisioni
    assert "«Funicolare di Mergellina» NON è nel feed" in decisioni
    assert "Montesanto" not in decisioni and "EAV" in note  # Montesanto: nota attesa, non decisione
    assert "tutte le stazioni degli itinerari proposti" in decisioni
    assert (
        "Funicolare di Mergellina)" not in decisioni
    )  # linea assente: la sua stazione non è segnalata due volte
    assert "stop_id S3" in note and "altre linee metro fuori dall'MVP: L2 (FS)" in note
    assert "TomTom copre tutti i 3 punti" in note
    assert not any(i.level == "ATTENZIONE" for i in issues)


def test_issue_ordinate_per_urgenza(tmp_path: Path, itineraries: None) -> None:
    data = full_data_dir(tmp_path)
    shutil.rmtree(data / "tomtom")  # genera un ATTENZIONE
    text, incomplete = build_report(data, TODAY)
    assert incomplete is True
    section = text.split("## Cosa devi decidere")[1].split("## Stato dei file")[0]
    order = [m for m in ("[ATTENZIONE]", "[DECISIONE]", "[NOTA]") if m in section]
    assert order == ["[ATTENZIONE]", "[DECISIONE]", "[NOTA]"]
    assert section.index("[ATTENZIONE]") < section.index("[DECISIONE]") < section.index("[NOTA]")


def test_calendario_scaduto_e_demo_non_coperta(tmp_path: Path) -> None:
    data = tmp_path / "data"
    add_gtfs(data)
    issues = build_issues(None, load_gtfs(data, date(2026, 11, 7)), None, None)
    attenzioni = issues_text(issues, "ATTENZIONE")
    assert "SCADUTO (ultimo giorno 2025-12-31)" in attenzioni
    assert "NON copre la data della demo (sabato 2026-11-14)" in attenzioni
    assert "include la demo" not in issues_text(issues, "DECISIONE")


def test_stazioni_mancanti_con_gli_itinerari_veri_nel_mini_feed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    add_gtfs(data)  # nel mini-GTFS non esistono Piscinola, Garibaldi...
    decisioni = issues_text(build_issues(None, load_gtfs(data, TODAY), None, None), "DECISIONE")
    assert "queste stazioni NON esistono sulla linea indicata" in decisioni
    assert "Piscinola (Linea 1)" in decisioni and "San Pasquale (Linea 6)" in decisioni
    assert "Cimarosa (Funicolare di Chiaia)" in decisioni  # la linea c'è, la stazione no
    assert "Manzoni (Funicolare di Mergellina)" not in decisioni  # la linea non c'è: già segnalata


def test_tomtom_senza_copertura(tmp_path: Path) -> None:
    data = tmp_path / "data"
    add_tomtom(data, oks=(True, False, True))
    decisioni = issues_text(
        build_issues(None, None, data_report.load_tomtom(data), None), "DECISIONE"
    )
    assert "TomTom NON copre: Punto 2" in decisioni and "taglio n. 4" in decisioni
    text, _ = build_report(data)
    assert "**NESSUN DATO** (HTTP 400: nessuna strada)" in text


def test_osm_strade_mancanti_e_copertura(tmp_path: Path) -> None:
    data = tmp_path / "data"
    add_osm(data, with_streets=False)
    issues = build_issues(data_report.load_osm(data), None, None, None)
    assert "«Via Francesco Caracciolo» non compare" in issues_text(issues, "DECISIONE")
    assert "«Viale Anton Dohrn» non compare" in issues_text(issues, "DECISIONE")
    nota = issues_text(issues, "NOTA")
    assert (
        "la quota di archi con il numero di corsie è 33,3%" in nota
        and "limite di velocità 33,3%" in nota
    )
    text, _ = build_report(data)
    assert "**Viale Anton Dohrn:** NON TROVATA" in text

    full = tmp_path / "full"
    add_osm(full, full_coverage=True)
    assert "la quota di archi" not in issues_text(
        build_issues(data_report.load_osm(full), None, None, None), "NOTA"
    )


def test_checksum_diverso_e_segnalato(tmp_path: Path) -> None:
    data = tmp_path / "data"
    graph = add_osm(data)
    with graph.open("ab") as handle:
        handle.write(b"<!-- modificato -->")
    issues = build_issues(data_report.load_osm(data), None, None, None)
    assert "OSM: lo sha256 del file non coincide" in issues_text(issues, "ATTENZIONE")
    text, _ = build_report(data)
    assert (
        "**DIVERSO**" in text
        and "alcuni checksum non coincidono" not in text.split("## Stato dei file")[0] + ""
    )


def test_cartella_vuota(tmp_path: Path) -> None:
    text, incomplete = build_report(tmp_path)
    assert incomplete is True
    for command in ("prepare_osm", "prepare_gtfs", "tomtom_probe", "prepare_pmtiles"):
        assert f"scripts.{command}" in text
    assert text.count("NON DISPONIBILE") == 3 and "NON ESEGUITA" in text
    assert "**Mancano dei dati**" in text
    assert "## Configurazione proposta" not in text  # senza feed non si propone nulla


def test_feed_non_utilizzabile(tmp_path: Path) -> None:
    data = tmp_path / "data"
    add_gtfs(data)
    (data / "gtfs" / "anm" / "trips.txt").unlink()
    text, _ = build_report(data, TODAY)
    assert "Il feed GTFS non è utilizzabile" in text and "**Feed non utilizzabile:**" in text
    assert "## Configurazione proposta" not in text


# --- CLI -------------------------------------------------------------------------------------


def test_main_scrive_il_report_e_lo_stampa(
    tmp_path: Path, itineraries: None, capsys: pytest.CaptureFixture[str]
) -> None:
    data = full_data_dir(tmp_path)
    assert data_report.main(["--data-dir", str(data)]) in (
        0,
        1,
    )  # "oggi" reale: il mini-feed è scaduto
    report = data / "report" / "data_report.md"
    assert report.is_file() and not list((data / "report").glob("*.part"))
    out = capsys.readouterr()
    assert report.read_text(encoding="utf-8").strip() == out.out.strip()
    assert "Report salvato in" in out.err


def test_main_codice_di_uscita(
    tmp_path: Path, itineraries: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert data_report.main(["--data-dir", str(tmp_path / "vuota")]) == 1
    assert "manca almeno un artefatto" in capsys.readouterr().err
    assert (tmp_path / "vuota" / "report" / "data_report.md").is_file()  # il report c'è comunque
    assert data_report.main(["--data-dir", str(full_data_dir(tmp_path))]) == 0


def synthetic_gtfs(last_start: str) -> dict[str, Any]:
    """Un feed 'valido' minimo, con la sola Linea 6 e il sabato che finisce a `last_start`."""
    saturday = {"date": "2026-11-14", "trips": 10, "first_start": "07:00", "last_start": last_start,
                "last_end": "99:99", "trips_21_23": 0, "trips_12_18": 5}  # fmt: skip
    return {
        "validation": {
            "errors": [],
            "calendar": {
                "valid_from": "2026-11-09",
                "valid_to": "2026-12-31",
                "expired": False,
                "starts_in_future": False,
            },  # fmt: skip
            "lines_of_interest": [
                {"name": "Linea 6", "found": True, "routes": [], "days": {"saturday": saturday}}
            ],
        },
        "demo_covered": True,
        "route_ids": {},
        "stations": [],
        "municipio_interchange_m": None,
        "arco": [{"stop_id": "1", "name": "ARCO MIRELLI", "lines": ["L6"], "metro": True}],
        "other_metro": [],
        "file": {"sha256_ok": True},
    }


@pytest.mark.parametrize(
    ("last_start", "flagged"),
    [
        ("15:50", True),
        ("20:30", True),
        ("21:29", True),
        ("21:30", False),
        ("22:00", False),
        ("25:30", False),
    ],
)
def test_soglia_della_sera_ai_bordi(last_start: str, flagged: bool) -> None:
    issues = build_issues(None, synthetic_gtfs(last_start), None, None)
    assert (
        "Linea 6: nessuna corsa dopo le 21:30 il sabato" in issues_text(issues, "DECISIONE")
    ) is flagged
