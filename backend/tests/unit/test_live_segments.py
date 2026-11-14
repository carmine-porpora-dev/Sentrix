import re
from pathlib import Path
from typing import Any

import networkx as nx
import pytest
import yaml
from pydantic import ValidationError

from app.data.resolvers import nearest_edges
from app.geo import haversine_m
from app.models.geo import GeoPoint
from app.models.live_segments import LiveSegment, LiveSegmentsConfig
from scripts import pick_live_segments as pick
from scripts.pick_live_segments import (
    DISTINCT_M,
    JUNCTION_OFFSET_M,
    SAME_STREET_M,
    SEGMENTS,
    PickError,
    SegmentSpec,
    pick_segments,
    render_yaml,
)
from scripts.prepare_osm import STUDY_AREA_BBOX
from scripts.prepare_pmtiles import PMTILES_BBOX
from tests.support import DELETE, mutated

YAML_PATH = LiveSegmentsConfig.DEFAULT_PATH

# I 14 tratti di 08 2, nell'ordine della spec (senza Viale Dohrn, tolto il 9/11/2026: vedi il test
# in fondo). «Riviera di Chiaia» e «Corso Vittorio Emanuele» hanno 2 punti ciascuno.
SPEC_IDS = [
    "via_caracciolo",
    "riviera_chiaia_1",
    "riviera_chiaia_2",
    "via_partenope",
    "via_posillipo",
    "galleria_laziale",
    "galleria_vittoria",
    "via_acton",
    "corso_vittorio_emanuele_1",
    "corso_vittorio_emanuele_2",
    "tangenziale_fuorigrotta",
    "tangenziale_vomero",
    "tangenziale_capodichino",
    "via_marina",
]
SPEC_LABELS = [
    "Via Caracciolo",
    "Riviera di Chiaia (punto 1)",
    "Riviera di Chiaia (punto 2)",
    "Via Partenope",
    "Via Posillipo",
    "Galleria Laziale",
    "Galleria della Vittoria",
    "Via Acton",
    "Corso Vittorio Emanuele (punto 1)",
    "Corso Vittorio Emanuele (punto 2)",
    "Tangenziale svincolo Fuorigrotta",
    "Tangenziale svincolo Vomero",
    "Tangenziale svincolo Capodichino",
    "Via Marina",
]


# --- il modello --------------------------------------------------------------------------------


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    return data


def error_text(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        LiveSegmentsConfig.model_validate(data)
    return str(info.value)


def test_il_file_ha_i_15_tratti_della_spec() -> None:
    assert LiveSegmentsConfig.DEFAULT_PATH == YAML_PATH and YAML_PATH.is_file()
    config = LiveSegmentsConfig.from_yaml()
    assert [s.id for s in config.segments] == SPEC_IDS
    assert [s.label for s in config.segments] == SPEC_LABELS
    assert len(config.segments) == 14


def test_i_punti_sono_nell_area_di_studio_e_distinti() -> None:
    config = LiveSegmentsConfig.from_yaml()
    west, south, east, north = STUDY_AREA_BBOX
    pm_west, pm_south, pm_east, pm_north = PMTILES_BBOX
    for s in config.segments:
        assert west <= s.lon <= east and south <= s.lat <= north, f"{s.id} fuori dal grafo OSM"
        assert pm_west <= s.lon <= pm_east and pm_south <= s.lat <= pm_north, s.id
    coordinates = [(s.lat, s.lon) for s in config.segments]
    assert len(set(coordinates)) == 14  # nessun punto ripetuto
    for i, a in enumerate(config.segments):
        for b in config.segments[i + 1 :]:
            assert float(haversine_m(a.lat, a.lon, (b.lat, b.lon))) >= DISTINCT_M - 1, (a.id, b.id)


def test_un_tratto_e_un_punto_con_id_ed_etichetta() -> None:
    segment = LiveSegment(id="prova", label="Via di prova", lat=40.83, lon=14.23)
    assert isinstance(segment, GeoPoint) and (segment.id, segment.label) == (
        "prova",
        "Via di prova",
    )
    assert LiveSegment.model_validate_json(segment.model_dump_json()) == segment


SEGMENT_CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    ("id duplicato", ("segments", 1, "id"), "via_caracciolo", "id di tratto duplicati"),
    ("id non è uno slug", ("segments", 0, "id"), "Via Caracciolo", "String should match pattern"),
    ("manca l'id", ("segments", 0, "id"), DELETE, "id\n  Field required"),
    ("manca l'etichetta", ("segments", 0, "label"), DELETE, "label obbligatoria"),
    ("etichetta vuota", ("segments", 0, "label"), "", "label obbligatoria"),
    ("etichetta di spazi", ("segments", 0, "label"), "   ", "label obbligatoria"),
    ("manca la latitudine", ("segments", 0, "lat"), DELETE, "lat\n  Field required"),
    ("latitudine fuori range", ("segments", 0, "lat"), 91, "less than or equal to 90"),
    ("longitudine fuori range", ("segments", 0, "lon"), -181, "greater than or equal to -180"),
    ("latitudine in testo", ("segments", 0, "lat"), "quaranta", "valid number"),
    ("chiave sconosciuta", ("segments", 0, "frc"), 2, "Extra inputs are not permitted"),
    ("nessun tratto", ("segments",), [], "at least 1 item"),
    ("chiave sconosciuta in radice", ("version",), 1, "Extra inputs are not permitted"),
]


@pytest.mark.parametrize(
    ("name", "path", "value", "fragment"), SEGMENT_CASES, ids=[c[0] for c in SEGMENT_CASES]
)
def test_tratti_non_validi(
    raw: dict[str, Any], name: str, path: tuple[str | int, ...], value: Any, fragment: str
) -> None:
    assert fragment in error_text(mutated(raw, path, value)), name


def test_chiave_duplicata_e_documento_non_mappa() -> None:
    with pytest.raises(yaml.constructor.ConstructorError, match="chiave duplicata"):
        LiveSegmentsConfig.from_yaml_text(YAML_PATH.read_text(encoding="utf-8") + "segments: []\n")
    with pytest.raises(ValueError, match="live_segments.yaml: il documento deve essere una mappa"):
        LiveSegmentsConfig.from_yaml_text("- a\n- b\n")


def test_hash_del_contenuto_non_dei_commenti(raw: dict[str, Any]) -> None:
    config = LiveSegmentsConfig.from_yaml()
    assert re.fullmatch(r"[0-9a-f]{64}", config.content_hash())
    reformatted = "# altro commento\n" + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
    assert LiveSegmentsConfig.from_yaml_text(reformatted).content_hash() == config.content_hash()
    moved = LiveSegmentsConfig.model_validate(
        mutated(raw, ("segments", 0, "lat"), raw["segments"][0]["lat"] + 1e-6)
    )
    assert moved.content_hash() != config.content_hash()


# --- la tabella dei tratti: cosa sono in OSM ---------------------------------------------------


def test_la_tabella_ha_i_15_tratti_della_spec_con_gli_id_giusti() -> None:
    expanded = [
        f"{s.id}_{i}" if s.points > 1 else s.id for s in SEGMENTS for i in range(1, s.points + 1)
    ]
    assert expanded == SPEC_IDS
    assert [s.points for s in SEGMENTS if s.points > 1] == [2, 2]


def test_i_nomi_osm_che_differiscono_dall_etichetta_sono_quelli_verificati_sul_grafo() -> None:
    names = {s.id: s.osm_name for s in SEGMENTS}
    assert names["via_marina"] == "Via Nuova Marina"  # in OSM «Via Marina» non esiste
    assert names["galleria_laziale"] == "Galleria di Posillipo (Laziale)"
    assert names["via_acton"] == "Via Ferdinando Acton"
    assert names["via_caracciolo"] == "Via Francesco Caracciolo"
    ramps = {s.id: s.ramp for s in SEGMENTS if s.ramp}
    assert ramps == {
        "tangenziale_fuorigrotta": "Uscita Fuorigrotta",
        "tangenziale_vomero": "Uscita Vomero",
        "tangenziale_capodichino": "Uscita Capodichino - Secondigliano",
    }
    assert {s.osm_name for s in SEGMENTS if s.ramp} == {"Tangenziale di Napoli"}


# --- scelta su grafi di prova ------------------------------------------------------------------


def new_graph() -> nx.MultiDiGraph:
    return nx.MultiDiGraph()


def street(
    g: nx.MultiDiGraph, u: int, v: int, a: tuple[float, float], b: tuple[float, float], name: Any,
    length: float, *, k: int = 0, highway: str = "primary", both: bool = True, **extra: Any,
) -> None:  # fmt: skip
    """Un arco da `a` a `b` (lon, lat), e di solito anche quello di ritorno."""
    for node, (lon, lat) in ((u, a), (v, b)):
        g.add_node(node, x=lon, y=lat)
    g.add_edge(u, v, key=k, name=name, length_m=length, highway=highway, **extra)
    if both:
        g.add_edge(v, u, key=k, name=name, length_m=length, highway=highway)


def spec(name: str, *, points: int = 1, ramp: str | None = None, sid: str = "x") -> SegmentSpec:
    return SegmentSpec(sid, "Etichetta X", name, points=points, ramp=ramp)


def test_un_punto_il_piu_lungo_a_meta() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2010, 40.8000), "Via Prova", 100)
    street(g, 2, 3, (14.2010, 40.8000), (14.2050, 40.8000), "Via Prova", 400)  # il più lungo
    street(g, 3, 4, (14.2050, 40.8000), (14.2060, 40.8000), "Via Prova", 80)
    (p,) = pick_segments(g, (spec("Via Prova"),))
    assert (p.lat, p.lon) == (40.8, 14.2030)  # metà di 2→3
    assert (p.id, p.label, p.edge, p.osm_name, p.length_m) == (
        "x",
        "Etichetta X",
        "2-3-0",
        "Via Prova",
        400,
    )


def test_le_coordinate_sono_arrotondate_a_6_decimali() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000000, 40.8000000), (14.2000034, 40.8000076), "Via Minima", 1)
    (p,) = pick_segments(g, (spec("Via Minima"),))
    assert (p.lon, p.lat) == (14.200002, 40.800004)  # metà: 14,2000017 e 40,8000038


def test_i_due_sensi_contano_una_volta_e_a_parita_vince_la_chiave_minore() -> None:
    g = new_graph()
    street(g, 5, 6, (14.2000, 40.8000), (14.2020, 40.8000), "Via Prova", 200, both=True)
    street(g, 1, 2, (14.2100, 40.8000), (14.2120, 40.8000), "Via Prova", 200, both=True)
    (p,) = pick_segments(g, (spec("Via Prova"),))
    assert p.edge == "1-2-0"  # a parità di lunghezza, la chiave più piccola


def test_il_nome_deve_essere_quello_esatto() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2020, 40.8000), "Via Nuova Marina dei Gigli", 200)
    with pytest.raises(PickError, match="x: nessun arco OSM chiamato «Via Nuova Marina»"):
        pick_segments(g, (spec("Via Nuova Marina"),))


def test_un_nome_fuso_con_punto_e_virgola_vale_se_una_parte_e_quella_giusta() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2020, 40.8000), "Via Prova; Via Altra", 200)
    (p,) = pick_segments(g, (spec("Via Prova"),))
    assert p.osm_name == "Via Prova; Via Altra"  # si riporta il nome intero


def test_archi_senza_nome_o_con_altri_nomi_non_contano() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2020, 40.8000), None, 900)
    street(g, 3, 4, (14.2100, 40.8000), (14.2120, 40.8000), "Via Altra", 900)
    with pytest.raises(PickError, match="nessun arco OSM chiamato «Via Prova»"):
        pick_segments(g, (spec("Via Prova"),))


def test_il_punto_sta_sulla_geometria_di_un_arco_curvo() -> None:
    from shapely.geometry import LineString  # type: ignore[import-untyped]

    g = new_graph()
    curve = LineString([(14.2000, 40.8000), (14.2010, 40.8040), (14.2020, 40.8000)])
    street(g, 1, 2, (14.2000, 40.8000), (14.2020, 40.8000), "Via Curva", 600, geometry=curve)
    (p,) = pick_segments(g, (spec("Via Curva"),))
    assert (p.lon, p.lat) == pytest.approx(
        (14.2010, 40.8040), abs=1e-6
    )  # il vertice: metà percorso
    ((key, distance),) = nearest_edges([GeoPoint(lat=p.lat, lon=p.lon)], g)
    assert distance < 0.5


def test_due_punti_il_secondo_lontano_dal_primo() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2040, 40.8000), "Via Lunga", 400)  # primo: 400 m
    street(g, 2, 3, (14.2040, 40.8000), (14.2070, 40.8000), "Via Lunga", 300)  # a 0,0035° ≈ 295 m
    street(g, 3, 4, (14.2070, 40.8000), (14.2090, 40.8000), "Via Lunga", 200)  # a ≈ 600 m: valido
    points = pick_segments(g, (spec("Via Lunga", points=2),))
    assert [p.id for p in points] == ["x_1", "x_2"]
    assert [p.label for p in points] == ["Etichetta X (punto 1)", "Etichetta X (punto 2)"]
    assert [p.edge for p in points] == ["1-2-0", "3-4-0"]  # 2-3 dista troppo poco dal primo
    distance = float(haversine_m(points[0].lat, points[0].lon, (points[1].lat, points[1].lon)))
    assert distance >= SAME_STREET_M


def test_secondo_punto_introvabile_e_un_errore_che_dice_quanti_ne_trova() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2020, 40.8000), "Via Corta", 200)
    street(g, 2, 3, (14.2020, 40.8000), (14.2030, 40.8000), "Via Corta", 100)
    with pytest.raises(PickError, match=r"x: trovo 1 punti su 2 .*«Via Corta».*500 m tra loro"):
        pick_segments(g, (spec("Via Corta", points=2),))


def test_due_tratti_non_usano_lo_stesso_punto() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2040, 40.8000), "Via Uno; Via Due", 400)  # in comune
    street(g, 3, 4, (14.2100, 40.8000), (14.2110, 40.8000), "Via Due", 90)
    first, second = pick_segments(g, (spec("Via Uno", sid="uno"), spec("Via Due", sid="due")))
    assert (first.edge, second.edge) == ("1-2-0", "3-4-0")  # «Via Due» salta l'arco già usato
    assert float(haversine_m(first.lat, first.lon, (second.lat, second.lon))) >= DISTINCT_M


def test_se_tutti_gli_archi_sono_troppo_vicini_a_un_altro_tratto_e_un_errore() -> None:
    g = new_graph()
    street(g, 1, 2, (14.2000, 40.8000), (14.2040, 40.8000), "Via Uno; Via Due", 400)
    with pytest.raises(PickError, match="due: trovo 0 punti su 1"):
        pick_segments(g, (spec("Via Uno", sid="uno"), spec("Via Due", sid="due")))


def test_distinti_vuol_dire_150_metri_non_di_meno() -> None:
    g = new_graph()
    # Due archi adiacenti: i punti medi distano 0,0010° ≈ 85 m (< 150 m) → il secondo è scartato.
    street(g, 1, 2, (14.2000, 40.8000), (14.2010, 40.8000), "Via Uno", 100)
    street(g, 2, 3, (14.2010, 40.8000), (14.2020, 40.8000), "Via Due", 100)
    with pytest.raises(PickError, match="due: trovo 0 punti"):
        pick_segments(g, (spec("Via Uno", sid="uno"), spec("Via Due", sid="due")))
    assert DISTINCT_M == 150 and SAME_STREET_M == 500 and JUNCTION_OFFSET_M == 150


# --- svincoli ----------------------------------------------------------------------------------


# Lunghezza dell'arco principale: coerente con le sue coordinate (0,01° di longitudine a 40,8° N),
# perché lo script si fida di `length_m` per decidere a che frazione dell'arco mettere il punto.
MAIN_LENGTH = round(float(haversine_m(40.8000, 14.2000, (40.8000, 14.2100))), 1)


def junction_graph(
    *, main_in_to_node: bool = True, main_length: float | None = None
) -> nx.MultiDiGraph:
    """La Tangenziale corre da ovest a est lungo 40.8; il nodo 20 è lo svincolo a 14.2100 (la rampa
    «Uscita Prova» si stacca da lì e scende a sud)."""
    length = main_length if main_length is not None else MAIN_LENGTH
    g = new_graph()
    if main_in_to_node:  # l'arco principale ARRIVA al nodo 20, da ovest (13 → 20)
        street(
            g,
            13,
            20,
            (14.2000, 40.8000),
            (14.2100, 40.8000),
            "Tangenziale di Napoli",
            length,
            highway="motorway",
            both=False,
        )
    else:  # l'arco principale PARTE dal nodo 20, verso est (20 → 13)
        street(
            g,
            20,
            13,
            (14.2100, 40.8000),
            (14.2200, 40.8000),
            "Tangenziale di Napoli",
            length,
            highway="motorway",
            both=False,
        )
    street(
        g,
        20,
        21,
        (14.2100, 40.8000),
        (14.2110, 40.7970),
        "Uscita Prova",
        350,
        highway="motorway_link",
        both=False,
    )
    return g


JUNCTION = SegmentSpec(
    "tang", "Tangenziale svincolo Prova", "Tangenziale di Napoli", ramp="Uscita Prova"
)


@pytest.mark.parametrize("main_in_to_node", [True, False])
def test_lo_svincolo_e_a_150_metri_dal_nodo_lungo_la_tangenziale(main_in_to_node: bool) -> None:
    g = junction_graph(main_in_to_node=main_in_to_node)
    (p,) = pick_segments(g, (JUNCTION,))
    node = (40.8000, 14.2100)
    distance = float(haversine_m(p.lat, p.lon, node))
    assert distance == pytest.approx(150, abs=1.5)  # lungo l'arco, a ~150 m dal nodo (non a metà)
    assert p.lat == pytest.approx(40.8000, abs=1e-6) and p.edge in {"13-20-0", "20-13-0"}
    assert (p.lon < 14.2100) is main_in_to_node  # dal lato dell'arco principale, non sulla rampa
    ((_, off_road),) = nearest_edges([GeoPoint(lat=p.lat, lon=p.lon)], g)
    assert off_road < 0.5


def test_un_arco_corto_dello_svincolo_si_usa_a_meta() -> None:
    g = junction_graph(main_length=200)  # più corto del doppio dello scarto (300 m)
    (p,) = pick_segments(g, (JUNCTION,))
    assert p.lon == pytest.approx((14.2000 + 14.2100) / 2, abs=1e-9)


def test_tra_gli_archi_dello_svincolo_vince_il_piu_lungo() -> None:
    g = junction_graph()
    street(
        g,
        20,
        30,
        (14.2100, 40.8000),
        (14.2110, 40.8000),
        "Tangenziale di Napoli",
        90,
        highway="motorway",
        both=False,
    )
    (p,) = pick_segments(g, (JUNCTION,))
    assert p.edge == "13-20-0" and p.length_m == round(MAIN_LENGTH)


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda g: g.remove_edge(20, 21, 0), "nessun arco OSM chiamato «Uscita Prova»"),
        (lambda g: g.remove_edge(13, 20, 0), "non si stacca da un arco «Tangenziale di Napoli»"),
        (
            lambda g: g.edges[13, 20, 0].update(highway="trunk"),
            "non si stacca da un arco «Tangenziale di Napoli» (motorway)",
        ),
        (lambda g: g.edges[13, 20, 0].update(name="Altra Strada"), "non si stacca da un arco"),
    ],
    ids=["senza rampa", "senza arco principale", "classe diversa", "nome diverso"],
)
def test_svincolo_non_costruibile(mutate: Any, fragment: str) -> None:
    g = junction_graph()
    mutate(g)
    with pytest.raises(PickError, match=re.escape(fragment)):
        pick_segments(g, (JUNCTION,))


def test_lo_svincolo_non_puo_coincidere_con_un_altro_tratto() -> None:
    g = junction_graph()
    street(g, 40, 41, (14.2090, 40.8000), (14.2100, 40.8000), "Via Vicina", 85)
    with pytest.raises(
        PickError, match="tang: il punto dello svincolo coincide con un altro tratto"
    ):
        pick_segments(g, (spec("Via Vicina", sid="vicina"), JUNCTION))


# --- determinismo e file ------------------------------------------------------------------------


def full_graph(node_order_reversed: bool = False) -> nx.MultiDiGraph:
    """Un grafo con un arco per ogni strada della tabella reale (e le rampe), tutti lontani tra
    loro: serve a far girare l'intero programma."""
    g = new_graph()
    node = 100
    lon0, lat0 = 14.15, 40.80
    index = 0
    for s in SEGMENTS:
        for _ in range(s.points):
            index += 1
            a = (lon0 + 0.012 * index, lat0 + 0.004 * (index % 5))
            b = (a[0] + 0.004, a[1] + 0.001)
            if s.ramp:
                street(g, node, node + 1, a, b, s.osm_name, 700, highway="motorway", both=False)
                street(
                    g,
                    node + 1,
                    node + 2,
                    b,
                    (b[0], b[1] - 0.003),
                    s.ramp,
                    300,
                    highway="motorway_link",
                    both=False,
                )
            else:
                street(g, node, node + 1, a, b, s.osm_name, 400 + 7 * index)
            node += 10
    if node_order_reversed:
        h = new_graph()
        for n in reversed(list(g.nodes)):
            h.add_node(n, **g.nodes[n])
        for u, v, k, d in reversed(list(g.edges(keys=True, data=True))):
            h.add_edge(u, v, key=k, **d)
        return h
    return g


def test_la_tabella_reale_su_un_grafo_completo_da_15_tratti_in_ordine() -> None:
    picked = pick_segments(full_graph())
    assert [p.id for p in picked] == SPEC_IDS
    assert [p.label for p in picked] == SPEC_LABELS
    assert all(p.length_m > 0 for p in picked)


def test_il_risultato_non_dipende_dall_ordine_di_inserimento_nel_grafo() -> None:
    assert pick_segments(full_graph()) == pick_segments(full_graph(node_order_reversed=True))


def test_render_yaml_si_rilegge_col_modello() -> None:
    picked = pick_segments(full_graph())
    text = render_yaml(picked)
    config = LiveSegmentsConfig.from_yaml_text(text)
    assert [(s.id, s.label, s.lat, s.lon) for s in config.segments] == [
        (p.id, p.label, p.lat, p.lon) for p in picked
    ]
    assert text.endswith("\n") and text.startswith("segments:\n")
    assert "Corso Vittorio Emanuele (punto 1)" in text
    first = [line for line in text.splitlines() if line.startswith("  - {")][0]
    assert re.fullmatch(
        r'  - \{ id: via_caracciolo, label: "Via Caracciolo", lat: [\d.]+, lon: [\d.]+ \}  '
        r"# arco \d+-\d+-\d+: «Via Francesco Caracciolo», \d+ m",
        first,
    )


def test_render_yaml_protegge_le_etichette_con_caratteri_speciali() -> None:
    from scripts.pick_live_segments import Picked

    tricky = Picked("a", 'Via "Roma": è #1', 40.83, 14.23, "1-2-0", "Via Roma", 100)
    text = render_yaml([tricky])
    assert "è" in text  # le lettere accentate restano leggibili nel file, non \\u00e8
    config = LiveSegmentsConfig.from_yaml_text(text)
    assert config.segments[0].label == 'Via "Roma": è #1'


# --- il programma intero -----------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "data"
    (directory / "osm").mkdir(parents=True)
    (directory / "osm" / "graph_drive.graphml").write_text("(il caricamento è simulato)")
    monkeypatch.setattr(pick, "load_osm_graph", lambda path: full_graph())
    return directory


def test_run_scrive_il_file_ed_e_idempotente(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "live_segments.yaml"
    assert pick.main(["--data-dir", str(data_dir), "--output", str(output)]) == 0
    assert f"Scritto {output}" in capsys.readouterr().out
    config = LiveSegmentsConfig.from_yaml(output)
    assert [s.id for s in config.segments] == SPEC_IDS
    before = output.read_bytes()
    assert pick.main(["--data-dir", str(data_dir), "--output", str(output)]) == 0
    assert "già aggiornato" in capsys.readouterr().out
    assert output.read_bytes() == before


def test_dry_run_non_scrive(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "live_segments.yaml"
    assert pick.main(["--data-dir", str(data_dir), "--output", str(output), "--dry-run"]) == 0
    assert (
        not output.exists() and "--dry-run: il file non è stato scritto." in capsys.readouterr().out
    )


def test_grafo_mancante_e_un_errore_con_istruzioni(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = pick.main(["--data-dir", str(tmp_path / "vuota"), "--output", str(tmp_path / "x.yaml")])
    assert code == 2 and "make data" in capsys.readouterr().err
    assert not (tmp_path / "x.yaml").exists()


def test_un_tratto_non_costruibile_non_scrive_niente(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = full_graph()
    broken.remove_edges_from(
        [
            (u, v, k)
            for u, v, k, d in broken.edges(keys=True, data=True)
            if d["name"] == "Via Partenope"
        ]
    )
    monkeypatch.setattr(pick, "load_osm_graph", lambda path: broken)
    output = tmp_path / "x.yaml"
    assert pick.main(["--data-dir", str(data_dir), "--output", str(output)]) == 1
    assert (
        "Tratti non costruibili: via_partenope: nessun arco OSM chiamato «Via Partenope»"
        in capsys.readouterr().err
    )
    assert not output.exists()


def test_un_file_che_il_modello_rifiuterebbe_non_si_scrive(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pick, "render_yaml", lambda picked: "segments: []\n")
    output = tmp_path / "x.yaml"
    with pytest.raises(ValidationError):
        pick.main(["--data-dir", str(data_dir), "--output", str(output)])
    assert not output.exists()


def test_il_file_del_repository_e_quello_che_lo_script_genera_dalla_stessa_tabella() -> None:
    # Il file committato ha un'etichetta e un id per ogni voce della tabella dello script.
    config = LiveSegmentsConfig.from_yaml()
    ids = {s.id for s in config.segments}
    assert ids == set(SPEC_IDS)
    text = YAML_PATH.read_text(encoding="utf-8")
    assert text.count("# arco ") == 14


def test_viale_dohrn_non_e_piu_un_tratto_perche_duplicava_via_caracciolo() -> None:
    """Prova reale su TomTom (F1-10, 9/11/2026): per il punto di Viale Dohrn, su un arco di 33 m,
    TomTom restituisce lo stesso segmento di Via Caracciolo (1.372 m, geometria identica): una
    richiesta in più a ogni aggiornamento per mostrare la stessa linea due volte."""
    assert "viale_dohrn" not in {s.id for s in SEGMENTS}
    assert "viale_dohrn" not in {s.id for s in LiveSegmentsConfig.from_yaml().segments}
