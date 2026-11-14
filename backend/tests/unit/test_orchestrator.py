import asyncio
import json
from pathlib import Path

import pytest

from app.data.resolvers import ResolveError
from app.engine.run import RoadResult
from app.engine.transit_run import TransitResult
from app.models.api import ManualResponse
from app.models.base import WINDOWS, Window
from tests.agents_support import config_with, road_result, transit_result
from tests.orchestrator_support import (
    LIVE_ANSWERS,
    Rig,
    RoutingBackend,
    StubEngines,
    empty_road,
    engines_with,
    make_rig,
    quiet_transit,
    run_of,
    zero_resources_event,
)
from tests.support import make_run

TWO = ((1001, "Piazza Vittoria", 1.2), (1002, "Piazza Sannazaro", 1.2))
ONE = TWO[:1]
SEQUENCE = ["INTAKE", "ANALYZE", "RECONCILE", "PLAN", "DISPATCH", "AWAIT", "VERIFY", "DONE"]


async def execute(rig: Rig, *, manual: bool = False) -> None:
    await asyncio.wait_for(rig.orchestrator.execute("run_1", manual=manual), timeout=30)
    await asyncio.wait_for(rig.center.settle(), timeout=5)


# --- nessun rifiuto -----------------------------------------------------------------------------


async def test_senza_rifiuti_il_run_attraversa_tutti_gli_stati(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(ONE))
    await execute(rig)
    run = run_of(rig)
    assert (run.state, run.iteration, run.replans, run.error) == ("DONE", 1, 0, None)
    assert run.ended_at is not None
    assert rig.states() == SEQUENCE


async def test_il_piano_ha_la_misura_accettata_e_la_richiesta_giusta(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(ONE))
    await execute(rig)
    (item,) = rig.repo.list_plan_items("run_1")
    assert (item.seq, item.status, item.recommendation.measure_type) == (
        1,
        "accepted",
        "traffic_post",
    )
    assert item.recommendation.target == "1001" and item.action_id is not None
    requests = rig.repo.list_operation_requests("run_1")
    post, notice = requests
    assert (post.action_id, post.iteration, post.state) == (
        item.action_id,
        1,
        "COMPLETED",
    )
    assert (post.priority, post.target_label, post.window, post.simulation) == (
        "high",
        "Piazza Vittoria",
        "departure",
        True,
    )
    assert post.target_geo is not None  # la posizione viene dal segnale
    assert (notice.type, notice.iteration, notice.state) == ("citizen_notice", 1, "COMPLETED")
    assert notice.payload["text"] == (
        "Misure in vigore per l'evento: presidio stradale a Piazza Vittoria (21:00–23:00)."
    )


async def test_verify_ricalcola_solo_la_finestra_della_misura_accettata(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(ONE))
    await execute(rig)
    action = rig.repo.list_plan_items("run_1")[0].action_id
    assert action is not None
    assert rig.engines.computed("road") == [
        ("it0", "arrival"),
        ("it0", "departure"),
        ("it1", "departure"),
    ]
    assert rig.engines.computed("transit") == [
        ("it0", "arrival"),
        ("it0", "departure"),
        ("it1", "departure"),
    ]
    after = [c for c in rig.engines.calls if c.iteration == "it1"]
    assert {c.actions for c in after} == {(action,)}  # solo la misura in vigore
    assert all(c.actions == () for c in rig.engines.calls if c.iteration == "it0")


async def test_i_risultati_degli_agenti_sono_salvati_in_template(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(ONE))
    await execute(rig)
    results = rig.repo.list_agent_results("run_1")
    assert [r.agent for r in results] == ["event_demand", "traffic", "transit", "operations"]
    assert all((r.text_origin, r.validation) == ("template", "fallback") for r in results)
    assert all(r.iteration == 0 for r in results)
    traffic = results[1]
    assert [f.trigger for f in traffic.findings] == ["critical_intersection"]


async def test_metriche_e_layer_per_ogni_iterazione(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(ONE))
    await execute(rig)
    for iteration in (0, 1):
        metrics = rig.repo.list_metrics("run_1", iteration)
        assert metrics, iteration
        assert len({m.id for m in metrics}) == len(metrics)
        names = rig.repo.list_layer_names("run_1", iteration)
        assert {"critical_intersections", "edges_vc", "requests", "stops"} <= set(names), names
    assert any(".event.attendance" in m.id for m in rig.repo.list_metrics("run_1", 0))
    assert not any(".event." in m.id for m in rig.repo.list_metrics("run_1", 1))


async def test_i_layer_uniscono_le_finestre_con_id_unici(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(ONE))
    await execute(rig)
    layer = rig.repo.get_layer("run_1", 0, "critical_intersections")
    assert layer is not None
    assert [(f.id, f.properties["window"]) for f in layer.features] == [
        ("departure:1001", "departure")
    ]
    edges = rig.repo.get_layer("run_1", 1, "edges_vc")
    assert edges is not None and len({f.id for f in edges.features}) == len(edges.features)
    requests = rig.repo.get_layer("run_1", 1, "requests")
    assert requests is not None
    assert [f.properties["state"] for f in requests.features] == [
        "COMPLETED"
    ]  # il presidio; l'avviso no


async def test_ogni_passaggio_ha_la_sua_decisione_e_gli_attori_sono_quelli_giusti(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path, engines_with(ONE))
    await execute(rig)
    log = rig.repo.list_decisions("run_1")
    actors = {d.actor for d in log}
    assert {"orchestrator", "event_demand", "traffic", "transit", "operations", "municipal_police",
            "public_comms"} <= actors  # fmt: skip
    assert [d.seq for d in log] == list(range(1, len(log) + 1))
    done = log[-1]
    assert (done.actor, done.decision, done.refs) == ("orchestrator", "Passo a DONE", ["DONE"])


# --- la scena di rifiuto (04 7) ----------------------------------------------------------------


async def test_un_rifiuto_una_ripianificazione_e_la_nuova_verifica(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(TWO))
    await execute(rig)
    run = run_of(rig)
    assert (run.state, run.iteration, run.replans) == ("DONE", 2, 1)
    assert rig.states() == [
        *SEQUENCE[:-2],
        "VERIFY",
        "REPLAN",
        "DISPATCH",
        "AWAIT",
        "VERIFY",
        "DONE",
    ]
    first, second, replacement = rig.repo.list_plan_items("run_1")
    assert (first.status, second.status, replacement.status) == ("accepted", "replaced", "accepted")
    assert second.replaced_by == replacement.seq == 3
    assert replacement.recommendation.measure_type == "signal_plan_change"
    assert replacement.recommendation.target == "1002"  # lo stesso incrocio
    assert replacement.recommendation.params == {"favored_edge_key": "9-1002-0"}
    assert replacement.recommendation.department == "traffic_control"


async def test_la_richiesta_sostitutiva_cita_quella_rifiutata(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(TWO))
    await execute(rig)
    first, refused, replacement, notice = rig.repo.list_operation_requests("run_1")
    assert (first.state, refused.state, refused.reject_code) == (
        "COMPLETED",
        "REJECTED",
        "UNAVAILABLE",
    )
    assert (replacement.type, replacement.iteration) == ("signal_plan_change", 2)
    assert replacement.alternative_of == refused.action_id
    assert replacement.payload == {"favored_edge_key": "9-1002-0"}
    assert notice.iteration == 2 and "Piazza Sannazaro" in str(notice.payload["text"])


async def test_verify_riceve_solo_le_misure_in_vigore_giro_dopo_giro(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(TWO))
    await execute(rig)
    first, refused, replacement, _ = rig.repo.list_operation_requests("run_1")
    by_iteration = {c.iteration: c.actions for c in rig.engines.calls if c.window == "departure"}
    assert by_iteration["it1"] == (first.action_id,)  # la rifiutata non c'è
    assert by_iteration["it2"] == (first.action_id, replacement.action_id)
    assert refused.action_id not in by_iteration["it2"]


async def test_il_motore_dice_l_effetto_solo_delle_misure_introdotte_in_ogni_iterazione(
    tmp_path: Path,
) -> None:
    """02 7: `effect_of` = le misure con `iteration` uguale a quella che si sta calcolando. Nel
    caso base nessuna; alla prima verifica le misure del primo giro; alla seconda solo la
    sostitutiva (la prima è già in vigore dall'iterazione 1: il suo effetto non si rifà)."""
    rig = make_rig(tmp_path, engines_with(TWO))
    await execute(rig)
    first, _refused, replacement, _notice = rig.repo.list_operation_requests("run_1")
    in_departure = {(it, ids) for window, it, ids in rig.engines.effect_of if window == "departure"}
    assert ("it0", ()) in in_departure
    assert ("it1", (first.action_id,)) in in_departure
    assert ("it2", (replacement.action_id,)) in in_departure
    # l'iterazione 0 non ha nessuna misura nuova, in nessuna finestra
    assert all(ids == () for _window, it, ids in rig.engines.effect_of if it == "it0")


async def test_la_ripianificazione_e_scritta_nel_registro_con_il_risultato_di_operations(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path, engines_with(TWO))
    await execute(rig)
    operations = [r for r in rig.repo.list_agent_results("run_1") if r.agent == "operations"]
    plan, replan = operations
    assert (plan.iteration, plan.tools_called[0]) == (0, "list_catalog")
    assert replan.iteration == 1 and replan.recommendations[0].measure_type == "signal_plan_change"
    log = [d.decision for d in rig.repo.list_decisions("run_1")]
    assert any(text.startswith("Alternativa per ") for text in log)
    assert "Esiti ricevuti: 1 accettate, 1 rifiutate" in log


# --- rifiuti ripetuti ---------------------------------------------------------------------------


async def test_senza_risorse_la_catena_delle_alternative_arriva_alla_prima_accettata(
    tmp_path: Path,
) -> None:
    """Presidio (nessuna pattuglia) → cambio semaforico (nessun cambio) → segnaletica, accettata."""
    rig = make_rig(tmp_path, engines_with(ONE), event=zero_resources_event())
    await execute(rig)
    run = run_of(rig)
    assert (run.state, run.iteration, run.replans) == ("DONE", 3, 2)
    items = rig.repo.list_plan_items("run_1")
    assert [(i.status, i.replaced_by) for i in items] == [
        ("replaced", 2),
        ("replaced", 3),
        ("accepted", None),
    ]
    assert [i.recommendation.measure_type for i in items] == [
        "traffic_post",
        "signal_plan_change",
        "detour_signage",
    ]
    post, plan_change, detour, notice = rig.repo.list_operation_requests("run_1")
    assert (post.reject_code, plan_change.reject_code) == ("UNAVAILABLE", "LIMIT_REACHED")
    assert detour.alternative_of == plan_change.action_id and detour.target == "9-1001-0"
    # l'etichetta della segnaletica contiene quella del presidio rifiutato: l'avviso passa lo stesso
    assert notice.state == "COMPLETED"
    assert "Archi a monte di Piazza Vittoria" in str(notice.payload["text"])


async def test_senza_alternative_serve_una_persona(tmp_path: Path) -> None:
    """Un presidio di afflusso rifiutato ripiega su corse aggiuntive; senza bus di riserva anche
    quelle sono rifiutate, e non resta altro: decisione umana."""
    transit: dict[Window, TransitResult] = {
        "arrival": quiet_transit("arrival"),
        "departure": transit_result(
            "departure",
            trips={"metro_line_1": 6, "metro_line_6": 3, "funicular": 18},
            loads={"metro_line_1": 0.5, "metro_line_6": 0.2, "funicular": 0.5},
        ),
    }
    engines = StubEngines({w: empty_road(w) for w in WINDOWS}, transit)
    rig = make_rig(tmp_path, engines, event=zero_resources_event())
    await execute(rig)
    run = run_of(rig)
    first, second = rig.repo.list_plan_items("run_1")
    assert (run.state, run.replans) == ("DONE", 2)
    assert first.recommendation.measure_type == "crowd_control_post"
    assert (first.status, first.replaced_by) == ("replaced", 2)
    assert second.recommendation.measure_type == "add_runs"
    assert second.recommendation.target == "metro_line_1"  # la linea che serve la fermata
    assert second.status == "human_decision_required"
    assert second.note == "Nessuna alternativa compatibile non ancora rifiutata"
    assert rig.repo.list_operation_requests("run_1")[-1].reject_code == "NO_RESERVE"
    decisions = [d.decision for d in rig.repo.list_decisions("run_1")]
    assert "Decisione umana richiesta" in decisions and "Nessun avviso ai cittadini" in decisions


async def test_dopo_il_tetto_di_ripianificazioni_si_chiede_una_persona(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.orchestrator.state_machine.MAX_REPLANS", 1)
    rig = make_rig(tmp_path, engines_with(ONE), event=zero_resources_event())
    await execute(rig)
    first, second = rig.repo.list_plan_items("run_1")
    assert (run_of(rig).replans) == 1
    assert (first.status, second.status) == ("replaced", "human_decision_required")
    assert second.note == "Rifiutata anche dopo 1 ripianificazioni"
    assert second.recommendation.measure_type == "signal_plan_change"
    decisions = [d.decision for d in rig.repo.list_decisions("run_1")]
    assert "Decisione umana richiesta" in decisions
    assert "Nessun avviso ai cittadini" in decisions  # niente di approvato, niente avviso


async def test_le_misure_oltre_il_tetto_del_piano_sono_scartate_con_la_nota(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(TWO), config=config_with(plan={"max_measures": 1}))
    await execute(rig)
    first, left_out = rig.repo.list_plan_items("run_1")
    assert (first.status, first.recommendation.target) == ("accepted", "1001")
    assert left_out.status == "discarded" and left_out.action_id is None
    assert left_out.note == "Fuori dal piano: oltre il limite di misure"
    assert left_out.recommendation.target == "1002"
    assert len(rig.repo.list_operation_requests("run_1")) == 2  # il presidio e l'avviso


async def test_una_misura_gia_rifiutata_non_si_ripropone_come_alternativa(tmp_path: Path) -> None:
    """Traffic propone il presidio e il cambio di piano allo stesso incrocio; senza risorse sono
    rifiutati insieme. Il cambio di piano è anche la prima alternativa del presidio, ma è già
    stato rifiutato: si passa alla segnaletica."""
    traffic = json.dumps(
        {
            "text": "Un incrocio critico.",
            "recommendations": [
                {"signal": "s1", "measure_type": "traffic_post", "rationale": "Un presidio."},
                {"signal": "s1", "measure_type": "signal_plan_change", "rationale": "Un cambio."},
            ],
        }
    )
    backend = RoutingBackend({"Traffic Agent": traffic})
    rig = make_rig(
        tmp_path, engines_with(ONE), mode="live", backend=backend, event=zero_resources_event()
    )
    await execute(rig)
    items = rig.repo.list_plan_items("run_1")
    assert [i.recommendation.measure_type for i in items[:2]] == [
        "traffic_post",
        "signal_plan_change",
    ]
    replacements = [i.recommendation.measure_type for i in items[2:]]
    assert replacements and set(replacements) == {"detour_signage"}  # mai il cambio di piano
    traffic_result = next(r for r in rig.repo.list_agent_results("run_1") if r.agent == "traffic")
    assert (traffic_result.text_origin, traffic_result.validation) == ("llm", "ok")


async def test_un_secondo_run_identico_non_chiama_l_llm(tmp_path: Path) -> None:
    """05 4: stessi dati, stessi input, stesse chiavi di cache: il secondo run (con un altro id,
    casuale) si serve dalla cache e ha le stesse decisioni, senza una chiamata al servizio."""
    backend = RoutingBackend(LIVE_ANSWERS)
    rig = make_rig(tmp_path, engines_with(TWO), mode="live", backend=backend)
    await execute(rig)
    first_calls = len(backend.sent)
    assert first_calls == 6  # domanda, Traffic, Transit, piano, ripianificazione, avviso
    rig.repo.add_run(make_run("run_2", llm_mode="live"))
    await asyncio.wait_for(rig.orchestrator.execute("run_2"), timeout=30)
    await asyncio.wait_for(rig.center.settle(), timeout=5)
    assert len(backend.sent) == first_calls  # nessuna nuova chiamata
    for run_id in ("run_1", "run_2"):
        results = rig.repo.list_agent_results(run_id)
        assert {r.text_origin for r in results} == ({"llm"} if run_id == "run_1" else {"llm_cache"})
    first = [(i.status, i.recommendation.measure_type) for i in rig.repo.list_plan_items("run_1")]
    second = [(i.status, i.recommendation.measure_type) for i in rig.repo.list_plan_items("run_2")]
    assert first == second


async def operations_inputs(tmp_path: Path, road_s: float, transit_s: float) -> list[str]:
    engines = engines_with(TWO)
    engines.delay_s, engines.transit_delay_s = road_s, transit_s
    traffic = json.dumps(
        {
            "text": "Due incroci critici.",
            "recommendations": [
                {"signal": "s1", "measure_type": "traffic_post", "rationale": "Un presidio."},
                {"signal": "s2", "measure_type": "traffic_post", "rationale": "Un presidio."},
            ],
        }
    )
    backend = RoutingBackend({"Traffic Agent": traffic})
    rig = make_rig(tmp_path, engines, mode="live", backend=backend)
    await execute(rig)
    return [sent for prompt, sent in backend.sent if "Operations Agent" in prompt]


async def test_l_input_degli_agenti_non_dipende_da_quale_motore_finisce_prima(
    tmp_path: Path,
) -> None:
    """Traffic e Transit girano insieme: l'ordine delle misure che Operations riceve (e quindi la
    chiave della cache LLM) non può dipendere dai tempi dei due motori."""
    road_slow = await operations_inputs(tmp_path / "a", road_s=0.2, transit_s=0.0)
    transit_slow = await operations_inputs(tmp_path / "b", road_s=0.0, transit_s=0.2)
    assert road_slow and road_slow == transit_slow


# --- niente da fare, scarti e RECONCILE ---------------------------------------------------------


async def test_senza_criticita_il_piano_e_vuoto_e_non_c_e_avviso(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(()))
    await execute(rig)
    run = run_of(rig)
    assert (run.state, run.iteration) == ("DONE", 0)
    assert rig.repo.list_plan_items("run_1") == []
    assert rig.repo.list_operation_requests("run_1") == []
    assert rig.states() == ["INTAKE", "ANALYZE", "RECONCILE", "PLAN", "DONE"]


async def test_una_deviazione_su_una_via_chiusa_e_scartata_da_reconcile(tmp_path: Path) -> None:
    road: dict[Window, RoadResult] = {
        "arrival": empty_road("arrival"),
        "departure": road_result(
            "departure",
            intersections=(),
            edges=(("9-5-0", "Via Caracciolo", 1.3),),
            closed=("9-5-0",),
        ),
    }
    engines = StubEngines(road, {w: quiet_transit(w) for w in WINDOWS})
    rig = make_rig(tmp_path, engines)
    await execute(rig)
    (item,) = rig.repo.list_plan_items("run_1")
    assert item.status == "discarded" and item.action_id is None
    assert item.note is not None and item.note.startswith(
        "R2: la via 9-5-0 è proposta come deviazione"
    )
    log = [d.decision for d in rig.repo.list_decisions("run_1")]
    assert "Misura scartata (R2)" in log
    assert rig.repo.list_operation_requests("run_1") == []  # niente è partito


# --- parallelismo, tempi ed errori --------------------------------------------------------------


async def test_traffic_e_transit_girano_in_parallelo(tmp_path: Path) -> None:
    engines = engines_with(())
    engines.delay_s = 0.25
    rig = make_rig(tmp_path, engines)
    await execute(rig)
    road = [(c.started, c.ended) for c in engines.calls if c.kind == "road"]
    transit = [(c.started, c.ended) for c in engines.calls if c.kind == "transit"]
    assert any(
        a0 < b1 and b0 < a1 for a0, a1 in road for b0, b1 in transit
    )  # intervalli che si sovrappongono
    elapsed = max(c.ended for c in engines.calls) - min(c.started for c in engines.calls)
    assert elapsed < 0.25 * 4 * 0.9  # in serie sarebbero quattro calcoli di fila


async def test_il_tempo_massimo_del_run_porta_in_errore(tmp_path: Path) -> None:
    engines = engines_with(ONE)
    engines.delay_s = 1.2
    rig = make_rig(tmp_path, engines, config=config_with(run={"timeout_s": 1}))
    await asyncio.wait_for(rig.orchestrator.execute("run_1"), timeout=10)
    run = run_of(rig)
    assert run.state == "ERROR" and run.error == "Tempo massimo del run superato (1 s)"
    assert run.ended_at is not None
    last = rig.repo.list_decisions("run_1")[-1]
    assert (last.actor, last.decision, last.refs) == ("system", "Run interrotto", ["ERROR"])


async def test_un_errore_del_motore_porta_in_errore_con_un_messaggio(tmp_path: Path) -> None:
    engines = engines_with(ONE)
    engines.fail_road = ValueError("Grafo stradale non disponibile")
    rig = make_rig(tmp_path, engines)
    await asyncio.wait_for(rig.orchestrator.execute("run_1"), timeout=10)
    run = run_of(rig)
    assert (run.state, run.error) == ("ERROR", "ValueError: Grafo stradale non disponibile")
    assert rig.states() == ["INTAKE", "ANALYZE", "ERROR"]  # la timeline finisce in ERROR


async def test_un_nome_dell_evento_che_non_si_trova_nei_dati_e_un_errore_leggibile(
    tmp_path: Path,
) -> None:
    """Il messaggio è per chi compila l'Evento: senza il nome della classe dell'eccezione."""
    engines = engines_with(ONE)
    message = "Chiusura «Via che non c'è»: nessun arco chiamato «Via Inesistente»"
    engines.fail_road = ResolveError(message)
    rig = make_rig(tmp_path, engines)
    await asyncio.wait_for(rig.orchestrator.execute("run_1"), timeout=10)
    run = run_of(rig)
    assert (run.state, run.error) == ("ERROR", message)
    assert rig.states() == ["INTAKE", "ANALYZE", "ERROR"]
    last = rig.repo.list_decisions("run_1")[-1]
    assert (last.actor, last.decision, last.rationale) == ("system", "Run interrotto", message)


async def test_un_run_che_non_c_e_e_un_errore_del_chiamante(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, engines_with(()))
    with pytest.raises(LookupError, match="'run_9'"):
        await rig.orchestrator.execute("run_9")


async def test_la_risposta_manuale_aspetta_una_persona(tmp_path: Path) -> None:
    """Con la risposta manuale ogni richiesta, avviso compreso, aspetta che una persona risponda."""
    rig = make_rig(tmp_path, engines_with(ONE))
    task = asyncio.create_task(rig.orchestrator.execute("run_1", manual=True))
    answered: list[str] = []
    for _ in range(400):
        await asyncio.sleep(0.01)
        for request in rig.repo.list_operation_requests("run_1"):
            if request.state == "RECEIVED" and request.action_id not in answered:
                assert not task.done()  # il run aspetta
                rig.center.respond_manually(request.action_id, ManualResponse(decision="accept"))
                answered.append(request.action_id)
        if task.done():
            break
    run = await asyncio.wait_for(task, timeout=10)
    await asyncio.wait_for(rig.center.settle(), timeout=5)
    assert run.state == "DONE" and len(answered) == 2  # il presidio e l'avviso
    actors = {d.actor for d in rig.repo.list_decisions("run_1")}
    assert "user" in actors  # le risposte sono della persona
