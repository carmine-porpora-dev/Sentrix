from typing import Any

import networkx as nx
import pytest

from app.data.resolvers import edge_key
from app.engine.background import Background, build_background
from app.engine.graph import GraphError, build_road_graph
from app.models.config import EngineConfig
from tests.support import build_raw_road_graph, make_event

EVENT = make_event(background={"arrival_peak_share": 0.35, "departure_peak_share": 0.4})

# Capacità degli archi del grafo di prova (tests.support.build_raw_road_graph) dopo
# engine.graph.build_road_graph con i default di engine.yaml: vedi test_engine_graph.py.
CAPACITY = {
    "1-2-0": 2700.0,
    "1-2-1": 600.0,
    "2-3-0": 1800.0,
    "3-4-0": 800.0,
    "4-5-0": 400.0,
    "5-1-0": 400.0,
    "3-3-0": 400.0,
    "2-1-0": 1800.0,
    "3-2-0": 600.0,
    "4-3-0": 400.0,
    "5-4-0": 400.0,
    "1-5-0": 1800.0,
    "2-5-0": 900.0,
}


@pytest.fixture(scope="module")
def road() -> nx.MultiDiGraph:
    return build_road_graph(build_raw_road_graph(), EngineConfig.from_yaml())


def small_graph(**capacities: float) -> nx.MultiDiGraph:
    """Archi 1→2, 2→3, ... con la capacità data e classi diverse (il fondo non ne dipende)."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    classes = ["motorway", "primary", "residential", "living_street"]
    for i, (name, capacity) in enumerate(capacities.items()):
        g.add_edge(i + 1, i + 2, key=0, capacity_vph=capacity, highway=classes[i % 4], name=name)
    return g


# --- v_bg = quota × capacità ---------------------------------------------------------------------


def test_fondo_in_arrivo_e_nel_deflusso_su_tutta_la_rete(road: nx.MultiDiGraph) -> None:
    arrival = build_background(road, EVENT, "arrival")
    departure = build_background(road, EVENT, "departure")
    assert (arrival.window, arrival.share) == ("arrival", 0.35)
    assert (departure.window, departure.share) == ("departure", 0.4)
    assert set(arrival.volumes) == set(CAPACITY) == set(departure.volumes)  # uno per arco
    in_graph_order = [edge_key(u, v, k) for u, v, k in road.edges(keys=True)]
    assert list(arrival.volumes) == list(departure.volumes) == in_graph_order  # ordine stabile
    assert arrival.volumes == pytest.approx({k: 0.35 * c for k, c in CAPACITY.items()})
    assert departure.volumes == pytest.approx({k: 0.4 * c for k, c in CAPACITY.items()})
    # tre valori a mano: 2.700 → 945 / 1.080; 800 → 280 / 320; 600 → 210 / 240
    assert [arrival.volumes[k] for k in ("1-2-0", "3-4-0", "1-2-1")] == pytest.approx(
        [945, 280, 210]
    )
    assert [departure.volumes[k] for k in ("1-2-0", "3-4-0", "1-2-1")] == pytest.approx(
        [1080, 320, 240]
    )


def test_la_quota_e_la_stessa_per_tutte_le_classi() -> None:
    graph = small_graph(
        a=1800, b=900, c=400, d=300
    )  # motorway, primary, residential, living_street
    background = build_background(graph, EVENT, "arrival")
    assert list(background.volumes.values()) == pytest.approx([630, 315, 140, 105])
    for (u, v, k), volume in zip(graph.edges(keys=True), background.volumes.values(), strict=True):
        assert volume / graph.edges[u, v, k]["capacity_vph"] == pytest.approx(0.35)


@pytest.mark.parametrize(("share", "factor"), [(0.0, 0.0), (1.0, 1.0), (0.5, 0.5)])
def test_quote_estreme(share: float, factor: float) -> None:
    event = make_event(background={"arrival_peak_share": share, "departure_peak_share": share})
    background = build_background(small_graph(a=1000, b=500), event, "arrival")
    assert list(background.volumes.values()) == [factor * 1000, factor * 500]


def test_il_fondo_segue_la_capacita_del_grafo_che_riceve() -> None:
    base = build_background(small_graph(a=1000), EVENT, "arrival")
    doubled = build_background(small_graph(a=2000), EVENT, "arrival")
    assert base.volumes == pytest.approx({"1-2-0": 350})
    assert doubled.volumes == pytest.approx({"1-2-0": 700})


# --- archi chiusi --------------------------------------------------------------------------------


def test_gli_archi_chiusi_hanno_fondo_zero_e_gli_altri_non_cambiano(road: nx.MultiDiGraph) -> None:
    plain = build_background(road, EVENT, "departure")
    closed = build_background(road, EVENT, "departure", closed=["2-3-0", "1-2-1"])
    assert closed.closed == frozenset({"2-3-0", "1-2-1"})
    assert closed.volumes["2-3-0"] == 0.0 and closed.volumes["1-2-1"] == 0.0
    assert list(closed.volumes) == list(plain.volumes)  # restano nell'elenco, a zero
    for key, volume in plain.volumes.items():
        if key not in ("2-3-0", "1-2-1"):
            assert closed.volumes[key] == volume
    # il traffico degli archi chiusi non va altrove: il totale scende di quanto valeva
    lost = plain.volumes["2-3-0"] + plain.volumes["1-2-1"]
    assert lost == pytest.approx(0.4 * (1800 + 600))
    assert sum(closed.volumes.values()) == pytest.approx(sum(plain.volumes.values()) - lost)


def test_chiavi_duplicate_e_ordine_delle_chiusure_non_contano(road: nx.MultiDiGraph) -> None:
    a = build_background(road, EVENT, "arrival", closed=["2-3-0", "1-2-1", "2-3-0"])
    b = build_background(road, EVENT, "arrival", closed={"1-2-1", "2-3-0"})
    assert a == b and len(a.closed) == 2


def test_arco_chiuso_inesistente_e_un_errore_con_l_elenco_ordinato(road: nx.MultiDiGraph) -> None:
    # sei chiavi in ordine sparso (l'ordine di un set cambia a ogni processo): l'elenco è ordinato
    missing = ["99-98-0", "3-4-9", "1-2-7", "20-1-0", "5-1-1", "1-5-3"]
    expected = (
        r"non esistono nel grafo: \['1-2-7', '1-5-3', '20-1-0', '3-4-9', '5-1-1', '99-98-0'\]"
    )
    with pytest.raises(GraphError, match=expected):
        build_background(road, EVENT, "arrival", closed=["1-2-0", *missing])


def test_una_rete_senza_capacita_e_un_errore_che_dice_quale_arco() -> None:
    raw = build_raw_road_graph()  # non è passata da build_road_graph
    with pytest.raises(GraphError, match=r"Arco 1-2-0: manca `capacity_vph`"):
        build_background(raw, EVENT, "arrival")


# --- determinismo e assunzioni -------------------------------------------------------------------


def test_deterministico_e_non_modifica_la_rete(road: nx.MultiDiGraph) -> None:
    def snapshot() -> list[Any]:
        return sorted(
            (u, v, k, sorted(d.items())) for u, v, k, d in road.edges(keys=True, data=True)
        )

    before = snapshot()
    first = build_background(road, EVENT, "arrival", closed=["2-3-0"])
    assert build_background(road, EVENT, "arrival", closed=["2-3-0"]) == first
    assert snapshot() == before


def test_assunzioni_senza_chiusure(road: nx.MultiDiGraph) -> None:
    assumptions = build_background(road, EVENT, "arrival").assumptions
    assert any("non una previsione" in a for a in assumptions)  # principio 6
    assert (
        "traffico di fondo = 35 % della capacità di ogni arco nella fascia di picco (arrival), "
        "uguale per tutte le classi di strada; calcolato sulla capacità di base, prima di "
        "chiusure e misure" in assumptions
    )
    assert not any(
        "redistribuito" in a for a in assumptions
    )  # senza chiusure non c'è niente da dire


def test_assunzioni_con_chiusure_e_nel_deflusso(road: nx.MultiDiGraph) -> None:
    assumptions = build_background(road, EVENT, "departure", closed=["2-3-0", "1-2-1"]).assumptions
    assert any(
        a.startswith("traffico di fondo = 40 % ") and "(departure)" in a for a in assumptions
    )
    assert (
        "il traffico di fondo degli archi chiusi non è redistribuito (2 archi a zero)"
        in assumptions
    )


def test_il_risultato_e_un_valore_immutabile(road: nx.MultiDiGraph) -> None:
    background = build_background(road, EVENT, "arrival")
    assert isinstance(background, Background)
    with pytest.raises(AttributeError):
        background.share = 0.9  # type: ignore[misc]
