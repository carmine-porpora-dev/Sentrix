import json
import re
import shutil
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd
import pytest
from pydantic import ValidationError

from app.data import seeds as seeds_module
from app.data.resolvers import nearest_edges, nearest_node
from app.data.seeds import DEFAULT_SEEDS_DIR, read_seed_events
from app.geo import haversine_m
from app.models.config import EngineConfig, ODEndpoint
from app.models.event import Event
from app.models.geo import GeoPoint
from app.models.live_segments import LiveSegmentsConfig
from scripts import resolve_seeds
from scripts.resolve_seeds import (
    LIVE_ON_ROAD_MAX_M,
    CheckResult,
    Row,
    check,
    check_live_segments,
    check_point,
    circle_feature,
    main_component,
    network_geojson,
    patched_seed,
    render_page,
    script_safe_json,
    seed_text,
    write_seeds,
)
from tests.support import GTFS_FIXTURE, build_street_graph

# Cosa trovano nel grafo di prova i nomi e il bbox dei preset veri (vedi tests/support.py).
CARACCIOLO_KEYS = ["1-2-0", "2-1-0", "2-3-0", "3-2-0", "3-4-0", "4-3-0"]
DOHRN_KEYS = ["3-4-0", "4-3-0"]


@pytest.fixture
def graph() -> nx.MultiDiGraph:
    return build_street_graph()


@pytest.fixture
def stops() -> pd.DataFrame:
    return pd.read_csv(GTFS_FIXTURE / "stops.txt", dtype=str)


@pytest.fixture
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


def strip_resolved(data: dict[str, Any]) -> dict[str, Any]:
    """Il preset senza `edge_keys` e `stop_ids`: i file veri possono averli già (li scrive questo
    script), i test partono sempre da preset da risolvere."""
    for closure in data["closures"]:
        closure.pop("edge_keys", None)
    for disruption in data["transit_disruptions"]:
        disruption.pop("stop_ids", None)
    return data


@pytest.fixture
def seeds_dir(tmp_path: Path) -> Path:
    target = tmp_path / "seeds"
    target.mkdir()
    for path in sorted(DEFAULT_SEEDS_DIR.glob("*.json")):
        data = strip_resolved(json.loads(path.read_text(encoding="utf-8")))
        (target / path.name).write_text(seed_text(data), encoding="utf-8")
    return target


@pytest.fixture
def events(seeds_dir: Path) -> list[Event]:
    return read_seed_events(seeds_dir)


# --- geometrie ---------------------------------------------------------------------------------


def test_cerchio_dell_area_e_chiuso_e_ha_il_raggio_giusto() -> None:
    center = GeoPoint(lat=40.8320, lon=14.2350)
    ring = circle_feature(center, 400, kind="area", event="x")["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 65
    distances = [float(haversine_m(lat, lon, (center.lat, center.lon))) for lon, lat in ring]
    assert distances == pytest.approx([400.0] * 65, rel=0.005)


def test_la_rete_di_sfondo_ha_una_linea_per_coppia_di_nodi(graph: nx.MultiDiGraph) -> None:
    network = network_geojson(graph)
    pairs = {frozenset((u, v)) for u, v in graph.edges()}
    assert len(network["features"]) == len(pairs)
    assert all(f["geometry"]["type"] == "LineString" for f in network["features"])
    flat = [c for f in network["features"] for c in f["geometry"]["coordinates"]]
    assert all(len(str(x).split(".")[1]) <= 5 for pair in flat for x in pair)  # 5 decimali


# --- punti ---------------------------------------------------------------------------------


def test_un_punto_vicino_a_un_nodo_e_risolto(graph: nx.MultiDiGraph) -> None:
    result = CheckResult()
    check_point(
        GeoPoint(lat=40.8334, lon=14.2350),
        graph,
        300,
        result,
        kind="zone",
        label="Zona A",
        zone_id="a",
    )
    (row,) = result.rows
    assert (row.group, row.ok, row.detail) == ("Punti", True, "nodo 2 a 100 m")
    kinds = [f["properties"]["kind"] for f in result.features]
    assert kinds == ["zone", "node", "snap"]
    zone = result.features[0]["properties"]
    assert (zone["node"], zone["distance_m"], zone["ok"], zone["zone_id"]) == (2, 100, True, "a")
    assert result.features[2]["geometry"]["coordinates"][1] == [14.235, 40.8325]  # il nodo 2


def test_il_limite_di_aggancio_e_inclusivo(graph: nx.MultiDiGraph) -> None:
    point = GeoPoint(lat=40.8334, lon=14.2350)
    _, distance = nearest_node(point, graph)
    result = CheckResult()
    check_point(point, graph, distance, result, kind="zone", label="Sul limite")
    assert result.rows[0].ok
    check_point(point, graph, distance - 1e-6, result, kind="zone", label="Appena oltre")
    assert not result.rows[1].ok


def test_un_punto_oltre_il_limite_e_segnalato_e_si_disegna_lo_stesso(
    graph: nx.MultiDiGraph,
) -> None:
    result = CheckResult()
    check_point(GeoPoint(lat=40.8334, lon=14.2350), graph, 50, result, kind="zone", label="Zona A")
    (row,) = result.rows
    assert not row.ok and row.detail == "nodo 2 a 100 m (massimo 50 m)"
    assert result.failures == [row]
    assert result.features[0]["properties"]["ok"] is False
    assert result.seed_failures == 0  # un punto non blocca la scrittura dei preset


# --- chiusure e fermate dei preset -------------------------------------------------------------


def test_i_preset_veri_si_risolvono_sul_grafo_di_prova(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    result = check(events, graph, stops, config)
    assert result.edge_keys == {
        "match_2027": [CARACCIOLO_KEYS, DOHRN_KEYS],
        "regate_sep_2026": [CARACCIOLO_KEYS, DOHRN_KEYS],
    }
    assert result.stop_ids == {"match_2027": [["S3"]], "regate_sep_2026": []}
    assert result.seed_failures == 0
    closure_rows = [r for r in result.rows if r.group == "Chiusure"]
    assert [(r.event, r.ok, r.detail) for r in closure_rows] == [
        ("match_2027", True, "6 archi, 600 m"),
        ("match_2027", True, "2 archi, 200 m"),
        ("regate_sep_2026", True, "6 archi, 600 m"),
        ("regate_sep_2026", True, "2 archi, 200 m"),
    ]
    stop_rows = [r for r in result.rows if r.group == "Fermate"]
    assert [(r.event, r.ok, r.detail) for r in stop_rows] == [("match_2027", True, "1 fermate: S3")]


def test_le_feature_delle_chiusure_e_delle_fermate(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    result = check(events, graph, stops, config)
    closures = [f["properties"] for f in result.features if f["properties"]["kind"] == "closure"]
    assert len(closures) == 2 * (6 + 2)
    first = closures[0]
    assert first == {
        "kind": "closure", "event": "match_2027", "label": events[0].closures[0].label,
        "edge_key": "1-2-0", "name": "Via Francesco Caracciolo", "length_m": 100,
    }  # fmt: skip
    merged = [c for c in closures if c["edge_key"] == "3-4-0"]
    assert {c["name"] for c in merged} == {"Viale Anton Dohrn; Via Francesco Caracciolo"}
    (stop,) = [f for f in result.features if f["properties"]["kind"] == "stop"]
    assert stop["geometry"]["coordinates"] == [14.2304, 40.8313]
    assert stop["properties"] == {
        "kind": "stop", "event": "match_2027", "label": events[0].transit_disruptions[0].label,
        "stop_id": "S3", "name": "ARCO MIRELLI",
    }  # fmt: skip
    areas = [f for f in result.features if f["properties"]["kind"] == "area"]
    assert {f["properties"]["event"] for f in areas} == {"match_2027", "regate_sep_2026"}


def test_i_punti_di_engine_yaml_sono_tutti_controllati(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    result = check(events, graph, stops, config)
    points = [r for r in result.rows if r.group == "Punti"]
    # 2 centri area + 13 zone + 5 arrivi auto + 7 estremi O/D con coordinate (gli altri 3 sono zone)
    assert len(points) == 2 + 13 + 5 + 7
    labels = [r.label for r in points]
    assert labels[:2] == ["Centro area: Rotonda Diaz"] * 2
    assert "Zona Bagnoli" in labels and "Arrivo auto: Piazza Vittoria" in labels
    assert any(label.startswith("O/D Capo Posillipo") and "(origine)" in label for label in labels)
    assert not any(
        "Bagnoli" in label and label.startswith("O/D") for label in labels
    )  # zona: già sopra
    kinds = {f["properties"]["kind"] for f in result.features}
    assert kinds == {
        "area",
        "closure",
        "stop",
        "area_center",
        "zone",
        "car_destination",
        "od_point",
        "node",
        "snap",
    }


def test_una_chiusura_che_non_si_risolve_blocca_i_preset_ma_non_le_altre(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    broken = events[0].model_copy(
        update={
            "closures": [
                events[0].closures[0].model_copy(update={"street_names": ["Via Inesistente"]}),
                events[0].closures[1],
            ]
        }
    )
    result = check([broken], graph, stops, config)
    assert result.seed_failures == 1
    assert result.edge_keys["match_2027"] == [[], DOHRN_KEYS]
    bad = [r for r in result.failures if r.group == "Chiusure"]
    assert len(bad) == 1 and "nessun arco chiamato «Via Inesistente»" in bad[0].detail


def test_una_fermata_che_non_si_risolve(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    disruption = events[0].transit_disruptions[0].model_copy(update={"stop_name": "Piscinola"})
    broken = events[0].model_copy(update={"transit_disruptions": [disruption]})
    result = check([broken], graph, stops, config)
    assert result.seed_failures == 1 and result.stop_ids["match_2027"] == [[]]
    (bad,) = [r for r in result.failures if r.group == "Fermate"]
    assert "Nessuna fermata chiamata «Piscinola»" in bad.detail


def test_le_chiavi_gia_nel_file_si_ricalcolano_dai_nomi(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    stale_closure = events[0].closures[0].model_copy(update={"edge_keys": ["99-98-0"]})
    stale = events[0].model_copy(update={"closures": [stale_closure]})
    result = check([stale], graph, stops, config)
    assert result.edge_keys["match_2027"] == [CARACCIOLO_KEYS]  # non l'arco inesistente
    assert result.seed_failures == 0


def test_una_chiusura_solo_per_chiavi_le_conserva(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    by_hand = events[0].closures[0].model_copy(update={"street_names": [], "edge_keys": ["5-6-0"]})
    result = check([events[0].model_copy(update={"closures": [by_hand]})], graph, stops, config)
    assert result.edge_keys["match_2027"] == [["5-6-0"]]


# --- tratti LIVE -------------------------------------------------------------------------------


def live_config(*extra: dict[str, Any]) -> LiveSegmentsConfig:
    """Due tratti sulle strade del grafo di prova: a metà dell'arco 1→2 (Via Caracciolo) e a metà
    dell'arco 7→8 (Via Torre Caracciolo)."""
    segments = [
        {"id": "caracciolo", "label": "Via Caracciolo", "lat": 40.83225, "lon": 14.2325},
        {"id": "torre", "label": "Via Torre", "lat": 40.8405, "lon": 14.2365},
        *extra,
    ]
    return LiveSegmentsConfig.model_validate({"segments": segments})


def test_tratti_live_sulla_strada(graph: nx.MultiDiGraph) -> None:
    result = CheckResult()
    check_live_segments(live_config(), graph, result)
    rows = [(r.group, r.event, r.label, r.ok) for r in result.rows]
    assert rows == [
        ("Tratti LIVE", None, "Via Caracciolo", True),
        ("Tratti LIVE", None, "Via Torre", True),
    ]
    assert result.rows[0].detail == "su «Via Francesco Caracciolo» (None), a 0 m dall'arco 1-2-0"
    first = result.features[0]
    assert first["geometry"]["coordinates"] == [14.2325, 40.83225]
    assert first["properties"] == {
        "kind": "live_segment", "label": "Via Caracciolo", "segment_id": "caracciolo",
        "osm_name": "Via Francesco Caracciolo", "highway": "None", "edge_key": "1-2-0",
        "distance_m": 0, "ok": True,
    }  # fmt: skip
    assert result.failures == [] and result.seed_failures == 0


def test_un_tratto_live_fuori_strada_e_segnalato(graph: nx.MultiDiGraph) -> None:
    off_road = {"id": "mare", "label": "In mezzo al mare", "lat": 40.8325 + 0.0009, "lon": 14.2350}
    result = CheckResult()
    check_live_segments(live_config(off_road), graph, result)
    (bad,) = result.failures
    assert bad.label == "In mezzo al mare"
    assert f"oltre {LIVE_ON_ROAD_MAX_M:.0f} m, non è su una strada" in bad.detail
    assert result.features[-1]["properties"]["ok"] is False
    assert result.seed_failures == 0  # un tratto LIVE non blocca la scrittura dei preset


def test_la_soglia_del_tratto_live_e_inclusiva(graph: nx.MultiDiGraph) -> None:
    # 0,0002° di latitudine a nord della metà dell'arco 1→2 (che sale di 0,0005° su 0,005° di lon)
    # sono 22 m dall'asse: entro la soglia di 25 m; 0,0004° (≈ 44 m) no.
    near = {"id": "vicino", "label": "Vicino", "lat": 40.83225 + 0.0002, "lon": 14.2325}
    far = {"id": "lontano", "label": "Lontano", "lat": 40.83225 + 0.0004, "lon": 14.2325}
    result = CheckResult()
    check_live_segments(live_config(near, far), graph, result)
    assert [r.ok for r in result.rows] == [True, True, True, False]


def test_la_soglia_dei_tratti_live_e_inclusiva_al_millimetro(
    graph: nx.MultiDiGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    point = {"id": "sul_limite", "label": "Sul limite", "lat": 40.83225 + 0.0002, "lon": 14.2325}
    ((_, distance),) = nearest_edges([GeoPoint(lat=point["lat"], lon=point["lon"])], graph)
    monkeypatch.setattr(resolve_seeds, "LIVE_ON_ROAD_MAX_M", distance)
    result = CheckResult()
    check_live_segments(live_config(point), graph, result)
    assert result.rows[-1].ok
    monkeypatch.setattr(resolve_seeds, "LIVE_ON_ROAD_MAX_M", distance - 1e-6)
    result = CheckResult()
    check_live_segments(live_config(point), graph, result)
    assert not result.rows[-1].ok


def test_il_tratto_live_nel_controllo_completo(
    graph: nx.MultiDiGraph, stops: pd.DataFrame, config: EngineConfig, events: list[Event]
) -> None:
    without = check(events, graph, stops, config)
    with_live = check(events, graph, stops, config, live_config())
    assert [r for r in with_live.rows if r.group != "Tratti LIVE"] == without.rows
    assert [r.group for r in with_live.rows].count("Tratti LIVE") == 2
    assert "live_segment" in {f["properties"]["kind"] for f in with_live.features}
    assert "live_segment" not in {f["properties"]["kind"] for f in without.features}


# --- file dei preset ---------------------------------------------------------------------------


def raw(name: str) -> dict[str, Any]:
    return strip_resolved(
        json.loads((DEFAULT_SEEDS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    )


def test_patched_seed_aggiunge_solo_le_chiavi_risolte() -> None:
    original = raw("match_2027")
    snapshot = json.dumps(original)
    patched = patched_seed(original, [["1-2-0"], ["3-4-0", "4-3-0"]], [["S3"]])
    assert json.dumps(original) == snapshot  # l'originale non si tocca
    assert [c["edge_keys"] for c in patched["closures"]] == [["1-2-0"], ["3-4-0", "4-3-0"]]
    assert patched["transit_disruptions"][0]["stop_ids"] == ["S3"]
    for closure in patched["closures"]:
        del closure["edge_keys"]
    del patched["transit_disruptions"][0]["stop_ids"]
    assert patched == original  # tutto il resto identico
    assert list(patched) == list(original)  # stesso ordine delle chiavi


def test_patched_seed_con_liste_di_lunghezza_sbagliata_e_un_errore() -> None:
    with pytest.raises(ValueError):
        patched_seed(raw("match_2027"), [["1-2-0"]], [["S3"]])  # due chiusure, una lista sola


def test_seed_text_e_json_leggibile_con_accapo_finale() -> None:
    text = seed_text({"name": "Città — «x»", "n": [1, 2]})
    assert text.endswith("}\n") and "Città — «x»" in text and '\n  "n": [\n    1,' in text


def test_write_seeds_scrive_riconvalida_ed_e_idempotente(
    graph: nx.MultiDiGraph,
    stops: pd.DataFrame,
    config: EngineConfig,
    events: list[Event],
    seeds_dir: Path,
) -> None:
    result = check(events, graph, stops, config)
    assert write_seeds(events, result, seeds_dir) == ["match_2027", "regate_sep_2026"]
    reread = {e.id: e for e in read_seed_events(seeds_dir)}  # il modello li accetta ancora
    assert [c.edge_keys for c in reread["match_2027"].closures] == [CARACCIOLO_KEYS, DOHRN_KEYS]
    assert reread["match_2027"].transit_disruptions[0].stop_ids == ["S3"]
    assert reread["regate_sep_2026"].transit_disruptions == []
    # Dopo aver tolto le chiavi risolte, l'evento è quello di prima: niente altro è cambiato.
    for e in read_seed_events(seeds_dir):
        no_keys = [c.model_copy(update={"edge_keys": []}) for c in e.closures]
        no_ids = [d.model_copy(update={"stop_ids": []}) for d in e.transit_disruptions]
        stripped = e.model_copy(update={"closures": no_keys, "transit_disruptions": no_ids})
        assert stripped == next(o for o in events if o.id == e.id)
    # Seconda volta: stessi dati, stessi file, nessuna riga cambiata.
    before = {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")}
    assert (
        write_seeds(
            read_seed_events(seeds_dir),
            check(read_seed_events(seeds_dir), graph, stops, config),
            seeds_dir,
        )
        == []
    )
    assert {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")} == before


def test_write_seeds_non_scrive_un_preset_che_il_modello_rifiuterebbe(
    graph: nx.MultiDiGraph,
    stops: pd.DataFrame,
    config: EngineConfig,
    events: list[Event],
    seeds_dir: Path,
) -> None:
    result = check(events, graph, stops, config)
    result.edge_keys["match_2027"][0] = ["non-una-chiave"]  # il modello vuole "u-v-k" numerici
    before = {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")}
    with pytest.raises(ValidationError, match="chiavi arco non valide"):
        write_seeds(events, result, seeds_dir)
    assert {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")} == before


# --- pagina -----------------------------------------------------------------------------------


def make_result() -> CheckResult:
    result = CheckResult()
    result.rows = [
        Row("Chiusure", "evt", "Via <b>Roma</b> & «Co»", True, "2 archi"),
        Row("Punti", None, "Zona X", False, "nodo 1 a 400 m (massimo 300 m)"),
    ]
    hostile = "</script><script>alert(1)</script><!--"
    point = {"type": "Point", "coordinates": [14.2, 40.8]}
    result.features = [
        {"type": "Feature", "geometry": point, "properties": {"kind": "zone", "label": hostile}}
    ]
    return result


def page_for(result: CheckResult, events: list[Event]) -> str:
    return render_page(
        result, {"type": "FeatureCollection", "features": []}, events, [[14.1, 40.8], [14.3, 40.9]]
    )


def embedded_data(page: str) -> dict[str, Any]:
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S)
    assert match is not None
    data: dict[str, Any] = json.loads(match.group(1))
    return data


def test_la_pagina_non_lascia_segnaposto_e_fissa_maplibre(events: list[Event]) -> None:
    page = page_for(make_result(), events)
    assert re.findall(r"__[A-Z_]+__", page) == []
    assert (
        "maplibre-gl/4.7.1/maplibre-gl.js" in page and "maplibre-gl/4.7.1/maplibre-gl.css" in page
    )
    assert page.count('integrity="sha384-') == 2 and page.count('crossorigin="anonymous"') == 2
    assert resolve_seeds.MAPLIBRE_JS_SRI in page and resolve_seeds.MAPLIBRE_CSS_SRI in page
    assert set(re.findall(r'(?:src|href)="(https?://[^"]+)"', page)) == {
        "https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.css",
        "https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.js",
    }  # nessun'altra risorsa esterna: né tile né font


def test_gli_hash_di_integrita_hanno_il_formato_sha384_in_base64() -> None:
    for sri in (resolve_seeds.MAPLIBRE_JS_SRI, resolve_seeds.MAPLIBRE_CSS_SRI):
        assert re.fullmatch(r"sha384-[A-Za-z0-9+/]{64}", sri), sri  # 48 byte = 64 caratteri
    assert resolve_seeds.MAPLIBRE_JS_SRI != resolve_seeds.MAPLIBRE_CSS_SRI


def test_nomi_con_html_non_escono_dal_loro_contesto(events: list[Event]) -> None:
    page = page_for(make_result(), events)
    assert "<script>alert(1)</script>" not in page and "</script><script>" not in page
    assert "Via &lt;b&gt;Roma&lt;/b&gt; &amp; «Co»" in page  # nella tabella: escape HTML
    data = embedded_data(page)  # il JSON incorporato è valido e ha il testo originale
    assert (
        data["features"]["features"][0]["properties"]["label"]
        == "</script><script>alert(1)</script><!--"
    )


def test_script_safe_json() -> None:
    text = script_safe_json({"a": "</script>", "b": "<!-- x"})
    assert "</" not in text and "<!--" not in text
    assert json.loads(text) == {"a": "</script>", "b": "<!-- x"}


def test_la_pagina_ha_eventi_esiti_e_riepilogo(events: list[Event]) -> None:
    page = page_for(make_result(), events)
    data = embedded_data(page)
    assert data["events"] == [
        {"id": "match_2027", "name": "Match 2027 — serata di regata", "date": "2027-07-10"},
        {
            "id": "regate_sep_2026",
            "name": "Regate preliminari settembre 2026",
            "date": "2026-09-26",
        },
    ]
    assert data["bounds"] == [[14.1, 40.8], [14.3, 40.9]]
    assert '<tr class="ok"><td>Chiusure</td><td>evt</td>' in page
    assert (
        '<tr class="err"><td>Punti</td><td>—</td><td>Zona X</td><td><b>ERRORE</b> nodo 1 a 400 m'
        in page
    )
    assert "1 voci su 2 risolte, 1 NON risolte" in page


# --- connessione dei punti ------------------------------------------------------------------------


def branch_graph() -> nx.MultiDiGraph:
    """Un triangolo 1-2-3 percorribile nei due sensi e un ramo 3→4 di sola uscita: dal nodo 4 si
    torna in città, ma in città non ci si arriva."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    coordinates = {
        1: (14.2300, 40.8300),
        2: (14.2310, 40.8300),
        3: (14.2305, 40.8310),
        4: (14.2305, 40.8330),
    }
    for node, (lon, lat) in coordinates.items():
        g.add_node(node, x=lon, y=lat)
    for a, b in [(1, 2), (2, 3), (3, 1)]:
        g.add_edge(a, b, key=0, length_m=100.0)
        g.add_edge(b, a, key=0, length_m=100.0)
    g.add_edge(3, 4, key=0, length_m=100.0)
    return g


def test_la_componente_principale_e_la_piu_grande() -> None:
    assert main_component(branch_graph()) == frozenset({1, 2, 3})
    assert main_component(nx.MultiDiGraph()) == frozenset()


def test_un_ramo_di_sola_uscita_non_e_un_punto_valido() -> None:
    g = branch_graph()
    main = main_component(g)
    inside, branch = CheckResult(), CheckResult()
    # un punto sul nodo 1 è nella componente principale; uno sul nodo 4 no, benché vicinissimo
    check_point(
        GeoPoint(lat=40.8300, lon=14.2300),
        g,
        50,
        inside,
        kind="zone",
        label="Dentro",
        connected=main,
    )
    check_point(
        GeoPoint(lat=40.8330, lon=14.2305), g, 50, branch, kind="zone", label="Ramo", connected=main
    )
    assert [r.ok for r in inside.rows] == [True]
    assert [r.ok for r in branch.rows] == [False]
    assert branch.rows[0].detail == (
        "nodo 4 a 0 m: fuori dalla componente principale della rete, "
        "non si arriva da o verso la città"
    )
    assert [f["properties"]["ok"] for f in branch.features] == [False] * len(branch.features)


def test_senza_componente_il_controllo_non_si_applica() -> None:
    result = CheckResult()
    check_point(
        GeoPoint(lat=40.8330, lon=14.2305), branch_graph(), 50, result, kind="zone", label="Ramo"
    )
    assert [r.ok for r in result.rows] == [True]


def test_distanza_e_connessione_si_dicono_entrambe() -> None:
    g = branch_graph()
    result = CheckResult()
    # a 100 m dal nodo 4: oltre il limite di 50 m e, in più, nodo fuori dalla componente
    check_point(
        GeoPoint(lat=40.8339, lon=14.2305),
        g,
        50,
        result,
        kind="zone",
        label="X",
        connected=main_component(g),
    )
    detail = result.rows[0].detail
    assert detail.startswith("nodo 4 a ") and "(massimo 50 m)" in detail
    assert detail.endswith(
        "fuori dalla componente principale della rete, non si arriva da o verso la città"
    )
    assert result.rows[0].ok is False


ON_MAIN = GeoPoint(lat=40.8300, lon=14.2300)  # nodo 1, nel triangolo
ON_BRANCH = GeoPoint(lat=40.8330, lon=14.2305)  # nodo 4, ramo di sola uscita


def all_on_main(config: EngineConfig, events: list[Event]) -> tuple[EngineConfig, list[Event]]:
    """Tutti i punti di engine.yaml e dei preset sul nodo 1 del grafo di prova (distanza libera)."""
    demand = config.demand.model_copy(
        update={
            "zones": [z.model_copy(update={"centroid": ON_MAIN}) for z in config.demand.zones],
            "car_destinations": [
                d.model_copy(update={"point": ON_MAIN}) for d in config.demand.car_destinations
            ],
            "od_pairs": [
                p.model_copy(
                    update={
                        "origin": ODEndpoint(point=ON_MAIN),
                        "destination": ODEndpoint(point=ON_MAIN),
                    }
                )
                for p in config.demand.od_pairs
            ],
        }
    )
    wide = config.model_copy(update={"node_snap_max_distance_m": 1e9, "demand": demand})
    return wide, [e.model_copy(update={"area_center": ON_MAIN}) for e in events]


def bad_points(config: EngineConfig, events: list[Event]) -> list[str]:
    stops = pd.DataFrame({"stop_id": [], "stop_name": []})
    result = check(
        [e.model_copy(update={"closures": [], "transit_disruptions": []}) for e in events],
        branch_graph(),
        stops,
        config,
    )
    return [r.label for r in result.rows if r.group == "Punti" and not r.ok]


def test_con_tutti_i_punti_nel_triangolo_non_c_e_niente_da_segnalare(
    config: EngineConfig, events: list[Event]
) -> None:
    assert bad_points(*all_on_main(config, events)) == []


def test_check_segnala_ogni_tipo_di_punto_agganciato_a_un_ramo_di_sola_uscita(
    config: EngineConfig, events: list[Event]
) -> None:
    wide, moved = all_on_main(config, events)
    zones = [
        z.model_copy(update={"centroid": ON_BRANCH}) if z.id == "gate_east" else z
        for z in wide.demand.zones
    ]
    gate = next(z for z in wide.demand.zones if z.id == "gate_east")
    cases = {
        "zona": (
            wide.model_copy(update={"demand": wide.demand.model_copy(update={"zones": zones})}),
            moved,
            [f"Zona {gate.name}"],
        ),
        "punto di arrivo": (
            wide.model_copy(
                update={
                    "demand": wide.demand.model_copy(
                        update={
                            "car_destinations": [
                                wide.demand.car_destinations[0].model_copy(
                                    update={"point": ON_BRANCH.model_copy(update={"label": "Ramo"})}
                                ),
                                *wide.demand.car_destinations[1:],
                            ]
                        }
                    )
                }
            ),
            moved,
            ["Arrivo auto: Ramo"],
        ),
        "estremo O/D": (
            wide.model_copy(
                update={
                    "demand": wide.demand.model_copy(
                        update={
                            "od_pairs": [
                                wide.demand.od_pairs[0].model_copy(
                                    update={"destination": ODEndpoint(point=ON_BRANCH)}
                                ),
                                *wide.demand.od_pairs[1:],
                            ]
                        }
                    )
                }
            ),
            moved,
            [f"O/D {wide.demand.od_pairs[0].label} (destinazione)"],
        ),
        "centro area": (
            wide,
            [moved[0].model_copy(update={"area_center": ON_BRANCH}), *moved[1:]],
            [
                f"Centro area: {moved[0].name}"
            ],  # senza etichetta del punto, vale il nome dell'evento
        ),
    }
    for name, (cfg, evs, expected) in cases.items():
        assert bad_points(cfg, evs) == expected, name


# --- il programma intero -----------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path: Path, graph: nx.MultiDiGraph, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "data"
    (directory / "osm").mkdir(parents=True)
    (directory / "osm" / "graph_drive.graphml").write_text("(il caricamento è simulato)")
    shutil.copytree(GTFS_FIXTURE, directory / "gtfs" / "anm")
    monkeypatch.setattr(resolve_seeds, "load_osm_graph", lambda path: graph)
    live = live_config()
    monkeypatch.setattr(
        resolve_seeds.LiveSegmentsConfig, "from_yaml", classmethod(lambda cls: live)
    )
    return directory


def run_main(data_dir: Path, seeds_dir: Path, *extra: str) -> int:
    return resolve_seeds.main(["--data-dir", str(data_dir), "--seeds-dir", str(seeds_dir), *extra])


def test_run_completo_scrive_preset_geojson_e_pagina(
    data_dir: Path, seeds_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_main(data_dir, seeds_dir)
    out = capsys.readouterr().out
    # Le zone di engine.yaml (Napoli intera) sono lontane dal grafo di prova: i punti NON si
    # risolvono, quindi il codice è 1, ma chiusure e fermate sì e i preset vengono scritti.
    assert code == 1
    assert "[OK ] Chiusure  match_2027" in out and "[ERR] Punti" in out
    assert "Preset aggiornati: match_2027, regate_sep_2026" in out
    match = next(e for e in read_seed_events(seeds_dir) if e.id == "match_2027")
    assert [c.edge_keys for c in match.closures] == [CARACCIOLO_KEYS, DOHRN_KEYS]
    report = data_dir / "report"
    geojson = json.loads((report / "seed_check.geojson").read_text(encoding="utf-8"))
    assert geojson["type"] == "FeatureCollection" and len(geojson["features"]) > 20
    page = (report / "seed_check.html").read_text(encoding="utf-8")
    assert "Verifica dei preset" in page and "ERRORE" in page and "maplibre-gl/4.7.1" in page


def test_run_senza_errori_ha_codice_zero(
    data_dir: Path,
    seeds_dir: Path,
    config: EngineConfig,
    graph: nx.MultiDiGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nodes = sorted(graph.nodes)  # un anello nei due sensi collega tutti i nodi del grafo di prova
    for a, b in zip(nodes, nodes[1:] + nodes[:1], strict=True):
        graph.add_edge(a, b, key=7, length_m=1.0)
        graph.add_edge(b, a, key=7, length_m=1.0)
    monkeypatch.setattr(
        resolve_seeds.EngineConfig,
        "from_yaml",
        classmethod(lambda cls: config.model_copy(update={"node_snap_max_distance_m": 1e9})),
    )
    assert run_main(data_dir, seeds_dir) == 0


def test_run_ripetuto_non_cambia_i_file(
    data_dir: Path, seeds_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_main(data_dir, seeds_dir)
    snapshot = {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")}
    capsys.readouterr()
    run_main(data_dir, seeds_dir)
    assert {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")} == snapshot
    assert "Preset aggiornati: nessuno (già risolti)" in capsys.readouterr().out


def test_dry_run_non_tocca_i_preset_ma_scrive_il_report(
    data_dir: Path, seeds_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")}
    run_main(data_dir, seeds_dir, "--dry-run")
    assert {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")} == before
    assert "--dry-run: i preset non sono stati modificati." in capsys.readouterr().out
    assert (data_dir / "report" / "seed_check.html").is_file()


def test_se_una_chiusura_non_si_risolve_i_preset_restano_intatti(
    data_dir: Path, seeds_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seeds_dir / "match_2027.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["closures"][1]["street_names"] = ["Viale Sbagliato"]
    path.write_text(seed_text(data), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")}
    assert run_main(data_dir, seeds_dir) == 1
    captured = capsys.readouterr()
    assert {p.name: p.read_bytes() for p in seeds_dir.glob("*.json")} == before  # nessuno dei due
    assert "nessun arco chiamato «Viale Sbagliato»" in captured.out
    assert "i preset NON sono stati modificati" in captured.err
    assert "ERRORE" in (data_dir / "report" / "seed_check.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("missing", ["osm/graph_drive.graphml", "gtfs/anm/stops.txt"])
def test_dati_mancanti_sono_un_errore_con_istruzioni(
    data_dir: Path, seeds_dir: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    (data_dir / missing).unlink()
    assert run_main(data_dir, seeds_dir) == 2
    assert "make data" in capsys.readouterr().err
    assert not (data_dir / "report").exists()


def test_un_preset_non_valido_ferma_tutto(
    data_dir: Path, seeds_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (seeds_dir / "match_2027.json").write_text('{ "id": "match_2027" ', encoding="utf-8")
    assert run_main(data_dir, seeds_dir) == 2
    assert "Preset non utilizzabili: match_2027.json" in capsys.readouterr().err
    assert not (data_dir / "report").exists()


def test_il_valore_di_default_dei_preset_e_quello_dell_app() -> None:
    assert resolve_seeds.DEFAULT_SEEDS_DIR == seeds_module.DEFAULT_SEEDS_DIR
