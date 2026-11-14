from collections.abc import Sequence
from typing import Any

import networkx as nx
import pytest

from app.data.resolvers import edge_key, parse_edge_key
from app.engine.assign import Assignment, Route, Router, assign, bpr_time
from app.engine.background import build_background
from app.engine.demand import OdFlow
from app.engine.graph import GraphError, build_road_graph
from app.models.config import AssignmentConfig, BprConfig, EngineConfig
from tests.support import build_raw_road_graph, make_event


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    """engine.yaml con 4 passi da 25 %: i valori attesi di questo file sono calcolati a mano su 4
    passi. Il default di engine.yaml (16) è provato a parte, in `test_il_default_di_engine_yaml`."""
    return with_steps(EngineConfig.from_yaml(), 4)


def add(
    g: nx.MultiDiGraph, u: int, v: int, t0: float, cap: float, k: int = 0, **extra: Any
) -> None:
    g.add_edge(u, v, key=k, t0_min=t0, capacity_vph=cap, **extra)


def flow(origin: int, dest: int, vph: float, zone: str = "z", label: str | None = None) -> OdFlow:
    return OdFlow(
        zone_id=zone, origin_node=origin, dest_node=dest, veh_per_hour=vph, destination_label=label
    )


def zero_bg(g: nx.MultiDiGraph) -> dict[str, float]:
    return {edge_key(u, v, k): 0.0 for u, v, k in g.edges(keys=True)}


def two_routes(cap1: float = 1000.0, **route1: Any) -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    add(g, 1, 2, 1.0, cap1, **route1)
    add(g, 1, 3, 0.6, 10000.0)
    add(g, 3, 2, 0.6, 10000.0)
    return g


def run(g: nx.MultiDiGraph, flows: Sequence[OdFlow], config: EngineConfig, **kw: Any) -> Assignment:
    return assign(g, kw.pop("background", None) or zero_bg(g), flows, config)


def with_steps(config: EngineConfig, steps: int) -> EngineConfig:
    assignment = AssignmentConfig(steps=steps, step_share=1 / steps)
    return config.model_copy(update={"assignment": assignment})


def event_of(result: Assignment, key: str) -> float:
    return result.edges[key].v_event


# --- BPR ---------------------------------------------------------------------------------------


def test_bpr_su_un_solo_arco_con_fondo(config: EngineConfig) -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    add(g, 1, 2, 1.0, 1000.0)
    result = assign(g, {"1-2-0": 500.0}, [flow(1, 2, 1000.0)], config)
    load = result.edges["1-2-0"]
    # fondo 500 + evento 1.000 = 1.500 su 1.000: v/c = 1,5 → t = 1 + 0,15 × 5,0625
    assert (load.v_event, load.v_background, load.v_total) == (1000.0, 500.0, 1500.0)
    assert load.capacity_vph == 1000.0 and load.vc == pytest.approx(1.5)
    assert load.t_min == pytest.approx(1.759375, rel=1e-12)
    assert load.cost_min == load.t_min  # senza fattore di percezione


def test_alfa_e_beta_vengono_dalla_configurazione(config: EngineConfig) -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    add(g, 1, 2, 1.0, 1000.0)
    other = config.model_copy(update={"bpr": BprConfig(alpha=0.5, beta=2)})
    result = assign(g, {"1-2-0": 500.0}, [flow(1, 2, 1000.0)], other)
    assert result.edges["1-2-0"].t_min == pytest.approx(1 + 0.5 * 1.5**2, rel=1e-12)  # 2,125


def test_bpr_time_formula() -> None:
    assert bpr_time(1.0, 1500.0, 1000.0, 0.15, 4.0) == pytest.approx(1.759375, rel=1e-12)
    assert bpr_time(2.0, 0.0, 1000.0, 0.15, 4.0) == 2.0  # a vuoto: il tempo a flusso libero
    assert bpr_time(1.0, 1000.0, 1000.0, 0.15, 4.0) == pytest.approx(1.15, rel=1e-12)


def test_senza_flussi_c_solo_il_fondo(config: EngineConfig) -> None:
    g = two_routes()
    result = assign(g, {"1-2-0": 900.0, "1-3-0": 0.0, "3-2-0": 100.0}, [], config)
    assert [load.v_event for load in result.edges.values()] == [0.0, 0.0, 0.0]
    assert result.edges["1-2-0"].t_min == pytest.approx(1 + 0.15 * 0.9**4, rel=1e-12)
    assert result.edges["3-2-0"].t_min == pytest.approx(0.6 * (1 + 0.15 * 0.01**4), rel=1e-12)
    assert result.demand_veh_per_hour == result.assigned_veh_per_hour == 0.0
    assert result.unassigned == ()


# --- incrementale ------------------------------------------------------------------------------


def test_quattro_passi_scelgono_il_percorso_passo_per_passo(config: EngineConfig) -> None:
    result = run(two_routes(), [flow(1, 2, 2000.0)], config)
    assert result.steps == 4
    assert event_of(result, "1-2-0") == pytest.approx(1500.0, rel=1e-12)
    assert event_of(result, "1-3-0") == pytest.approx(500.0, rel=1e-12)
    assert event_of(result, "3-2-0") == pytest.approx(500.0, rel=1e-12)
    assert result.edges["1-2-0"].vc == pytest.approx(1.5) and result.edges[
        "1-2-0"
    ].t_min == pytest.approx(1.759375, rel=1e-12)
    # percorso 2: v/c = 0,05 → t = 0,6 × (1 + 0,15 × 0,05^4) = 0,6000005625
    assert result.edges["1-3-0"].t_min == pytest.approx(0.6000005625, rel=1e-12)


def test_un_passo_solo_e_tutto_o_niente(config: EngineConfig) -> None:
    result = run(two_routes(), [flow(1, 2, 2000.0)], with_steps(config, 1))
    # tutto sul percorso 1 (costo 1,0 < 1,2): v/c = 2 → t = 1 + 0,15 × 16 = 3,4
    assert event_of(result, "1-2-0") == pytest.approx(2000.0, rel=1e-12)
    assert event_of(result, "1-3-0") == 0.0
    assert result.edges["1-2-0"].t_min == pytest.approx(3.4, rel=1e-12)


def test_due_passi(config: EngineConfig) -> None:
    result = run(two_routes(), [flow(1, 2, 2000.0)], with_steps(config, 2))
    # passo 1: 1.000 sul percorso 1; passo 2: v = 1.000 → 1,15 < 1,2 → altri 1.000
    assert event_of(result, "1-2-0") == pytest.approx(2000.0, rel=1e-12)
    assert result.steps == 2


def test_il_fondo_orienta_la_scelta(config: EngineConfig) -> None:
    g = two_routes()
    without = run(g, [flow(1, 2, 1000.0)], config)
    assert event_of(without, "1-2-0") == pytest.approx(1000.0)  # 1 + 0,15 × 0,75^4 = 1,047 < 1,2
    background = {"1-2-0": 1500.0, "1-3-0": 0.0, "3-2-0": 0.0}  # costo del percorso 1: 1,759
    with_bg = assign(g, background, [flow(1, 2, 1000.0)], config)
    assert event_of(with_bg, "1-2-0") == 0.0
    assert event_of(with_bg, "1-3-0") == pytest.approx(1000.0)


def test_fattore_di_percezione_orienta_la_scelta_ma_non_il_tempo(config: EngineConfig) -> None:
    perceived = run(two_routes(cap1=10000.0, perceived_factor=1.5), [flow(1, 2, 1000.0)], config)
    plain = run(two_routes(cap1=10000.0), [flow(1, 2, 1000.0)], config)
    # senza fattore il percorso 1 (costo 1,0) vince in tutti i passi; con 1,5 (> 1,2) vince il 2
    assert event_of(plain, "1-2-0") == pytest.approx(1000.0)
    assert event_of(perceived, "1-2-0") == 0.0
    assert event_of(perceived, "1-3-0") == pytest.approx(1000.0)
    # il tempo riportato è quello reale (1,0 a vuoto), il costo è 1,5 volte
    assert perceived.edges["1-2-0"].t_min == 1.0
    assert perceived.edges["1-2-0"].cost_min == pytest.approx(1.5)
    assert perceived.edges["1-3-0"].cost_min == perceived.edges["1-3-0"].t_min  # fattore 1


# --- conservazione -----------------------------------------------------------------------------


def grid() -> nx.MultiDiGraph:
    """Griglia 3×3 (nodi 1-9), archi nei due sensi con tempi e capacità diversi."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for row in range(3):
        for col in range(3):
            node = 3 * row + col + 1
            for other in (node + 1 if col < 2 else None, node + 3 if row < 2 else None):
                if other is not None:
                    t0 = 0.5 + 0.1 * ((node * other) % 5)
                    cap = 600.0 + 100.0 * ((node + other) % 4)
                    add(g, node, other, t0, cap)
                    add(g, other, node, t0 + 0.05, cap + 50.0)
    return g


def test_conservazione_del_flusso_ai_nodi(config: EngineConfig) -> None:
    g = grid()
    flows = [
        flow(1, 9, 800.0, "a"),
        flow(1, 7, 400.0, "b"),
        flow(3, 7, 600.0, "c"),
        flow(5, 9, 300.0, "d"),
        flow(9, 1, 200.0, "e"),
    ]
    result = run(g, flows, config)
    net_out: dict[int, float] = dict.fromkeys(g.nodes, 0.0)
    for key, load in result.edges.items():
        u, v, _ = parse_edge_key(key)
        net_out[u] += load.v_event
        net_out[v] -= load.v_event
    expected: dict[int, float] = dict.fromkeys(g.nodes, 0.0)
    for f in flows:  # ogni nodo emette ciò che parte da lì e assorbe ciò che vi arriva
        expected[f.origin_node] += f.veh_per_hour
        expected[f.dest_node] -= f.veh_per_hour
    assert net_out == pytest.approx(expected, abs=1e-9)
    assert result.demand_veh_per_hour == pytest.approx(2300.0)
    assert result.assigned_veh_per_hour == pytest.approx(2300.0) and result.unassigned == ()


def test_assegnato_piu_non_assegnato_e_la_domanda(config: EngineConfig) -> None:
    g = two_routes()
    g.add_edge(8, 9, key=0, t0_min=1.0, capacity_vph=500.0)  # un'isola: 8→9, non raggiungibile da 1
    flows = [flow(1, 2, 900.0, "ok"), flow(1, 9, 300.0, "isola"), flow(77, 2, 50.0, "fuori")]
    result = run(g, flows, config)
    assert [f.zone_id for f in result.unassigned] == ["isola", "fuori"]  # ordine delle coppie
    assert result.demand_veh_per_hour == pytest.approx(1250.0)
    assert result.unassigned_veh_per_hour == pytest.approx(350.0)
    assert result.assigned_veh_per_hour == pytest.approx(900.0)
    assert result.assigned_veh_per_hour + result.unassigned_veh_per_hour == pytest.approx(1250.0)
    assert event_of(result, "8-9-0") == 0.0  # l'isola non riceve niente
    assert "2 coppie O/D senza percorso non assegnate (350 veic/h)" in result.assumptions


def test_senza_nessuna_coppia_non_assegnata_niente_avviso(config: EngineConfig) -> None:
    result = run(two_routes(), [flow(1, 2, 100.0)], config)
    assert not any("senza percorso" in a for a in result.assumptions)


def test_origine_uguale_a_destinazione_e_assegnata_senza_caricare_la_rete(
    config: EngineConfig,
) -> None:
    result = run(two_routes(), [flow(1, 1, 500.0), flow(1, 2, 100.0)], config)
    assert result.unassigned == ()
    assert result.assigned_veh_per_hour == pytest.approx(600.0)
    assert event_of(result, "1-2-0") + event_of(result, "1-3-0") == pytest.approx(100.0)


def test_piu_destinazioni_dalla_stessa_origine(config: EngineConfig) -> None:
    g = two_routes()
    add(g, 2, 4, 0.5, 5000.0)
    result = run(g, [flow(1, 2, 400.0, "a"), flow(1, 4, 800.0, "b")], config)
    assert event_of(result, "2-4-0") == pytest.approx(800.0)  # solo il flusso verso 4 lo usa
    total_from_1 = event_of(result, "1-2-0") + event_of(result, "1-3-0")
    assert total_from_1 == pytest.approx(1200.0)  # tutto ciò che parte da 1 passa da un'uscita


# --- archi chiusi ------------------------------------------------------------------------------


def od_time(result: Assignment, origin: int, dest: int) -> float:
    """Il tempo del cammino minimo (per costo) tra due nodi sui carichi finali, in minuti."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for key, load in result.edges.items():
        u, v, k = parse_edge_key(key)
        g.add_edge(u, v, key=k, w=load.cost_min)
    return float(nx.dijkstra_path_length(g, origin, dest, weight="w"))


def test_un_arco_chiuso_e_escluso_e_il_traffico_lo_aggira(config: EngineConfig) -> None:
    g = two_routes()
    g.edges[1, 2, 0]["capacity_vph"] = 0.0
    result = assign(g, {"1-3-0": 0.0, "3-2-0": 0.0}, [flow(1, 2, 2000.0)], config)
    assert "1-2-0" not in result.edges and list(result.edges) == ["1-3-0", "3-2-0"]
    assert event_of(result, "1-3-0") == event_of(result, "3-2-0") == pytest.approx(2000.0)
    # 2.000 su 10.000: v/c = 0,2 → t = 0,6 × (1 + 0,15 × 0,0016) = 0,600144 per arco
    assert result.edges["1-3-0"].t_min == pytest.approx(0.600144, rel=1e-12)


def test_chiudere_un_arco_usato_non_riduce_il_tempo_origine_destinazione(
    config: EngineConfig,
) -> None:
    g = two_routes()
    flows = [flow(1, 2, 2000.0)]
    base = run(g, flows, config)
    closed_graph = two_routes()
    closed_graph.edges[1, 2, 0]["capacity_vph"] = 0.0
    closed = assign(closed_graph, {"1-3-0": 0.0, "3-2-0": 0.0}, flows, config)
    base_time, closed_time = od_time(base, 1, 2), od_time(closed, 1, 2)
    assert base_time == pytest.approx(2 * 0.6000005625, rel=1e-12)  # 1,200001125
    assert closed_time == pytest.approx(2 * 0.600144, rel=1e-12)  # 1,200288
    assert closed_time >= base_time


def test_senza_percorso_dopo_la_chiusura_la_coppia_non_e_assegnata(config: EngineConfig) -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    add(g, 1, 2, 1.0, 0.0)  # l'unica strada è chiusa
    add(g, 2, 3, 1.0, 1000.0)
    result = assign(g, {"2-3-0": 0.0}, [flow(1, 3, 500.0), flow(2, 3, 100.0)], config)
    assert [f.origin_node for f in result.unassigned] == [1]
    assert event_of(result, "2-3-0") == pytest.approx(100.0)


# --- determinismo e parità di costo ------------------------------------------------------------


def symmetric() -> nx.MultiDiGraph:
    """Due percorsi identici 1→3→2 e 1→4→2."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for u, v in [(1, 3), (3, 2), (1, 4), (4, 2)]:
        add(g, u, v, 0.5, 10000.0)
    return g


def test_a_parita_di_costo_vince_l_arco_con_la_chiave_minore(config: EngineConfig) -> None:
    result = run(symmetric(), [flow(1, 2, 1000.0)], with_steps(config, 1))
    # il predecessore del nodo 2 è l'arco 3→2 (chiave 3-2-0 < 4-2-0)
    assert event_of(result, "3-2-0") == event_of(result, "1-3-0") == pytest.approx(1000.0)
    assert event_of(result, "4-2-0") == event_of(result, "1-4-0") == 0.0


def test_a_quattro_passi_i_percorsi_pari_si_alternano(config: EngineConfig) -> None:
    result = run(symmetric(), [flow(1, 2, 1000.0)], config)
    # passo 1 → via 3; passo 2 → via 4 (la 3 costa di più); passo 3 → pari, via 3; passo 4 → 4
    for key in ("1-3-0", "3-2-0", "1-4-0", "4-2-0"):
        assert event_of(result, key) == pytest.approx(500.0)


def test_archi_paralleli_a_parita_di_costo_vince_la_chiave_minore(config: EngineConfig) -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    add(g, 1, 2, 1.0, 1000.0, k=1)  # inserito per primo, ma ha la chiave maggiore
    add(g, 1, 2, 1.0, 1000.0, k=0)
    result = run(g, [flow(1, 2, 400.0)], with_steps(config, 1))
    assert event_of(result, "1-2-0") == pytest.approx(400.0)
    assert event_of(result, "1-2-1") == 0.0


def test_archi_paralleli_vince_il_piu_veloce(config: EngineConfig) -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    add(g, 1, 2, 1.0, 10000.0, k=0)
    add(g, 1, 2, 0.8, 10000.0, k=1)
    result = run(g, [flow(1, 2, 400.0)], with_steps(config, 1))
    assert event_of(result, "1-2-1") == pytest.approx(400.0) and event_of(result, "1-2-0") == 0.0


def reversed_copy(g: nx.MultiDiGraph) -> nx.MultiDiGraph:
    other: nx.MultiDiGraph = nx.MultiDiGraph()
    other.add_nodes_from(reversed(list(g.nodes)))
    for u, v, k, data in reversed(list(g.edges(keys=True, data=True))):
        other.add_edge(u, v, key=k, **data)
    return other


def test_il_risultato_non_dipende_dall_ordine_di_grafo_e_coppie(config: EngineConfig) -> None:
    # valori «scomodi» (non rappresentabili esattamente): una somma in ordine diverso darebbe
    # un risultato diverso negli ultimi bit
    flows = [
        flow(1, 9, 803.37, "a"),
        flow(1, 7, 411.91, "b"),
        flow(3, 7, 627.13, "c"),
        flow(1, 9, 97.77, "d"),
        flow(5, 9, 311.29, "e"),
        flow(3, 7, 53.03, "f"),
        flow(9, 1, 207.11, "g"),
    ]
    g = grid()
    first = run(g, flows, config)
    for other in (
        run(g, flows, config),  # ripetibile
        run(reversed_copy(g), flows, config),  # grafo inserito al contrario
        run(g, list(reversed(flows)), config),  # coppie in ordine diverso
        run(g, flows[3:] + flows[:3], config),
    ):
        assert other == first
        assert list(other.edges) == list(first.edges)  # anche l'ordine degli archi
        assert [load.v_event for load in other.edges.values()] == [
            load.v_event for load in first.edges.values()
        ]  # bit per bit
    # e con i percorsi pari
    sym = run(symmetric(), [flow(1, 2, 1000.0)], config)
    mirrored = run(reversed_copy(symmetric()), [flow(1, 2, 1000.0)], config)
    assert mirrored == sym and list(mirrored.edges) == list(sym.edges)


def test_il_grafo_e_gli_input_non_vengono_modificati(config: EngineConfig) -> None:
    g = two_routes()
    background = zero_bg(g)
    flows = [flow(1, 2, 2000.0)]
    attrs = sorted((u, v, k, sorted(d.items())) for u, v, k, d in g.edges(keys=True, data=True))
    assign(g, background, flows, config)
    assert attrs == sorted(
        (u, v, k, sorted(d.items())) for u, v, k, d in g.edges(keys=True, data=True)
    )
    assert background == {"1-2-0": 0.0, "1-3-0": 0.0, "3-2-0": 0.0}
    assert flows == [flow(1, 2, 2000.0)]


def test_seed_assunzioni_e_ordine_degli_archi(config: EngineConfig) -> None:
    result = run(two_routes(), [flow(1, 2, 100.0)], config)
    assert result.seed == 42 and result.steps == 4
    assert list(result.edges) == ["1-2-0", "1-3-0", "3-2-0"]  # ordine di chiave
    assert any("non una previsione" in a for a in result.assumptions)  # principio 6
    assert any(
        "4 passi da 25 %" in a and "non è un equilibrio d'utente" in a for a in result.assumptions
    )
    assert "archi chiusi (capacità 0) esclusi dall'instradamento" in result.assumptions


def test_anelli_su_se_stessi_sono_nei_risultati_ma_non_nei_percorsi(config: EngineConfig) -> None:
    g = two_routes()
    add(g, 1, 1, 0.1, 500.0)
    result = assign(g, {**zero_bg(g), "1-1-0": 100.0}, [flow(1, 2, 100.0)], config)
    assert event_of(result, "1-1-0") == 0.0
    assert result.edges["1-1-0"].v_total == 100.0


# --- errori ------------------------------------------------------------------------------------


def test_fondo_mancante_per_un_arco_aperto(config: EngineConfig) -> None:
    g = two_routes()
    with pytest.raises(GraphError, match="Arco 3-2-0: manca il traffico di fondo"):
        assign(g, {"1-2-0": 0.0, "1-3-0": 0.0}, [], config)


def test_arco_chiuso_non_ha_bisogno_del_fondo(config: EngineConfig) -> None:
    g = two_routes()
    g.edges[3, 2, 0]["capacity_vph"] = 0.0
    assert list(assign(g, {"1-2-0": 0.0, "1-3-0": 0.0}, [], config).edges) == ["1-2-0", "1-3-0"]


@pytest.mark.parametrize("missing", ["t0_min", "capacity_vph"])
def test_arco_senza_attributi_del_motore(config: EngineConfig, missing: str) -> None:
    g = two_routes()
    del g.edges[1, 2, 0][missing]
    with pytest.raises(GraphError, match=r"Arco 1-2-0: mancano `t0_min` o `capacity_vph`"):
        assign(g, {}, [], config)


def test_capacita_negativa_e_fattore_non_positivo(config: EngineConfig) -> None:
    g = two_routes()
    g.edges[1, 2, 0]["capacity_vph"] = -5.0
    with pytest.raises(GraphError, match="Arco 1-2-0: capacità negativa"):
        assign(g, zero_bg(g), [], config)
    for bad in (0.0, -1.0):
        h = two_routes(perceived_factor=bad)
        with pytest.raises(GraphError, match="perceived_factor non positivo"):
            assign(h, zero_bg(h), [], config)


# --- con la rete costruita dal grafo OSM di prova -------------------------------------------------


def test_integrazione_con_rete_fondo_e_domanda_di_prova(config: EngineConfig) -> None:
    road = build_road_graph(build_raw_road_graph(), config)
    event = make_event(background={"arrival_peak_share": 0.35, "departure_peak_share": 0.4})
    background = build_background(road, event, "arrival")
    result = assign(road, background.volumes, [flow(1, 4, 600.0)], config)
    assert len(result.edges) == 13 and result.unassigned == ()
    # da 1 a 4: via 5 (1-5-0 t0 0,18 + 5-4-0 t0 0,12 = 0,30 min) batte 1→2→3→4 (0,3 + 0,6 + 0,2)
    loaded = {key for key, load in result.edges.items() if load.v_event > 0}
    assert loaded == {"1-5-0", "5-4-0"}
    assert all(result.edges[key].v_event == pytest.approx(600.0) for key in loaded)
    # 5-4-0: capacità 400, fondo 0,35 × 400 = 140, evento 600 → 740, v/c = 1,85
    # t = 0,12 × (1 + 0,15 × 1,85^4) = 0,12 × 2,757026 = 0,330843
    load = result.edges["5-4-0"]
    assert (load.v_background, load.v_total) == (pytest.approx(140.0), pytest.approx(740.0))
    assert load.vc == pytest.approx(1.85) and load.t_min == pytest.approx(0.330843, rel=1e-6)
    # 1-5-0: capacità 1.800, fondo 630 → 1.230, v/c = 0,68333
    assert result.edges["1-5-0"].v_total == pytest.approx(1230.0)
    assert result.edges["1-5-0"].t_min == pytest.approx(0.18 * (1 + 0.15 * (1230 / 1800) ** 4))
    # gli archi del fondo non toccati hanno solo il fondo
    assert result.edges["2-3-0"].v_total == pytest.approx(630.0)


def test_a_parita_di_costo_conta_la_chiave_non_chi_e_piu_vicino(config: EngineConfig) -> None:
    """Il nodo 4 è più vicino all'origine del 3 (0,5 contro 0,75) e viene estratto per primo, ma i
    due percorsi 1→3→2 (0,75 + 0,25) e 1→4→2 (0,5 + 0,5) costano esattamente 1,0: vince l'arco
    entrante con la chiave minore, 3-2-0, e non il primo che arriva."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for u, v, t0 in [(1, 3, 0.75), (3, 2, 0.25), (1, 4, 0.5), (4, 2, 0.5)]:
        add(g, u, v, t0, 10000.0)
    result = run(g, [flow(1, 2, 400.0)], with_steps(config, 1))
    assert event_of(result, "3-2-0") == event_of(result, "1-3-0") == pytest.approx(400.0)
    assert event_of(result, "4-2-0") == event_of(result, "1-4-0") == 0.0


def test_le_coppie_non_assegnate_sono_nell_ordine_delle_coppie(config: EngineConfig) -> None:
    """Gli indici 1 e 8 di un `set` si scorrono come 8, 1: l'ordine va imposto, non sperato."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node in range(1, 11):
        add(g, node, node + 1, 1.0, 1000.0)
    g.add_node(20)
    flows = [flow(k, 20 if k in (2, 9) else 11, 10.0, f"z{k}") for k in range(1, 11)]
    result = run(g, flows, config)
    assert [f.origin_node for f in result.unassigned] == [2, 9]
    assert result.unassigned_veh_per_hour == pytest.approx(20.0)


def test_il_default_di_engine_yaml_e_16_passi_da_un_sedicesimo() -> None:
    default = EngineConfig.from_yaml()
    assert (default.assignment.steps, default.assignment.step_share) == (16, 0.0625)
    result = assign(two_routes(), zero_bg(two_routes()), [flow(1, 2, 2000.0)], default)
    assert result.steps == 16
    assert "16 passi da 6.25 %" in " ".join(result.assumptions)
    assert result.assigned_veh_per_hour == pytest.approx(2000.0, rel=1e-12)
    # Rete a due percorsi, passi da 125 veic/h. Il percorso 1 (t0 = 1, c = 1.000) costa meno del 2
    # (1,2) finché 1 + 0,15 (L/1000)^4 < 1,2, cioè L < 1.074,6. Dopo 8 passi L = 1.000 e il costo è
    # 1,15: il passo 9 va ancora sul percorso 1 (L = 1.125, costo 1,2403 > 1,2); gli altri 7 passi
    # vanno sul 2 (875). Con 4 passi era 1.500/500: 16 passi si avvicinano al riparto di equilibrio.
    assert event_of(result, "1-2-0") == pytest.approx(1125.0, rel=1e-12)
    assert event_of(result, "1-3-0") == pytest.approx(875.0, rel=1e-12)
    assert event_of(result, "3-2-0") == pytest.approx(875.0, rel=1e-12)
    four = assign(two_routes(), zero_bg(two_routes()), [flow(1, 2, 2000.0)], with_steps(default, 4))
    assert event_of(four, "1-2-0") == pytest.approx(1500.0, rel=1e-12)


# --- Router: cammini minimi sui carichi finali -------------------------------------------------


def routed(g: nx.MultiDiGraph, flows: list[OdFlow], config: EngineConfig) -> tuple[Assignment, Any]:
    result = assign(g, zero_bg(g), flows, config)
    return result, Router(g, result.edges)


def with_length(g: nx.MultiDiGraph, **lengths: float) -> nx.MultiDiGraph:
    for key, length in lengths.items():
        u, v, k = parse_edge_key(key)
        g.edges[u, v, k]["length_m"] = length
    return g


def test_router_cammino_tempo_e_lunghezza(config: EngineConfig) -> None:
    g = with_length(two_routes(), **{"1-2-0": 700.0, "1-3-0": 400.0, "3-2-0": 450.0})
    _, router = routed(g, [], config)
    found = router.routes([(1, 2)])[(1, 2)]
    # a vuoto: la diretta costa 1,0 contro 0,6 + 0,6 = 1,2
    assert found is not None
    assert (found.edges, found.time_min, found.length_m) == (("1-2-0",), 1.0, 700.0)
    # da 1 a 3 e da 3 a 2 sono un solo arco ciascuno
    assert router.routes([(1, 3)])[(1, 3)] == Route(("1-3-0",), 0.6, 400.0)


def test_router_sceglie_per_costo_e_riporta_il_tempo_reale(config: EngineConfig) -> None:
    """La diretta dura 1,0 ma costa 1,5 (fattore di percezione): il cammino scelto è il giro, e il
    tempo riportato è quello reale del giro (1,2), più lungo di quello della diretta."""
    g = with_length(two_routes(cap1=10000.0, perceived_factor=1.5), **{"1-2-0": 700.0})
    _, router = routed(g, [], config)
    found = router.routes([(1, 2)])[(1, 2)]
    assert found is not None
    assert found.edges == ("1-3-0", "3-2-0")
    assert found.time_min == pytest.approx(1.2, rel=1e-12)  # non 1,5


def test_router_origine_uguale_destinazione_e_senza_percorso(config: EngineConfig) -> None:
    g = two_routes()
    g.add_node(9)
    _, router = routed(g, [], config)
    routes = router.routes([(1, 1), (2, 1), (1, 9), (1, 77), (77, 1)])
    assert routes[(1, 1)] == Route((), 0.0, 0.0)
    assert routes[(2, 1)] is None  # nessun arco torna indietro
    assert routes[(1, 9)] is None  # nodo isolato
    assert routes[(1, 77)] is None and routes[(77, 1)] is None  # nodo fuori dalla rete


def test_router_a_parita_di_costo_vince_la_chiave_minore(config: EngineConfig) -> None:
    _, router = routed(symmetric(), [], config)
    found = router.routes([(1, 2)])[(1, 2)]
    assert found is not None and found.edges == ("1-3-0", "3-2-0")
    other = routed(reversed_copy(symmetric()), [], config)[1].routes([(1, 2)])[(1, 2)]
    assert other == found


def test_router_non_instrada_sugli_archi_chiusi(config: EngineConfig) -> None:
    g = two_routes()
    g.edges[1, 2, 0]["capacity_vph"] = 0.0
    result = assign(g, {"1-3-0": 0.0, "3-2-0": 0.0}, [], config)
    found = Router(g, result.edges).routes([(1, 2)])[(1, 2)]
    assert found is not None and found.edges == ("1-3-0", "3-2-0")


def test_router_con_carichi_di_un_altra_rete_e_un_errore(config: EngineConfig) -> None:
    g = two_routes()
    result = assign(g, zero_bg(g), [], config)
    other = two_routes()
    add(other, 2, 4, 1.0, 100.0)  # un arco aperto che i carichi non conoscono
    with pytest.raises(GraphError, match="Arco 2-4-0"):
        Router(other, result.edges)


def test_router_piu_coppie_insieme_come_una_alla_volta(config: EngineConfig) -> None:
    g = grid()
    _, router = routed(g, [flow(1, 9, 500.0)], config)
    pairs = [(1, 9), (1, 7), (3, 7), (9, 1), (5, 5)]
    together = router.routes(pairs)
    for pair in pairs:
        assert router.routes([pair])[pair] == together[pair]
    assert together[(5, 5)] is not None and together[(5, 5)].edges == ()


def test_router_il_cammino_scelto_e_quello_su_cui_va_il_traffico(config: EngineConfig) -> None:
    """Con un solo percorso possibile e un solo passo, il Router trova gli archi che l'assegnazione
    ha caricato."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for u, v in [(1, 2), (2, 3), (3, 4)]:
        add(g, u, v, 1.0, 1000.0)
    result, router = routed(g, [flow(1, 4, 300.0)], with_steps(config, 1))
    found = router.routes([(1, 4)])[(1, 4)]
    assert found is not None
    assert set(found.edges) == {k for k, load in result.edges.items() if load.v_event > 0}
