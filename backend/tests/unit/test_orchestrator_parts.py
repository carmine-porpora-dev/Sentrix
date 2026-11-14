from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from app.agents.payloads import PlanCandidate
from app.models.agents import Recommendation
from app.models.api import Feature, FeatureCollection
from app.operations.alternatives import list_alternatives_for_measure
from app.orchestrator.engines import RealEngines
from app.orchestrator.layers import annotate_evidence, merge_by_name, merge_windows, requests_layer
from app.orchestrator.lookup import EngineTargetLookup
from app.orchestrator.reconcile import closed_edges, reconcile
from tests.agents_support import CATALOG, CONFIG, EVIDENCE, measure, road_result
from tests.support import make_request

# --- RECONCILE ----------------------------------------------------------------------------------


def cand(
    identifier: str, measure: str, target: str, window: str = "departure", evidence: str = EVIDENCE
) -> PlanCandidate:
    recommendation = Recommendation(
        measure_type=measure,
        target=target,
        department="traffic_control",
        window=window,
        rationale="Perché.",
        evidence_ids=[evidence],
    )
    return PlanCandidate(identifier, recommendation, f"Etichetta {identifier}", "warning")


def test_senza_conflitti_resta_tutto_nell_ordine_d_arrivo() -> None:
    items = [cand("c1", "traffic_post", "1001"), cand("c2", "detour_signage", "1-2-0")]
    result = reconcile(items, frozenset())
    assert result.kept == items and result.discarded == []


def test_r1_una_deviazione_dei_bus_su_un_arco_chiuso_e_scartata() -> None:
    bus = cand("c1", "bus_detour", "1-2-0,3-4-0")
    result = reconcile([bus], frozenset({"3-4-0"}))
    assert result.kept == []
    (discard,) = result.discarded
    assert (discard.rule, discard.candidate) == ("R1", bus)
    assert discard.reason == "deviazione dei bus su arco chiuso (3-4-0)"


def test_r2_la_stessa_via_come_deviazione_e_come_chiusa_scarta_la_deviazione() -> None:
    detour = cand("c1", "detour_signage", "1-2-0,3-4-0")
    other = cand("c2", "detour_signage", "5-6-0")
    result = reconcile([detour, other], frozenset({"1-2-0"}))
    assert result.kept == [other]
    (discard,) = result.discarded
    assert (discard.rule, discard.reason) == (
        "R2",
        "la via 1-2-0 è proposta come deviazione ma è chiusa",
    )


def test_gli_archi_chiusi_non_toccano_le_altre_misure() -> None:
    post = cand("c1", "traffic_post", "1-2-0")  # un presidio non è una deviazione
    assert reconcile([post], frozenset({"1-2-0"})).kept == [post]


def test_r3_le_misure_doppie_si_unificano_e_la_prima_prende_le_evidenze() -> None:
    first = cand("c1", "traffic_post", "1001", evidence="m.run_1.it0.a")
    twin = cand("c2", "traffic_post", "1001", evidence="m.run_1.it0.b")
    other_window = cand("c3", "traffic_post", "1001", window="arrival")
    result = reconcile([first, twin, other_window], frozenset())
    kept_first, kept_other = result.kept
    assert kept_first.recommendation.evidence_ids == ["m.run_1.it0.a", "m.run_1.it0.b"]
    assert kept_first.target_label == "Etichetta c1" and kept_other == other_window
    (discard,) = result.discarded
    assert (discard.rule, discard.candidate) == ("R3", twin)
    assert discard.reason == "doppia di una misura uguale (traffic_post, 1001)"


def test_r3_la_stessa_evidenza_non_si_ripete() -> None:
    result = reconcile(
        [cand("c1", "traffic_post", "1001"), cand("c2", "traffic_post", "1001")], frozenset()
    )
    assert result.kept[0].recommendation.evidence_ids == [EVIDENCE]


def test_le_regole_si_applicano_in_ordine_r1_r2_poi_r3() -> None:
    closed = cand("c1", "detour_signage", "1-2-0")
    twins = [cand("c2", "traffic_post", "1001"), cand("c3", "traffic_post", "1001")]
    result = reconcile([closed, *twins], frozenset({"1-2-0"}))
    assert [d.rule for d in result.discarded] == ["R2", "R3"]
    assert [c.id for c in result.kept] == ["c2"]


def test_gli_archi_chiusi_si_leggono_dal_layer_di_tutte_le_finestre() -> None:
    arrival = road_result("arrival", edges=(("1-2-0", "A", 1.3),), closed=("1-2-0",))
    departure = road_result("departure", edges=(("3-4-0", "B", 1.3),), closed=("3-4-0",))
    quiet = road_result("departure", edges=(("5-6-0", "C", 1.3),))
    assert closed_edges([arrival, departure, quiet]) == {"1-2-0", "3-4-0"}
    assert closed_edges([]) == frozenset()


# --- lookup dei bersagli ------------------------------------------------------------------------


def routes_of(stop: str) -> list[str]:
    return {"2116": ["metro_line_1", "funicular"]}.get(stop, [])


def test_gli_archi_a_monte_sono_quelli_entranti_con_flusso_dal_v_c_piu_alto() -> None:
    road = road_result("departure", intersections=((1001, "Piazza Vittoria", 1.2),))
    layer = road.metrics.layers["edges_vc"]
    extra = [
        Feature(
            id=k, geometry=None, properties={"edge_key": k, "vc": vc, "detour": d, "closed": False}
        )
        for k, vc, d in (
            ("7-1001-0", 1.9, True),
            ("8-1001-1", 0.7, True),
            ("2-1001-0", 1.9, False),
            ("9-1002-0", 3.0, True),
        )
    ]
    result = road.model_copy(
        update={
            "metrics": road.metrics.__class__(
                **{
                    **road.metrics.__dict__,
                    "layers": {"edges_vc": FeatureCollection(features=[*layer.features, *extra])},
                }
            )
        }
    )
    lookup = EngineTargetLookup(result, routes_of)
    assert lookup.upstream_edges("1001") == ["7-1001-0", "9-1001-0", "8-1001-1"]  # v/c, poi chiave
    assert lookup.upstream_edges("1002") == ["9-1002-0"]
    assert lookup.upstream_edges("5") == []


def test_l_arco_favorito_e_quello_dell_incrocio_critico() -> None:
    lookup = EngineTargetLookup(road_result("departure"), routes_of)
    assert lookup.favored_edge_key("1001") == "9-1001-0"
    assert lookup.favored_edge_key("42") is None


def test_senza_risultato_stradale_non_ci_sono_archi() -> None:
    lookup = EngineTargetLookup(None, routes_of)
    assert lookup.upstream_edges("1001") == [] and lookup.favored_edge_key("1001") is None


def test_le_linee_di_una_fermata_vengono_dal_motore() -> None:
    lookup = EngineTargetLookup(None, routes_of)
    assert lookup.routes_serving("2116") == ["metro_line_1", "funicular"]
    assert lookup.routes_serving("9999") == []


def test_il_lookup_serve_le_alternative_del_catalogo() -> None:
    lookup = EngineTargetLookup(road_result("departure"), routes_of)
    found = list_alternatives_for_measure(
        CATALOG, "traffic_post", "1001", "Piazza Vittoria", lookup
    )
    assert [a.type for a in found] == ["signal_plan_change", "detour_signage"]
    assert found[0].payload == {"favored_edge_key": "9-1001-0"}
    assert found[1].target == "9-1001-0"
    stop = list_alternatives_for_measure(CATALOG, "crowd_control_post", "2116", "Fermata", lookup)
    assert [(a.type, a.target) for a in stop] == [("add_runs", "metro_line_1")]


# --- layer --------------------------------------------------------------------------------------


def layer(*ids: Any) -> FeatureCollection:
    return FeatureCollection(
        features=[Feature(id=i, geometry=None, properties={"k": 1}) for i in ids]
    )


def test_le_finestre_si_uniscono_con_id_unici_e_la_finestra_in_ogni_feature() -> None:
    merged = merge_windows({"departure": layer("a", None, 7), "arrival": layer("a")})
    assert [(f.id, f.properties["window"]) for f in merged.features] == [
        ("arrival:a", "arrival"),
        ("departure:a", "departure"),
        (None, "departure"),
        ("departure:7", "departure"),
    ]
    assert all(f.properties["k"] == 1 for f in merged.features)  # le altre proprietà restano


def test_un_layer_che_c_e_solo_in_una_finestra_resta() -> None:
    merged = merge_by_name(
        {
            "arrival": {"stops": layer("s")},
            "departure": {"stops": layer("t"), "sections": layer("x")},
        }
    )
    assert [f.id for f in merged["stops"].features] == ["arrival:s", "departure:t"]
    assert [f.id for f in merged["sections"].features] == ["departure:x"]
    assert merge_by_name({}) == {}


def test_il_layer_delle_richieste_ha_stato_dipartimento_e_posizione() -> None:
    located = make_request("act_1", state="ACCEPTED", target_geo={"lat": 40.83, "lon": 14.25})
    nowhere = make_request("act_2", type="citizen_notice")
    layer_ = requests_layer([located, nowhere])
    (feature,) = layer_.features  # senza posizione non c'è feature
    assert feature.id == "act_1" and feature.geometry == {
        "type": "Point",
        "coordinates": [14.25, 40.83],
    }
    assert feature.properties == {
        "action_id": "act_1",
        "type": "traffic_post",
        "department": "municipal_police",
        "state": "ACCEPTED",
        "window": "departure",
        "target_label": "Incrocio 1",
        "iteration": 1,
    }


# --- provenienza dei popup ----------------------------------------------------------------------


def _measures(window: str = "departure") -> list[Any]:
    return [
        measure(("road", window, "critical_edges.count"), 3, "n"),
        measure(("road", window, "edge_vc.1-2-0"), 1.3, "rapporto"),
        measure(("transit", window, "stops_overloaded"), 26, "n", "estimate"),
        measure(("transit", window, "stop_load.2116"), 1.6, "rapporto", "estimate"),
        measure(("transit", window, "max_section_load.metro_line_1"), 2.7, "rapporto", "estimate"),
    ]


def _layers() -> dict[str, FeatureCollection]:
    def fc(*props: dict[str, Any]) -> FeatureCollection:
        return FeatureCollection(
            features=[Feature(id=str(i), geometry=None, properties=p) for i, p in enumerate(props)]
        )

    return {
        "edges_vc": fc({"edge_key": "1-2-0"}, {"edge_key": "9-9-0"}),
        "stops": fc({"stop_id": "2116"}, {"stop_id": "7"}),
        "sections": fc({"route_class": "metro_line_1"}, {"route_class": "funicular"}),
        "closures": fc({"label": "Via"}),
    }


def test_ogni_feature_dichiara_il_measured_da_cui_viene_il_suo_numero() -> None:
    out = annotate_evidence("departure", _layers(), _measures())
    ids = {name: [f.properties.get("evidence_id") for f in out[name].features] for name in out}
    assert ids["edges_vc"] == [  # il derivato dell'arco, o il Measured della finestra
        "m.run_1.it0.road.departure.edge_vc.1-2-0",
        "m.run_1.it0.road.departure.critical_edges.count",
    ]
    assert ids["stops"] == [
        "m.run_1.it0.transit.departure.stop_load.2116",
        "m.run_1.it0.transit.departure.stops_overloaded",
    ]
    assert ids["sections"] == [  # il carico massimo della linea; senza, il Measured delle fermate
        "m.run_1.it0.transit.departure.max_section_load.metro_line_1",
        "m.run_1.it0.transit.departure.stops_overloaded",
    ]
    assert ids["closures"] == [None]  # gli altri layer non hanno numeri da mostrare


def test_la_provenienza_guarda_solo_la_finestra_della_feature() -> None:
    measures = _measures("arrival") + _measures("departure")
    out = annotate_evidence("arrival", _layers(), measures)
    assert all(".arrival." in str(f.properties["evidence_id"]) for f in out["edges_vc"].features)


def test_senza_i_measured_di_riferimento_non_si_annota() -> None:
    with pytest.raises(KeyError, match="departure"):
        annotate_evidence("departure", _layers(), _measures()[1:2])


# --- le linee di una fermata, dal feed ----------------------------------------------------------


def test_le_linee_di_una_fermata_sono_per_frequenza_e_senza_bus() -> None:
    stop_times = pd.DataFrame(
        {
            "trip_id": ["t1", "t2", "t3", "t4", "t5", "t6"],
            "stop_id": ["S", "S", "S", "S", "S", "OTHER"],
        }
    )
    trips = pd.DataFrame(
        {
            "trip_id": ["t1", "t2", "t3", "t4", "t5", "t6"],
            "route_id": ["f1", "m1", "m1", "bus9", "bus9", "m6"],  # la funicolare arriva per prima
        }
    )
    kinds = {"m1": "metro_line_1", "f1": "funicular", "bus9": "bus", "m6": "metro_line_6"}
    network = SimpleNamespace(
        feed=SimpleNamespace(stop_times=stop_times, trips=trips),
        classes=SimpleNamespace(of=lambda route_id: kinds.get(route_id)),
    )
    engines = RealEngines(
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        network,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        ["metro_line_1", "metro_line_6", "funicular"],
    )
    assert engines.routes_serving("S") == ["metro_line_1", "funicular"]  # bus escluso
    assert engines.routes_serving("OTHER") == ["metro_line_6"]
    assert engines.routes_serving("NESSUNA") == []


# --- registro, piano e simulazione ---------------------------------------------------------------


def test_le_finestre_hanno_un_solo_elenco_nell_ordine_canonico() -> None:
    from app.models.base import WINDOWS

    assert WINDOWS == ("arrival", "departure")


def test_il_registro_scrive_il_passaggio_di_stato_e_la_timeline_lo_rilegge(tmp_path: Any) -> None:
    from datetime import datetime

    from app.clock import ROME
    from app.orchestrator.journal import ENTER, FAILED, Journal, state_transitions
    from tests.operations_support import make_repo

    repo = make_repo(tmp_path, "run_1")
    journal = Journal(repo)
    assert journal.enter("run_1", "ANALYZE", "perché").state == "ANALYZE"
    journal.log("run_1", "traffic", "Risultato", "testo", ["m.x"])  # non è un cambio di stato
    journal.log("run_1", "orchestrator", "Altro", "testo")  # nemmeno questo
    journal.log("run_1", "system", "Altro ancora", "testo")
    journal.log("run_1", "traffic", f"{ENTER}RECONCILE", "non è l'orchestratore", ["RECONCILE"])
    run = journal.fail("run_1", "Motore rotto", datetime(2026, 11, 11, 12, 0, tzinfo=ROME))
    assert (run.state, run.error) == ("ERROR", "Motore rotto") and run.ended_at is not None
    decisions = repo.list_decisions("run_1")
    assert [s for s, _ in state_transitions(decisions)] == ["ANALYZE", "ERROR"]
    assert decisions[0].decision == f"{ENTER}ANALYZE" and decisions[-1].decision == FAILED
    assert decisions[0].refs == ["ANALYZE"] and decisions[-1].actor == "system"


def test_il_piano_numera_gli_elementi_e_li_scrive_subito(tmp_path: Any) -> None:
    from app.agents.payloads import PlanCandidate
    from app.orchestrator.plan_book import PlanBook
    from tests.agents_support import candidate
    from tests.operations_support import make_repo

    repo = make_repo(tmp_path, "run_1")
    book = PlanBook(repo, "run_1")
    one: PlanCandidate = candidate("c1")
    assert book.add(one, status="discarded", note="Fuori dal piano") == 1
    assert book.propose(one) == 2 and book.pending == [2] and book.replaces == {}
    assert book.propose(one, replaces="act_run_1_001") == 3
    assert book.pending == [2, 3] and book.replaces == {3: "act_run_1_001"}
    assert book.meta[2] is one and book.items[1].note == "Fuori dal piano"
    book.update(2, status="accepted", action_id="act_run_1_002")
    saved = {i.seq: (i.status, i.action_id) for i in repo.list_plan_items("run_1")}
    assert saved == {
        1: ("discarded", None),
        2: ("accepted", "act_run_1_002"),
        3: ("proposed", None),
    }


def test_un_aggiornamento_incoerente_del_piano_non_cambia_niente(tmp_path: Any) -> None:
    from pydantic import ValidationError

    from app.orchestrator.plan_book import PlanBook
    from tests.agents_support import candidate
    from tests.operations_support import make_repo

    repo = make_repo(tmp_path, "run_1")
    book = PlanBook(repo, "run_1")
    seq = book.propose(candidate("c1"))
    with pytest.raises(ValidationError):
        book.update(seq, status="accepted")  # manca l'action_id della richiesta inviata
    assert book.items[seq].status == "proposed"
    assert repo.list_plan_items("run_1")[0].status == "proposed"


def test_la_simulazione_dice_l_orario_di_ogni_finestra_dell_evento(tmp_path: Any) -> None:
    from datetime import datetime

    from app.clock import ROME
    from app.data.seeds import read_seed_events
    from app.orchestrator.simulation import Simulation
    from tests.operations_support import make_repo
    from tests.orchestrator_support import engines_with

    event = next(e for e in read_seed_events() if e.id == "match_2027")
    simulation = Simulation(
        engines=engines_with(()),
        repo=make_repo(tmp_path, "run_1"),
        config=CONFIG,
        event=event,
        level="mid",
        run_id="run_1",
        as_of=datetime(2026, 11, 11, 10, 0, tzinfo=ROME),
    )
    assert simulation.window_spans() == {"arrival": "16:00–19:00", "departure": "21:00–23:00"}


def test_l_iterazione_si_salva_prima_con_i_layer_e_per_ultime_le_metriche(tmp_path: Any) -> None:
    """L'API considera calcolata un'iterazione quando ha le metriche: i layer devono esserci già."""
    from datetime import datetime

    from app.clock import ROME
    from app.data.seeds import read_seed_events
    from app.models.base import WINDOWS
    from app.orchestrator.simulation import Simulation
    from tests.agents_support import transit_result
    from tests.operations_support import make_repo
    from tests.orchestrator_support import engines_with

    repo = make_repo(tmp_path, "run_1")
    calls: list[str] = []

    class Recording:
        def __getattr__(self, name: str) -> Any:
            return getattr(repo, name)

        def put_layer(self, *args: Any) -> None:
            calls.append("layer")
            repo.put_layer(*args)

        def put_metrics(self, *args: Any) -> None:
            calls.append("metrics")
            repo.put_metrics(*args)

    simulation = Simulation(
        engines=engines_with(()),
        repo=Recording(),  # type: ignore[arg-type]
        config=CONFIG,
        event=next(e for e in read_seed_events() if e.id == "match_2027"),
        level="mid",
        run_id="run_1",
        as_of=datetime(2026, 11, 11, 10, 0, tzinfo=ROME),
    )
    simulation.road[0] = {w: road_result(w) for w in WINDOWS}
    simulation.transit[0] = {w: transit_result(w) for w in WINDOWS}
    assert not repo.has_metrics("run_1", 0)
    simulation.store(0)
    assert len(calls) > 1 and set(calls[:-1]) == {"layer"} and calls[-1] == "metrics"
    assert repo.has_metrics("run_1", 0)
