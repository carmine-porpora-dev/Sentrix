from typing import Any

import networkx as nx
import pytest

from app.data.resolvers import ResolveError
from app.engine.assign import EdgeLoad, assign
from app.engine.background import build_background
from app.engine.demand import OdFlow
from app.engine.measures import (
    NON_ROAD_TYPES,
    ROAD_TYPES,
    MeasureError,
    apply_measures,
    favored_edge_key,
)
from app.models.catalog import CatalogConfig
from app.models.config import EngineConfig, MeasureEffects
from app.models.operations import ACTIVE_STATES, OperationRequest
from tests.support import make_event, make_request


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


def road() -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node, (lon, lat) in {
        1: (14.230, 40.830),
        2: (14.231, 40.831),
        3: (14.232, 40.830),
        4: (14.233, 40.829),
        5: (14.234, 40.830),
        6: (14.235, 40.831),
    }.items():
        g.add_node(node, x=lon, y=lat)
    for u, v, cap, name in [
        (1, 3, 400.0, "Via A"),
        (2, 3, 1000.0, "Via B"),
        (4, 3, 800.0, "Via C"),
        (3, 5, 1200.0, "Via D"),
        (5, 6, 900.0, "Via E"),
        (3, 1, 600.0, "Via A"),
    ]:
        g.add_edge(u, v, key=0, t0_min=1.0, capacity_vph=cap, name=name, length_m=500.0)
    return g


def capacities(g: nx.MultiDiGraph) -> dict[str, float]:
    return {f"{u}-{v}-{k}": d["capacity_vph"] for u, v, k, d in g.edges(keys=True, data=True)}


BASE_CAPACITY = {
    "1-3-0": 400.0,
    "2-3-0": 1000.0,
    "4-3-0": 800.0,
    "3-5-0": 1200.0,
    "5-6-0": 900.0,
    "3-1-0": 600.0,
}


def req(
    measure_type: str,
    target: str,
    action_id: str = "act_1",
    *,
    state: str = "ACCEPTED",
    window: str = "departure",
    iteration: int = 1,
    payload: dict[str, Any] | None = None,
) -> OperationRequest:
    return make_request(
        action_id,
        type=measure_type,
        target=target,
        state=state,
        window=window,
        iteration=iteration,
        payload=payload or {},
    )


def run(
    requests: list[OperationRequest],
    config: EngineConfig,
    event: Any = None,
    window: Any = "departure",
) -> Any:
    return apply_measures(road(), event or make_event(), window, requests, config)


# --- close_road ----------------------------------------------------------------------------------


def test_close_road_porta_a_zero_la_capacita_degli_archi_indicati(config: EngineConfig) -> None:
    net = run(
        [req("close_road", "1-3-0, 5-6-0, 1-3-0")], config
    )  # lo spazio e il doppione contano zero
    assert capacities(net.graph) == {**BASE_CAPACITY, "1-3-0": 0.0, "5-6-0": 0.0}
    assert net.closed == frozenset({"1-3-0", "5-6-0"})
    assert net.applied == ("act_1",)


# --- traffic_post --------------------------------------------------------------------------------


def test_traffic_post_aumenta_la_capacita_degli_archi_entranti(config: EngineConfig) -> None:
    net = run([req("traffic_post", "3")], config)
    # entranti nel nodo 3: 1→3 (400 → 500), 2→3 (1.000 → 1.250), 4→3 (800 → 1.000); gli altri no
    assert capacities(net.graph) == pytest.approx(
        {**BASE_CAPACITY, "1-3-0": 500.0, "2-3-0": 1250.0, "4-3-0": 1000.0}
    )
    assert net.closed == frozenset()


def test_un_arco_chiuso_resta_chiuso_dopo_un_presidio(config: EngineConfig) -> None:
    net = run([req("close_road", "2-3-0", "a1"), req("traffic_post", "3", "a2")], config)
    assert net.graph.edges[2, 3, 0]["capacity_vph"] == 0.0
    assert net.graph.edges[1, 3, 0]["capacity_vph"] == pytest.approx(500.0)
    assert net.closed == frozenset({"2-3-0"})


# --- signal_plan_change --------------------------------------------------------------------------


def test_signal_plan_change_aumenta_solo_l_arco_favorito(config: EngineConfig) -> None:
    net = run([req("signal_plan_change", "3", payload={"favored_edge_key": "2-3-0"})], config)
    assert capacities(net.graph) == pytest.approx({**BASE_CAPACITY, "2-3-0": 1150.0})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, r"manca payload\['favored_edge_key'\]"),
        ({"favored_edge_key": 7}, r"manca payload\['favored_edge_key'\]"),
        ({"favored_edge_key": "2-3"}, "chiave arco non valida"),
        ({"favored_edge_key": "3-5-0"}, "non è un arco entrante nell'incrocio 3"),  # esce da 3
        ({"favored_edge_key": "2-3-9"}, "non è un arco entrante nell'incrocio 3"),  # non esiste
        ({"favored_edge_key": "5-6-0"}, "non è un arco entrante nell'incrocio 3"),  # altro incrocio
    ],
)
def test_signal_plan_change_con_arco_favorito_non_valido(
    config: EngineConfig, payload: dict[str, Any], message: str
) -> None:
    with pytest.raises(MeasureError, match=rf"act_1 \(signal_plan_change\): .*{message}"):
        run([req("signal_plan_change", "3", payload=payload)], config)


# --- detour_signage ------------------------------------------------------------------------------


def test_detour_signage_cambia_il_costo_percepito_non_la_capacita(config: EngineConfig) -> None:
    net = run([req("detour_signage", "2-3-0,1-3-0")], config)
    assert capacities(net.graph) == BASE_CAPACITY
    assert net.graph.edges[2, 3, 0]["perceived_factor"] == pytest.approx(1.2)
    assert net.graph.edges[1, 3, 0]["perceived_factor"] == pytest.approx(1.2)
    assert "perceived_factor" not in net.graph.edges[4, 3, 0]
    assert net.closed == frozenset()


def test_due_segnaletiche_sullo_stesso_arco_si_compongono(config: EngineConfig) -> None:
    net = run([req("detour_signage", "2-3-0", "a1"), req("detour_signage", "2-3-0", "a2")], config)
    assert net.graph.edges[2, 3, 0]["perceived_factor"] == pytest.approx(1.44)


# --- chiusure dell'Evento ------------------------------------------------------------------------


def test_chiusura_dell_evento_per_chiavi_e_per_nome(config: EngineConfig) -> None:
    event = make_event(
        closures=[
            {"label": "Per chiavi", "edge_keys": ["5-6-0"]},
            {"label": "Per nome", "street_names": ["Via A"]},
        ]
    )
    net = run([], config, event)
    # «Via A» sono 1→3 e 3→1; 5→6 è per chiave
    assert capacities(net.graph) == {**BASE_CAPACITY, "1-3-0": 0.0, "3-1-0": 0.0, "5-6-0": 0.0}
    assert net.closed == frozenset({"1-3-0", "3-1-0", "5-6-0"})
    assert "chiusure dell'evento: 3 archi chiusi, 0 a capacità ridotta" in net.assumptions


def test_un_arco_in_piu_chiusure_si_conta_una_volta(config: EngineConfig) -> None:
    """5-6-0 è in tre chiusure, 1-3-0 in una: 2 archi chiusi; 2-3-0 è solo ridotto (1)."""
    event = make_event(
        closures=[
            {"label": "A", "edge_keys": ["5-6-0", "1-3-0"]},
            {"label": "B", "edge_keys": ["5-6-0"]},
            {
                "label": "C",
                "edge_keys": ["5-6-0", "2-3-0"],
                "mode": "capacity_reduction",
                "capacity_factor": 0.5,
            },
        ]
    )
    net = run([], config, event)
    assert net.closed == frozenset({"5-6-0", "1-3-0"})
    assert capacities(net.graph)["2-3-0"] == 500.0
    assert "chiusure dell'evento: 2 archi chiusi, 1 a capacità ridotta" in net.assumptions


def test_riduzione_di_capacita_non_e_una_chiusura(config: EngineConfig) -> None:
    event = make_event(
        closures=[
            {
                "label": "Corsia chiusa",
                "edge_keys": ["2-3-0", "3-5-0"],
                "mode": "capacity_reduction",
                "capacity_factor": 0.5,
            }
        ]
    )
    net = run([], config, event)
    assert capacities(net.graph) == {**BASE_CAPACITY, "2-3-0": 500.0, "3-5-0": 600.0}
    assert net.closed == frozenset()
    assert "chiusure dell'evento: 0 archi chiusi, 2 a capacità ridotta" in net.assumptions


def test_chiusure_in_ogni_finestra(config: EngineConfig) -> None:
    event = make_event(closures=[{"label": "C", "edge_keys": ["5-6-0"]}])
    for window in ("arrival", "departure"):
        assert run([], config, event, window).closed == frozenset({"5-6-0"})


def test_chiusura_che_non_si_risolve_e_un_errore(config: EngineConfig) -> None:
    event = make_event(closures=[{"label": "Fantasma", "street_names": ["Via Che Non C'è"]}])
    with pytest.raises(ResolveError, match="nessun arco chiamato"):
        run([], config, event)


# --- finestra, stati, tipi ------------------------------------------------------------------------


def test_una_misura_si_applica_solo_alla_sua_finestra(config: EngineConfig) -> None:
    requests = [req("traffic_post", "3", "a1", window="arrival"), req("close_road", "5-6-0", "a2")]
    departure = run(requests, config, window="departure")
    arrival = run(requests, config, window="arrival")
    assert departure.applied == ("a2",) and departure.closed == frozenset({"5-6-0"})
    assert arrival.applied == ("a1",) and arrival.closed == frozenset()
    assert arrival.graph.edges[1, 3, 0]["capacity_vph"] == pytest.approx(500.0)
    assert departure.graph.edges[1, 3, 0]["capacity_vph"] == 400.0


def test_gli_stati_che_valgono_come_accettati() -> None:
    # 04 3: ACCEPTED → IN_PROGRESS → COMPLETED sono tutti «accettata»
    assert {"ACCEPTED", "IN_PROGRESS", "COMPLETED"} == ACTIVE_STATES


@pytest.mark.parametrize("state", ["ACCEPTED", "IN_PROGRESS", "COMPLETED"])
def test_gli_stati_accettati_si_applicano(config: EngineConfig, state: str) -> None:
    assert run([req("close_road", "5-6-0", state=state)], config).closed == frozenset({"5-6-0"})


@pytest.mark.parametrize("state", ["CREATED", "SENT", "RECEIVED", "REJECTED"])
def test_una_richiesta_non_accettata_e_un_errore(config: EngineConfig, state: str) -> None:
    extra = (
        {"reject_code": "UNAVAILABLE", "reject_reason": "nessuna pattuglia"}
        if state == "REJECTED"
        else {}
    )
    request = make_request("act_9", type="close_road", target="5-6-0", state=state, **extra)
    with pytest.raises(
        MeasureError, match=rf"act_9 \(close_road\): la richiesta è {state}, non accettata"
    ):
        run([request], config)


def test_anche_una_richiesta_di_un_altra_finestra_si_convalida(config: EngineConfig) -> None:
    with pytest.raises(MeasureError, match="non accettata"):
        run(
            [req("close_road", "5-6-0", window="arrival", state="RECEIVED")],
            config,
            window="departure",
        )


def test_tipo_ignoto_e_un_errore(config: EngineConfig) -> None:
    with pytest.raises(MeasureError, match="act_1: tipo di misura sconosciuto 'teletrasporto'"):
        run([req("teletrasporto", "3")], config)


@pytest.mark.parametrize("measure_type", sorted(NON_ROAD_TYPES))
def test_le_misure_di_altri_moduli_non_toccano_la_rete(
    config: EngineConfig, measure_type: str
) -> None:
    net = run([req(measure_type, "qualunque cosa")], config)
    assert capacities(net.graph) == BASE_CAPACITY and net.applied == ()
    assert all("perceived_factor" not in d for *_, d in net.graph.edges(keys=True, data=True))


def test_ogni_tipo_del_catalogo_e_classificato() -> None:
    catalog = {m.type for m in CatalogConfig.from_yaml().measures}
    assert catalog | {"close_road", "bus_detour"} <= ROAD_TYPES | NON_ROAD_TYPES
    assert not ROAD_TYPES & NON_ROAD_TYPES
    assert {"close_road", "traffic_post", "signal_plan_change", "detour_signage"} == ROAD_TYPES


# --- bersagli che non esistono -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("measure_type", "target", "message"),
    [
        ("traffic_post", "incrocio_1", "il bersaglio 'incrocio_1' non è un id di nodo"),
        ("traffic_post", "99", "l'incrocio 99 non esiste nella rete"),
        ("close_road", "1-3-0,9-9-9", "l'arco 9-9-9 non esiste nella rete"),
        ("close_road", "1-3", "chiave arco non valida"),
        ("detour_signage", "2-3-1", "l'arco 2-3-1 non esiste nella rete"),
        ("detour_signage", "2-3-0,,1-3-0", "chiave arco non valida"),
    ],
)
def test_bersagli_inesistenti_o_malformati(
    config: EngineConfig, measure_type: str, target: str, message: str
) -> None:
    with pytest.raises(MeasureError, match=rf"act_1 \({measure_type}\): .*{message}"):
        run([req(measure_type, target)], config)


# --- determinismo ---------------------------------------------------------------------------------


def test_l_ordine_di_applicazione_e_fisso_e_il_risultato_identico_bit_per_bit(
    config: EngineConfig,
) -> None:
    # 400 × 1,25 × 1,15 dà 575 in un ordine e 574,9999999999999 nell'altro
    post = req("traffic_post", "3", "z1", iteration=1)
    signal = req(
        "signal_plan_change", "3", "a1", iteration=2, payload={"favored_edge_key": "1-3-0"}
    )
    forward = run([post, signal], config)
    backward = run([signal, post], config)
    assert (
        forward.graph.edges[1, 3, 0]["capacity_vph"] == 575.0
    )  # (400 × 1,25) × 1,15: prima l'iterazione 1
    assert capacities(forward.graph) == capacities(backward.graph)  # bit per bit
    assert forward.applied == backward.applied == ("z1", "a1")  # per iterazione, non per id
    # a pari iterazione si ordina per action_id
    same = run(
        [
            req("signal_plan_change", "3", "b", payload={"favored_edge_key": "1-3-0"}),
            req("traffic_post", "3", "a"),
        ],
        config,
    )
    assert same.applied == ("a", "b") and same.graph.edges[1, 3, 0]["capacity_vph"] == 575.0


def test_la_rete_di_base_non_viene_modificata(config: EngineConfig) -> None:
    base = road()
    before = capacities(base)
    event = make_event(closures=[{"label": "C", "edge_keys": ["5-6-0"]}])
    apply_measures(
        base,
        event,
        "departure",
        [req("traffic_post", "3", "a"), req("detour_signage", "2-3-0", "b")],
        config,
    )
    assert capacities(base) == before
    assert all("perceived_factor" not in d for *_, d in base.edges(keys=True, data=True))


def test_stessi_input_stesso_risultato(config: EngineConfig) -> None:
    requests = [req("traffic_post", "3", "a"), req("detour_signage", "2-3-0", "b")]
    first, second = run(requests, config), run(requests, config)
    assert capacities(first.graph) == capacities(second.graph)
    assert (first.closed, first.applied, first.assumptions) == (
        second.closed,
        second.applied,
        second.assumptions,
    )


# --- valori da engine.yaml -----------------------------------------------------------------------


def test_i_fattori_vengono_dalla_configurazione(config: EngineConfig) -> None:
    effects = MeasureEffects.model_validate(
        {
            "traffic_post": {"capacity_factor": 2.0, "scope": "incoming_edges"},
            "signal_plan_change": {
                "capacity_factor": 3.0,
                "scope": "incoming_edges_favored_direction",
            },
            "detour_signage": {"perceived_time_factor": 2.0, "scope": "saturated_path_edges"},
            "close_road": {"capacity_factor": 0.0},
        }
    )
    other = config.model_copy(update={"measure_effects": effects})
    net = run(
        [
            req("traffic_post", "3", "a"),
            req("signal_plan_change", "3", "b", payload={"favored_edge_key": "2-3-0"}),
            req("detour_signage", "5-6-0", "c"),
        ],
        other,
    )
    assert net.graph.edges[1, 3, 0]["capacity_vph"] == 800.0  # × 2
    assert net.graph.edges[2, 3, 0]["capacity_vph"] == 6000.0  # × 2 × 3
    assert net.graph.edges[5, 6, 0]["perceived_factor"] == 2.0


def test_una_scope_che_il_motore_non_sa_applicare_e_un_errore(config: EngineConfig) -> None:
    raw = config.measure_effects.model_dump()
    raw["traffic_post"]["scope"] = "incoming_edges_favored_direction"
    with pytest.raises(MeasureError, match=r"measure_effects\.traffic_post\.scope"):
        run([], config.model_copy(update={"measure_effects": MeasureEffects.model_validate(raw)}))
    raw = config.measure_effects.model_dump()
    raw["signal_plan_change"]["scope"] = "incoming_edges"
    with pytest.raises(MeasureError, match=r"measure_effects\.signal_plan_change\.scope"):
        run([], config.model_copy(update={"measure_effects": MeasureEffects.model_validate(raw)}))


def test_assunzioni(config: EngineConfig) -> None:
    net = run(
        [
            req("traffic_post", "3", "a"),
            req("traffic_post", "3", "b"),
            req("detour_signage", "2-3-0", "c"),
            req("close_road", "5-6-0", "d"),
        ],
        config,
    )
    assert any("non una previsione" in a for a in net.assumptions)
    assert "2 × traffic_post: capacità × 1.25 sugli archi entranti" in net.assumptions
    assert (
        "1 × detour_signage: costo percepito × 1.2 sugli archi indicati, tempo reale invariato"
        in net.assumptions
    )
    assert "1 × close_road: archi chiusi" in net.assumptions
    assert not any("chiusure dell'evento" in a for a in net.assumptions)


# --- l'arco favorito ---------------------------------------------------------------------------


def load(vc: float) -> EdgeLoad:
    return EdgeLoad(
        v_event=0.0,
        v_background=0.0,
        capacity_vph=100.0,
        v_total=vc * 100,
        vc=vc,
        t_min=1.0,
        cost_min=1.0,
    )


def test_arco_favorito_e_l_entrante_con_il_vc_piu_alto() -> None:
    loads = {"1-3-0": load(0.5), "2-3-0": load(1.7), "4-3-0": load(0.9), "3-5-0": load(9.0)}
    assert favored_edge_key(road(), 3, loads) == "2-3-0"  # 3-5-0 esce dal nodo: non conta


def test_a_parita_di_vc_vince_la_chiave_minore() -> None:
    loads = {"4-3-0": load(1.2), "1-3-0": load(1.2), "2-3-0": load(1.2)}
    assert favored_edge_key(road(), 3, loads) == "1-3-0"


def test_gli_archi_senza_carico_non_sono_candidati() -> None:
    # 2→3 è chiuso (nessun carico), quindi tra gli aperti vince il v/c più alto
    loads = {"1-3-0": load(0.4), "4-3-0": load(0.8)}
    assert favored_edge_key(road(), 3, loads) == "4-3-0"


def test_senza_archi_entranti_aperti_e_un_errore() -> None:
    with pytest.raises(MeasureError, match="L'incrocio 3 non ha archi entranti aperti"):
        favored_edge_key(road(), 3, {"3-5-0": load(1.0)})
    with pytest.raises(MeasureError, match="L'incrocio 6 non ha archi entranti aperti"):
        favored_edge_key(road(), 6, {})  # 5→6 esiste ma non ha un carico


# --- insieme con fondo e assegnazione -------------------------------------------------------------


def flow(origin: int, dest: int, vph: float) -> OdFlow:
    return OdFlow(
        zone_id="z", origin_node=origin, dest_node=dest, veh_per_hour=vph, destination_label=None
    )


def veh_hours(result: Any) -> float:
    return sum(load.v_total * load.t_min / 60 * 0.5 for load in result.edges.values())


def chain() -> nx.MultiDiGraph:
    """1→3→5: un solo percorso, con il collo di bottiglia sull'arco entrante 1→3 (c = 400)."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_edge(1, 3, key=0, t0_min=1.0, capacity_vph=400.0, name="Via A", length_m=500.0)
    g.add_edge(3, 5, key=0, t0_min=1.0, capacity_vph=1200.0, name="Via D", length_m=500.0)
    return g


def test_un_presidio_non_peggiora_le_ore_veicolo(config: EngineConfig) -> None:
    """02 10: traffic_post su un incrocio critico non peggiora veh_hours. Il fondo si calcola sulla
    rete di base: 0,3 × 400 = 120 veic/h su 1→3 con e senza il presidio."""
    base = chain()
    event = make_event()
    background = build_background(base, event, "departure").volumes
    plain = apply_measures(base, event, "departure", [], config)
    posted = apply_measures(base, event, "departure", [req("traffic_post", "3")], config)
    flows = [flow(1, 5, 600.0)]
    before = assign(plain.graph, background, flows, config)
    after = assign(posted.graph, background, flows, config)
    assert background == pytest.approx({"1-3-0": 120.0, "3-5-0": 360.0})
    # v = 120 + 600 = 720 in entrambi i casi; v/c = 1,8 contro 720/500 = 1,44
    assert before.edges["1-3-0"].v_total == after.edges["1-3-0"].v_total == pytest.approx(720.0)
    assert before.edges["1-3-0"].vc == pytest.approx(1.8)
    assert after.edges["1-3-0"].vc == pytest.approx(1.44)
    assert veh_hours(after) < veh_hours(before)


def test_il_fondo_degli_archi_chiusi_e_zero_con_le_chiavi_di_closed(config: EngineConfig) -> None:
    g = chain()
    g.add_edge(1, 5, key=0, t0_min=1.5, capacity_vph=900.0, name="Via X", length_m=500.0)
    event = make_event()
    net = apply_measures(g, event, "departure", [req("close_road", "1-5-0")], config)
    background = build_background(g, event, "departure", net.closed).volumes
    assert background["1-5-0"] == 0.0 and background["1-3-0"] == pytest.approx(120.0)
    result = assign(net.graph, background, [flow(1, 5, 600.0)], config)
    assert "1-5-0" not in result.edges  # chiuso: fuori dai risultati
    assert result.edges["1-3-0"].v_event == pytest.approx(600.0)  # il traffico passa per 1→3→5


def two_routes() -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_edge(1, 2, key=0, t0_min=1.0, capacity_vph=10000.0, name="Diretta", length_m=500.0)
    g.add_edge(1, 3, key=0, t0_min=0.55, capacity_vph=10000.0, name="Giro", length_m=500.0)
    g.add_edge(3, 2, key=0, t0_min=0.55, capacity_vph=10000.0, name="Giro", length_m=500.0)
    return g


def test_la_segnaletica_sposta_il_traffico_ma_non_cambia_il_tempo_reale(
    config: EngineConfig,
) -> None:
    base = two_routes()
    event = make_event(background={"arrival_peak_share": 0.0, "departure_peak_share": 0.0})
    background = build_background(base, event, "departure").volumes
    plain = apply_measures(base, event, "departure", [], config)
    signed = apply_measures(base, event, "departure", [req("detour_signage", "1-2-0")], config)
    flows = [flow(1, 2, 1000.0)]
    without = assign(plain.graph, background, flows, config)
    with_sign = assign(signed.graph, background, flows, config)
    # senza segnaletica la diretta (1,0) batte il giro (1,1); con ×1,2 (1,2) vince il giro
    assert without.edges["1-2-0"].v_event == pytest.approx(1000.0)
    assert with_sign.edges["1-2-0"].v_event == 0.0
    assert with_sign.edges["1-3-0"].v_event == pytest.approx(1000.0)
    # l'arco segnalato: tempo reale 1,0 (nessun traffico), costo 1,2
    assert with_sign.edges["1-2-0"].t_min == 1.0
    assert with_sign.edges["1-2-0"].cost_min == pytest.approx(1.2)
