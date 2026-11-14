import datetime as dt
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import networkx as nx
import pytest

from app.data.osm_graph import load_osm_graph
from app.data.resolvers import edge_key, parse_edge_key, resolve_point
from app.data.seeds import read_seed_events
from app.engine.assign import Assignment, Router, assign
from app.engine.background import build_background
from app.engine.cli import main as cli_main
from app.engine.demand import Demand, build_demand
from app.engine.graph import build_road_graph, clear_road_graph_cache, load_road_graph
from app.engine.measures import RoadNetwork, apply_measures
from app.engine.metrics import build_reference, od_pair_nodes
from app.engine.run import RoadEngine, RoadResult
from app.models.base import WINDOWS, Window
from app.models.config import EngineConfig
from app.models.edge_overrides import EdgeOverrides
from app.models.event import Closure, Event
from app.models.operations import OperationRequest
from app.models.run import AttendanceLevel
from tests.integration.conftest import FEED_PATH
from tests.support import graph_fingerprint, make_request

pytestmark = pytest.mark.realdata

LEVELS: tuple[AttendanceLevel, ...] = get_args(AttendanceLevel)  # low, mid, high
SEED_IDS = sorted(event.id for event in read_seed_events())
PAIR_IDS = [pair.id for pair in EngineConfig.from_yaml().demand.od_pairs]
AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
PREFIX = ("t", "it0")
FIXTURES = Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "fixtures"

RunKey = tuple[str, AttendanceLevel, Window]


@pytest.fixture(scope="module")
def engine(road_graph: nx.MultiDiGraph, road_config: EngineConfig) -> RoadEngine:
    return RoadEngine(road_graph, road_config)


@pytest.fixture(scope="module")
def runs(engine: RoadEngine, seed_events: dict[str, Event]) -> dict[RunKey, RoadResult]:
    """Dodici calcoli (2 preset × 3 livelli × 2 finestre), uno per volta, condivisi dai test."""
    return {
        (event_id, level, window): engine.run(
            seed_events[event_id], level, window, id_prefix=PREFIX, as_of=AS_OF
        ).result
        for event_id in SEED_IDS
        for level in LEVELS
        for window in WINDOWS
    }


def metric(result: RoadResult, name: str) -> float:
    found = [m for m in result.metrics.measures if m.id.endswith(f".road.{result.window}.{name}")]
    assert len(found) == 1, f"{name}: {len(found)} metriche"
    value = found[0].value
    assert isinstance(value, int | float)
    return float(value)


# --- i passi del motore a mano, per guardare dentro l'assegnazione --------------------------------


@dataclass(frozen=True)
class Steps:
    network: RoadNetwork
    demand: Demand
    assignment: Assignment


def steps_of(
    base: nx.MultiDiGraph,
    config: EngineConfig,
    event: Event,
    level: AttendanceLevel,
    window: Window,
    requests: list[OperationRequest],
) -> Steps:
    network = apply_measures(base, event, window, requests, config)
    background = build_background(base, event, window, network.closed)
    demand = build_demand(event, level, window, config, base)
    return Steps(network, demand, assign(network.graph, background.volumes, demand.flows, config))


@pytest.fixture(scope="module")
def mid_steps(
    road_graph: nx.MultiDiGraph, road_config: EngineConfig, seed_events: dict[str, Event]
) -> dict[tuple[str, Window], Steps]:
    return {
        (event_id, window): steps_of(
            road_graph, road_config, seed_events[event_id], "mid", window, []
        )
        for event_id in SEED_IDS
        for window in WINDOWS
    }


# --- sensibilità ----------------------------------------------------------------------------------


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_sensibilita_low_mid_high(
    runs: dict[RunKey, RoadResult], event_id: str, window: Window
) -> None:
    def values(name: str) -> list[float]:
        return [metric(runs[(event_id, level, window)], name) for level in LEVELS]

    low, mid, high = values("veh_hours")
    assert low < mid < high, (low, mid, high)
    # con più persone non migliora niente: tempi medi, archi critici e loro lunghezza
    for name in ("od_time.mean", "critical_edges.count", "critical_edges.km"):
        low, mid, high = values(name)
        assert low <= mid <= high, (name, low, mid, high)


# --- unità, forma e provenienza di ogni metrica ---------------------------------------------------

BASE_UNITS = {
    "veh_hours": "veic·h",
    "od_time.mean": "min",
    "critical_edges.count": "n",
    "critical_edges.km": "km",
    "detour_extra_km": "km",
    "unassigned_pairs": "n",
}


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_unita_e_forma_di_ogni_metrica(
    runs: dict[RunKey, RoadResult],
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
    level: AttendanceLevel,
    window: Window,
) -> None:
    result = runs[(event_id, level, window)]
    background = seed_events[event_id].background
    share = (
        background.arrival_peak_share if window == "arrival" else background.departure_peak_share
    )
    prefix = f"m.t.it0.road.{window}."
    expected = dict(BASE_UNITS)
    for pair in PAIR_IDS:
        expected[f"od_time.{pair}"] = "min"
        expected[f"od_time_ref.{pair}"] = "min"
    top_n = road_config.metrics.critical_intersections_top_n
    ranks = {f"critical_intersection.{n}.vc": "rapporto" for n in range(1, top_n + 1)}

    measures = result.metrics.measures
    ids = [m.id for m in measures]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith(prefix) for i in ids)
    tails = {m.id.removeprefix(prefix): m for m in measures}
    present_ranks = [name for name in tails if name in ranks]
    assert set(tails) == set(expected) | set(present_ranks)
    # i primi N incroci, senza buchi (1, 2, …) e in ordine di v/c decrescente
    assert present_ranks == list(ranks)[: len(present_ranks)]
    assert len(present_ranks) >= 1

    for name, measure in tails.items():
        assert measure.unit == (expected | ranks)[name], name
        assert measure.kind == "simulated" and measure.source == "engine.metrics v1", name
        assert measure.as_of == AS_OF and measure.method and measure.inputs, name
        assert any("non una previsione" in a for a in measure.assumptions), name
        assert f"traffico di fondo = {share * 100:g} % della capacità" in " | ".join(
            measure.assumptions
        ), name
        assert isinstance(measure.value, int | float) and measure.value == measure.value  # no NaN
        if name != "detour_extra_km":  # l'unica con segno
            assert measure.value >= 0, name

    vcs = [metric(result, name) for name in present_ranks]
    assert vcs == sorted(vcs, reverse=True)
    assert metric(result, "unassigned_pairs") == 0  # la rete è connessa (resolve_seeds)
    count, km = metric(result, "critical_edges.count"), metric(result, "critical_edges.km")
    assert (count == 0) == (km == 0)

    times = [metric(result, f"od_time.{pair}") for pair in PAIR_IDS]
    refs = [metric(result, f"od_time_ref.{pair}") for pair in PAIR_IDS]
    assert metric(result, "od_time.mean") == pytest.approx(sum(times) / len(times))
    # senza misure il carico c'è solo in più e le chiusure tolgono archi: mai più veloci di R
    assert all(t >= r - 1e-9 for t, r in zip(times, refs, strict=True))


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_il_riferimento_r_non_dipende_dal_livello_ne_dalle_chiusure_dell_evento(
    engine: RoadEngine,
    runs: dict[RunKey, RoadResult],
    road_graph: nx.MultiDiGraph,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
    window: Window,
) -> None:
    """R è il solo traffico di fondo sulla rete di base: uguale a ogni livello, e uguale anche se
    all'Evento si tolgono le chiusure o se ne mette una sul cammino di una coppia."""

    def refs(result: RoadResult) -> list[float]:
        return [metric(result, f"od_time_ref.{pair}") for pair in PAIR_IDS]

    event = seed_events[event_id]
    at_mid = refs(runs[(event_id, "mid", window)])
    assert refs(runs[(event_id, "low", window)]) == at_mid
    assert refs(runs[(event_id, "high", window)]) == at_mid
    free = event.model_copy(update={"closures": []})
    assert refs(engine.run(free, "mid", window, id_prefix=PREFIX, as_of=AS_OF).result) == at_mid
    # una chiusura sul cammino di R di una coppia cambia il suo tempo finale, non quello di R
    first = od_pair_nodes(event, road_graph, road_config)[PAIR_IDS[0]]
    reference = build_reference(road_graph, event, window, road_config)
    route = Router(road_graph, reference.edges).routes([first])[first]
    assert route is not None and len(route.edges) >= 3
    key = route.edges[len(route.edges) // 2]
    blocked = event.model_copy(update={"closures": [Closure(label="Prova", edge_keys=[key])]})
    result = engine.run(blocked, "mid", window, id_prefix=PREFIX, as_of=AS_OF).result
    assert refs(result) == at_mid
    assert metric(result, f"od_time.{PAIR_IDS[0]}") > at_mid[0]


# --- le stesse metriche che l'interfaccia vede nelle fixture --------------------------------------


def fixture_metrics() -> dict[str, tuple[str, str]]:
    """Coda dell'id → (unità, kind) di ogni metrica stradale delle fixture del frontend."""
    found: dict[str, tuple[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            id_ = node.get("id")
            if isinstance(id_, str) and ".road." in id_ and "unit" in node:
                found[id_.split(".", 3)[3]] = (node["unit"], node["kind"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads((FIXTURES / "run_metrics" / "iteration_0.json").read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize("event_id", SEED_IDS)
def test_il_motore_produce_le_metriche_delle_fixture_con_le_stesse_unita(
    runs: dict[RunKey, RoadResult], event_id: str
) -> None:
    """Il frontend nasce sul mock (D12): il motore deve dargli gli stessi id, unità e kind."""
    expected = fixture_metrics()
    assert len(expected) == 26  # 13 per finestra
    produced: dict[str, tuple[str, str]] = {}
    for window in WINDOWS:
        for m in runs[(event_id, "mid", window)].metrics.measures:
            produced[m.id.split(".", 3)[3]] = (m.unit, m.kind)
    assert {k: produced.get(k) for k in expected} == expected


# --- determinismo ---------------------------------------------------------------------------------


def test_stessi_input_stesso_output_byte_per_byte(
    runs: dict[RunKey, RoadResult],
    road_graph: nx.MultiDiGraph,
    road_graph_path: Path,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
) -> None:
    """Una rete ricostruita dal file e un motore nuovo (senza cache di R) danno gli stessi byte."""
    clear_road_graph_cache()
    rebuilt = load_road_graph(road_graph_path, road_config, EdgeOverrides.from_yaml())
    assert rebuilt is not road_graph
    fresh = RoadEngine(rebuilt, road_config)
    for event_id in SEED_IDS:
        for window in WINDOWS:
            again = fresh.run(
                seed_events[event_id], "mid", window, id_prefix=PREFIX, as_of=AS_OF
            ).result
            assert again.model_dump_json() == runs[(event_id, "mid", window)].model_dump_json()


# --- conservazione --------------------------------------------------------------------------------


def node_balance(assignment: Assignment) -> dict[int, float]:
    """Per ogni nodo, flusso dell'evento entrante meno uscente."""
    balance: dict[int, float] = defaultdict(float)
    for key, load in assignment.edges.items():
        origin, dest, _ = parse_edge_key(key)
        balance[origin] -= load.v_event
        balance[dest] += load.v_event
    return balance


def assert_flow_conserved(steps: Steps, config: EngineConfig) -> None:
    """La domanda è tutta assegnata o dichiarata non assegnata, e in ogni nodo il flusso che entra
    meno quello che esce è la domanda che vi arriva meno quella che vi parte (degli assegnati)."""
    demand, assignment = steps.demand, steps.assignment
    total = sum(f.veh_per_hour for f in demand.flows)
    # domanda auto = persone in auto / occupazione, riportate all'ora (fascia di 30 minuti)
    expected = demand.car_persons / demand.car_occupancy * 60 / config.time_slice_minutes
    assert total == pytest.approx(expected, rel=1e-9)
    assert assignment.demand_veh_per_hour == pytest.approx(total, rel=1e-9)
    assert assignment.assigned_veh_per_hour + assignment.unassigned_veh_per_hour == pytest.approx(
        total, rel=1e-9
    )
    unassigned = {(f.zone_id, f.origin_node, f.dest_node) for f in assignment.unassigned}
    wanted: dict[int, float] = defaultdict(float)
    for f in demand.flows:
        if (f.zone_id, f.origin_node, f.dest_node) not in unassigned:
            wanted[f.origin_node] -= f.veh_per_hour
            wanted[f.dest_node] += f.veh_per_hour
    got = node_balance(assignment)
    worst = max(abs(got.get(n, 0.0) - wanted.get(n, 0.0)) for n in set(got) | set(wanted))
    assert worst <= 1e-6 * total, worst


@pytest.mark.parametrize("level", ("mid", "high"))
@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_conservazione_dei_veicoli(
    road_graph: nx.MultiDiGraph,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
    window: Window,
    level: AttendanceLevel,
) -> None:
    steps = steps_of(road_graph, road_config, seed_events[event_id], level, window, [])
    assert steps.assignment.unassigned == ()  # sui dati veri ogni coppia ha un cammino
    assert_flow_conserved(steps, road_config)


@pytest.mark.parametrize("event_id", SEED_IDS)
def test_conservazione_con_una_destinazione_irraggiungibile(
    road_graph: nx.MultiDiGraph,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
) -> None:
    """Chiusi tutti gli archi entranti nel primo punto di arrivo, le sue coppie sono «non assegnate»
    e il resto della domanda si conserva."""
    point = road_config.demand.car_destinations[0].point
    dest = resolve_point(point, road_graph, max_distance_m=road_config.node_snap_max_distance_m)
    targets = [edge_key(u, v, k) for u, v, k in road_graph.in_edges(dest, keys=True)]
    close = make_request(
        "act_1",
        type="close_road",
        target=",".join(targets),
        window="arrival",
        iteration=1,
        state="ACCEPTED",
    )
    steps = steps_of(road_graph, road_config, seed_events[event_id], "mid", "arrival", [close])
    cut_off = [f for f in steps.demand.flows if f.dest_node == dest]
    assert cut_off
    assert {(f.zone_id, f.dest_node) for f in steps.assignment.unassigned} == {
        (f.zone_id, dest) for f in cut_off
    }
    assert steps.assignment.unassigned_veh_per_hour == pytest.approx(
        sum(f.veh_per_hour for f in cut_off)
    )
    assert_flow_conserved(steps, road_config)


# --- chiusura di un arco usato --------------------------------------------------------------------

# Il solo caso, su 20, in cui il tempo O/D scende dopo la chiusura (-0,34 min, -2,0 %).
KNOWN_CLOSURE_IMPROVEMENT = ("regate_sep_2026", "arrival", "bagnoli_centrale")
CLOSURE_CASES = [
    pytest.param(
        event_id,
        window,
        pair,
        marks=pytest.mark.xfail(
            strict=True,
            raises=AssertionError,
            reason="assegnazione incrementale, non un equilibrio: chiudere l'arco libera altri "
            "archi (16,875 → 16,534 min); vedi CHANGELOG F2-TEST",
        )
        if (event_id, window, pair) == KNOWN_CLOSURE_IMPROVEMENT
        else (),
    )
    for event_id in SEED_IDS
    for window in WINDOWS
    for pair in PAIR_IDS
]


def busiest_edge_of_route(steps: Steps, pair: tuple[int, int]) -> tuple[str, float]:
    """L'arco del cammino della coppia con più flusso dell'evento, e il tempo del cammino."""
    route = Router(steps.network.graph, steps.assignment.edges).routes([pair])[pair]
    assert route is not None
    used = [key for key in route.edges if steps.assignment.edges[key].v_event > 0]
    assert used, "il cammino della coppia non porta flusso dell'evento"
    return max(used, key=lambda key: (steps.assignment.edges[key].v_event, key)), route.time_min


@pytest.mark.parametrize(("event_id", "window", "pair_id"), CLOSURE_CASES)
def test_chiudere_un_arco_usato_non_riduce_il_tempo_della_coppia(
    engine: RoadEngine,
    runs: dict[RunKey, RoadResult],
    mid_steps: dict[tuple[str, Window], Steps],
    road_graph: nx.MultiDiGraph,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
    window: Window,
    pair_id: str,
) -> None:
    event = seed_events[event_id]
    pair = od_pair_nodes(event, road_graph, road_config)[pair_id]
    key, _ = busiest_edge_of_route(mid_steps[(event_id, window)], pair)
    close = make_request(
        "act_1", type="close_road", target=key, window=window, iteration=1, state="ACCEPTED"
    )
    closed = engine.run(event, "mid", window, [close], id_prefix=("t", "it1"), as_of=AS_OF).result
    before = metric(runs[(event_id, "mid", window)], f"od_time.{pair_id}")
    after = metric(closed, f"od_time.{pair_id}")
    assert closed.applied == ("act_1",)
    assert after >= before, f"{key}: {before:.3f} → {after:.3f} min"


@pytest.mark.parametrize("pair_id", PAIR_IDS)
@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_a_carichi_fissi_chiudere_un_arco_non_accorcia_il_cammino(
    mid_steps: dict[tuple[str, Window], Steps],
    road_graph: nx.MultiDiGraph,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
    window: Window,
    pair_id: str,
) -> None:
    """La proprietà esatta: con gli stessi carichi, senza un arco il cammino minimo non può essere
    più corto (e la strada chiusa non si usa più)."""
    event = seed_events[event_id]
    steps = mid_steps[(event_id, window)]
    pair = od_pair_nodes(event, road_graph, road_config)[pair_id]
    key, before = busiest_edge_of_route(steps, pair)
    close = make_request(
        "act_1", type="close_road", target=key, window=window, iteration=1, state="ACCEPTED"
    )
    network = apply_measures(road_graph, event, window, [close], road_config)
    after = Router(network.graph, steps.assignment.edges).routes([pair])[pair]
    assert after is None or after.time_min >= before
    assert after is None or key not in after.edges


# --- presidio su un incrocio critico --------------------------------------------------------------

# Il solo caso, su 16, in cui le ore-veicolo salgono: +5,45 % (119.303 → 125.808 veic·h) a livello
# `high`, dove il v/c arriva a 6,4. Con 32 passi sono +0,25 % su due altri nodi, con 64 nessuno.
KNOWN_POST_WORSENING = ("match_2027", "departure", "high", 1)
POST_CASES = [
    pytest.param(
        event_id,
        window,
        level,
        rank,
        marks=pytest.mark.xfail(
            strict=True,
            raises=AssertionError,
            reason="oltre sei volte la capacità l'assegnazione a 16 passi non è un equilibrio: "
            "il presidio sposta traffico su percorsi più lunghi; vedi CHANGELOG F2-TEST",
        )
        if (event_id, window, level, rank) == KNOWN_POST_WORSENING
        else (),
    )
    for event_id in SEED_IDS
    for window in WINDOWS
    for level in ("mid", "high")
    for rank in (1, 2)
]


@pytest.mark.parametrize(("event_id", "window", "level", "rank"), POST_CASES)
def test_un_presidio_su_un_incrocio_critico_non_peggiora_le_ore_veicolo(
    engine: RoadEngine,
    runs: dict[RunKey, RoadResult],
    seed_events: dict[str, Event],
    event_id: str,
    window: Window,
    level: AttendanceLevel,
    rank: int,
) -> None:
    base = runs[(event_id, level, window)]
    node = base.metrics.critical_intersections[rank - 1].node
    post = make_request(
        "act_1", type="traffic_post", target=str(node), window=window, iteration=1, state="ACCEPTED"
    )
    done = engine.run(
        seed_events[event_id], level, window, [post], id_prefix=("t", "it1"), as_of=AS_OF
    ).result
    assert done.applied == ("act_1",)
    before, after = metric(base, "veh_hours"), metric(done, "veh_hours")
    assert after <= before, f"nodo {node}: {before:.1f} → {after:.1f} ({after / before - 1:+.2%})"


# --- la riga di comando sui due preset ------------------------------------------------------------


@pytest.mark.parametrize("event_id", SEED_IDS)
def test_la_riga_di_comando_stampa_e_scrive_per_il_preset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    runs: dict[RunKey, RoadResult],
    road_graph_path: Path,
    event_id: str,
) -> None:
    data = tmp_path / "data"
    (data / "osm").mkdir(parents=True)
    (data / "osm" / road_graph_path.name).symlink_to(road_graph_path)
    (data / "gtfs").symlink_to(FEED_PATH.parent)  # la riga di comando calcola anche il TPL
    assert cli_main(["--data-dir", str(data), "--event", event_id, "--level", "mid"]) == 0
    out = capsys.readouterr().out
    written = json.loads((data / "out" / f"{event_id}_mid.json").read_text(encoding="utf-8"))
    assert list(written["windows"]) == list(WINDOWS)
    for window in WINDOWS:
        result = RoadResult.model_validate(written["windows"][window])
        reference = runs[(event_id, "mid", window)]
        # gli stessi numeri del motore chiamato direttamente (gli id hanno il prefisso della CLI)
        assert [m.value for m in result.metrics.measures] == [
            m.value for m in reference.metrics.measures
        ]
        veh_hours = metric(reference, "veh_hours")
        assert any(
            line.split()[:2] == ["veh_hours", f"{veh_hours:.3f}"] for line in out.splitlines()
        )
    assert out.count("\n== ") == len(WINDOWS)  # un titolo per finestra


# --- il motore non modifica la rete ---------------------------------------------------------------


def test_la_rete_di_base_resta_com_e_dopo_i_calcoli(
    engine: RoadEngine,
    runs: dict[RunKey, RoadResult],
    road_graph: nx.MultiDiGraph,
    road_graph_path: Path,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
) -> None:
    """Dopo tutti i calcoli di questo modulo, e dopo altri con ogni tipo di misura, la rete è
    identica a una ricostruita dal file: nessuna funzione del motore ne ha toccato gli attributi."""
    for event_id in SEED_IDS:
        for window in WINDOWS:
            base = runs[(event_id, "mid", window)]
            its = base.metrics.critical_intersections
            requests = [
                make_request(
                    "act_1", type="traffic_post", target=str(its[0].node), window=window,
                    iteration=1, state="ACCEPTED",
                ),
                make_request(
                    "act_2", type="signal_plan_change", target=str(its[-1].node), window=window,
                    iteration=1, state="ACCEPTED", payload={"favored_edge_key": its[-1].edge_key},
                ),
                make_request(
                    "act_3", type="detour_signage",
                    target=",".join(e.edge_key for e in base.metrics.critical_edges[:3]),
                    window=window, iteration=1, state="ACCEPTED",
                ),
                make_request(
                    "act_4", type="close_road", target=base.metrics.critical_edges[3].edge_key,
                    window=window, iteration=1, state="ACCEPTED",
                ),
            ]  # fmt: skip
            done = engine.run(seed_events[event_id], "mid", window, requests, id_prefix=PREFIX)
            assert done.result.applied == ("act_1", "act_2", "act_3", "act_4")
    rebuilt = build_road_graph(
        load_osm_graph(road_graph_path), road_config, EdgeOverrides.from_yaml()
    )
    assert graph_fingerprint(road_graph) == graph_fingerprint(rebuilt)
