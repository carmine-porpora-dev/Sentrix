from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from app.models.base import FrozenModel, RefId, Sha256, Slug, Window
from app.models.geo import GeoPoint
from app.models.provenance import Kind, MeasuredId

Severity = Literal["info", "warning", "critical"]
AgentName = Literal["event_demand", "traffic", "transit", "operations"]
TextOrigin = Literal["llm", "llm_cache", "template"]
Validation = Literal["ok", "retried", "fallback"]


def _unique(values: list[str], what: str) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError(f"{what}: voci duplicate")
    return values


class Finding(FrozenModel):
    summary: str = Field(min_length=1)
    severity: Severity
    window: Window
    trigger: Slug  # tipo di criticità: un trigger di catalog.yaml (es. critical_intersection)
    target: str | None = None  # id di incrocio/arco/linea/fermata
    evidence_ids: list[MeasuredId] = Field(min_length=1)  # obbligatorie, almeno una
    location: GeoPoint | None = None

    @field_validator("evidence_ids")
    @classmethod
    def _unique_evidence(cls, value: list[str]) -> list[str]:
        return _unique(value, "evidence_ids")


class Recommendation(FrozenModel):
    measure_type: Slug  # una misura di catalog.yaml
    target: str = Field(min_length=1)  # id di incrocio/arco/linea/fermata
    department: Slug  # id del dipartimento virtuale
    window: Window
    params: dict[str, JsonValue] = Field(default_factory=dict)  # es. {"until": "23:30"}, {"n": 4}
    rationale: str = Field(min_length=1)
    evidence_ids: list[MeasuredId] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def _unique_evidence(cls, value: list[str]) -> list[str]:
        return _unique(value, "evidence_ids")


class AgentResult(FrozenModel):
    run_id: RefId
    agent: AgentName
    iteration: int = Field(ge=0)  # 0 = senza misure
    input_hash: Sha256  # impronta degli input: chiave della cache LLM
    tools_called: list[str]
    tool_output_ids: list[str]
    findings: list[Finding]
    recommendations: list[Recommendation]
    data_sources: list[str]
    data_kind: list[Kind]
    assumptions: list[str]
    requires_approval: bool
    text: str = Field(min_length=1)  # sintesi leggibile (LLM o template)
    text_origin: TextOrigin
    duration_ms: int = Field(ge=0)
    validation: Validation

    @model_validator(mode="after")
    def _origin_matches_validation(self) -> "AgentResult":
        # Output LLM non valido → un retry → testo template (spech 6.3): il fallback è sempre
        # template, e un retry riuscito produce un testo che viene dall'LLM.
        if self.validation == "fallback" and self.text_origin != "template":
            raise ValueError("validation 'fallback' richiede text_origin 'template'")
        if self.validation == "retried" and self.text_origin == "template":
            raise ValueError("validation 'retried' non può avere un testo 'template'")
        return self
