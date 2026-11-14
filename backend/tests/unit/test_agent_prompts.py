import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.agents import prompt_loader
from app.agents.drafts import (
    AnalysisDraft,
    EventDemandDraft,
    NoticeDraft,
    PlanDraft,
    ReplanDraft,
    json_schema,
)
from app.agents.payloads import (
    PlanCandidate,
    allowed_measures,
    alternative_ids,
    analysis_input,
    measure_payload,
    notice_input,
    plan_input,
    replan_input,
    signal_ids,
    without_run_id,
)
from app.agents.prompt_loader import PROMPTS_DIR, PromptError, load_prompt
from app.agents.tools import AgentTools, Signal, traffic_tools, transit_tools
from app.llm.cache import cache_key
from app.models.agents import Recommendation
from app.models.agents_config import AgentsConfig
from app.models.api import ResourceBalance
from app.models.catalog import CatalogConfig
from app.operations.alternatives import Alternative
from tests.agents_support import AS_OF, RUN, measure, road_result, transit_result
from tests.support import make_request

CATALOG = CatalogConfig.from_yaml()
CONFIG = AgentsConfig.from_yaml()
PROMPTS = [
    "event_demand",
    "traffic",
    "transit",
    "operations_plan",
    "operations_replan",
    "operations_notice",
]
FORBIDDEN = ("previsto", "prevista", "previsione", "rilevato", "misurato")


# --- prompt -------------------------------------------------------------------------------------


def test_ci_sono_i_sei_prompt_e_nessun_altro() -> None:
    assert sorted(p.stem for p in PROMPTS_DIR.glob("*.md")) == sorted(PROMPTS)


@pytest.mark.parametrize("name", PROMPTS)
def test_ogni_prompt_ha_versione_e_testo(name: str) -> None:
    prompt = load_prompt(name)
    assert prompt.name == name and prompt.version >= 1
    assert (
        prompt.text.startswith("Sei ") and "<!--" not in prompt.text
    )  # l'intestazione non è nel testo
    assert prompt.text.endswith("\n") and "Non calcolare nulla" in prompt.text


@pytest.mark.parametrize("name", PROMPTS)
def test_ogni_prompt_dice_di_non_inventare_e_di_non_usare_le_parole_vietate(name: str) -> None:
    text = load_prompt(name).text
    assert "Non usare mai le parole" in text
    for word in FORBIDDEN:
        assert f'"{word}"' in text, (
            name,
            word,
        )  # l'elenco del prompt è quello della configurazione


def test_le_parole_vietate_del_prompt_sono_quelle_della_configurazione() -> None:
    configured = set(CONFIG.language.forbidden_when_simulated)
    assert set(FORBIDDEN) <= configured


@pytest.mark.parametrize("name", ["traffic", "transit"])
def test_i_prompt_di_analisi_parlano_di_segnali_e_misure_ammesse(name: str) -> None:
    text = load_prompt(name).text
    for must in ("`signals`", "`allowed`", "`findings`", "`recommendations`", "`signal`"):
        assert must in text, (name, must)


def test_l_etichetta_ha_nome_versione_e_impronta_del_testo() -> None:
    label = load_prompt("traffic").label
    name, rest = label.split("@")
    version, fingerprint = rest.split(":")
    assert name == "traffic" and version == str(load_prompt("traffic").version)
    assert fingerprint == hashlib.sha256(load_prompt("traffic").text.encode()).hexdigest()[:8]
    assert label == load_prompt("traffic").label  # stabile


def test_cambiare_una_parola_cambia_l_etichetta_anche_senza_alzare_la_versione() -> None:
    prompt = load_prompt("traffic")
    edited = prompt_loader.Prompt(
        prompt.name, prompt.version, prompt.text.replace("Sei ", "Tu sei ", 1)
    )
    assert edited.label != prompt.label
    schema = json_schema(AnalysisDraft)
    assert cache_key("m", edited.label, schema, {}) != cache_key("m", prompt.label, schema, {})


def test_un_prompt_che_non_c_e_o_senza_intestazione_e_un_errore(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(PromptError, match="non trovato"):
        load_prompt("non_esiste")
    (tmp_path / "senza.md").write_text("Sei un agente.\n", encoding="utf-8")
    monkeypatch.setattr(prompt_loader, "PROMPTS_DIR", tmp_path)
    prompt_loader.load_prompt.cache_clear()
    try:
        with pytest.raises(PromptError, match="manca l'intestazione"):
            load_prompt("senza")
    finally:
        prompt_loader.load_prompt.cache_clear()


def test_la_versione_e_quella_dell_intestazione(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "prova.md").write_text(
        "<!-- versione: 7 -->\n\nSei un agente.\n\n", encoding="utf-8"
    )
    monkeypatch.setattr(prompt_loader, "PROMPTS_DIR", tmp_path)
    prompt_loader.load_prompt.cache_clear()
    try:
        prompt = load_prompt("prova")
    finally:
        prompt_loader.load_prompt.cache_clear()
    assert (prompt.version, prompt.text) == (7, "Sei un agente.\n")  # niente righe vuote ai bordi
    assert prompt.label.startswith("prova@7:")


def test_senza_l_id_del_run_gli_id_dei_measured_non_cambiano_tra_un_run_e_l_altro() -> None:
    payload: dict[str, Any] = {
        "measures": [{"id": "m.run_ab12cd34.it0.road.departure.veh_hours", "value": 1}],
        "signals": [{"evidence": ["m.run_ab12cd34.it2.transit.arrival.stop_load.2116"]}],
        "context": {"event": "Sulla m.cosa.it0. non agisce: testo libero"},
    }
    other = json.loads(json.dumps(payload).replace("run_ab12cd34", "run_99999999"))
    assert without_run_id(payload) == without_run_id(other)
    clean = without_run_id(payload)
    assert clean["measures"][0]["id"] == "m.run.it0.road.departure.veh_hours"
    assert clean["signals"][0]["evidence"] == ["m.run.it2.transit.arrival.stop_load.2116"]
    assert payload["measures"][0]["id"].startswith("m.run_ab12cd34")  # l'originale non cambia


# --- schemi -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model", [EventDemandDraft, AnalysisDraft, PlanDraft, ReplanDraft, NoticeDraft]
)
def test_lo_schema_e_json_semplice_senza_riferimenti(model: Any) -> None:
    schema = json_schema(model)
    text = json.dumps(schema)
    assert (
        "$ref" not in text
        and "$defs" not in text
        and '"title"' not in text
        and '"default"' not in text
    )
    assert schema["type"] == "object" and "text" in schema["properties"]
    assert schema["additionalProperties"] is False  # un campo in più è un errore, non si ignora


def test_lo_schema_di_analisi_ha_i_campi_che_il_prompt_descrive() -> None:
    schema = json_schema(AnalysisDraft)
    assert set(schema["properties"]) == {"text", "findings", "recommendations", "assumptions"}
    finding = schema["properties"]["findings"]["items"]
    assert set(finding["properties"]) == {"signal", "summary"}  # nessuna evidenza, nessun bersaglio
    recommendation = schema["properties"]["recommendations"]["items"]
    assert set(recommendation["properties"]) == {"signal", "measure_type", "rationale"}


@pytest.mark.parametrize(
    ("model", "required"),
    [
        (EventDemandDraft, {"text"}),
        (AnalysisDraft, {"text"}),
        (PlanDraft, {"text"}),
        (ReplanDraft, {"text", "rationale"}),  # la scelta può essere null, ma va motivata
        (NoticeDraft, {"text"}),
    ],
)
def test_i_campi_obbligatori_sono_solo_quelli_che_servono(model: Any, required: set[str]) -> None:
    assert set(json_schema(model)["required"]) == required


def test_la_scelta_di_replan_ammette_null_nello_schema() -> None:
    choice = json_schema(ReplanDraft)["properties"]["choice"]
    assert {"type": "null"} in choice["anyOf"] and {"type": "string"} in choice["anyOf"]


def test_il_tipo_di_misura_ha_il_formato_di_uno_slug() -> None:
    items = json_schema(AnalysisDraft)["properties"]["recommendations"]["items"]
    assert "pattern" in items["properties"]["measure_type"]


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (
            AnalysisDraft,
            {"text": "ok", "findings": [{"signal": "s1", "summary": "x", "severity": "critical"}]},
        ),
        (
            AnalysisDraft,
            {
                "text": "ok",
                "recommendations": [
                    {"signal": "s1", "measure_type": "Traffic Post", "rationale": "x"}
                ],
            },
        ),
        (AnalysisDraft, {"text": ""}),
        (AnalysisDraft, {"findings": []}),
        (ReplanDraft, {"text": "ok", "rationale": ""}),
        (NoticeDraft, {"text": "  ", "extra": 1}),
    ],
)
def test_una_bozza_con_campi_in_piu_o_vuoti_non_e_valida(model: Any, data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (AnalysisDraft, {"text": "ok", "findings": [{"signal": "", "summary": "x"}]}),
        (AnalysisDraft, {"text": "ok", "findings": [{"signal": "s1", "summary": ""}]}),
        (AnalysisDraft, {"text": "ok", "findings": [{"signal": "s1"}]}),
        (
            AnalysisDraft,
            {
                "text": "ok",
                "recommendations": [{"signal": "s1", "measure_type": "x", "rationale": ""}],
            },
        ),
        (AnalysisDraft, {"text": "ok", "recommendations": [{"signal": "s1", "measure_type": "x"}]}),
        (PlanDraft, {"text": "ok", "plan": [{"candidate": "", "rationale": "x"}]}),
        (PlanDraft, {"text": "ok", "plan": [{"candidate": "c1", "rationale": ""}]}),
        (ReplanDraft, {"text": "ok", "choice": "a1"}),  # manca la motivazione
        (ReplanDraft, {"text": "", "rationale": "x"}),
        (EventDemandDraft, {"text": ""}),
        (PlanDraft, {"text": ""}),
        (NoticeDraft, {"text": ""}),
        (AnalysisDraft, {"text": ""}),
        (NoticeDraft, {}),
    ],
)
def test_i_campi_di_testo_vuoti_o_mancanti_nelle_sottobozze_non_sono_validi(
    model: Any, data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_una_risposta_senza_findings_ne_raccomandazioni_e_valida() -> None:
    draft = AnalysisDraft.model_validate({"text": "Nessuna criticità."})
    assert draft.findings == [] and draft.recommendations == [] and draft.assumptions == []


def test_la_scelta_di_replan_puo_essere_nessuna_o_mancare() -> None:
    assert (
        ReplanDraft.model_validate({"text": "x", "choice": None, "rationale": "y"}).choice is None
    )
    assert ReplanDraft.model_validate({"text": "x", "rationale": "y"}).choice is None
    assert (
        ReplanDraft.model_validate({"text": "x", "choice": "a2", "rationale": "y"}).choice == "a2"
    )


# --- input dell'LLM ----------------------------------------------------------------------------


def traffic() -> AgentTools:
    return traffic_tools(
        {"departure": road_result()}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG
    )


def test_ogni_segnale_prende_un_id_corto_nell_ordine_degli_strumenti() -> None:
    tools = traffic()
    ids = signal_ids(tools.signals)
    assert list(ids) == ["s1", "s2"] and list(ids.values()) == tools.signals


def test_i_tipi_di_misura_ammessi_sono_quelli_del_catalogo_per_trigger_e_bersaglio() -> None:
    def signal(trigger: str, kind: Any) -> Signal:
        return Signal(
            trigger=trigger,
            target="x",
            target_kind=kind,
            target_label="X",
            window="departure",
            severity="info",
            evidence_ids=["m.r.it0.a"],
        )

    assert allowed_measures(signal("critical_intersection", "intersection"), CATALOG) == [
        "traffic_post",
        "signal_plan_change",
    ]
    assert allowed_measures(signal("saturated_path", "edges"), CATALOG) == ["detour_signage"]
    assert allowed_measures(signal("line_no_service_in_window", "route"), CATALOG) == [
        "extend_hours"
    ]
    assert allowed_measures(signal("section_overloaded", "route"), CATALOG) == [
        "extend_hours",
        "add_runs",
    ]
    assert allowed_measures(signal("stop_overloaded", "stop"), CATALOG) == ["crowd_control_post"]
    assert allowed_measures(signal("stop_overloaded_unsafe", "stop"), CATALOG) == [
        "stop_suspension"
    ]
    # un trigger giusto su un tipo di bersaglio sbagliato non è un'opzione
    assert allowed_measures(signal("critical_intersection", "stop"), CATALOG) == []
    assert allowed_measures(signal("inventato", "intersection"), CATALOG) == []


def test_l_input_di_analisi_ha_misure_segnali_e_contesto() -> None:
    tools = traffic()
    built = analysis_input(tools, CATALOG)
    payload = built.payload
    assert payload["agent"] == "traffic" and set(payload) == {
        "agent",
        "context",
        "measures",
        "signals",
    }
    assert payload["measures"][0] == {
        "id": "m.run_1.it0.road.departure.veh_hours",
        "value": 4820.0,
        "unit": "veic·h",
        "kind": "simulated",
    }
    first = payload["signals"][0]
    assert first == {
        "id": "s1",
        "trigger": "critical_intersection",
        "target": "Piazza Vittoria",
        "window": "departure",
        "severity": "critical",
        "evidence": ["m.run_1.it0.road.departure.critical_intersection.1.vc"],
        "allowed": ["traffic_post", "signal_plan_change"],
    }
    assert built.signals["s1"] is tools.signals[0]
    json.dumps(payload)  # serializzabile


def test_i_valori_si_arrotondano_a_tre_decimali_e_le_stringhe_restano() -> None:
    assert (
        measure_payload(measure(("road", "departure", "x"), 1.0779123, "rapporto"))["value"]
        == 1.078
    )
    assert (
        measure_payload(measure(("transit", "departure", "itinerary_used.z"), "a piedi", "testo"))[
            "value"
        ]
        == "a piedi"
    )
    assert measure_payload(measure(("road", "departure", "n"), 727, "n"))["value"] == 727


def test_lo_stesso_input_da_lo_stesso_testo_e_la_stessa_chiave() -> None:
    first = json.dumps(analysis_input(traffic(), CATALOG).payload, sort_keys=True)
    second = json.dumps(analysis_input(traffic(), CATALOG).payload, sort_keys=True)
    assert first == second


def test_l_input_del_trasporto_porta_gli_itinerari_nel_contesto() -> None:
    tools = transit_tools(
        {"departure": transit_result()}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG
    )
    payload = analysis_input(tools, CATALOG).payload
    assert payload["context"] == {"itineraries": {"departure:vomero": "funicolare, poi a piedi"}}
    assert {s["trigger"] for s in payload["signals"]} >= {
        "line_no_service_in_window",
        "section_overloaded",
    }


def recommendation(measure_type: str = "traffic_post") -> Recommendation:
    return Recommendation(
        measure_type=measure_type,
        target="1001",
        department="municipal_police",
        window="departure",
        rationale="Incrocio saturo.",
        evidence_ids=["m.run_1.it0.road.departure.critical_intersection.1.vc"],
    )


def test_l_input_del_piano_ha_candidati_risorse_e_tetto() -> None:
    candidates = [PlanCandidate("c1", recommendation(), "Piazza Vittoria", "critical")]
    resources = [
        ResourceBalance(
            department="municipal_police",
            window="departure",
            resource="patrols",
            total=6,
            used=5,
            remaining=1,
        )
    ]
    payload = plan_input(
        candidates, resources, [measure(("road", "departure", "veh_hours"), 1.0, "veic·h")], 6
    )
    assert payload["candidates"] == [
        {
            "id": "c1",
            "measure_type": "traffic_post",
            "department": "municipal_police",
            "target": "Piazza Vittoria",
            "window": "departure",
            "severity": "critical",
            "rationale": "Incrocio saturo.",
            "evidence": ["m.run_1.it0.road.departure.critical_intersection.1.vc"],
        }
    ]
    assert payload["resources"][0] == {
        "department": "municipal_police",
        "window": "departure",
        "resource": "patrols",
        "total": 6,
        "used": 5,
        "remaining": 1,
    }
    assert payload["max_measures"] == 6 and payload["measures"][0]["id"].endswith("veh_hours")


def test_l_input_del_replan_ha_il_rifiuto_e_le_alternative_con_id() -> None:
    rejected = make_request(
        "act_2", state="REJECTED", reject_code="UNAVAILABLE", reject_reason="Pattuglie esaurite"
    )
    alternatives = alternative_ids(
        [
            Alternative("signal_plan_change", "traffic_control", "1001", "Piazza Vittoria"),
            Alternative("detour_signage", "traffic_control", "1-2-0", "Archi a monte"),
        ]
    )
    payload = replan_input(rejected, alternatives, [])
    assert list(alternatives) == ["a1", "a2"]
    assert payload["rejected"] == {
        "measure_type": "traffic_post",
        "department": "municipal_police",
        "target": "Incrocio 1",
        "window": "departure",
        "reject_code": "UNAVAILABLE",
        "reject_reason": "Pattuglie esaurite",
    }
    assert [a["id"] for a in payload["alternatives"]] == ["a1", "a2"]
    assert payload["alternatives"][0]["measure_type"] == "signal_plan_change"


def test_l_input_dell_avviso_ha_solo_le_misure_accettate_con_i_loro_orari() -> None:
    accepted = [make_request("act_1", state="ACCEPTED")]
    payload = notice_input(accepted, [], {"arrival": "12:00–15:00", "departure": "18:00–21:00"})
    assert payload["accepted"] == [
        {
            "measure_type": "traffic_post",
            "department": "municipal_police",
            "target": "Incrocio 1",
            "window": "departure",
            "hours": "18:00–21:00",  # lo scrive il codice (Event.window_span), non l'LLM
        }
    ]
    assert set(payload) == {"accepted", "measures"}
