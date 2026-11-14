from typing import Any

import networkx as nx
import pandas as pd
import pytest

from app.data.resolvers import (
    ResolveError,
    edge_coordinates,
    edge_key,
    edge_point,
    edges_named,
    match_keys,
    match_stops,
    nearest_edges,
    nearest_node,
    normalize_name,
    osm_name_parts,
    parse_edge_key,
    resolve_closure,
    resolve_point,
    resolve_stop,
)
from app.models.event import Closure
from app.models.geo import GeoPoint
from tests.support import (
    BBOX,
    CARACCIOLO,
    DOHRN,
    GTFS_FIXTURE,
    STREET_NODES,
    build_street_graph,
)


@pytest.fixture
def graph() -> nx.MultiDiGraph:
    return build_street_graph()


def closure(
    *names: str, bbox: tuple[float, float, float, float] | None = None, **kw: Any
) -> Closure:
    return Closure(label="Chiusura di prova", street_names=list(names), bbox=bbox, **kw)


def numeric(keys: list[str]) -> list[str]:
    """Ordine atteso: per numeri (9-10-0 prima di 10-9-0), non alfabetico."""
    return sorted(keys, key=lambda key: tuple(int(part) for part in key.split("-")))


IN_BBOX = ["1-2-0", "2-1-0", "2-3-0", "3-2-0", "3-4-0", "4-3-0"]
EVERYWHERE = numeric([*IN_BBOX, "5-6-0", "9-10-0", "10-9-0"])


# --- nomi ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MEDAGLIE D'ORO ", "MEDAGLIE D ORO"),
        ("UNIVERSITA'", "UNIVERSITA"),
        ("Città di Napoli", "CITTA DI NAPOLI"),
        ("C.SO V. EMANUELE", "C SO V EMANUELE"),
        ("  San   Pasquale ", "SAN PASQUALE"),
        ("Via Francesco Caracciòlo", "VIA FRANCESCO CARACCIOLO"),
        ("", ""),
        ("---", ""),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    ("name", "parts"),
    [
        ("Via Roma", ["Via Roma"]),
        (
            "Piazza della Repubblica; Via Francesco Caracciolo",
            ["Piazza della Repubblica", "Via Francesco Caracciolo"],
        ),
        ("A;B; ;C ", ["A", "B", "C"]),
        ("", []),
        (None, []),
        (42, []),
        (float("nan"), []),
    ],
)
def test_osm_name_parts(name: Any, parts: list[str]) -> None:
    assert osm_name_parts(name) == parts


def test_match_keys_il_nome_intero_ha_la_priorita() -> None:
    names = [("a", ["Arco Mirelli"]), ("b", ["Schipa - Arco Mirelli"]), ("c", ["Arco Mirellina"])]
    assert match_keys("arco mirelli", names) == ["a"]  # esatto: solo lui
    assert match_keys("arco mirelli", names[1:]) == ["b"]  # senza esatto: le parole intere
    assert match_keys("Arco Mirelli", [("c", ["Arco Mirellina"])]) == []  # 'MIRELLINA' non conta


def test_match_keys_parole_non_adiacenti_e_ordine_indifferente() -> None:
    names = [
        ("a", ["Via Francesco Caracciolo"]),
        ("b", ["Via Torre Caracciolo"]),
        ("c", ["Via Roma"]),
    ]
    assert match_keys("Via Caracciolo", names) == [
        "a",
        "b",
    ]  # 01 6: «via caracciolo» ≈ «via francesco caracciolo»
    assert match_keys("Caracciolo Francesco", names) == ["a"]
    assert match_keys("Via", names) == ["a", "b", "c"]


@pytest.mark.parametrize("query", ["", "   ", "---", "'"])
def test_match_keys_ricerca_vuota_non_trova_niente(query: str) -> None:
    assert match_keys(query, [("a", ["Via Roma"]), ("b", [""])]) == []


def test_match_keys_chiavi_senza_nomi_e_ordine_di_arrivo() -> None:
    assert match_keys("Via Roma", [("z", ["Via Roma"]), ("a", []), ("m", ["via roma"])]) == [
        "z",
        "m",
    ]


# --- chiusure --------------------------------------------------------------------------------


def test_chiusura_per_nome_senza_bbox_trova_la_via_ovunque(graph: nx.MultiDiGraph) -> None:
    assert resolve_closure(closure(CARACCIOLO), graph) == EVERYWHERE


def test_il_bbox_scarta_gli_omonimi_lontani(graph: nx.MultiDiGraph) -> None:
    assert resolve_closure(closure(CARACCIOLO, bbox=BBOX), graph) == IN_BBOX


def test_un_nome_fuso_con_punto_e_virgola_vale_per_entrambe_le_vie(graph: nx.MultiDiGraph) -> None:
    assert resolve_closure(closure(DOHRN), graph) == ["3-4-0", "4-3-0"]
    assert "3-4-0" in resolve_closure(closure(CARACCIOLO), graph)


@pytest.mark.parametrize(
    "spelling",
    [
        "via francesco caracciolo",
        "VIA  FRANCESCO   CARACCIOLO",
        "Via Francesco Caracciòlo",
        "Via Francesco-Caracciolo!",
    ],
)
def test_maiuscole_accenti_e_spazi_non_contano(graph: nx.MultiDiGraph, spelling: str) -> None:
    assert resolve_closure(closure(spelling, bbox=BBOX), graph) == IN_BBOX


def test_il_nome_intero_esclude_le_vie_che_lo_contengono(graph: nx.MultiDiGraph) -> None:
    keys = resolve_closure(closure(CARACCIOLO), graph)
    assert "4-1-0" not in keys  # «Via Francesco Caracciolo Nuova» non è «Via Francesco Caracciolo»
    assert resolve_closure(closure("Caracciolo Nuova"), graph) == [
        "4-1-0"
    ]  # senza esatto, le parole


def test_il_nome_corto_trova_anche_gli_omonimi_parziali(graph: nx.MultiDiGraph) -> None:
    # 01 6: «via caracciolo» ≈ «via francesco caracciolo». Prezzo: trova anche Torre e Tristano.
    keys = resolve_closure(closure("Via Caracciolo"), graph)
    assert {"7-8-0", "8-7-0", "1-2-0", "4-1-0"} <= set(keys)
    assert resolve_closure(closure("Via Caracciolo", bbox=BBOX), graph) == numeric(
        [*IN_BBOX, "4-1-0"]
    )


def test_piu_nomi_danno_l_unione_senza_doppioni_e_in_ordine(graph: nx.MultiDiGraph) -> None:
    keys = resolve_closure(closure(DOHRN, CARACCIOLO, bbox=BBOX), graph)
    assert keys == IN_BBOX  # 3-4-0 e 4-3-0 stanno in entrambi: una volta sola


@pytest.mark.parametrize("names", [(CARACCIOLO, "Via Marina"), ("Via Marina", CARACCIOLO)])
def test_l_unione_dei_nomi_non_dipende_dall_ordine(
    graph: nx.MultiDiGraph, names: tuple[str, str]
) -> None:
    # Nessuno dei due elenchi contiene l'altro: «Via Marina» è solo l'arco parallelo 1→2 (chiave 1).
    keys = resolve_closure(closure(*names, bbox=BBOX), graph)
    assert keys == numeric([*IN_BBOX, "1-2-1"])


def test_l_ordine_e_numerico_non_alfabetico(graph: nx.MultiDiGraph) -> None:
    keys = resolve_closure(closure(CARACCIOLO), graph)
    assert keys.index("9-10-0") < keys.index("10-9-0")  # come stringhe sarebbe il contrario
    assert keys == numeric(keys)


def test_ogni_nome_deve_trovare_qualcosa(graph: nx.MultiDiGraph) -> None:
    with pytest.raises(ResolveError, match="nessun arco chiamato «Via Inesistente»"):
        resolve_closure(closure(CARACCIOLO, "Via Inesistente"), graph)


def test_nessun_arco_con_quel_nome(graph: nx.MultiDiGraph) -> None:
    with pytest.raises(
        ResolveError, match=r"«Chiusura di prova»: nessun arco chiamato «Via Marinella»"
    ):
        resolve_closure(closure("Via Marinella"), graph)


def test_archi_trovati_ma_nessuno_nel_bbox(graph: nx.MultiDiGraph) -> None:
    far = (14.30, 40.90, 14.31, 40.91)
    with pytest.raises(
        ResolveError,
        match=r"9 archi chiamati «Via Francesco Caracciolo», nessuno con il punto medio dentro",
    ):
        resolve_closure(closure(CARACCIOLO, bbox=far), graph)


def test_il_bbox_usa_il_punto_medio_dell_arco_non_gli_estremi(graph: nx.MultiDiGraph) -> None:
    # Gli archi 3→4 e 4→3 (nome fuso con Dohrn) vanno da 14,2400 a 14,2450: punto medio 14,2425.
    only_east_end = (14.2440, 40.8300, 14.2460, 40.8360)  # contiene l'estremo 4, non il punto medio
    with pytest.raises(ResolveError, match="nessuno con il punto medio dentro"):
        resolve_closure(closure(DOHRN, bbox=only_east_end), graph)
    only_midpoint = (14.2420, 40.8300, 14.2430, 40.8360)  # nessun estremo, ma il punto medio sì
    assert resolve_closure(closure(DOHRN, bbox=only_midpoint), graph) == ["3-4-0", "4-3-0"]


def test_il_bbox_e_inclusivo_sui_bordi(graph: nx.MultiDiGraph) -> None:
    mid_lon = (14.2400 + 14.2450) / 2  # punto medio di 3→4, con la stessa aritmetica del codice
    mid_lat = (40.8330 + 40.8335) / 2
    keys = ["3-4-0", "4-3-0"]
    # Il punto medio sul bordo est/nord, poi sul bordo ovest/sud: dentro in tutti e due i casi.
    assert resolve_closure(closure(DOHRN, bbox=(14.2, 40.8, mid_lon, mid_lat)), graph) == keys
    assert resolve_closure(closure(DOHRN, bbox=(mid_lon, mid_lat, 14.3, 40.9)), graph) == keys
    # Appena oltre il bordo: fuori.
    with pytest.raises(ResolveError):
        resolve_closure(closure(DOHRN, bbox=(14.2, 40.8, mid_lon - 1e-6, 40.9)), graph)
    with pytest.raises(ResolveError):
        resolve_closure(closure(DOHRN, bbox=(14.2, 40.8, 14.3, mid_lat - 1e-6)), graph)


def test_un_arco_curvo_si_misura_sulla_geometria(graph: nx.MultiDiGraph) -> None:
    around_endpoints_mean = (14.2270, 40.8300, 14.2280, 40.8310)  # contiene la media degli estremi
    with pytest.raises(ResolveError, match="nessuno con il punto medio dentro"):
        resolve_closure(closure("Via Curva", bbox=around_endpoints_mean), graph)
    around_real_midpoint = (14.2270, 40.8470, 14.2280, 40.8500)
    assert resolve_closure(closure("Via Curva", bbox=around_real_midpoint), graph) == ["6-1-0"]


def test_gli_archi_senza_nome_o_con_nome_non_testo_sono_ignorati(graph: nx.MultiDiGraph) -> None:
    with pytest.raises(ResolveError):
        resolve_closure(closure("42"), graph)  # l'arco 7→1 ha name=42 (intero): non è un nome


def test_arco_parallelo_con_chiave_diversa(graph: nx.MultiDiGraph) -> None:
    assert resolve_closure(closure("Via Marina"), graph) == ["1-2-1"]


def test_chiavi_gia_risolte_sono_quelle_e_si_controlla_che_esistano(graph: nx.MultiDiGraph) -> None:
    given = ["3-4-0", "1-2-0", "1-2-1"]
    c = Closure(label="Scelta a mano", edge_keys=given)
    assert resolve_closure(c, graph) == given  # stesso ordine, nessuna ricerca per nome


def test_chiavi_gia_risolte_prevalgono_su_nomi_e_bbox(graph: nx.MultiDiGraph) -> None:
    c = Closure(
        label="Scelta a mano",
        street_names=["Via Inesistente"],
        bbox=(0.0, 0.0, 1.0, 1.0),
        edge_keys=["5-6-0"],
    )
    assert resolve_closure(c, graph) == ["5-6-0"]


def test_chiavi_inesistenti_sono_un_errore_con_l_elenco(graph: nx.MultiDiGraph) -> None:
    c = Closure(label="Scelta a mano", edge_keys=["1-2-0", "1-2-7", "99-98-0"])
    with pytest.raises(
        ResolveError, match=r"«Scelta a mano»: archi non presenti nel grafo: 1-2-7, 99-98-0"
    ):
        resolve_closure(c, graph)


def test_il_grafo_non_viene_modificato(graph: nx.MultiDiGraph) -> None:
    before = sorted(
        (u, v, k, tuple(sorted((a, str(b)) for a, b in d.items())))
        for u, v, k, d in graph.edges(keys=True, data=True)
    )
    resolve_closure(closure(CARACCIOLO, DOHRN, bbox=BBOX), graph)
    edges_named(graph, CARACCIOLO)
    after = sorted(
        (u, v, k, tuple(sorted((a, str(b)) for a, b in d.items())))
        for u, v, k, d in graph.edges(keys=True, data=True)
    )
    assert before == after


def test_il_risultato_non_dipende_dall_ordine_di_inserimento() -> None:
    forward = resolve_closure(closure(CARACCIOLO, bbox=BBOX), build_street_graph())
    backward = resolve_closure(
        closure(CARACCIOLO, bbox=BBOX), build_street_graph(list(reversed(list(STREET_NODES))))
    )
    assert forward == backward == IN_BBOX


def test_edge_key() -> None:
    assert edge_key(15413637, 11805376900, 0) == "15413637-11805376900-0"


def test_parse_edge_key_e_l_inverso_di_edge_key() -> None:
    assert parse_edge_key("15413637-11805376900-0") == (15413637, 11805376900, 0)
    assert parse_edge_key(edge_key(7, 8, 12)) == (7, 8, 12)


@pytest.mark.parametrize(
    "bad", ["", "1-2", "1-2-3-4", "a-2-0", "1--0", "-1-2-0", "1-2-x", " 1-2-0", "1-2-0 ", "1-2-²"]
)
def test_parse_edge_key_rifiuta_le_forme_sbagliate(bad: str) -> None:
    with pytest.raises(ValueError, match="chiave arco non valida"):
        parse_edge_key(bad)


def test_coordinate_di_un_arco_con_e_senza_geometria(graph: nx.MultiDiGraph) -> None:
    assert edge_coordinates(graph, (1, 2, 0), 6) == [[14.23, 40.832], [14.235, 40.8325]]
    assert edge_coordinates(graph, (6, 1, 0), 6) == [
        [14.225, 40.829],
        [14.2275, 40.85],
        [14.23, 40.832],
    ]
    assert edge_coordinates(graph, (6, 1, 0), 2) == [[14.22, 40.83], [14.23, 40.85], [14.23, 40.83]]


def test_edges_named_restituisce_chiavi_e_attributi(graph: nx.MultiDiGraph) -> None:
    named = edges_named(graph, DOHRN)
    assert [key for key, _ in named] == [(3, 4, 0), (4, 3, 0)]
    assert all(data["length_m"] == 100.0 for _, data in named)
    assert edges_named(graph, "Via Inesistente") == []


# --- punti -----------------------------------------------------------------------------------


def test_un_punto_sul_nodo_trova_quel_nodo(graph: nx.MultiDiGraph) -> None:
    assert nearest_node(GeoPoint(lat=40.8320, lon=14.2300), graph) == (1, 0.0)
    assert resolve_point(GeoPoint(lat=40.8320, lon=14.2300), graph, max_distance_m=300) == 1


def test_distanza_dal_nodo_piu_vicino(graph: nx.MultiDiGraph) -> None:
    # 0,0009° di latitudine a nord del nodo 2 = 100,08 m (0,0009 × 111 195).
    node, distance = nearest_node(GeoPoint(lat=40.8325 + 0.0009, lon=14.2350), graph)
    assert node == 2 and distance == pytest.approx(100.08, abs=0.05)


def test_il_nodo_e_il_piu_vicino_non_il_primo(graph: nx.MultiDiGraph) -> None:
    assert nearest_node(GeoPoint(lat=40.8331, lon=14.2398), graph)[0] == 3
    assert nearest_node(GeoPoint(lat=40.8963, lon=14.2703), graph)[0] == 10  # a 28 m; il 9 a 42 m


def test_oltre_la_distanza_massima_e_un_errore_con_i_numeri(graph: nx.MultiDiGraph) -> None:
    point = GeoPoint(lat=40.8325 + 0.0009, lon=14.2350)  # a 100,08 m dal nodo 2
    assert resolve_point(point, graph, max_distance_m=100.2) == 2
    with pytest.raises(
        ResolveError, match=r"dista 100 m dal nodo stradale più vicino \(massimo 100 m\)"
    ):
        resolve_point(point, graph, max_distance_m=100.0)


def test_il_limite_e_inclusivo(graph: nx.MultiDiGraph) -> None:
    point = GeoPoint(lat=40.8325 + 0.0009, lon=14.2350)
    _, distance = nearest_node(point, graph)
    assert resolve_point(point, graph, max_distance_m=distance) == 2


def test_un_punto_lontano_da_tutto(graph: nx.MultiDiGraph) -> None:
    with pytest.raises(ResolveError, match=r"\(41\.50000, 14\.50000\) dista .* m"):
        resolve_point(GeoPoint(lat=41.5, lon=14.5), graph, max_distance_m=300)


def test_a_parita_vince_l_id_minore() -> None:
    forward = nearest_node(GeoPoint(lat=40.8000, lon=14.2000), build_street_graph())
    backward = nearest_node(
        GeoPoint(lat=40.8000, lon=14.2000), build_street_graph(list(reversed(list(STREET_NODES))))
    )
    assert forward[0] == backward[0] == 11  # i nodi 11 e 12 hanno le stesse coordinate


# --- fermate (mini-GTFS) ---------------------------------------------------------------------


@pytest.fixture
def stops() -> pd.DataFrame:
    return pd.read_csv(GTFS_FIXTURE / "stops.txt", dtype=str)


def test_fermata_per_nome(stops: pd.DataFrame) -> None:
    assert resolve_stop("Arco Mirelli", stops) == ["S3"]
    assert resolve_stop("arco  MIRELLI", stops) == ["S3"]
    assert resolve_stop("Rotonda Diaz", stops) == ["S1"]


def test_fermata_per_parole_se_non_c_e_il_nome_intero(stops: pd.DataFrame) -> None:
    assert resolve_stop("Chiaia", stops) == ["S2", "S6"]  # nell'ordine della tabella
    assert resolve_stop("funicolare", stops) == ["S6"]


def test_fermata_inesistente_e_un_errore(stops: pd.DataFrame) -> None:
    with pytest.raises(ResolveError, match="Nessuna fermata chiamata «Piscinola»"):
        resolve_stop("Piscinola", stops)
    with pytest.raises(ResolveError):
        resolve_stop("", stops)


def test_il_nome_esatto_esclude_le_fermate_vicine_per_nome() -> None:
    table = pd.DataFrame(
        {
            "stop_id": ["6236", "6237", "2508", "2513"],
            "stop_name": [
                "ARCO MIRELLI",
                "ARCO MIRELLI",
                "SCHIPA - ARCO MIRELLI",
                "CRISPI-ARCO MIRELLI",
            ],
        }
    )  # come nel feed ANM vero: la stazione e due fermate bus
    assert resolve_stop("Arco Mirelli", table) == ["6236", "6237"]
    assert resolve_stop("Schipa Arco Mirelli", table) == ["2508"]


def test_match_stops_restituisce_le_righe_intere(stops: pd.DataFrame) -> None:
    found = match_stops("Mergellina", stops)
    assert list(found.columns) == list(stops.columns)
    assert found.iloc[0].to_dict()["stop_lat"] == "40.8270"
    assert match_stops("Piscinola", stops).empty


def test_un_nome_mancante_non_diventa_la_parola_nan_o_none() -> None:
    table = pd.DataFrame({"stop_id": ["1", "2"], "stop_name": [None, float("nan")]})
    assert match_stops("nan", table).empty and match_stops("None", table).empty


def test_match_stops_ignora_nomi_mancanti_e_non_cambia_la_tabella() -> None:
    table = pd.DataFrame(
        {"stop_id": ["1", "2", "3"], "stop_name": [None, "VANVITELLI ", "MEDAGLIE D'ORO"]}
    )
    before = table.copy()
    assert list(match_stops("Vanvitelli", table)["stop_id"]) == ["2"]
    assert list(match_stops("medaglie d'oro", table)["stop_id"]) == ["3"]
    pd.testing.assert_frame_equal(table, before)


# --- punti lungo un arco e arco più vicino ------------------------------------------------------


def test_edge_point_su_un_arco_dritto(graph: nx.MultiDiGraph) -> None:
    # 1→2 va da (14.2300, 40.8320) a (14.2350, 40.8325).
    assert edge_point(graph, (1, 2, 0), 0.0) == (14.23, 40.832)
    assert edge_point(graph, (1, 2, 0), 1.0) == (14.235, 40.8325)
    lon, lat = edge_point(graph, (1, 2, 0), 0.5)
    assert (lon, lat) == ((14.23 + 14.235) / 2, (40.832 + 40.8325) / 2)
    lon, lat = edge_point(graph, (1, 2, 0), 0.25)
    assert (lon, lat) == pytest.approx((14.23125, 40.832125), abs=1e-12)


def test_edge_point_segue_la_geometria_dell_arco_curvo(graph: nx.MultiDiGraph) -> None:
    # 6→1 ha una geometria con un vertice a (14.2275, 40.8500): il punto medio sale fin là.
    assert edge_point(graph, (6, 1, 0), 0.0) == pytest.approx((14.2250, 40.8290))
    assert edge_point(graph, (6, 1, 0), 1.0) == pytest.approx((14.2300, 40.8320))
    lon, lat = edge_point(graph, (6, 1, 0), 0.5)
    assert (lon, lat) == pytest.approx((14.227325, 40.848523), abs=1e-6)  # calcolato a mano


def test_arco_piu_vicino_a_un_punto(graph: nx.MultiDiGraph) -> None:
    on_edge = GeoPoint(lat=40.83225, lon=14.2325)  # a metà dell'arco 1→2 (e 2→1: stessa linea)
    ((key, distance),) = nearest_edges([on_edge], graph)
    assert key == (1, 2, 0) and distance == pytest.approx(
        0.0, abs=0.01
    )  # a parità, la chiave minore


def test_distanza_dalla_linea_in_metri(graph: nx.MultiDiGraph) -> None:
    # Il segmento 7→8 va da (14.2350, 40.8400) a (14.2380, 40.8410). Il punto 0,0009° a nord del
    # nodo 7 dista circa 100 m dal nodo, ma meno dalla LINEA. Valore calcolato a parte con una
    # proiezione azimutale equidistante su WGS84 (pyproj e shapely): 91,52 m. La funzione usa
    # la sfera (111 195 m per grado): differenza di 0,07 m.
    point = GeoPoint(lat=40.8409, lon=14.2350)
    ((key, distance),) = nearest_edges([point], graph)
    assert key in {(7, 8, 0), (8, 7, 0)}
    assert distance == pytest.approx(91.52, abs=0.2)


def test_la_distanza_e_dal_segmento_non_dalla_retta_prolungata(graph: nx.MultiDiGraph) -> None:
    # Il nodo 5 è un vicolo cieco: l'arco 5→6 sale di 0,001° su 0,005° di longitudine. Il punto
    # (40.82782, 14.2191) sta sul PROLUNGAMENTO della sua retta, 0,0009° a ovest del nodo 5: dalla
    # retta dista 0, dal segmento (cioè dal nodo 5) 78,51 m (calcolato a parte con aeqd su WGS84).
    point = GeoPoint(lat=40.82782, lon=14.2191)
    ((key, distance),) = nearest_edges([point], graph)
    assert key == (5, 6, 0)
    assert distance == pytest.approx(78.51, abs=0.2)


def test_piu_punti_in_una_chiamata_danno_gli_stessi_risultati_di_uno_alla_volta(
    graph: nx.MultiDiGraph,
) -> None:
    points = [
        GeoPoint(lat=40.83225, lon=14.2325),
        GeoPoint(lat=40.8409, lon=14.2350),
        GeoPoint(lat=40.8960, lon=14.2700),
    ]
    together = nearest_edges(points, graph)
    assert together == [nearest_edges([p], graph)[0] for p in points]
    assert nearest_edges([], graph) == []


def test_arco_piu_vicino_non_dipende_dall_ordine_di_inserimento() -> None:
    point = GeoPoint(lat=40.8325, lon=14.2325)
    forward = nearest_edges([point], build_street_graph())
    backward = nearest_edges([point], build_street_graph(list(reversed(list(STREET_NODES)))))
    assert forward == backward


def test_arco_piu_vicino_su_un_segmento_che_non_e_il_primo(graph: nx.MultiDiGraph) -> None:
    # 6→1 ha il vertice (14.2275, 40.8500): il secondo segmento va da lì a (14.2300, 40.8320).
    # Il suo punto di mezzo, (14.22875, 40.8410), sta sull'arco e a oltre 100 m dal primo segmento.
    ((key, distance),) = nearest_edges([GeoPoint(lat=40.8410, lon=14.22875)], graph)
    assert key == (6, 1, 0) and distance < 0.5
