import datetime as dt
import logging
import os
import signal
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox
import pytest

from app.data.resolvers import resolve_point
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.assign import assign
from app.engine.background import build_background
from app.engine.demand import build_demand
from app.engine.graph import GraphError, build_road_graph, clear_road_graph_cache, load_road_graph
from app.engine.measures import MeasureError, apply_measures
from app.engine.metrics import build_reference, road_metrics
from app.engine.run import RoadEngine, RoadResult, RoadRunError, RoadRunner, RoadTimings
from app.models.config import EngineConfig
from app.models.event import Event
from tests.support import (
    HUB,
    build_star_raw_graph,
    graph_fingerprint,
    make_event,
    make_request,
)

AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
PREFIX = ("run1", "it0")


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


@pytest.fixture(scope="module")
def raw_star(config: EngineConfig) -> nx.MultiDiGraph:
    return build_star_raw_graph(config)


@pytest.fixture(scope="module")
def base(raw_star: nx.MultiDiGraph, config: EngineConfig) -> nx.MultiDiGraph:
    return build_road_graph(raw_star, config)


@pytest.fixture(scope="module")
def graph_path(tmp_path_factory: pytest.TempPathFactory, raw_star: nx.MultiDiGraph) -> Path:
    path = tmp_path_factory.mktemp("osm") / "graph_drive.graphml"
    ox.save_graphml(raw_star, path)
    return path


@pytest.fixture
def engine(base: nx.MultiDiGraph, config: EngineConfig) -> RoadEngine:
    return RoadEngine(base, config)


def engine_json(engine: RoadEngine, event: Event, level: Any, window: Any) -> str:
    return engine.run(event, level, window, id_prefix=PREFIX, as_of=AS_OF).result.model_dump_json()


def inbound_key_of_car_destination(base: nx.MultiDiGraph, config: EngineConfig) -> tuple[str, int]:
    """L'arco che entra nel primo punto di arrivo delle auto e il suo nodo."""
    node = resolve_point(
        config.demand.car_destinations[0].point,
        base,
        max_distance_m=config.node_snap_max_distance_m,
    )
    return f"{HUB}-{node}-0", node


# --- RoadEngine.run -------------------------------------------------------------------------------


@pytest.mark.parametrize("window", ["arrival", "departure"])
def test_il_risultato_porta_evento_livello_finestra_e_id(engine: RoadEngine, window: Any) -> None:
    run = engine.run(make_event(), "high", window, id_prefix=PREFIX, as_of=AS_OF)
    result = run.result
    assert (result.event_id, result.level, result.window) == ("test_event", "high", window)
    assert result.applied == ()
    measures = result.metrics.measures
    assert len(measures) > 10
    assert all(m.id.startswith(f"m.run1.it0.road.{window}.") for m in measures)
    assert {m.kind for m in measures} == {"simulated"}
    assert {m.as_of for m in measures} == {AS_OF}


def test_il_livello_cambia_i_numeri(engine: RoadEngine) -> None:
    def veh_hours(level: Any) -> float:
        run = engine.run(make_event(), level, "arrival", id_prefix=PREFIX, as_of=AS_OF)
        return next(m.value for m in run.result.metrics.measures if m.id.endswith(".veh_hours"))  # type: ignore[return-value]

    assert veh_hours("low") < veh_hours("mid") < veh_hours("high")


def test_stessi_input_stesso_risultato_byte_per_byte(
    base: nx.MultiDiGraph, config: EngineConfig
) -> None:
    event = make_event()
    first = engine_json(RoadEngine(base, config), event, "mid", "departure")
    second = engine_json(RoadEngine(base, config), event, "mid", "departure")
    assert first == second
    assert len(first) > 1000


def test_un_solo_istante_per_tutto_il_risultato(engine: RoadEngine) -> None:
    run = engine.run(make_event(), "mid", "arrival", id_prefix=PREFIX)
    instants = {m.as_of for m in run.result.metrics.measures}
    assert len(instants) == 1
    assert instants.pop().tzinfo is not None


def test_il_risultato_si_serializza_e_si_rilegge(engine: RoadEngine) -> None:
    result = engine.run(make_event(), "mid", "arrival", id_prefix=PREFIX, as_of=AS_OF).result
    again = RoadResult.model_validate_json(result.model_dump_json())
    assert again == result
    assert again.model_dump_json() == result.model_dump_json()
    assert set(again.metrics.layers) == {"edges_vc", "closures", "critical_intersections"}


def test_una_misura_accettata_cambia_la_rete(
    engine: RoadEngine, base: nx.MultiDiGraph, config: EngineConfig
) -> None:
    event = make_event()
    key, node = inbound_key_of_car_destination(base, config)
    close = make_request("act_7", type="close_road", target=key, window="arrival", state="ACCEPTED")
    plain = engine.run(event, "mid", "arrival", id_prefix=PREFIX, as_of=AS_OF).result
    closed = engine.run(event, "mid", "arrival", [close], id_prefix=PREFIX, as_of=AS_OF).result

    def value(result: RoadResult, name: str) -> float:
        return next(m.value for m in result.metrics.measures if m.id.endswith(f".{name}"))  # type: ignore[return-value]

    demand = build_demand(event, "mid", "arrival", config, base)
    cut_off = sum(1 for flow in demand.flows if flow.dest_node == node)
    assert cut_off > 0
    assert (plain.applied, closed.applied) == ((), ("act_7",))
    assert value(plain, "unassigned_pairs") == 0
    assert value(closed, "unassigned_pairs") == cut_off


def test_una_misura_di_un_altra_finestra_non_si_applica(
    engine: RoadEngine, base: nx.MultiDiGraph, config: EngineConfig
) -> None:
    key, _ = inbound_key_of_car_destination(base, config)
    other = make_request(
        "act_7", type="close_road", target=key, window="departure", state="ACCEPTED"
    )
    run = engine.run(make_event(), "mid", "arrival", [other], id_prefix=PREFIX, as_of=AS_OF)
    assert run.result.applied == ()


def test_gli_errori_dei_dati_arrivano_com_erano(engine: RoadEngine) -> None:
    rejected = make_request(
        "act_9", type="close_road", target="1-2-0", window="arrival", state="RECEIVED"
    )
    with pytest.raises(MeasureError, match="act_9"):
        engine.run(make_event(), "mid", "arrival", [rejected], id_prefix=PREFIX)


def test_le_misure_non_toccano_la_rete_di_base(base: nx.MultiDiGraph, config: EngineConfig) -> None:
    """Dopo un run con una chiusura, un run senza dà lo stesso risultato di un motore nuovo."""
    event = make_event()
    key, _ = inbound_key_of_car_destination(base, config)
    close = make_request("act_7", type="close_road", target=key, window="arrival", state="ACCEPTED")
    used = RoadEngine(base, config)
    used.run(event, "mid", "arrival", [close], id_prefix=PREFIX, as_of=AS_OF)
    assert engine_json(used, event, "mid", "arrival") == engine_json(
        RoadEngine(base, config), event, "mid", "arrival"
    )


def test_run_compone_i_passi_del_motore(base: nx.MultiDiGraph, config: EngineConfig) -> None:
    """Il risultato è quello dei sei passi eseguiti a mano, con la chiusura e il livello alto."""
    event = make_event()
    key, _ = inbound_key_of_car_destination(base, config)
    close = make_request(
        "act_7", type="close_road", target=key, window="departure", state="ACCEPTED"
    )
    network = apply_measures(base, event, "departure", [close], config)
    background = build_background(base, event, "departure", network.closed)
    demand = build_demand(event, "high", "departure", config, base)
    assignment = assign(network.graph, background.volumes, demand.flows, config)
    reference = build_reference(base, event, "departure", config)
    expected = road_metrics(
        base,
        network,
        assignment,
        reference,
        demand,
        event,
        config,
        background=background,
        id_prefix=PREFIX,
        as_of=AS_OF,
    )
    run = RoadEngine(base, config).run(
        event, "high", "departure", [close], id_prefix=PREFIX, as_of=AS_OF
    )
    assert run.result.applied == network.applied == ("act_7",)
    assert run.result.metrics == expected


def test_ogni_tempo_va_nel_suo_campo(engine: RoadEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Quattro letture dell'orologio: R dura 1 s, l'assegnazione 2 s, le metriche 3 s."""
    readings = iter([10.0, 11.0, 13.0, 16.0])
    monkeypatch.setattr("app.engine.run.time.perf_counter", lambda: next(readings))
    timings = engine.run(make_event(), "mid", "arrival", id_prefix=PREFIX, as_of=AS_OF).timings
    assert timings == RoadTimings(
        reference_s=1.0, reference_cached=False, assign_s=2.0, metrics_s=3.0, total_s=6.0
    )


def test_il_motore_non_modifica_quello_che_riceve(
    base: nx.MultiDiGraph, config: EngineConfig
) -> None:
    """Rete di base, Evento, configurazione e richieste restano come erano (funzioni pure)."""
    key, node = inbound_key_of_car_destination(base, config)
    event = make_event(closures=[{"label": "Prova", "edge_keys": [key]}])
    requests = [
        make_request(
            "act_1", type="traffic_post", target=str(HUB), window="arrival", state="ACCEPTED"
        ),
        make_request(
            "act_2", type="detour_signage", target=f"{HUB}-{node}-0", window="arrival",
            state="ACCEPTED",
        ),
    ]  # fmt: skip
    before = (
        graph_fingerprint(base),
        event.content_hash(),
        config.content_hash(),
        [r.content_hash() for r in requests],
    )
    engine = RoadEngine(base, config)
    for window in ("arrival", "departure"):
        engine.run(event, "high", window, requests, id_prefix=PREFIX, as_of=AS_OF)
    assert before == (
        graph_fingerprint(base),
        event.content_hash(),
        config.content_hash(),
        [r.content_hash() for r in requests],
    )


# --- effetto locale delle misure introdotte in questa iterazione (02 7) ----------------------


def effect_ids(run: Any) -> list[str]:
    return [m.id for m in run.result.metrics.measures if ".measure_effect." in m.id]


def test_senza_effect_of_nessun_effetto_e_nessuna_seconda_assegnazione(
    base: nx.MultiDiGraph, engine: RoadEngine
) -> None:
    post = make_request(
        "act_1", type="traffic_post", target=str(HUB), window="arrival", state="ACCEPTED"
    )
    run = engine.run(make_event(), "high", "arrival", [post], id_prefix=PREFIX, as_of=AS_OF)
    assert effect_ids(run) == []


def test_effect_of_dice_l_effetto_solo_delle_misure_nuove_della_finestra(
    engine: RoadEngine,
) -> None:
    new = make_request(
        "act_1", type="traffic_post", target=str(HUB), window="arrival", state="ACCEPTED"
    )
    old = make_request(
        "act_0", type="traffic_post", target=str(HUB), window="arrival", state="ACCEPTED",
        iteration=1,
    )  # fmt: skip
    notice = make_request(
        "act_2", type="citizen_notice", target="citizens", window="arrival", state="ACCEPTED"
    )
    other_window = make_request(
        "act_3", type="traffic_post", target=str(HUB), window="departure", state="ACCEPTED"
    )
    run = engine.run(
        make_event(),
        "high",
        "arrival",
        [old, new, notice, other_window],
        id_prefix=PREFIX,
        as_of=AS_OF,
        effect_of={"act_1", "act_2", "act_3"},
    )
    # solo act_1: act_0 è già in vigore, act_2 non è stradale, act_3 è di un'altra finestra
    assert effect_ids(run) == [
        "m.run1.it0.road.arrival.measure_effect.act_1.vc_before",
        "m.run1.it0.road.arrival.measure_effect.act_1.vc_after",
    ]


def test_lo_stato_di_prima_e_quello_senza_le_misure_nuove(
    base: nx.MultiDiGraph, config: EngineConfig
) -> None:
    """`vc_before` è il v/c sull'arco toccato con le sole misure già in vigore, `vc_after` quello
    della stessa corsa con tutte: i due numeri si ritrovano facendo girare il motore a mano. La
    misura nuova (un presidio sul nodo di arrivo) porta la capacità dell'arco entrante a × 1,25."""
    _, node = inbound_key_of_car_destination(base, config)
    old = make_request(
        "act_0", type="traffic_post", target=str(HUB), window="arrival", state="ACCEPTED",
        iteration=1,
    )  # fmt: skip
    new = make_request(
        "act_1", type="traffic_post", target=str(node), window="arrival", state="ACCEPTED",
        iteration=2,
    )  # fmt: skip
    event = make_event()
    engine = RoadEngine(base, config)
    full = engine.run(
        event, "high", "arrival", [old, new], id_prefix=PREFIX, as_of=AS_OF, effect_of={"act_1"}
    )

    def load(requests: list[Any]) -> Any:
        net = apply_measures(base, event, "arrival", requests, config)
        demand = build_demand(event, "high", "arrival", config, base)
        background = build_background(base, event, "arrival", net.closed)
        return assign(net.graph, background.volumes, demand.flows, config)

    edge = f"{HUB}-{node}-0"
    values = {
        m.id.rsplit(".", 1)[1]: m.value
        for m in full.result.metrics.measures
        if ".measure_effect." in m.id
    }
    assert values["vc_before"] == pytest.approx(load([old]).edges[edge].vc)
    assert values["vc_after"] == pytest.approx(load([old, new]).edges[edge].vc)
    assert values["vc_before"] != values["vc_after"]  # il presidio cambia davvero il carico


def test_senza_misure_nuove_della_finestra_non_si_rifa_l_assegnazione(
    base: nx.MultiDiGraph, config: EngineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L'effetto costa una seconda assegnazione: si paga solo se la finestra ha una misura nuova."""
    import app.engine.run as run_module

    calls: list[int] = []
    real = run_module.assign

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_module, "assign", counting)
    post = make_request(
        "act_1", type="traffic_post", target=str(HUB), window="departure", state="ACCEPTED"
    )
    engine = RoadEngine(base, config)
    engine.run(make_event(), "high", "arrival", [post], id_prefix=PREFIX, as_of=AS_OF)
    engine.run(
        make_event(), "high", "arrival", [post], id_prefix=PREFIX, as_of=AS_OF, effect_of={"act_1"}
    )  # nuova, ma di un'altra finestra
    assert len(calls) == 2  # una assegnazione per corsa
    engine.run(
        make_event(),
        "high",
        "departure",
        [post],
        id_prefix=PREFIX,
        as_of=AS_OF,
        effect_of={"act_1"},
    )
    assert len(calls) == 4  # la corsa con una misura nuova della sua finestra ne fa due


def test_l_effetto_non_cambia_le_altre_metriche_ed_e_deterministico(
    base: nx.MultiDiGraph, config: EngineConfig
) -> None:
    post = make_request(
        "act_1", type="traffic_post", target=str(HUB), window="arrival", state="ACCEPTED"
    )
    event = make_event()

    def run(effect_of: set[str]) -> RoadResult:
        return (
            RoadEngine(base, config)
            .run(
                event, "high", "arrival", [post], id_prefix=PREFIX, as_of=AS_OF, effect_of=effect_of
            )
            .result
        )

    plain, with_effect, again = run(set()), run({"act_1"}), run({"act_1"})
    only = [m for m in with_effect.metrics.measures if ".measure_effect." not in m.id]
    assert only == list(plain.metrics.measures)  # le metriche della fascia sono quelle di sempre
    assert with_effect.metrics.layers == plain.metrics.layers
    assert with_effect.model_dump_json() == again.model_dump_json()


def test_l_impronta_del_grafo_vede_ogni_cambiamento(base: nx.MultiDiGraph) -> None:
    fingerprint = graph_fingerprint(base)
    assert graph_fingerprint(base.copy()) == fingerprint
    for change in (
        lambda g: g.edges[HUB, HUB + 1, 0].update(capacity_vph=1.0),
        lambda g: g.nodes[HUB].update(x=0.0),
        lambda g: g.add_edge(HUB, HUB + 1, key=7, length_m=1.0),
        lambda g: g.remove_node(HUB + 2),
    ):
        changed = base.copy()
        change(changed)
        assert graph_fingerprint(changed) != fingerprint


# --- cache di R -----------------------------------------------------------------------------------


def test_r_si_calcola_una_volta_per_evento_e_finestra(engine: RoadEngine) -> None:
    event = make_event()

    def cached(event: Event, level: Any, window: Any) -> bool:
        return engine.run(
            event, level, window, id_prefix=PREFIX, as_of=AS_OF
        ).timings.reference_cached

    assert cached(event, "mid", "arrival") is False
    assert cached(event, "mid", "arrival") is True
    assert cached(event, "high", "arrival") is True  # il livello non entra in R
    assert cached(event, "mid", "departure") is False  # un'altra finestra
    other = make_event(background={"arrival_peak_share": 0.5, "departure_peak_share": 0.3})
    assert cached(other, "mid", "arrival") is False  # un altro Evento
    assert cached(event, "mid", "arrival") is True  # e il primo è ancora lì


def test_con_la_cache_il_risultato_non_cambia(base: nx.MultiDiGraph, config: EngineConfig) -> None:
    event = make_event()
    warm = RoadEngine(base, config)
    warm.run(event, "low", "arrival", id_prefix=PREFIX, as_of=AS_OF)  # calcola R
    cached = warm.run(event, "mid", "arrival", id_prefix=PREFIX, as_of=AS_OF)
    assert cached.timings.reference_cached
    assert cached.timings.reference_s < cached.timings.assign_s
    assert cached.result.model_dump_json() == engine_json(
        RoadEngine(base, config), event, "mid", "arrival"
    )


def test_la_cache_di_r_e_limitata(base: nx.MultiDiGraph, config: EngineConfig) -> None:
    engine = RoadEngine(base, config, reference_cache_size=1)
    event = make_event()

    def cached(window: Any) -> bool:
        return engine.run(
            event, "mid", window, id_prefix=PREFIX, as_of=AS_OF
        ).timings.reference_cached

    assert [cached("arrival"), cached("arrival")] == [False, True]
    assert cached("departure") is False  # fa uscire la finestra di arrivo
    assert cached("arrival") is False  # ricalcolata, non sbagliata
    assert cached("arrival") is True


def test_i_tempi_sono_coerenti(engine: RoadEngine) -> None:
    timings = engine.run(make_event(), "mid", "arrival", id_prefix=PREFIX).timings
    parts = (timings.reference_s, timings.assign_s, timings.metrics_s)
    assert all(part > 0 for part in parts)
    assert timings.total_s == pytest.approx(sum(parts))


# --- RoadRunner: processi veri --------------------------------------------------------------------


@pytest.fixture(scope="module")
def runner(graph_path: Path, config: EngineConfig) -> Iterator[RoadRunner]:
    with RoadRunner(graph_path, config) as started:
        yield started


def test_due_processi_ciascuno_con_il_grafo(runner: RoadRunner, base: nx.MultiDiGraph) -> None:
    pids = {worker.pid for worker in runner.workers}
    assert len(pids) == 2
    assert os.getpid() not in pids
    assert {worker.edges for worker in runner.workers} == {base.number_of_edges()}
    assert all(worker.load_s > 0 for worker in runner.workers)


def test_il_pool_da_lo_stesso_risultato_del_motore_in_processo(
    runner: RoadRunner, graph_path: Path, config: EngineConfig, base: nx.MultiDiGraph
) -> None:
    clear_road_graph_cache()
    local = RoadEngine(load_road_graph(graph_path, config), config)
    event = make_event()
    key, _ = inbound_key_of_car_destination(base, config)
    close = make_request("act_7", type="close_road", target=key, window="arrival", state="ACCEPTED")
    cases: list[tuple[Any, Any]] = [("low", "arrival"), ("mid", "arrival"), ("high", "departure")]
    for level, window in cases:
        got = runner.run(event, level, window, [close], id_prefix=PREFIX, as_of=AS_OF)
        want = local.run(event, level, window, [close], id_prefix=PREFIX, as_of=AS_OF).result
        assert got.model_dump_json() == want.model_dump_json(), (level, window)
        assert got.level == level and got.window == window
    assert got.applied == () and want.applied == ()  # la chiusura è dell'arrivo, qui è deflusso


def test_il_pool_logga_i_tempi(
    graph_path: Path, config: EngineConfig, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.INFO, logger="app.engine.run"),
        RoadRunner(graph_path, config, max_workers=1) as one,
    ):
        one.run(make_event(), "mid", "arrival", id_prefix=PREFIX)
        one.run(make_event(), "high", "arrival", id_prefix=PREFIX)
    lines = [r.getMessage() for r in caplog.records if r.name == "app.engine.run"]
    assert any("Motore stradale pronto: 1 processi" in line for line in lines)
    runs = [line for line in lines if line.startswith("Strada test_event")]
    assert len(runs) == 2
    assert "mid arrival: " in runs[0] and " s (R " in runs[0] and "in cache" not in runs[0]
    assert "high arrival: " in runs[1] and "in cache" in runs[1]
    assert all("oltre il budget" not in line for line in lines)


def test_oltre_il_budget_il_log_avvisa(
    graph_path: Path,
    config: EngineConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("app.engine.run.ROAD_BUDGET_S", 0.0)
    with (
        RoadRunner(graph_path, config, max_workers=1) as one,
        caplog.at_level(logging.WARNING, logger="app.engine.run"),
    ):
        one.run(make_event(), "mid", "arrival", id_prefix=PREFIX)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "oltre il budget di 0 s" in warnings[0].getMessage()


def test_gli_errori_dei_dati_attraversano_i_processi_e_il_pool_resta_vivo(
    runner: RoadRunner,
) -> None:
    rejected = make_request(
        "act_9", type="close_road", target="1-2-0", window="arrival", state="RECEIVED"
    )
    with pytest.raises(MeasureError, match="act_9"):
        runner.run(make_event(), "mid", "arrival", [rejected], id_prefix=PREFIX)
    result = runner.run(make_event(), "mid", "arrival", id_prefix=PREFIX)
    assert result.window == "arrival"


def test_senza_il_file_del_grafo_l_errore_e_chiaro(tmp_path: Path, config: EngineConfig) -> None:
    runner = RoadRunner(tmp_path / "nowhere.graphml", config)
    with pytest.raises(GraphError, match=r"Manca il grafo stradale .*nowhere\.graphml.*make data"):
        runner.start()
    with pytest.raises(GraphError, match="make data"):
        runner.run(make_event(), "mid", "arrival", id_prefix=PREFIX)


def test_se_un_processo_muore_il_calcolo_dopo_riparte(
    graph_path: Path, config: EngineConfig
) -> None:
    with RoadRunner(graph_path, config, max_workers=1) as one:
        first = one.workers[0].pid
        os.kill(first, signal.SIGKILL)
        with pytest.raises(RoadRunError, match="si è interrotto"):
            one.run(make_event(), "mid", "arrival", id_prefix=PREFIX)
        result = one.run(make_event(), "mid", "arrival", id_prefix=PREFIX)
        assert result.event_id == "test_event"
        assert one.workers[0].pid != first


def test_start_e_close_si_ripetono_senza_danni(graph_path: Path, config: EngineConfig) -> None:
    one = RoadRunner(graph_path, config, max_workers=1)
    one.start()
    workers = one.workers
    one.start()  # già avviato: nessun secondo pool
    assert one.workers == workers
    one.close()
    one.close()
    one.start()  # dopo close si riparte, con un processo nuovo
    assert one.workers[0].pid != workers[0].pid
    assert one.run(make_event(), "mid", "arrival", id_prefix=PREFIX).event_id == "test_event"
    one.close()


def test_un_grafo_illeggibile_ferma_l_avvio_con_un_errore_chiaro(
    tmp_path: Path, config: EngineConfig
) -> None:
    broken = tmp_path / "graph_drive.graphml"
    broken.write_text("non è un GraphML")
    runner = RoadRunner(broken, config, max_workers=1)
    with pytest.raises(RoadRunError, match="Avvio dei processi di calcolo fallito"):
        runner.start()
    assert runner.workers == ()


def test_close_ferma_i_processi(graph_path: Path, config: EngineConfig) -> None:
    one = RoadRunner(graph_path, config, max_workers=1)
    one.start()
    pid = one.workers[0].pid
    os.kill(pid, 0)  # c'è
    one.close()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_i_numeri_dichiarano_fondo_domanda_chiusure_e_origine_della_rete(
    engine: RoadEngine, base: nx.MultiDiGraph, config: EngineConfig
) -> None:
    key, _ = inbound_key_of_car_destination(base, config)
    close = make_request("act_7", type="close_road", target=key, window="arrival", state="ACCEPTED")
    result = engine.run(
        make_event(), "mid", "arrival", [close], id_prefix=PREFIX, as_of=AS_OF
    ).result
    for measure in result.metrics.measures:
        text = " | ".join(measure.assumptions)
        assert "traffico di fondo = 30 % della capacità" in text, measure.id
        assert "profilo triangolare tra 12:00 e 15:00" in text, measure.id
        assert "1 × close_road" in text, measure.id
        assert (
            "il traffico di fondo degli archi chiusi non è redistribuito (1 archi a zero)" in text
        )
        assert f"rete di {base.number_of_edges()} archi; corsie per senso:" in text, measure.id
        assert measure.assumptions.count(STATIC_MODEL_ASSUMPTION) == 1, measure.id
