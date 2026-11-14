import dataclasses
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from app.data.gtfs import GtfsFeed, RouteClasses, load_feed
from app.data.map_views import event_preview, network_edges, transit_lines, transit_stops
from app.models.api import Feature, FeatureCollection
from app.models.api_config import NetworkConfig
from app.models.config import EngineConfig
from tests.support import (
    BBOX,
    CARACCIOLO,
    GTFS_FIXTURE,
    build_classed_street_graph,
    build_street_graph,
    make_event,
)
from tests.transit_world import write_world_feed

WIDE = (14.19, 40.79, 14.28, 40.90)  # più largo di `detail_max_span_deg`: solo le strade maggiori
NARROW = (14.229, 40.831, 14.236, 40.834)  # abbastanza piccolo per vederle tutte


def config(**changes: Any) -> NetworkConfig:
    fields: dict[str, Any] = {
        "major_classes": ["motorway", "trunk", "primary", "secondary", "tertiary"],
        "detail_max_span_deg": 0.012,
        "max_span_deg": 0.25,
        "max_features": 4000,
    }
    return NetworkConfig.model_validate({**fields, **changes})


def path(feature: Feature) -> Any:
    """Le coordinate della geometria di una feature."""
    assert feature.geometry is not None
    return feature.geometry["coordinates"]


def keys(collection: FeatureCollection) -> list[str]:
    return [str(feature.properties["edge_key"]) for feature in collection.features]


def by_key(collection: FeatureCollection) -> dict[str, dict[str, Any]]:
    return {str(f.properties["edge_key"]): dict(f.properties) for f in collection.features}


# --- strade ------------------------------------------------------------------------------------


def test_un_area_grande_mostra_solo_le_strade_maggiori_una_volta_per_strada() -> None:
    edges = network_edges(build_classed_street_graph(), WIDE, config())
    # una feature per strada (i due sensi insieme), prima per chiave
    assert keys(edges) == ["1-2-0", "1-7-0", "2-3-0", "3-4-0", "9-10-0"]
    reverse = {k: p["reverse_key"] for k, p in by_key(edges).items()}
    assert reverse == {
        "1-2-0": "2-1-0",
        "1-7-0": "7-1-0",
        "2-3-0": "3-2-0",
        "3-4-0": "4-3-0",
        "9-10-0": "10-9-0",
    }


def test_un_area_piccola_mostra_tutte_le_strade_con_le_maggiori_per_prime() -> None:
    edges = network_edges(build_classed_street_graph(), NARROW, config())
    # maggiori (1-2, 1-7, 2-3) e poi le altre (1-2-1 «Via Marina», 4-1, 6-1), ognuna per chiave
    assert keys(edges) == ["1-2-0", "1-7-0", "2-3-0", "1-2-1", "4-1-0", "6-1-0"]


def test_il_confine_dell_area_piccola_e_la_soglia() -> None:
    graph = build_classed_street_graph()
    limit = config(detail_max_span_deg=0.5, max_span_deg=0.5)  # 0,5 si scrive esatto in binario
    exact = (14.0, 40.5, 14.5, 41.0)
    over = (14.0, 40.5, 14.5001, 41.0)
    assert "1-2-1" in keys(network_edges(graph, exact, limit))
    assert "1-2-1" not in keys(network_edges(graph, over, limit))


def test_due_archi_paralleli_con_nomi_diversi_sono_due_strade() -> None:
    props = by_key(network_edges(build_classed_street_graph(), NARROW, config()))
    assert props["1-2-0"]["reverse_key"] == "2-1-0"  # Via Caracciolo, nei due sensi
    assert props["1-2-1"]["name"] == "Via Marina"
    assert props["1-2-1"]["reverse_key"] is None  # il parallelo non è il ritorno dell'altra


def test_i_nomi_nell_altro_ordine_sono_la_stessa_strada() -> None:
    graph = build_classed_street_graph()
    graph.edges[4, 3, 0]["name"] = f"{CARACCIOLO}; Viale Anton Dohrn"  # OSMnx li fonde come vuole
    props = by_key(network_edges(graph, WIDE, config()))
    assert props["3-4-0"]["reverse_key"] == "4-3-0"


def test_tre_archi_uguali_tra_gli_stessi_nodi_non_si_abbinano_due_volte() -> None:
    graph = build_classed_street_graph()
    graph.add_edge(2, 1, key=1, name=CARACCIOLO, length_m=100.0, highway="primary")  # un terzo
    edges = network_edges(graph, WIDE, config())
    props = by_key(edges)
    assert props["1-2-0"]["reverse_key"] == "2-1-0"
    assert props["2-1-1"]["reverse_key"] is None  # 1-2-0 è già il ritorno di 2-1-0
    used = [k for p in props.values() for k in (p["edge_key"], p["reverse_key"]) if k]
    assert len(used) == len(set(used))  # nessun arco compare due volte


def test_due_anelli_sullo_stesso_nodo_non_sono_l_uno_il_ritorno_dell_altro() -> None:
    graph = build_classed_street_graph()
    for k in (0, 1):
        graph.add_edge(2, 2, key=k, name="Rotatoria", length_m=100.0, highway="primary")
    props = by_key(network_edges(graph, WIDE, config()))
    assert props["2-2-0"]["reverse_key"] is None and props["2-2-1"]["reverse_key"] is None


def test_nomi_diversi_nei_due_sensi_sono_due_strade() -> None:
    # 7→8 «Via Torre Caracciolo» e 8→7 «Via Tristano Caracciolo»: stessa classe e lunghezza
    props = by_key(
        network_edges(build_classed_street_graph(), (14.234, 40.839, 14.239, 40.842), config())
    )
    assert props["7-8-0"]["reverse_key"] is None
    assert props["8-7-0"]["reverse_key"] is None


def test_un_arco_che_tocca_il_bordo_dell_area_c_e() -> None:
    # 1→2 arriva fino a 14,2350: l'area parte esattamente da lì
    touching = (14.2350, 40.8324, 14.2355, 40.8326)
    assert "1-2-0" in keys(network_edges(build_classed_street_graph(), touching, config()))


def test_un_senso_unico_non_ha_il_ritorno() -> None:
    props = by_key(network_edges(build_classed_street_graph(), NARROW, config()))
    assert props["6-1-0"]["reverse_key"] is None
    assert props["4-1-0"]["reverse_key"] is None  # c'è 4-1 ma non 1-4


def test_lunghezza_o_classe_diverse_non_fanno_il_ritorno() -> None:
    graph = build_classed_street_graph()
    graph.edges[2, 1, 0]["length_m"] = 150.0
    graph.edges[3, 2, 0]["highway"] = "secondary"
    props = by_key(network_edges(graph, WIDE, config()))
    assert props["1-2-0"]["reverse_key"] is None
    assert props["2-3-0"]["reverse_key"] is None
    assert props["3-4-0"]["reverse_key"] == "4-3-0"


def test_le_proprieta_di_una_strada() -> None:
    props = by_key(network_edges(build_classed_street_graph(), NARROW, config()))
    wide = by_key(network_edges(build_classed_street_graph(), WIDE, config()))
    assert wide["3-4-0"]["name"] == "Viale Anton Dohrn; Via Francesco Caracciolo"
    assert wide["3-4-0"]["highway"] == "secondary"
    assert wide["3-4-0"]["length_m"] == 100
    assert wide["1-7-0"]["name"] == ""  # arco senza nome
    assert wide["1-7-0"]["highway"] == "tertiary"  # niente `_link`
    assert props["2-3-0"]["highway"] == "primary, residential"  # più classi


def test_la_geometria_segue_la_linea_dell_arco() -> None:
    edges = network_edges(build_classed_street_graph(), NARROW, config())
    feature = next(f for f in edges.features if f.id == "6-1-0")
    assert path(feature) == [[14.225, 40.829], [14.2275, 40.85], [14.23, 40.832]]
    straight = next(f for f in edges.features if f.id == "1-2-0")
    assert path(straight) == [[14.23, 40.832], [14.235, 40.8325]]


def test_un_arco_curvo_si_trova_dove_passa_la_sua_linea() -> None:
    # gli estremi di «Via Curva» sono a sud; la linea sale a 40,85: la si vede lì, e basta
    north = (14.2270, 40.845, 14.2280, 40.851)
    assert keys(network_edges(build_classed_street_graph(), north, config())) == ["6-1-0"]


def test_un_area_senza_strade_e_vuota() -> None:
    assert (
        network_edges(build_classed_street_graph(), (14.5, 41.0, 14.51, 41.01), config()).features
        == []
    )


def test_il_tetto_alle_feature_tiene_le_maggiori() -> None:
    edges = network_edges(build_classed_street_graph(), NARROW, config(max_features=2))
    assert keys(edges) == ["1-2-0", "1-7-0"]


def test_le_classi_maggiori_sono_un_parametro() -> None:
    only_secondary = config(major_classes=["secondary"])
    assert keys(network_edges(build_classed_street_graph(), WIDE, only_secondary)) == ["3-4-0"]


def test_gli_archi_senza_classe_non_sono_maggiori() -> None:
    assert network_edges(build_street_graph(), WIDE, config()).features == []


# --- fermate -----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def feed() -> GtfsFeed:
    return load_feed(GTFS_FIXTURE)


def test_le_fermate_nell_area_con_le_linee_che_le_servono(feed: GtfsFeed) -> None:
    stops = transit_stops(feed, (14.229, 40.831, 14.241, 40.835), config())
    found = {str(f.id): dict(f.properties) for f in stops.features}
    assert set(found) == {"S1", "S2", "S3", "S6"}  # S4, S5 sono lontane
    assert found["S2"] == {
        "stop_id": "S2",
        "name": "RIVIERA DI CHIAIA",
        "routes": ["CHIAIA", "F1", "L1"],
        "kind": "real",
    }
    assert found["S1"]["routes"] == ["L1", "L6"]
    point = next(f for f in stops.features if f.id == "S1").geometry
    assert point == {"type": "Point", "coordinates": [14.235, 40.832]}


def test_le_fermate_sul_bordo_dell_area_ci_sono(feed: GtfsFeed) -> None:
    assert [
        f.id for f in transit_stops(feed, (14.2350, 40.8320, 14.2351, 40.8321), config()).features
    ] == ["S1"]


def test_un_area_senza_fermate_e_vuota(feed: GtfsFeed) -> None:
    assert transit_stops(feed, (14.5, 41.0, 14.51, 41.01), config()).features == []


def test_il_tetto_alle_fermate(feed: GtfsFeed) -> None:
    stops = transit_stops(feed, (14.0, 40.0, 15.0, 41.0), config(max_features=2))
    assert len(stops.features) == 2


def test_una_fermata_senza_corse_ha_l_elenco_delle_linee_vuoto(feed: GtfsFeed) -> None:
    lonely = dataclasses.replace(
        feed, stop_times=feed.stop_times[feed.stop_times["stop_id"] != "S4"]
    )
    found = transit_stops(lonely, (14.21, 40.82, 14.22, 40.83), config()).features
    assert [(f.id, f.properties["routes"]) for f in found] == [("S4", [])]


def test_senza_i_nomi_delle_linee_si_usa_il_route_id(tmp_path: Path) -> None:
    world = load_feed(write_world_feed(tmp_path))
    stops = transit_stops(world, (14.234, 40.831, 14.237, 40.835), config())
    routes = {str(f.id): f.properties["routes"] for f in stops.features}
    assert routes["g1"] == ["RL"]
    assert routes["u1"] == ["RB", "RX"]  # due linee, in ordine
    assert routes["d5"] == ["RD"] and routes["m2"] == ["RS"]


# --- linee -------------------------------------------------------------------------------------

CLASSES = RouteClasses(
    {
        "metro_line_1": frozenset({"R1"}),
        "metro_line_6": frozenset({"R2"}),
        "funicular": frozenset({"R3"}),
        "bus": frozenset({"R4", "R6"}),
    }
)
RAIL = ("metro_line_1", "metro_line_6", "funicular")


def test_le_linee_sono_la_corsa_piu_lunga_con_le_fermate_in_ordine(feed: GtfsFeed) -> None:
    lines = transit_lines(feed, CLASSES, RAIL)
    assert [f.id for f in lines.features] == ["R1", "R2", "R3"]
    first = lines.features[0]
    assert first.properties == {
        "route_id": "R1",
        "route_class": "metro_line_1",
        "label": "METRO LINEA L1",
        "kind": "line",
    }
    # L1_A ha tre fermate, scritte fuori ordine nel file: contano i `stop_sequence` (S1, S2, S3)
    assert path(first) == [
        [14.235, 40.832],
        [14.2352, 40.833],
        [14.2304, 40.8313],
    ]
    assert path(lines.features[2]) == [[14.24, 40.834], [14.2352, 40.833]]


def test_si_disegnano_solo_le_classi_chieste(feed: GtfsFeed) -> None:
    lines = transit_lines(feed, CLASSES, ("funicular",))
    assert [(f.id, f.properties["route_class"]) for f in lines.features] == [("R3", "funicular")]
    assert transit_lines(feed, CLASSES, ()).features == []


def test_il_nome_lungo_mancante_ripiega_sul_breve(feed: GtfsFeed) -> None:
    routes = feed.routes.copy()
    routes.loc[routes["route_id"] == "R3", "route_long_name"] = pd.NA
    patched = dataclasses.replace(feed, routes=routes)
    labels = {f.id: f.properties["label"] for f in transit_lines(patched, CLASSES, RAIL).features}
    assert labels == {"R1": "METRO LINEA L1", "R2": "METRO LINEA L6", "R3": "F1"}


def test_senza_i_nomi_nel_feed_la_linea_porta_il_route_id(tmp_path: Path) -> None:
    world = load_feed(write_world_feed(tmp_path))
    classes = RouteClasses(
        {
            "metro_line_1": frozenset({"RL"}),
            "metro_line_6": frozenset({"RS"}),
            "funicular": frozenset({"RD"}),
            "bus": frozenset({"RB"}),
        }
    )
    lines = transit_lines(world, classes, RAIL)
    assert {f.id: f.properties["label"] for f in lines.features} == {
        "RD": "RD",
        "RL": "RL",
        "RS": "RS",
    }
    # RD: la corsa più lunga è TE (tre fermate); RL: tre fermate, la prima in elenco
    paths = {str(f.id): len(path(f)) for f in lines.features}
    assert paths == {"RD": 3, "RL": 3, "RS": 2}


def test_una_linea_con_meno_di_due_fermate_note_non_si_disegna(feed: GtfsFeed) -> None:
    only_one = feed.stops[feed.stops["stop_id"] != "S1"]
    cut = dataclasses.replace(feed, stops=only_one)
    ids = [f.id for f in transit_lines(cut, CLASSES, RAIL).features]
    assert ids == ["R1", "R3"]  # R2 (S3 → S1) resta con una sola fermata nota


# --- anteprima di un Evento --------------------------------------------------------------------


def preview(**changes: Any) -> FeatureCollection:
    event = make_event(
        car_destinations=[
            {"point": {"lat": 40.8330, "lon": 14.2400, "label": "Parcheggio"}, "share_pct": 100}
        ],
        **changes,
    )
    return event_preview(
        event, build_classed_street_graph(), load_feed(GTFS_FIXTURE).stops, EngineConfig.from_yaml()
    )


def of_kind(collection: FeatureCollection, kind: str) -> list[Any]:
    return [f for f in collection.features if f.properties["kind"] == kind]


def test_l_anteprima_senza_chiusure_ha_il_centro_e_gli_arrivi_in_auto() -> None:
    result = preview()
    assert [f.properties["kind"] for f in result.features] == ["area_center", "car_destination"]
    center, car = result.features
    assert center.geometry == {"type": "Point", "coordinates": [14.235, 40.832]}
    assert center.properties["label"] == "Rotonda Diaz"
    assert center.properties["node"] == 2 and center.properties["distance_m"] == 56
    assert car.properties["label"] == "Arrivo auto: Parcheggio"
    assert car.properties["node"] == 3 and car.properties["distance_m"] == 0  # proprio sul nodo


def test_le_chiusure_per_nome_diventano_una_linea_per_arco() -> None:
    closure = {"label": "Via Caracciolo", "street_names": [CARACCIOLO], "bbox": list(BBOX)}
    result = preview(closures=[closure])
    lines = of_kind(result, "closure")
    assert [f.id for f in lines] == ["1-2-0", "2-1-0", "2-3-0", "3-2-0", "3-4-0", "4-3-0"]
    assert all(f.properties["label"] == "Via Caracciolo" for f in lines)
    first = lines[0].properties
    assert (first["edge_key"], first["name"], first["length_m"]) == ("1-2-0", CARACCIOLO, 100)
    assert path(lines[0]) == [[14.23, 40.832], [14.235, 40.8325]]


def test_le_chiusure_con_le_chiavi_gia_scelte_non_cercano_altro() -> None:
    closure = {"label": "Scelta a mano", "edge_keys": ["1-2-1"]}
    lines = of_kind(preview(closures=[closure]), "closure")
    assert [(f.id, f.properties["name"]) for f in lines] == [("1-2-1", "Via Marina")]


def test_una_chiusura_che_non_si_risolve_non_compare_ma_le_altre_si() -> None:
    closures = [
        {"label": "Strada inventata", "street_names": ["Via Che Non Esiste"]},
        {"label": "Chiavi sbagliate", "edge_keys": ["99-98-0"]},
        {"label": "Via Marina", "street_names": ["Via Marina"]},
    ]
    lines = of_kind(preview(closures=closures), "closure")
    assert [f.id for f in lines] == ["1-2-1"]


def test_le_fermate_interrotte_per_nome_o_per_id() -> None:
    disruptions = [
        {"label": "Rotonda Diaz chiusa", "stop_name": "ROTONDA DIAZ", "window": "both"},
        {
            "label": "Mergellina chiusa",
            "stop_name": "qualunque",
            "stop_ids": ["S4"],
            "window": "arrival",
        },
    ]
    stops = of_kind(preview(transit_disruptions=disruptions), "stop")
    assert [(f.id, f.properties["label"], f.properties["name"]) for f in stops] == [
        ("S1", "Rotonda Diaz chiusa", "ROTONDA DIAZ"),
        ("S4", "Mergellina chiusa", "MERGELLINA"),
    ]
    assert stops[0].geometry == {"type": "Point", "coordinates": [14.235, 40.832]}
    assert stops[0].properties["stop_id"] == "S1"


def test_una_fermata_che_non_si_risolve_non_compare() -> None:
    disruptions = [
        {"label": "Fantasma", "stop_name": "FERMATA CHE NON C'È", "window": "both"},
        {"label": "Id sconosciuto", "stop_name": "x", "stop_ids": ["ZZ"], "window": "both"},
    ]
    assert of_kind(preview(transit_disruptions=disruptions), "stop") == []


def test_il_centro_senza_etichetta_porta_il_nome_dell_evento() -> None:
    result = preview(area_center={"lat": 40.8320, "lon": 14.2350})
    assert of_kind(result, "area_center")[0].properties["label"] == "Evento di prova"


def test_gli_arrivi_in_auto_senza_etichetta_si_dicono() -> None:
    event = make_event(
        car_destinations=[{"point": {"lat": 40.833, "lon": 14.24}, "share_pct": 100}]
    )
    result = event_preview(
        event, build_classed_street_graph(), load_feed(GTFS_FIXTURE).stops, EngineConfig.from_yaml()
    )
    assert (
        of_kind(result, "car_destination")[0].properties["label"] == "Arrivo auto: senza etichetta"
    )


def test_senza_destinazioni_proprie_valgono_quelle_di_engine_yaml() -> None:
    event = make_event()
    default = EngineConfig.from_yaml().demand.car_destinations
    result = event_preview(
        event, build_classed_street_graph(), load_feed(GTFS_FIXTURE).stops, EngineConfig.from_yaml()
    )
    assert len(of_kind(result, "car_destination")) == len(default)
