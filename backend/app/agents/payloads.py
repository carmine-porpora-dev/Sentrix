import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agents.tools import AgentTools, Signal
from app.models.agents import Recommendation, Severity
from app.models.api import ResourceBalance
from app.models.catalog import CatalogConfig
from app.models.geo import GeoPoint
from app.models.operations import OperationRequest
from app.models.provenance import Measured
from app.operations.alternatives import Alternative

VALUE_DECIMALS = 3
RUN_PLACEHOLDER = "run"
_RUN_IN_ID = re.compile(r"(?<![\w.])m\.[A-Za-z0-9_-]+\.(it\d+\.)")


def without_run_id(payload: dict[str, Any]) -> dict[str, Any]:
    """Lo stesso input con `m.<run>.it<n>.…` al posto dell'id del run (`m.run.it<n>.…`).

    Gli id dei `Measured` portano l'id del run, che è casuale: senza questo, due run identici
    avrebbero input diversi, quindi chiavi di cache diverse, e la cache demo (05 1) non verrebbe
    mai usata. All'LLM l'id serve solo per distinguere i valori; gli id veri restano nei risultati
    (i finding citano le evidenze del segnale, non quelle che l'LLM vede)."""
    text = _RUN_IN_ID.sub(rf"m.{RUN_PLACEHOLDER}.\1", json.dumps(payload, ensure_ascii=False))
    restored: dict[str, Any] = json.loads(text)
    return restored


def measure_payload(measured: Measured) -> dict[str, Any]:
    value = measured.value
    return {
        "id": measured.id,
        "value": round(value, VALUE_DECIMALS) if isinstance(value, float) else value,
        "unit": measured.unit,
        "kind": measured.kind,
    }


def measures_payload(measures: Sequence[Measured]) -> list[dict[str, Any]]:
    return [measure_payload(m) for m in measures]


def allowed_measures(signal: Signal, catalog: CatalogConfig) -> list[str]:
    """I tipi di misura del catalogo che giustificano questo segnale (il suo trigger) e che agiscono
    su un bersaglio del suo tipo, nell'ordine del catalogo."""
    return [
        measure.type
        for measure in catalog.measures
        if signal.trigger in measure.triggers and measure.target_kind == signal.target_kind
    ]


def signal_ids(signals: Sequence[Signal]) -> dict[str, Signal]:
    """`s1`, `s2`… nell'ordine degli strumenti."""
    return {f"s{index}": signal for index, signal in enumerate(signals, start=1)}


@dataclass(frozen=True)
class AnalysisInput:
    payload: dict[str, Any]
    signals: dict[str, Signal]  # id corto → segnale, per ritrovare ciò che l'LLM sceglie


def analysis_input(tools: AgentTools, catalog: CatalogConfig) -> AnalysisInput:
    """L'input di Event & Demand, Traffic e Transit."""
    signals = signal_ids(tools.signals)
    payload: dict[str, Any] = {
        "agent": tools.agent,
        "context": tools.context,
        "measures": measures_payload(tools.measures),
        "signals": [
            {
                "id": identifier,
                "trigger": signal.trigger,
                "target": signal.target_label,
                "window": signal.window,
                "severity": signal.severity,
                "evidence": signal.evidence_ids,
                "allowed": allowed_measures(signal, catalog),
            }
            for identifier, signal in signals.items()
        ],
    }
    return AnalysisInput(payload=payload, signals=signals)


@dataclass(frozen=True)
class PlanCandidate:
    """Una misura proposta da Traffic o Transit, pronta per Operations."""

    id: str  # c1, c2…
    recommendation: Recommendation
    target_label: str
    severity: Severity  # quella del segnale da cui nasce: ordina il piano di riserva
    location: GeoPoint | None = None  # dove sta, per la mappa e per `target_geo` della richiesta


def plan_input(
    candidates: Sequence[PlanCandidate],
    resources: Sequence[ResourceBalance],
    measures: Sequence[Measured],
    max_measures: int,
) -> dict[str, Any]:
    return {
        "candidates": [
            {
                "id": c.id,
                "measure_type": c.recommendation.measure_type,
                "department": c.recommendation.department,
                "target": c.target_label,
                "window": c.recommendation.window,
                "severity": c.severity,
                "rationale": c.recommendation.rationale,
                "evidence": c.recommendation.evidence_ids,
            }
            for c in candidates
        ],
        "resources": [
            {
                "department": r.department,
                "window": r.window,
                "resource": r.resource,
                "total": r.total,
                "used": r.used,
                "remaining": r.remaining,
            }
            for r in resources
        ],
        "measures": measures_payload(measures),
        "max_measures": max_measures,
    }


def alternative_ids(alternatives: Sequence[Alternative]) -> dict[str, Alternative]:
    return {f"a{index}": alt for index, alt in enumerate(alternatives, start=1)}


def replan_input(
    rejected: OperationRequest, alternatives: dict[str, Alternative], measures: Sequence[Measured]
) -> dict[str, Any]:
    return {
        "rejected": {
            "measure_type": rejected.type,
            "department": rejected.department,
            "target": rejected.target_label,
            "window": rejected.window,
            "reject_code": rejected.reject_code,
            "reject_reason": rejected.reject_reason,
        },
        "alternatives": [
            {
                "id": identifier,
                "measure_type": alt.type,
                "department": alt.department,
                "target": alt.target_label,
            }
            for identifier, alt in alternatives.items()
        ],
        "measures": measures_payload(measures),
    }


def notice_input(
    accepted: Sequence[OperationRequest],
    measures: Sequence[Measured],
    hours: Mapping[str, str],
) -> dict[str, Any]:
    """`hours`: l'orario di ogni finestra («21:00–23:00», `Event.window_span`): l'avviso li riporta
    com'è, non li scrive l'LLM."""
    return {
        "accepted": [
            {
                "measure_type": request.type,
                "department": request.department,
                "target": request.target_label,
                "window": request.window,
                "hours": hours[request.window],
            }
            for request in accepted
        ],
        "measures": measures_payload(measures),
    }


# --- ciò che un testo può ripetere dell'input ----------------------------------------------------

# le stringhe dell'input con cifre che un testo può riportare così come sono: il nome di un
# bersaglio, il motivo di un rifiuto, l'orario di una finestra; più tutto `context` (date, orari,
# nomi di linee e itinerari). Gli id (`m.run_1.it0…`, `s1`) non ci sono: non sono numeri da citare.
NAME_KEYS = frozenset({"target", "reject_reason", "hours"})


@dataclass(frozen=True)
class QuotedValue:
    value: float
    unit: str | None  # None per i numeri che non sono Measured (le risorse dei dipartimenti)


@dataclass(frozen=True)
class Quotable:
    """Tutto ciò che i validatori ammettono come numero in un testo scritto dall'LLM."""

    values: tuple[QuotedValue, ...]
    names: tuple[str, ...]
    kinds: dict[str, str]  # id del Measured → kind

    @property
    def any_simulated(self) -> bool:
        return "simulated" in self.kinds.values()


def _strings(node: Any, keys: frozenset[str] | None = None, key: str | None = None) -> list[str]:
    """Le stringhe di `node` (tutte, o solo quelle sotto le chiavi `keys`)."""
    if isinstance(node, str):
        return [node] if keys is None or key in keys else []
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in _strings(v, keys, str(k))]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item, keys, key)]
    return []


def _number(node: Any) -> float | None:
    return float(node) if isinstance(node, int | float) and not isinstance(node, bool) else None


def quotable(payload: dict[str, Any]) -> Quotable:
    """Dall'input già costruito: i valori dei `Measured`, i numeri delle risorse e il tetto di
    misure, e le stringhe da cui un testo può riprendere cifre. Una funzione sola sul payload (e
    non sugli oggetti da cui nasce) perché i validatori controllino esattamente ciò che l'LLM ha
    visto."""
    values: list[QuotedValue] = []
    kinds: dict[str, str] = {}
    for item in payload.get("measures", []):
        kinds[item["id"]] = item["kind"]
        if (number := _number(item["value"])) is not None:
            values.append(QuotedValue(number, item["unit"]))
    for item in payload.get("resources", []):
        for field_name in ("total", "used", "remaining"):
            values.append(QuotedValue(float(item[field_name]), None))
    if (limit := _number(payload.get("max_measures"))) is not None:
        values.append(QuotedValue(limit, None))
    names = _strings(payload.get("context", {})) + _strings(
        {k: v for k, v in payload.items() if k != "context"}, NAME_KEYS
    )
    return Quotable(values=tuple(values), names=tuple(names), kinds=kinds)
