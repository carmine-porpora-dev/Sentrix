import re
from datetime import datetime
from typing import Any

import pytest

from app.engine.assign import Assignment, assign
from app.engine.background import build_background
from app.engine.measure_effects import EFFECT_TYPES, SOURCE, measure_effects
from app.engine.measures import apply_measures
from app.models.config import EngineConfig
from app.models.provenance import Measured
from tests.support import make_event
from tests.unit.test_engine_measures import chain, flow, req, road, two_routes

PREFIX = ("run_1", "it1")
AS_OF = datetime.fromisoformat("2026-11-11T12:00:00+01:00")


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


def states(
    graph: Any, flows: list[Any], measures: list[Any], config: EngineConfig, **event: Any
) -> tuple[Any, Assignment, Assignment]:
    """La rete con le misure, e le assegnazioni senza e con."""
    ev = make_event(**event)
    background = build_background(graph, ev, "departure").volumes
    plain = apply_measures(graph, ev, "departure", [], config)
    net = apply_measures(graph, ev, "departure", measures, config)
    before = assign(plain.graph, background, flows, config)
    after = assign(net.graph, background, flows, config)
    return net.graph, before, after


def effects(
    requests: list[Any],
    graph: Any,
    before: Assignment,
    after: Assignment,
    window: Any = "departure",
) -> dict[str, Measured]:
    found = measure_effects(
        requests, graph, before, after, window=window, id_prefix=PREFIX, as_of=AS_OF
    )
    return {m.id.removeprefix("m.run_1.it1.road."): m for m in found}


def test_un_presidio_dice_il_v_c_degli_archi_entranti_prima_e_dopo(config: EngineConfig) -> None:
    """v = 120 + 600 = 720 su 1→3: c = 400 → v/c 1,8; con ×1,25 c = 500 → 1,44 (come in
    test_engine_measures)."""
    post = req("traffic_post", "3")
    graph, before, after = states(chain(), [flow(1, 5, 600.0)], [post], config)
    out = effects([post], graph, before, after)
    assert set(out) == {
        "departure.measure_effect.act_1.vc_before",
        "departure.measure_effect.act_1.vc_after",
    }
    assert out["departure.measure_effect.act_1.vc_before"].value == pytest.approx(1.8)
    assert out["departure.measure_effect.act_1.vc_after"].value == pytest.approx(1.44)


def test_un_cambio_semaforico_tocca_solo_l_arco_favorito(config: EngineConfig) -> None:
    """Due archi entranti nel nodo 3: 1→3 (c = 400) e 2→3 (c = 1.000), il flusso va per 1→3 e per
    2→3 con 600 veic/h ciascuno: il favorito è 2→3 (c × 1,15 = 1.150)."""
    g = road()
    flows = [flow(1, 5, 600.0), flow(2, 5, 600.0)]
    change = req("signal_plan_change", "3", payload={"favored_edge_key": "2-3-0"})
    graph, before, after = states(g, flows, [change], config)
    out = effects([change], graph, before, after)
    b, a = (
        out["departure.measure_effect.act_1.vc_before"],
        out["departure.measure_effect.act_1.vc_after"],
    )
    # solo 2→3: v = fondo 0,3 × 1.000 + 600 = 900 → 0,9 prima; 900 / 1.150 dopo
    assert b.value == pytest.approx(before.edges["2-3-0"].vc)
    assert a.value == pytest.approx(after.edges["2-3-0"].vc)
    assert isinstance(a.value, float) and isinstance(b.value, float)
    assert a.value < b.value
    assert "1-3-0" not in b.inputs[1] and "2-3-0" in b.inputs[1]


def test_la_segnaletica_toglie_traffico_dall_arco_indicato(config: EngineConfig) -> None:
    sign = req("detour_signage", "1-2-0")
    graph, before, after = states(
        two_routes(),
        [flow(1, 2, 1000.0)],
        [sign],
        config,
        background={"arrival_peak_share": 0.0, "departure_peak_share": 0.0},
    )
    out = effects([sign], graph, before, after)
    # la diretta ha 1.000 veic/h su 10.000 (0,1) senza segnaletica e 0 con (il traffico va sul giro)
    assert out["departure.measure_effect.act_1.vc_before"].value == pytest.approx(0.1)
    assert out["departure.measure_effect.act_1.vc_after"].value == pytest.approx(0.0)


def test_il_massimo_tra_gli_archi_toccati(config: EngineConfig) -> None:
    """Il presidio tocca tre archi entranti: vale il massimo v/c, non una media."""
    g = road()
    post = req("traffic_post", "3")
    graph, before, after = states(g, [flow(1, 5, 600.0), flow(2, 5, 300.0)], [post], config)
    out = effects([post], graph, before, after)
    incoming = ["1-3-0", "2-3-0", "4-3-0"]
    assert out["departure.measure_effect.act_1.vc_before"].value == pytest.approx(
        max(before.edges[k].vc for k in incoming)
    )
    assert out["departure.measure_effect.act_1.vc_after"].value == pytest.approx(
        max(after.edges[k].vc for k in incoming)
    )


def test_ogni_numero_ha_la_sua_provenienza(config: EngineConfig) -> None:
    post = req("traffic_post", "3", "act_7")
    graph, before, after = states(chain(), [flow(1, 5, 600.0)], [post], config)
    for m in measure_effects(
        [post], graph, before, after, window="departure", id_prefix=PREFIX, as_of=AS_OF
    ):
        assert re.fullmatch(
            r"m\.run_1\.it1\.road\.departure\.measure_effect\.act_7\.vc_(before|after)", m.id
        )
        assert (m.unit, m.kind, m.source, m.as_of) == ("rapporto", "simulated", SOURCE, AS_OF)
        assert "act_7" in m.inputs[0] and "traffic_post" in m.inputs[0]
        assert "1 archi toccati" in m.inputs[1]
        assert any("non una previsione" in a for a in m.assumptions)  # il modello statico
        assert any("stessa iterazione" in a for a in m.assumptions)
        assert any("non un equilibrio" in a for a in m.assumptions)
    before_m, after_m = [
        m
        for m in measure_effects(
            [post], graph, before, after, window="departure", id_prefix=PREFIX, as_of=AS_OF
        )
    ]
    assert before_m.id.endswith("vc_before") and "senza le misure introdotte" in before_m.method
    assert after_m.id.endswith("vc_after") and "con tutte le misure" in after_m.method


def test_le_misure_senza_effetto_da_confrontare_non_hanno_numeri(config: EngineConfig) -> None:
    """Una chiusura (v/c non definito), un tipo non stradale, un'altra finestra: nessun Measured."""
    others = [
        req("close_road", "1-3-0", "a1"),
        req("citizen_notice", "citizens", "a2"),
        req("crowd_control_post", "x", "a3"),
        req("traffic_post", "3", "a4", window="arrival"),
    ]
    graph, before, after = states(chain(), [flow(1, 5, 600.0)], [others[0]], config)
    assert (
        measure_effects(
            others, graph, before, after, window="departure", id_prefix=PREFIX, as_of=AS_OF
        )
        == ()
    )
    assert {"traffic_post", "signal_plan_change", "detour_signage"} == EFFECT_TYPES


def test_una_misura_di_un_altra_finestra_non_ha_numeri_qui(config: EngineConfig) -> None:
    """Gli archi toccati hanno un carico (la rete è la stessa) ma la misura è dell'arrivo: in
    deflusso non ha un effetto da dire."""
    post = req("traffic_post", "3", window="arrival")
    graph, before, after = states(chain(), [flow(1, 5, 600.0)], [req("traffic_post", "3")], config)
    assert effects([post], graph, before, after, window="departure") == {}
    assert len(effects([post], graph, before, after, window="arrival")) == 2


def test_un_arco_senza_carico_non_si_confronta(config: EngineConfig) -> None:
    """Il bersaglio è chiuso dopo (nessun carico): non c'è un v/c da dire, nessun Measured."""
    g = chain()
    post = req("traffic_post", "3")
    graph, before, after = states(g, [flow(1, 5, 600.0)], [post], config)
    closed_after = Assignment(
        steps=after.steps,
        seed=after.seed,
        edges={k: v for k, v in after.edges.items() if k != "1-3-0"},
        unassigned=after.unassigned,
        demand_veh_per_hour=after.demand_veh_per_hour,
        assigned_veh_per_hour=after.assigned_veh_per_hour,
        assumptions=after.assumptions,
    )
    assert effects([post], graph, before, closed_after) == {}


def test_l_ordine_e_per_iterazione_e_action_id(config: EngineConfig) -> None:
    a = req("traffic_post", "3", "act_b", iteration=2)
    b = req("traffic_post", "3", "act_a", iteration=2)
    c = req("traffic_post", "3", "act_z", iteration=1)
    graph, before, after = states(chain(), [flow(1, 5, 600.0)], [a, b, c], config)
    ids = [
        m.id.split(".")[-2]
        for m in measure_effects(
            [a, b, c], graph, before, after, window="departure", id_prefix=PREFIX, as_of=AS_OF
        )
    ]
    assert ids == ["act_z", "act_z", "act_a", "act_a", "act_b", "act_b"]
