import hashlib
import json
from collections import Counter
from pathlib import Path

import networkx as nx
import osmnx as ox
import pytest

from app.data.osm_graph import load_osm_graph
from scripts import prepare_osm
from scripts.prepare_osm import (
    DownloadError,
    download_with_retry,
    enrich_graph,
    parse_lanes,
    parse_maxspeed,
)

NAN = float("nan")
BBOX = (14.14, 40.80, 14.30, 40.90)


# --- Parser --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2", 2),
        (" 3 ", 3),
        (2, 2),
        ("2.0", 2),
        ("2;3", 2),  # più valori: il minimo (collo di bottiglia)
        (["3", "2"], 2),
        (["2", "3"], 2),
        ("1;none", 1),
        ("0", None),
        ("-1", None),
        ("2.5", None),
        ("two", None),
        ("", None),
        (None, None),
        (NAN, None),
        ([], None),
    ],
)
def test_parse_lanes(value: object, expected: int | None) -> None:
    assert parse_lanes(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("50", 50),
        ("  60  ", 60),
        (50, 50),
        (50.0, 50),
        ("50 km/h", 50),
        ("30 mph", 48),  # 48,28
        ("50 mph", 80),  # 80,47
        ("50;70", 50),
        (["50", "70"], 50),
        (["50", "30 mph"], 48),
        (["50", "signals"], 50),
        ("IT:urban", None),  # simbolico: nessun numero inventato, ci pensa il motore
        ("IT:rural", None),
        ("none", None),
        ("signals", None),
        ("walk", None),
        ("0", None),
        ("", None),
        (None, None),
        (NAN, None),
        ([], None),
    ],
)
def test_parse_maxspeed(value: object, expected: int | None) -> None:
    assert parse_maxspeed(value) == expected


# --- Arricchimento -------------------------------------------------------------------


def make_graph() -> nx.MultiDiGraph:
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph(crs="EPSG:4326")
    graph.add_node(1, x=14.20, y=40.83, street_count=3)
    graph.add_node(2, x=14.21, y=40.84, street_count=3)
    graph.add_node(3, x=14.22, y=40.85, street_count=2)
    common = {"oneway": False, "reversed": False}
    graph.add_edge(
        1,
        2,
        0,
        osmid=100,
        highway="primary",
        lanes="2",
        maxspeed="50",
        name="Via Francesco Caracciolo",
        length=120.5,
        **common,
    )
    graph.add_edge(
        2,
        3,
        0,
        osmid=[101, 102],
        highway=["secondary", "tertiary"],
        lanes=["2", "3"],
        maxspeed="30 mph",
        name=["Via A", "Via B", "Via A"],
        length=80.0,
        **common,
    )
    graph.add_edge(
        3, 1, 0, osmid=103, highway="residential", maxspeed="IT:urban", length=40.0, **common
    )  # niente lanes, niente name
    return graph


def test_enrich_graph_attributi_e_conteggi() -> None:
    graph = make_graph()
    report = enrich_graph(graph)

    first, second, third = (graph.edges[1, 2, 0], graph.edges[2, 3, 0], graph.edges[3, 1, 0])
    assert (first["length_m"], first["highway"], first["lanes"], first["maxspeed_kmh"]) == (
        120.5,
        "primary",
        2,
        50,
    )
    assert first["name"] == "Via Francesco Caracciolo"
    assert (second["highway"], second["lanes"], second["maxspeed_kmh"]) == ("secondary", 2, 48)
    assert second["name"] == "Via A; Via B"  # unici, in ordine
    # Tag mancante o non numerico -> attributo assente, nessun valore di riserva.
    assert "lanes" not in third
    assert "maxspeed_kmh" not in third
    assert "name" not in third
    # Il tag grezzo e osmid restano com'erano.
    assert third["maxspeed"] == "IT:urban"
    assert second["osmid"] == [101, 102]

    assert report.edges == 3
    assert report.lanes_parsed == 2
    assert report.maxspeed_parsed == 2
    assert report.maxspeed_unparsed == Counter({"IT:urban": 1})
    assert report.lanes_unparsed == Counter()
    assert report.missing_highway == 0


def test_enrich_graph_senza_highway_e_lanes_non_numerico() -> None:
    graph: nx.MultiDiGraph[int] = nx.MultiDiGraph()
    graph.add_edge(1, 2, 0, osmid=1, length=10, lanes="many", highway=NAN)
    report = enrich_graph(graph)
    edge = graph.edges[1, 2, 0]
    assert "highway" not in edge
    assert "lanes" not in edge  # il grezzo non numerico non resta con un tipo ambiguo
    assert report.missing_highway == 1
    assert report.lanes_unparsed == Counter({"many": 1})


def test_graphml_salva_e_ricarica_con_i_tipi_giusti(tmp_path: Path) -> None:
    graph = make_graph()
    enrich_graph(graph)
    path = tmp_path / "g.graphml"
    ox.save_graphml(graph, path)
    loaded = load_osm_graph(path)

    first, second, third = (loaded.edges[1, 2, 0], loaded.edges[2, 3, 0], loaded.edges[3, 1, 0])
    assert isinstance(first["lanes"], int) and first["lanes"] == 2
    assert isinstance(first["maxspeed_kmh"], int) and first["maxspeed_kmh"] == 50
    assert isinstance(first["length_m"], float) and first["length_m"] == 120.5
    assert second["highway"] == "secondary"
    assert second["name"] == "Via A; Via B"
    assert "lanes" not in third and "maxspeed_kmh" not in third and "name" not in third


# --- Retry ---------------------------------------------------------------------------


class FlakyDownload:
    def __init__(self, failures: int, error: Exception) -> None:
        self.failures, self.error, self.calls = failures, error, 0

    def __call__(self, bbox: tuple[float, float, float, float]) -> nx.MultiDiGraph:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return make_graph()


def test_retry_riesce_dopo_due_errori_con_le_attese_previste() -> None:
    flaky = FlakyDownload(2, ConnectionError("giù"))
    waits: list[float] = []
    graph = download_with_retry(BBOX, download=flaky, sleep=waits.append)
    assert graph.number_of_edges() == 3
    assert flaky.calls == 3
    assert waits == [10, 30]


def test_retry_esaurito_solleva_errore_con_istruzioni() -> None:
    flaky = FlakyDownload(99, TimeoutError("lento"))
    waits: list[float] = []
    with pytest.raises(DownloadError) as info:
        download_with_retry(BBOX, download=flaky, sleep=waits.append)
    assert flaky.calls == 4  # 1 tentativo + 3 nuovi
    assert waits == [10, 30, 60]
    message = str(info.value)
    assert (
        "4 tentativi" in message and "TimeoutError" in message and "graph_drive.graphml" in message
    )


def test_retry_errore_non_di_rete_non_si_riprova() -> None:
    flaky = FlakyDownload(99, ValueError("bbox sbagliato"))
    waits: list[float] = []
    with pytest.raises(ValueError, match="bbox sbagliato"):
        download_with_retry(BBOX, download=flaky, sleep=waits.append)
    assert flaky.calls == 1
    assert waits == []


# --- Flusso completo (download simulato) ---------------------------------------------


@pytest.fixture
def fake_download(monkeypatch: pytest.MonkeyPatch) -> list[tuple[float, ...]]:
    calls: list[tuple[float, ...]] = []

    def fake(bbox: tuple[float, float, float, float]) -> nx.MultiDiGraph:
        calls.append(bbox)
        return make_graph()

    monkeypatch.setattr(prepare_osm, "download_graph", fake)
    return calls


def test_main_scrive_grafo_e_meta_poi_e_idempotente(
    tmp_path: Path, fake_download: list[tuple[float, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert prepare_osm.main(["--data-dir", str(tmp_path)]) == 0
    graph_path = tmp_path / "osm" / "graph_drive.graphml"
    meta_path = tmp_path / "osm" / "graph_drive.graphml.meta.json"
    assert graph_path.is_file() and meta_path.is_file()
    assert not list((tmp_path / "osm").glob("*.part"))
    assert fake_download == [BBOX]

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert set(meta) == {"source_url", "fetched_at", "license", "sha256", "notes"}
    assert meta["sha256"] == hashlib.sha256(graph_path.read_bytes()).hexdigest()
    assert meta["source_url"].startswith("https://") and meta["source_url"].endswith("/interpreter")
    assert meta["fetched_at"].endswith("+01:00") or meta["fetched_at"].endswith(
        "+02:00"
    )  # Europe/Rome
    assert "OpenStreetMap" in meta["license"]
    assert "3 nodi, 3 archi" in meta["notes"]
    out = capsys.readouterr().out
    assert "Archi con lanes numerico: 2 (66.7%)" in out
    assert "'IT:urban': 1" in out

    # Seconda esecuzione: salta senza scaricare.
    assert prepare_osm.main(["--data-dir", str(tmp_path)]) == 0
    assert len(fake_download) == 1
    assert "salto" in capsys.readouterr().out

    # --force: riscarica.
    assert prepare_osm.main(["--data-dir", str(tmp_path), "--force"]) == 0
    assert len(fake_download) == 2


def test_main_rifa_se_manca_il_meta(tmp_path: Path, fake_download: list[tuple[float, ...]]) -> None:
    prepare_osm.main(["--data-dir", str(tmp_path)])
    (tmp_path / "osm" / "graph_drive.graphml.meta.json").unlink()
    assert prepare_osm.main(["--data-dir", str(tmp_path)]) == 0
    assert len(fake_download) == 2  # grafo senza meta = esecuzione interrotta: si rifà


def test_main_errore_di_download_esce_con_1_e_non_lascia_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def always_down(bbox: object, **kwargs: object) -> nx.MultiDiGraph:
        raise DownloadError("Overpass non raggiungibile dopo 4 tentativi")

    monkeypatch.setattr(prepare_osm, "download_with_retry", always_down)
    assert prepare_osm.main(["--data-dir", str(tmp_path)]) == 1
    assert "ERRORE" in capsys.readouterr().err
    assert not (tmp_path / "osm").exists()


@pytest.mark.parametrize(
    "bbox",
    [
        ["14.3", "40.8", "14.1", "40.9"],
        ["14.1", "40.9", "14.3", "40.8"],
        ["14.1", "40.8", "14.3", "95"],
    ],
)
def test_bbox_non_valido_viene_rifiutato(bbox: list[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        prepare_osm.main(["--data-dir", str(tmp_path), "--bbox", *bbox])
    assert info.value.code == 2
