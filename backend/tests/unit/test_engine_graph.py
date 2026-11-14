import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox
import pytest

from app.engine.graph import (
    GraphError,
    build_road_graph,
    clear_road_graph_cache,
    describe_sources,
    load_road_graph,
    osm_lanes_per_direction,
    road_params,
)
from app.models.config import EngineConfig, RoadDefault
from app.models.edge_overrides import EdgeOverrides
from tests.support import build_raw_road_graph

ENGINE_ATTRIBUTES = ("lanes", "lanes_source", "speed_kmh", "speed_source", "t0_min", "capacity_vph")


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    clear_road_graph_cache()
    yield
    clear_road_graph_cache()


def overrides_of(*items: dict[str, Any]) -> EdgeOverrides:
    return EdgeOverrides.model_validate({"version": 1, "overrides": list(items)})


def attrs(graph: nx.MultiDiGraph, key: tuple[int, int, int]) -> dict[str, Any]:
    return {name: graph.edges[key][name] for name in ENGINE_ATTRIBUTES}


# (arco, corsie, origine corsie, velocità, origine velocità, t0 in minuti, capacità)
EXPECTED = [
    # tutto da OSM: lanes=3 e maxspeed=60; capacità = 3 × 900 della classe primary
    ((1, 2, 0), 3, "osm", 60.0, "osm", 0.3, 2700.0),
    # arco parallelo: corsie di riserva del tertiary (1), velocità OSM 40: 310 m a 40 km/h = 27,9 s
    ((1, 2, 1), 1, "default", 40.0, "osm", 310 / (40 / 3.6) / 60, 600.0),
    # tutto di riserva: primary → 2 corsie, 50 km/h, 2 × 900; 500 m a 50 km/h = 36 s = 0,6 min
    ((2, 3, 0), 2, "default", 50.0, "default", 0.6, 1800.0),
    # corsie OSM (2) ma capacità per corsia della classe residential (400): 2 × 400, non altro
    ((3, 4, 0), 2, "osm", 30.0, "default", 0.2, 800.0),
    # classe emergency_bay non prevista → riga `default`; 60 m a 30 km/h = 7,2 s = 0,12 min
    ((4, 5, 0), 1, "default", 30.0, "default", 0.12, 400.0),
    # senza `highway` → riga `default`; 150 m a 30 km/h = 18 s = 0,3 min
    ((5, 1, 0), 1, "default", 30.0, "default", 0.3, 400.0),
    # anello su se stesso: viene trattato come gli altri; 20 m a 30 km/h = 2,4 s = 0,04 min
    ((3, 3, 0), 1, "default", 30.0, "default", 0.04, 400.0),
    # doppio senso, lanes OSM 4 = 2 + 2: 2 per senso; 2 × 900; 300 m a 50 km/h = 21,6 s = 0,36 min
    ((2, 1, 0), 2, "osm", 50.0, "default", 0.36, 1800.0),
    # doppio senso, lanes OSM 2 = 1 + 1: 1 per senso (e non 2: sarebbe il doppio della capacità
    # reale); 1 × 600; 500 m a 40 km/h = 45 s = 0,75 min
    ((3, 2, 0), 1, "osm", 40.0, "default", 0.75, 600.0),
    # doppio senso, lanes OSM 3 (dispari): per difetto 3 // 2 = 1; 1 × 400
    ((4, 3, 0), 1, "osm", 30.0, "default", 0.2, 400.0),
    # doppio senso, lanes OSM 1: mai meno di una corsia per senso (1 // 2 = 0 → 1)
    ((5, 4, 0), 1, "osm", 30.0, "default", 0.12, 400.0),
    # doppio senso SENZA lanes OSM: i valori di riserva sono già per senso, non si dimezzano:
    # primary → 2 corsie; 2 × 900; 150 m a 50 km/h = 10,8 s = 0,18 min
    ((1, 5, 0), 2, "default", 50.0, "default", 0.18, 1800.0),
    # `oneway` assente con lanes OSM 2: in OSM l'assenza vuol dire doppio senso → 1; 1 × 900;
    # 200 m a 50 km/h = 14,4 s = 0,24 min
    ((2, 5, 0), 1, "osm", 50.0, "default", 0.24, 900.0),
]


@pytest.mark.parametrize(
    ("key", "lanes", "lanes_source", "speed", "speed_source", "t0", "capacity"), EXPECTED
)
def test_attributi_di_ogni_arco(
    config: EngineConfig,
    key: tuple[int, int, int],
    lanes: int,
    lanes_source: str,
    speed: float,
    speed_source: str,
    t0: float,
    capacity: float,
) -> None:
    got = attrs(build_road_graph(build_raw_road_graph(), config), key)
    assert got["lanes"] == lanes and isinstance(got["lanes"], int)
    assert got["lanes_source"] == lanes_source
    assert got["speed_kmh"] == speed and isinstance(got["speed_kmh"], float)
    assert got["speed_source"] == speed_source
    assert got["t0_min"] == pytest.approx(t0, rel=1e-12)
    assert got["capacity_vph"] == pytest.approx(capacity, rel=1e-12)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"lanes": 2, "oneway": True}, 2),  # senso unico: com'è
        ({"lanes": 3, "oneway": True}, 3),
        ({"lanes": 1, "oneway": True}, 1),
        ({"lanes": 2, "oneway": False}, 1),  # doppio senso: i due sensi insieme
        ({"lanes": 4, "oneway": False}, 2),
        ({"lanes": 5, "oneway": False}, 2),  # dispari: per difetto
        ({"lanes": 3, "oneway": False}, 1),
        ({"lanes": 1, "oneway": False}, 1),  # mai zero
        ({"lanes": 2}, 1),  # `oneway` assente = doppio senso (semantica OSM)
        ({"oneway": False}, None),  # OSM non dà le corsie
        ({"oneway": True}, None),
        ({}, None),
    ],
)
def test_corsie_osm_per_senso_di_marcia(data: dict[str, Any], expected: int | None) -> None:
    assert osm_lanes_per_direction(data) == expected


def test_la_correzione_manuale_e_gia_per_senso_e_non_si_dimezza(config: EngineConfig) -> None:
    ov = overrides_of({"edge_key": "2-1-0", "lanes": 3, "reason": "3 corsie per senso"})
    got = attrs(build_road_graph(build_raw_road_graph(), config, ov), (2, 1, 0))
    # arco a doppio senso con lanes OSM 4: la correzione (3) vale per senso, 3 × 900
    assert got["lanes"] == 3 and got["lanes_source"] == "override"
    assert got["capacity_vph"] == 2700.0


def test_ogni_arco_ha_tutti_gli_attributi_e_la_topologia_non_cambia(config: EngineConfig) -> None:
    raw = build_raw_road_graph()
    graph = build_road_graph(raw, config)
    assert (
        sorted(graph.edges(keys=True))
        == sorted(raw.edges(keys=True))
        == sorted(key for key, *_ in EXPECTED)
    )
    for _u, _v, _k, data in graph.edges(keys=True, data=True):
        assert all(name in data for name in ENGINE_ATTRIBUTES)
        assert data["lanes_source"] in {"osm", "default", "override"}
        assert data["speed_source"] in {"osm", "default", "override"}
        assert data["t0_min"] > 0 and data["capacity_vph"] > 0
    assert dict(graph.nodes(data=True)) == dict(raw.nodes(data=True))


def test_gli_attributi_osm_restano_come_sono(config: EngineConfig) -> None:
    graph = build_road_graph(build_raw_road_graph(), config)
    first = graph.edges[1, 2, 0]
    assert (first["highway"], first["maxspeed_kmh"], first["length_m"], first["oneway"]) == (
        "primary",
        60,
        300.0,
        True,
    )
    assert "maxspeed_kmh" not in graph.edges[2, 3, 0]  # il valore di riserva non finisce lì


def test_il_grafo_grezzo_non_viene_modificato(config: EngineConfig) -> None:
    def snapshot(g: nx.MultiDiGraph) -> list[Any]:
        return sorted((u, v, k, sorted(d.items())) for u, v, k, d in g.edges(keys=True, data=True))

    raw = build_raw_road_graph()
    before = snapshot(raw)
    graph = build_road_graph(
        raw, config, overrides_of({"edge_key": "2-3-0", "lanes": 4, "reason": "r"})
    )
    assert snapshot(raw) == before
    assert "capacity_vph" not in raw.edges[2, 3, 0] and "lanes" not in raw.edges[2, 3, 0]
    graph.edges[2, 3, 0]["capacity_vph"] = 0.0  # la copia è indipendente
    assert "capacity_vph" not in raw.edges[2, 3, 0]


def test_i_numeri_vengono_dalla_configurazione_non_dal_codice(config: EngineConfig) -> None:
    changed = dict(config.road_defaults)
    changed["primary"] = RoadDefault(lanes=5, speed_kmh=90, capacity_per_lane=1000)
    changed["default"] = RoadDefault(lanes=3, speed_kmh=20, capacity_per_lane=100)
    graph = build_road_graph(
        build_raw_road_graph(), config.model_copy(update={"road_defaults": changed})
    )
    # 2-3-0 è primary senza dati OSM: 5 corsie, 90 km/h, 5 × 1000; 500 m a 90 km/h = 20 s
    assert attrs(graph, (2, 3, 0)) == {
        "lanes": 5,
        "lanes_source": "default",
        "speed_kmh": 90.0,
        "speed_source": "default",
        "t0_min": pytest.approx(500 / 25 / 60),
        "capacity_vph": 5000.0,
    }
    # senza `highway` vale la riga `default` modificata: 3 corsie, 20 km/h, 3 × 100; 150 m a 20 km/h
    assert attrs(graph, (5, 1, 0))["capacity_vph"] == 300.0
    assert attrs(graph, (5, 1, 0))["t0_min"] == pytest.approx(150 / (20 / 3.6) / 60)
    # corsie OSM della 1-2-0 (3) × capacità per corsia modificata (1000), velocità OSM invariata
    assert attrs(graph, (1, 2, 0))["capacity_vph"] == 3000.0


def test_il_risultato_non_dipende_dall_ordine_degli_archi(config: EngineConfig) -> None:
    raw = build_raw_road_graph()
    shuffled: nx.MultiDiGraph = nx.MultiDiGraph()
    shuffled.add_nodes_from(reversed(list(raw.nodes(data=True))))
    for u, v, k, d in reversed(list(raw.edges(keys=True, data=True))):
        shuffled.add_edge(u, v, key=k, **d)
    overrides = overrides_of({"edge_key": "3-4-0", "speed_kmh": 20, "reason": "r"})
    a = build_road_graph(raw, config, overrides)
    b = build_road_graph(shuffled, config, overrides)
    assert {key: attrs(a, key) for key in a.edges(keys=True)} == {
        key: attrs(b, key) for key in b.edges(keys=True)
    }
    again = build_road_graph(raw, config, overrides)
    assert [(key, attrs(a, key)) for key in a.edges(keys=True)] == [
        (key, attrs(again, key)) for key in again.edges(keys=True)
    ]


# --- classi di strada -----------------------------------------------------------------------------


def test_road_params_classe_nota_sconosciuta_e_assente(config: EngineConfig) -> None:
    assert road_params(config, "primary") == RoadDefault(
        lanes=2, speed_kmh=50, capacity_per_lane=900
    )
    default = RoadDefault(lanes=1, speed_kmh=30, capacity_per_lane=400)
    assert config.road_defaults["default"] == default
    assert road_params(config, "emergency_bay") == default
    assert road_params(config, None) == default
    assert road_params(config, ["primary", "secondary"]) == default  # non è una stringa
    assert road_params(config, "default") == default
    assert road_params(config, "Primary") == default  # le classi OSM sono minuscole: nessuna magia


# --- da dove vengono corsie e velocità ---------------------------------------------------------


def test_origine_di_corsie_e_velocita_per_le_assunzioni(config: EngineConfig) -> None:
    """Dei 13 archi di prova: `lanes` in OSM su 7 (1-2-0, 3-4-0, 2-1-0, 3-2-0, 4-3-0, 5-4-0,
    2-5-0), velocità in OSM su 2 (1-2-0 e 1-2-1)."""
    built = build_road_graph(build_raw_road_graph(), config)
    assert describe_sources(built) == (
        "rete di 13 archi; "
        "corsie per senso: 7 da OSM, 6 da valore di riserva della classe, 0 da correzione manuale; "
        "velocità: 2 da OSM, 11 da valore di riserva della classe, 0 da correzione manuale"
    )


def test_le_correzioni_manuali_compaiono_nell_origine(config: EngineConfig) -> None:
    ov = overrides_of(
        {"edge_key": "2-3-0", "lanes": 4, "reason": "OSM senza lanes"},  # riserva → correzione
        {"edge_key": "1-2-0", "speed_kmh": 30, "reason": "zona 30"},  # OSM → correzione
    )
    built = build_road_graph(build_raw_road_graph(), config, ov)
    assert describe_sources(built) == (
        "rete di 13 archi; "
        "corsie per senso: 7 da OSM, 5 da valore di riserva della classe, 1 da correzione manuale; "
        "velocità: 1 da OSM, 11 da valore di riserva della classe, 1 da correzione manuale"
    )


# --- correzioni manuali ---------------------------------------------------------------------------


def test_correzione_delle_corsie_dove_osm_non_le_ha(config: EngineConfig) -> None:
    ov = overrides_of({"edge_key": "2-3-0", "lanes": 4, "reason": "OSM senza lanes"})
    got = attrs(build_road_graph(build_raw_road_graph(), config, ov), (2, 3, 0))
    # 4 corsie × 900 della classe; la velocità resta di riserva (50) e il tempo non cambia
    assert got["lanes"] == 4 and got["lanes_source"] == "override"
    assert got["capacity_vph"] == 3600.0
    assert got["speed_kmh"] == 50.0 and got["speed_source"] == "default"
    assert got["t0_min"] == pytest.approx(0.6)


def test_la_correzione_prevale_sul_dato_osm(config: EngineConfig) -> None:
    ov = overrides_of({"edge_key": "1-2-0", "speed_kmh": 30, "reason": "OSM 60 ma zona 30"})
    got = attrs(build_road_graph(build_raw_road_graph(), config, ov), (1, 2, 0))
    # velocità 30 (era 60 da OSM): 300 m a 30 km/h = 36 s = 0,6 min; corsie OSM invariate
    assert got["speed_kmh"] == 30.0 and got["speed_source"] == "override"
    assert got["t0_min"] == pytest.approx(0.6)
    assert got["lanes"] == 3 and got["lanes_source"] == "osm" and got["capacity_vph"] == 2700.0


def test_correzione_di_corsie_e_velocita_insieme(config: EngineConfig) -> None:
    ov = overrides_of({"edge_key": "5-1-0", "lanes": 2, "speed_kmh": 40, "reason": "r"})
    got = attrs(build_road_graph(build_raw_road_graph(), config, ov), (5, 1, 0))
    # classe `default` (400 per corsia): 2 × 400; 150 m a 40 km/h = 13,5 s = 0,225 min
    assert got == {
        "lanes": 2,
        "lanes_source": "override",
        "speed_kmh": 40.0,
        "speed_source": "override",
        "t0_min": pytest.approx(0.225),
        "capacity_vph": 800.0,
    }


def test_la_correzione_tocca_solo_il_suo_arco(config: EngineConfig) -> None:
    raw = build_raw_road_graph()
    plain = build_road_graph(raw, config)
    ov = overrides_of({"edge_key": "2-3-0", "lanes": 4, "reason": "r"})
    corrected = build_road_graph(raw, config, ov)
    for key in plain.edges(keys=True):
        if key != (2, 3, 0):
            assert attrs(corrected, key) == attrs(plain, key)
    assert attrs(corrected, (2, 3, 0)) != attrs(plain, (2, 3, 0))


def test_un_arco_parallelo_si_corregge_da_solo(config: EngineConfig) -> None:
    ov = overrides_of({"edge_key": "1-2-1", "lanes": 2, "reason": "r"})
    graph = build_road_graph(build_raw_road_graph(), config, ov)
    assert (
        attrs(graph, (1, 2, 1))["lanes"] == 2 and attrs(graph, (1, 2, 1))["capacity_vph"] == 1200.0
    )
    assert attrs(graph, (1, 2, 0))["lanes_source"] == "osm"


def test_nessuna_correzione_o_elenco_vuoto_non_cambiano_niente(config: EngineConfig) -> None:
    raw = build_raw_road_graph()
    base = build_road_graph(raw, config)
    for ov in (None, overrides_of()):
        other = build_road_graph(raw, config, ov)
        assert {k: attrs(other, k) for k in other.edges(keys=True)} == {
            k: attrs(base, k) for k in base.edges(keys=True)
        }


def test_correzione_su_arco_inesistente_e_un_errore_con_l_elenco(config: EngineConfig) -> None:
    # sei chiavi inesistenti in ordine sparso (più una esistente): l'elenco è ordinato e completo.
    # Con poche chiavi un ordine casuale (l'ordine di un set cambia a ogni processo) potrebbe
    # coincidere con quello giusto e il controllo passerebbe per caso.
    missing = ["99-98-0", "3-4-9", "1-2-7", "20-1-0", "5-1-1", "1-5-3"]
    ov = overrides_of(
        *({"edge_key": key, "lanes": 2, "reason": "r"} for key in ["1-2-0", *missing])
    )
    expected = (
        r"non esistono nel grafo: \['1-2-7', '1-5-3', '20-1-0', '3-4-9', '5-1-1', '99-98-0'\]"
    )
    with pytest.raises(GraphError, match=expected):
        build_road_graph(build_raw_road_graph(), config, ov)


# --- dati non utilizzabili ------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, 0, -5.0, math.nan, math.inf, -math.inf, "100"])
def test_lunghezza_non_valida_e_un_errore_che_dice_quale_arco(
    config: EngineConfig, bad: Any
) -> None:
    raw = build_raw_road_graph()
    if bad is None:
        del raw.edges[2, 3, 0]["length_m"]
    else:
        raw.edges[2, 3, 0]["length_m"] = bad
    with pytest.raises(GraphError, match=r"Arco 2-3-0: lunghezza `length_m` non valida"):
        build_road_graph(raw, config)


# --- caricamento da file, una volta per processo --------------------------------------------------


@pytest.fixture
def graph_file(tmp_path: Path) -> Path:
    path = tmp_path / "osm" / "graph_drive.graphml"
    path.parent.mkdir()
    ox.save_graphml(build_raw_road_graph(), path)
    return path


def test_dal_file_si_ottengono_gli_stessi_attributi(config: EngineConfig, graph_file: Path) -> None:
    from_file = load_road_graph(graph_file, config)
    in_memory = build_road_graph(build_raw_road_graph(), config)
    assert sorted(from_file.edges(keys=True)) == sorted(in_memory.edges(keys=True))
    for key in in_memory.edges(keys=True):
        assert attrs(from_file, key) == attrs(in_memory, key)  # i tipi tornano interi e float


def test_il_grafo_si_costruisce_una_volta_sola(config: EngineConfig, graph_file: Path) -> None:
    first = load_road_graph(graph_file, config)
    assert load_road_graph(graph_file, config) is first
    # una configurazione con lo stesso contenuto è la stessa configurazione
    assert load_road_graph(graph_file, EngineConfig.from_yaml()) is first
    clear_road_graph_cache()
    assert load_road_graph(graph_file, config) is not first


def test_configurazione_o_correzioni_diverse_danno_un_grafo_diverso(
    config: EngineConfig, graph_file: Path
) -> None:
    base = load_road_graph(graph_file, config)
    changed = dict(config.road_defaults)
    changed["primary"] = RoadDefault(lanes=5, speed_kmh=90, capacity_per_lane=1000)
    other_config = load_road_graph(graph_file, config.model_copy(update={"road_defaults": changed}))
    corrected = load_road_graph(
        graph_file, config, overrides_of({"edge_key": "2-3-0", "lanes": 4, "reason": "r"})
    )
    assert len({id(base), id(other_config), id(corrected)}) == 3
    assert attrs(base, (2, 3, 0))["lanes"] == 2
    assert attrs(other_config, (2, 3, 0))["lanes"] == 5
    assert attrs(corrected, (2, 3, 0))["lanes"] == 4
    assert load_road_graph(graph_file, config, overrides_of()) is not base  # chiave con hash vuoto


def test_file_diversi_hanno_grafi_diversi(
    config: EngineConfig, graph_file: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other.graphml"
    other.write_bytes(graph_file.read_bytes())
    assert load_road_graph(other, config) is not load_road_graph(graph_file, config)


def test_grafo_mancante_dice_cosa_fare(config: EngineConfig, tmp_path: Path) -> None:
    with pytest.raises(GraphError, match=r"Manca il grafo stradale .*nowhere\.graphml.*make data"):
        load_road_graph(tmp_path / "nowhere.graphml", config)
