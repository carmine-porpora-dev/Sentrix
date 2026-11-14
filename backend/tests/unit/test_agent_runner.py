import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.agents.payloads import PlanCandidate
from app.agents.prompt_loader import Prompt, load_prompt
from app.agents.runner import AgentRunner
from app.agents.tools import AgentTools
from app.llm.client import LlmUnavailable
from app.models.agents import AgentResult, Recommendation
from app.models.agents_config import AgentsConfig
from app.models.api import ResourceBalance
from app.models.base import LlmMode
from app.operations.alternatives import Alternative
from tests.agents_support import (
    CATALOG,
    CONFIG,
    EVIDENCE,
    candidate,
    config_with,
    event_demand_agent_tools,
    traffic_agent_tools,
    transit_agent_tools,
)
from tests.llm_support import FakeBackend, make_client, make_llm_repo
from tests.support import make_request as make_operation

SHA256 = re.compile(r"[0-9a-f]{64}")


def runner(
    tmp_path: Path,
    *responses: str | Exception,
    mode: LlmMode = "live",
    config: AgentsConfig = CONFIG,
) -> tuple[AgentRunner, FakeBackend]:
    backend = FakeBackend(*responses)
    client = make_client(
        make_llm_repo(tmp_path), None if mode == "template" else backend, mode=mode
    )
    return AgentRunner(client, config, CATALOG), backend


def reply(**fields: Any) -> str:
    return json.dumps({"text": "Sintesi.", **fields})


def check_result(result: AgentResult, agent: str, origin: str, validation: str) -> None:
    assert (result.agent, result.text_origin, result.validation) == (agent, origin, validation)
    assert result.run_id == "run_1" and result.iteration == 0
    assert SHA256.fullmatch(result.input_hash) and result.duration_ms >= 0


# --- Event & Demand -----------------------------------------------------------------------------


async def test_event_demand_in_modalita_template(tmp_path: Path) -> None:
    run, backend = runner(tmp_path, mode="template")
    tools = event_demand_agent_tools()
    result = await run.event_demand(tools, run_id="run_1", iteration=0)
    check_result(result, "event_demand", "template", "fallback")
    assert result.text.startswith(
        "Napoli–Juventus 2027 (27/08/2027): ipotesi di scenario di 45.000"
    )
    assert result.findings == [] and result.recommendations == [] and not result.requires_approval
    assert result.tool_output_ids == [m.id for m in tools.measures]
    assert result.tools_called == tools.tools_called
    assert result.data_kind == ["simulated"] and result.data_sources == ["engine.metrics v1"]
    assert "L'affluenza è un'ipotesi di scenario indicata nell'Evento." in result.assumptions
    assert backend.calls == []  # nessuna chiamata


async def test_event_demand_con_l_llm_non_riceve_i_segnali(tmp_path: Path) -> None:
    run, backend = runner(tmp_path, reply(text="Si attendono 45.000 persone, ipotesi di scenario."))
    result = await run.event_demand(event_demand_agent_tools(), run_id="run_1", iteration=0)
    check_result(result, "event_demand", "llm", "ok")
    assert result.text == "Si attendono 45.000 persone, ipotesi di scenario."
    sent = json.loads(backend.calls[0]["contents"])
    assert "signals" not in sent and sent["context"]["event"] == "Napoli–Juventus 2027"


async def test_event_demand_con_un_numero_inventato_due_volte_ripiega(tmp_path: Path) -> None:
    bad = reply(text="Si attendono 99.999 persone.")
    run, backend = runner(tmp_path, bad, bad)
    result = await run.event_demand(event_demand_agent_tools(), run_id="run_1", iteration=0)
    check_result(result, "event_demand", "template", "fallback")
    assert "99.999" not in result.text and len(backend.calls) == 2


# --- Traffic e Transit --------------------------------------------------------------------------


async def test_traffic_in_modalita_template_un_finding_per_segnale(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    tools = traffic_agent_tools()
    analysis = await run.analyse(tools, run_id="run_1", iteration=0)
    result = analysis.result
    check_result(result, "traffic", "template", "fallback")
    first, second = result.findings
    signal = tools.signals[0]
    assert (first.trigger, first.target, first.window, first.severity) == (
        "critical_intersection",
        signal.target,
        "departure",
        "critical",
    )
    assert first.evidence_ids == signal.evidence_ids and first.location == signal.location
    assert first.summary.startswith("Piazza Vittoria: incrocio con rapporto v/c 1,2")
    assert second.trigger == "saturated_path"
    assert result.requires_approval and result.tool_output_ids == [m.id for m in tools.measures]


async def test_le_raccomandazioni_prendono_dal_segnale_e_dal_catalogo(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    tools = traffic_agent_tools()
    analysis = await run.analyse(tools, run_id="run_1", iteration=0)
    first, second = analysis.result.recommendations
    assert (first.measure_type, first.target, first.window) == ("traffic_post", "1001", "departure")
    assert first.department == CATALOG.measure("traffic_post").department  # type: ignore[union-attr]
    assert first.evidence_ids == tools.signals[0].evidence_ids and first.params == {}
    assert (second.measure_type, second.department) == ("detour_signage", "traffic_control")
    assert [(c.id, c.target_label, c.severity) for c in analysis.candidates] == [
        ("c1", "Piazza Vittoria", "critical"),
        ("c2", "Riviera di Chiaia", "critical"),
    ]
    assert [c.recommendation for c in analysis.candidates] == [first, second]


async def test_con_l_llm_i_finding_sono_solo_quelli_scelti(tmp_path: Path) -> None:
    answer = reply(
        findings=[{"signal": "s2", "summary": "Le salite di Riviera di Chiaia sono sature."}],
        recommendations=[
            {"signal": "s2", "measure_type": "detour_signage", "rationale": "Deviare."}
        ],
        assumptions=["Modello statico e non calibrato."],
    )
    run, backend = runner(tmp_path, answer)
    tools = traffic_agent_tools()
    analysis = await run.analyse(tools, run_id="run_1", iteration=0)
    result = analysis.result
    check_result(result, "traffic", "llm", "ok")
    assert [f.target for f in result.findings] == [tools.signals[1].target]
    assert result.findings[0].summary == "Le salite di Riviera di Chiaia sono sature."
    assert [r.rationale for r in result.recommendations] == ["Deviare."]
    assert result.assumptions == ["Modello statico e non calibrato."]
    assert result.text == "Sintesi."
    assert [c.id for c in analysis.candidates] == ["c1"]  # numerati sulle raccomandazioni
    assert backend.calls[0]["schema"]["properties"]["findings"]["items"]["required"]


async def test_il_cambio_di_piano_porta_l_arco_da_favorire(tmp_path: Path) -> None:
    answer = reply(
        recommendations=[
            {
                "signal": "s1",
                "measure_type": "signal_plan_change",
                "rationale": "Cambiare il piano.",
            },
            {"signal": "s1", "measure_type": "traffic_post", "rationale": "Un presidio."},
        ]
    )
    run, _ = runner(tmp_path, answer)
    tools = traffic_agent_tools()
    analysis = await run.analyse(tools, run_id="run_1", iteration=0)
    plan_change, post = analysis.result.recommendations
    favored = tools.signals[0].measure_params["signal_plan_change"]["favored_edge_key"]
    assert favored and plan_change.params == {"favored_edge_key": favored}
    assert post.params == {}  # i parametri sono solo di chi li chiede


async def test_una_risposta_non_valida_e_poi_valida_e_riprovata(tmp_path: Path) -> None:
    run, backend = runner(
        tmp_path,
        reply(recommendations=[{"signal": "s1", "measure_type": "close_road", "rationale": "x"}]),
        reply(
            recommendations=[{"signal": "s1", "measure_type": "traffic_post", "rationale": "ok"}]
        ),
    )
    analysis = await run.analyse(traffic_agent_tools(), run_id="run_1", iteration=0)
    check_result(analysis.result, "traffic", "llm", "retried")
    assert "close_road" in backend.calls[1]["contents"]  # il motivo del primo rifiuto


async def test_due_risposte_non_valide_danno_il_testo_di_riserva(tmp_path: Path) -> None:
    bad = reply(findings=[{"signal": "s9", "summary": "Inventato."}])
    run, _ = runner(tmp_path, bad, bad)
    analysis = await run.analyse(traffic_agent_tools(), run_id="run_1", iteration=0)
    check_result(analysis.result, "traffic", "template", "fallback")
    assert [f.trigger for f in analysis.result.findings] == [
        "critical_intersection",
        "saturated_path",
    ]


async def test_un_servizio_che_non_risponde_da_il_testo_di_riserva(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, LlmUnavailable("nessuna rete"))
    analysis = await run.analyse(traffic_agent_tools(), run_id="run_1", iteration=0)
    check_result(analysis.result, "traffic", "template", "fallback")
    assert len(analysis.result.findings) == 2


async def test_transit_in_modalita_template(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    tools = transit_agent_tools()
    analysis = await run.analyse(tools, run_id="run_1", iteration=2)
    result = analysis.result
    assert (result.agent, result.iteration, result.data_kind) == ("transit", 2, ["estimate"])
    assert [(r.measure_type, r.target, r.department) for r in result.recommendations] == [
        ("extend_hours", "metro_line_1", "transport_control"),
        ("extend_hours", "metro_line_6", "transport_control"),
        ("crowd_control_post", "2116", "municipal_police"),
    ]
    assert [c.target_label for c in analysis.candidates] == [
        "Linea 1 della metropolitana",
        "Linea 6 della metropolitana",
        "Riviera di Chiaia",
    ]


async def test_gli_stessi_input_hanno_lo_stesso_input_hash(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    first = (await run.analyse(traffic_agent_tools(), run_id="run_1", iteration=0)).result
    again = (await run.analyse(traffic_agent_tools(), run_id="run_1", iteration=0)).result
    other = (await run.analyse(transit_agent_tools(), run_id="run_1", iteration=0)).result
    assert first.input_hash == again.input_hash != other.input_hash


async def test_all_llm_arriva_il_prompt_dell_agente_e_la_chiave_segue_il_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, backend = runner(tmp_path, reply())
    first = (await run.analyse(traffic_agent_tools(), run_id="run_1", iteration=0)).result
    assert backend.calls[0]["system"] == load_prompt("traffic").text

    prompt = load_prompt("traffic")
    edited = Prompt(prompt.name, prompt.version, prompt.text + "Una riga in più.\n")
    monkeypatch.setattr("app.agents.runner.load_prompt", lambda name: edited)
    run, _ = runner(tmp_path, reply())
    second = (await run.analyse(traffic_agent_tools(), run_id="run_1", iteration=0)).result
    assert first.input_hash != second.input_hash  # un altro prompt, un'altra chiave di cache


def tools_of(run_id: str) -> AgentTools:
    """Gli strumenti di Traffic come se il run avesse un altro id (negli id dei Measured)."""
    base = traffic_agent_tools()
    return AgentTools.model_validate_json(base.model_dump_json().replace("run_1", run_id))


async def test_due_run_identici_hanno_la_stessa_chiave_e_lo_stesso_invio(tmp_path: Path) -> None:
    """L'id del run è casuale e sta negli id dei Measured: non deve entrare nell'input dell'LLM, o
    la cache demo non servirebbe mai a un run nuovo."""
    run, backend = runner(tmp_path, reply(), reply())
    first = await run.analyse(tools_of("run_a1b2c3d4"), run_id="run_a1b2c3d4", iteration=0)
    second = await run.analyse(tools_of("run_ffff0000"), run_id="run_ffff0000", iteration=0)
    assert first.result.input_hash == second.result.input_hash
    assert len(backend.calls) == 1  # il secondo run è servito dalla cache: nessuna nuova chiamata
    assert (second.result.text_origin, second.result.validation) == ("llm_cache", "ok")
    sent = backend.calls[0]["contents"]
    assert "a1b2c3d4" not in sent and "m.run.it0.road.departure.veh_hours" in sent


async def test_i_risultati_tengono_gli_id_veri_dei_measured(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    result = (
        await run.analyse(tools_of("run_a1b2c3d4"), run_id="run_a1b2c3d4", iteration=0)
    ).result
    assert result.tool_output_ids[0] == "m.run_a1b2c3d4.it0.road.departure.veh_hours"
    assert all(e.startswith("m.run_a1b2c3d4.it0.") for f in result.findings for e in f.evidence_ids)
    assert all(
        e.startswith("m.run_a1b2c3d4.it0.") for r in result.recommendations for e in r.evidence_ids
    )


# --- Operations: piano --------------------------------------------------------------------------

RESOURCES = [
    ResourceBalance(
        department="municipal_police",
        window="departure",
        resource="patrols",
        total=6,
        used=5,
        remaining=1,
    )
]


def candidates(*severities: str) -> list[PlanCandidate]:
    return [
        PlanCandidate(
            "x",
            Recommendation(
                measure_type="traffic_post",
                target=f"10{i}",
                department="municipal_police",
                window="departure",
                rationale=f"Motivo {i}.",
                evidence_ids=[EVIDENCE],
            ),
            f"Incrocio {i}",
            severity,  # type: ignore[arg-type]
        )
        for i, severity in enumerate(severities, start=1)
    ]


async def test_il_piano_di_riserva_ordina_per_gravita(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    outcome = await run.plan(
        candidates("warning", "critical", "info"), RESOURCES, [], run_id="run_1", iteration=0
    )
    check_result(outcome.result, "operations", "template", "fallback")
    assert [c.target_label for c in outcome.chosen] == ["Incrocio 2", "Incrocio 1", "Incrocio 3"]
    assert [c.id for c in outcome.chosen] == ["c2", "c1", "c3"]  # rinumerati nell'ordine d'ingresso
    assert outcome.result.recommendations == [c.recommendation for c in outcome.chosen]
    assert outcome.result.requires_approval and outcome.result.tools_called == [
        "list_catalog",
        "get_department_resources",
    ]


async def test_il_piano_rispetta_il_tetto_della_configurazione(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template", config=config_with(plan={"max_measures": 2}))
    outcome = await run.plan(
        candidates("critical", "critical", "critical"), RESOURCES, [], run_id="run_1", iteration=0
    )
    assert [c.target_label for c in outcome.chosen] == ["Incrocio 1", "Incrocio 2"]


async def test_il_piano_dell_llm_cambia_l_ordine_e_la_motivazione(tmp_path: Path) -> None:
    answer = reply(
        plan=[
            {"candidate": "c2", "rationale": "Prima: è la più grave."},
            {"candidate": "c1", "rationale": "Poi questa."},
        ]
    )
    run, backend = runner(tmp_path, answer)
    outcome = await run.plan(
        candidates("warning", "critical"), RESOURCES, [], run_id="run_1", iteration=1
    )
    assert (outcome.result.text_origin, outcome.result.validation) == ("llm", "ok")
    assert [c.target_label for c in outcome.chosen] == ["Incrocio 2", "Incrocio 1"]
    assert [c.recommendation.rationale for c in outcome.chosen] == [
        "Prima: è la più grave.",
        "Poi questa.",
    ]
    assert outcome.chosen[0].recommendation.target == "102"  # tutto il resto resta com'era
    sent = json.loads(backend.calls[0]["contents"])
    assert [c["id"] for c in sent["candidates"]] == ["c1", "c2"] and sent[
        "max_measures"
    ] == CONFIG.plan.max_measures


async def test_un_candidato_che_non_c_e_ripiega_sul_piano_di_riserva(tmp_path: Path) -> None:
    bad = reply(plan=[{"candidate": "c9", "rationale": "x"}])
    run, _ = runner(tmp_path, bad, bad)
    outcome = await run.plan(candidates("critical"), RESOURCES, [], run_id="run_1", iteration=0)
    assert outcome.result.validation == "fallback" and len(outcome.chosen) == 1


async def test_nessun_candidato_nessun_piano(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    outcome = await run.plan([], RESOURCES, [], run_id="run_1", iteration=0)
    assert outcome.chosen == [] and not outcome.result.requires_approval
    assert outcome.result.text == "Nessuna misura da pianificare."


# --- Operations: ripianificazione ---------------------------------------------------------------

ORIGINAL = candidate("c1").recommendation
ALTERNATIVES = [
    Alternative(
        "signal_plan_change",
        "traffic_control",
        "1001",
        "Piazza Vittoria",
        {"favored_edge_key": "11-22-0"},
    ),
    Alternative("detour_signage", "traffic_control", "11-22-0,33-22-0", "Archi a monte"),
]


def rejected() -> Any:
    return make_operation(
        "act_2", state="REJECTED", reject_code="UNAVAILABLE", reject_reason="Pattuglie esaurite"
    )


async def test_la_ripianificazione_di_riserva_sceglie_la_prima_alternativa(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    outcome = await run.replan(rejected(), ORIGINAL, ALTERNATIVES, [], run_id="run_1", iteration=2)
    assert (outcome.result.iteration, outcome.result.validation) == (2, "fallback")
    assert outcome.alternative == ALTERNATIVES[0]
    recommendation = outcome.recommendation
    assert recommendation is not None
    assert (
        recommendation.measure_type,
        recommendation.target,
        recommendation.department,
        recommendation.window,
        recommendation.params,
        recommendation.evidence_ids,
    ) == (
        "signal_plan_change",
        "1001",
        "traffic_control",
        "departure",
        {"favored_edge_key": "11-22-0"},
        [EVIDENCE],  # le evidenze sono quelle della misura rifiutata
    )
    assert outcome.result.recommendations == [recommendation]
    assert outcome.result.tools_called == ["list_alternatives_for_measure", "get_request_status"]


async def test_l_llm_puo_preferire_un_altra_alternativa(tmp_path: Path) -> None:
    answer = json.dumps(
        {"text": "Meglio la segnaletica.", "choice": "a2", "rationale": "Più rapida."}
    )
    run, _ = runner(tmp_path, answer)
    outcome = await run.replan(rejected(), ORIGINAL, ALTERNATIVES, [], run_id="run_1", iteration=2)
    assert outcome.alternative == ALTERNATIVES[1]
    assert outcome.recommendation is not None
    assert outcome.recommendation.rationale == "Più rapida."
    assert outcome.recommendation.params == {}
    assert outcome.result.text == "Meglio la segnaletica." and outcome.result.text_origin == "llm"


async def test_se_nessuna_alternativa_va_bene_serve_una_decisione_umana(tmp_path: Path) -> None:
    answer = json.dumps(
        {"text": "Nessuna va bene.", "choice": None, "rationale": "Nessuna adatta."}
    )
    run, _ = runner(tmp_path, answer)
    outcome = await run.replan(rejected(), ORIGINAL, ALTERNATIVES, [], run_id="run_1", iteration=2)
    assert outcome.alternative is None and outcome.recommendation is None
    assert outcome.result.recommendations == [] and not outcome.result.requires_approval


async def test_senza_alternative_compatibili_nemmeno_il_testo_di_riserva_ne_inventa(
    tmp_path: Path,
) -> None:
    run, _ = runner(tmp_path, mode="template")
    outcome = await run.replan(rejected(), ORIGINAL, [], [], run_id="run_1", iteration=2)
    assert outcome.alternative is None and outcome.recommendation is None
    assert "serve una decisione umana" in outcome.result.text


# --- Operations: avviso -------------------------------------------------------------------------

HOURS = {"arrival": "12:00–15:00", "departure": "18:00–21:00"}


async def test_l_avviso_di_riserva_elenca_le_misure_approvate(tmp_path: Path) -> None:
    run, _ = runner(tmp_path, mode="template")
    outcome = await run.notice([make_operation("act_1", state="ACCEPTED")], [], HOURS)
    assert (outcome.text_origin, outcome.validation) == ("template", "fallback")
    assert (
        outcome.text
        == "Misure in vigore per l'evento: presidio stradale a Incrocio 1 (18:00–21:00)."
    )


async def test_l_avviso_dell_llm_riporta_gli_orari_dell_input(tmp_path: Path) -> None:
    answer = json.dumps({"text": "Presidio a Incrocio 1 dalle 18:00 alle 21:00."})
    run, backend = runner(tmp_path, answer)
    outcome = await run.notice([make_operation("act_1", state="ACCEPTED")], [], HOURS)
    assert (outcome.text_origin, outcome.validation) == ("llm", "ok")
    assert json.loads(backend.calls[0]["contents"])["accepted"][0]["hours"] == "18:00–21:00"


async def test_un_avviso_con_un_orario_inventato_ripiega(tmp_path: Path) -> None:
    bad = json.dumps({"text": "Presidio dalle 17:00."})
    run, _ = runner(tmp_path, bad, bad)
    outcome = await run.notice([make_operation("act_1", state="ACCEPTED")], [], HOURS)
    assert outcome.text_origin == "template" and "17:00" not in outcome.text
