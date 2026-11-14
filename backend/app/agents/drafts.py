from typing import Any

from pydantic import Field

from app.models.base import FrozenModel, Slug


class FindingDraft(FrozenModel):
    signal: str = Field(min_length=1, description="Id di un segnale dell'input (es. s1)")
    summary: str = Field(min_length=1, description="Una frase che interpreta il segnale")


class RecommendationDraft(FrozenModel):
    signal: str = Field(min_length=1, description="Id del segnale che giustifica la misura")
    measure_type: Slug = Field(description="Un tipo tra quelli `allowed` di quel segnale")
    rationale: str = Field(min_length=1, description="Perché questa misura, in una frase")


class EventDemandDraft(FrozenModel):
    text: str = Field(min_length=1, description="Sintesi della domanda e delle aree di impatto")
    assumptions: list[str] = Field(default_factory=list)


class AnalysisDraft(FrozenModel):
    """Traffic e Transit: finding sulle criticità e raccomandazioni dal catalogo."""

    text: str = Field(min_length=1, description="Sintesi in due o tre frasi")
    findings: list[FindingDraft] = Field(default_factory=list)
    recommendations: list[RecommendationDraft] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class PlanChoice(FrozenModel):
    candidate: str = Field(min_length=1, description="Id di una misura candidata (es. c1)")
    rationale: str = Field(min_length=1, description="Perché sta a questo posto del piano")


class PlanDraft(FrozenModel):
    """Operations, PLAN: quali misure candidate entrano nel piano, in che ordine."""

    text: str = Field(min_length=1, description="Il piano in due o tre frasi")
    plan: list[PlanChoice] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ReplanDraft(FrozenModel):
    """Operations, REPLAN: quale alternativa chiedere al posto di una misura rifiutata."""

    text: str = Field(min_length=1)
    choice: str | None = Field(
        default=None, description="Id dell'alternativa scelta (es. a1), o null se nessuna va bene"
    )
    rationale: str = Field(min_length=1)


class NoticeDraft(FrozenModel):
    """Operations, fine run: l'avviso ai cittadini, che cita solo misure approvate."""

    text: str = Field(min_length=1, description="L'avviso, in italiano semplice")


def json_schema(model: type[FrozenModel]) -> dict[str, Any]:
    """Lo schema JSON di una bozza, per `response_json_schema` di Gemini: senza `$ref` né `$defs` (i
    riferimenti si risolvono sul posto), senza `title` e senza `default` (rumore che non serve al
    modello). Ordine e contenuto stabili: lo schema entra nella chiave della cache."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = str(node["$ref"]).rsplit("/", 1)[-1]
                return resolve(definitions[name])
            return {k: resolve(v) for k, v in node.items() if k not in ("title", "default")}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved
