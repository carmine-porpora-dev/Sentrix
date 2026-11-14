from typing import Any

import pytest
from pydantic import ValidationError

from app.models.agents import AgentResult, Finding, Recommendation
from tests.support import DELETE, mutated

EVIDENCE = "m.run42.it1.road.critical_intersection.vc"
EVIDENCE_2 = "m.run42.it1.od.bagnoli_centrale.time"
HASH = "a" * 64


def finding() -> dict[str, Any]:
    return {
        "summary": "Incrocio critico a piazza Vittoria nella fascia di arrivo",
        "severity": "critical",
        "window": "arrival",
        "trigger": "critical_intersection",
        "target": "node_123",
        "evidence_ids": [EVIDENCE],
        "location": {"lat": 40.8345, "lon": 14.2440, "label": "Piazza Vittoria"},
    }


def recommendation() -> dict[str, Any]:
    return {
        "measure_type": "traffic_post",
        "target": "node_123",
        "department": "municipal_police",
        "window": "arrival",
        "params": {"n": 2, "until": "23:30", "tags": ["a", "b"], "extra": {"x": 1.5, "y": None}},
        "rationale": "Rapporto v/c oltre la soglia critica",
        "evidence_ids": [EVIDENCE, EVIDENCE_2],
    }


def agent_result() -> dict[str, Any]:
    return {
        "run_id": "run42",
        "agent": "traffic",
        "iteration": 0,
        "input_hash": HASH,
        "tools_called": ["road.metrics"],
        "tool_output_ids": [EVIDENCE],
        "findings": [finding()],
        "recommendations": [recommendation()],
        "data_sources": ["osm 2026-11-07"],
        "data_kind": ["simulated"],
        "assumptions": ["traffico di fondo a quota fissa"],
        "requires_approval": False,
        "text": "Un incrocio supera la soglia critica.",
        "text_origin": "llm",
        "duration_ms": 1850,
        "validation": "ok",
    }


def error_text(model: Any, data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        model.model_validate(data)
    return str(info.value)


# --- Finding -------------------------------------------------------------------------------


def test_finding_valido_e_andata_e_ritorno_json() -> None:
    f = Finding.model_validate(finding())
    assert (f.severity, f.window, f.trigger, f.target) == (
        "critical",
        "arrival",
        "critical_intersection",
        "node_123",
    )
    assert f.location is not None and f.location.label == "Piazza Vittoria"
    assert Finding.model_validate_json(f.model_dump_json()) == f
    minimal = {k: v for k, v in finding().items() if k not in ("target", "location")}
    assert Finding.model_validate(minimal).target is None


FINDING_CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    ("nessuna evidenza", ("evidence_ids",), [], "at least 1 item"),
    (
        "evidenza che non è un id Measured",
        ("evidence_ids",),
        ["il numero è 42"],
        "String should match pattern",
    ),
    (
        "evidenza senza prefisso m.",
        ("evidence_ids",),
        ["run42.it1.x"],
        "String should match pattern",
    ),
    ("evidenze duplicate", ("evidence_ids",), [EVIDENCE, EVIDENCE], "voci duplicate"),
    ("manca il campo evidenze", ("evidence_ids",), DELETE, "Field required"),
    ("sintesi vuota", ("summary",), "", "at least 1 character"),
    ("gravità sconosciuta", ("severity",), "grave", "severity"),
    ("finestra sconosciuta", ("window",), "both", "window"),
    (
        "trigger non è uno slug",
        ("trigger",),
        "Critical Intersection",
        "String should match pattern",
    ),
    ("posizione fuori range", ("location", "lat"), 91, "less than or equal to 90"),
    ("chiave sconosciuta", ("colore",), "rosso", "Extra inputs are not permitted"),
]


@pytest.mark.parametrize(
    ("name", "path", "value", "fragment"), FINDING_CASES, ids=[c[0] for c in FINDING_CASES]
)
def test_finding_non_valido(
    name: str, path: tuple[str | int, ...], value: Any, fragment: str
) -> None:
    assert fragment in error_text(Finding, mutated(finding(), path, value)), name


# --- Recommendation -----------------------------------------------------------------------


def test_recommendation_valida_con_parametri_json() -> None:
    r = Recommendation.model_validate(recommendation())
    assert r.params == {
        "n": 2,
        "until": "23:30",
        "tags": ["a", "b"],
        "extra": {"x": 1.5, "y": None},
    }
    assert r.evidence_ids == [EVIDENCE, EVIDENCE_2]
    assert Recommendation.model_validate_json(r.model_dump_json()) == r
    assert (
        Recommendation.model_validate(
            {k: v for k, v in recommendation().items() if k != "params"}
        ).params
        == {}
    )


def test_i_default_dei_parametri_non_sono_condivisi() -> None:
    base = {k: v for k, v in recommendation().items() if k != "params"}
    a, b = Recommendation.model_validate(base), Recommendation.model_validate(base)
    assert a.params is not b.params


REC_CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    ("nessuna evidenza", ("evidence_ids",), [], "at least 1 item"),
    ("evidenza malformata", ("evidence_ids",), ["xyz"], "String should match pattern"),
    ("evidenze duplicate", ("evidence_ids",), [EVIDENCE, EVIDENCE], "voci duplicate"),
    ("motivazione vuota", ("rationale",), "", "at least 1 character"),
    ("misura non è uno slug", ("measure_type",), "Posto di blocco", "String should match pattern"),
    (
        "dipartimento non è uno slug",
        ("department",),
        "Polizia Municipale",
        "String should match pattern",
    ),
    ("bersaglio vuoto", ("target",), "", "at least 1 character"),
    ("finestra sconosciuta", ("window",), "night", "window"),
    ("parametri non JSON", ("params",), {"x": {1, 2}}, "params"),
    ("parametri non è un oggetto", ("params",), [1, 2], "params"),
]


@pytest.mark.parametrize(
    ("name", "path", "value", "fragment"), REC_CASES, ids=[c[0] for c in REC_CASES]
)
def test_recommendation_non_valida(
    name: str, path: tuple[str | int, ...], value: Any, fragment: str
) -> None:
    assert fragment in error_text(Recommendation, mutated(recommendation(), path, value)), name


# --- AgentResult --------------------------------------------------------------------------


def test_agent_result_valido() -> None:
    r = AgentResult.model_validate(agent_result())
    assert (r.agent, r.iteration, r.validation, r.text_origin) == ("traffic", 0, "ok", "llm")
    assert r.findings[0].trigger == "critical_intersection" and r.data_kind == ["simulated"]
    assert AgentResult.model_validate_json(r.model_dump_json()) == r


def test_i_quattro_agenti_e_i_tre_kind() -> None:
    for agent in ("event_demand", "traffic", "transit", "operations"):
        assert AgentResult.model_validate(mutated(agent_result(), ("agent",), agent)).agent == agent
    data = mutated(agent_result(), ("data_kind",), ["real", "estimate", "simulated"])
    assert AgentResult.model_validate(data).data_kind == ["real", "estimate", "simulated"]


def test_durata_zero_e_valida() -> None:
    # Un risultato in cache o da template può durare 0 ms.
    assert AgentResult.model_validate(mutated(agent_result(), ("duration_ms",), 0)).duration_ms == 0


def test_un_risultato_senza_trovati_ne_raccomandazioni_e_valido() -> None:
    data = mutated(mutated(agent_result(), ("findings",), []), ("recommendations",), [])
    assert AgentResult.model_validate(data).findings == []


AGENT_CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    ("agente sconosciuto", ("agent",), "oracolo", "agent"),
    ("iterazione negativa", ("iteration",), -1, "greater than or equal to 0"),
    ("durata negativa", ("duration_ms",), -5, "greater than or equal to 0"),
    ("testo vuoto", ("text",), "", "at least 1 character"),
    ("hash corto", ("input_hash",), "abc", "String should match pattern"),
    ("hash in maiuscolo", ("input_hash",), "A" * 64, "String should match pattern"),
    ("hash non esadecimale", ("input_hash",), "g" * 64, "String should match pattern"),
    ("kind sconosciuto", ("data_kind",), ["previsione"], "data_kind"),
    ("origine del testo sconosciuta", ("text_origin",), "oracolo", "text_origin"),
    ("validazione sconosciuta", ("validation",), "forse", "validation"),
    ("run_id con un punto", ("run_id",), "run.42", "String should match pattern"),
    ("trovato non valido dentro l'elenco", ("findings", 0, "evidence_ids"), [], "at least 1 item"),
    ("manca requires_approval", ("requires_approval",), DELETE, "Field required"),
    ("chiave sconosciuta", ("colore",), "rosso", "Extra inputs are not permitted"),
]


@pytest.mark.parametrize(
    ("name", "path", "value", "fragment"), AGENT_CASES, ids=[c[0] for c in AGENT_CASES]
)
def test_agent_result_non_valido(
    name: str, path: tuple[str | int, ...], value: Any, fragment: str
) -> None:
    assert fragment in error_text(AgentResult, mutated(agent_result(), path, value)), name


def test_errore_annidato_con_il_percorso_giusto() -> None:
    with pytest.raises(ValidationError) as info:
        AgentResult.model_validate(
            mutated(agent_result(), ("recommendations", 0, "evidence_ids"), [])
        )
    assert [tuple(e["loc"]) for e in info.value.errors()] == [
        ("recommendations", 0, "evidence_ids")
    ]


@pytest.mark.parametrize(
    ("validation", "origin", "ok"),
    [
        ("fallback", "template", True),
        ("fallback", "llm", False),
        ("fallback", "llm_cache", False),
        ("retried", "llm", True),
        ("retried", "llm_cache", True),
        ("retried", "template", False),
        ("ok", "template", True),  # LLM_MODE=template: nessun LLM, nessun problema
        ("ok", "llm", True),
        ("ok", "llm_cache", True),
    ],
)
def test_coerenza_tra_validazione_e_origine_del_testo(
    validation: str, origin: str, ok: bool
) -> None:
    data = mutated(mutated(agent_result(), ("validation",), validation), ("text_origin",), origin)
    if ok:
        assert AgentResult.model_validate(data).validation == validation
    else:
        assert "validation" in error_text(AgentResult, data)


def test_immutabili() -> None:
    r = AgentResult.model_validate(agent_result())
    with pytest.raises(ValidationError, match="frozen"):
        r.text = "altro"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        r.findings[0].summary = "altro"  # type: ignore[misc]
