from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.agents import templates
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
    alternative_ids,
    analysis_input,
    notice_input,
    plan_input,
    replan_input,
    without_run_id,
)
from app.agents.prompt_loader import load_prompt
from app.agents.tools import AgentTools
from app.agents.validators import (
    parse_analysis,
    parse_event_demand,
    parse_notice,
    parse_plan,
    parse_replan,
)
from app.llm.client import LlmClient, LlmRequest
from app.models.agents import (
    AgentName,
    AgentResult,
    Finding,
    Recommendation,
    TextOrigin,
    Validation,
)
from app.models.agents_config import AgentsConfig
from app.models.api import ResourceBalance
from app.models.base import FrozenModel
from app.models.catalog import CatalogConfig
from app.models.operations import OperationRequest
from app.models.provenance import Measured
from app.operations.alternatives import Alternative

# gli strumenti di Operations sono metodi del Centro (05 2): qui solo i nomi, per il risultato
PLAN_TOOLS = ["list_catalog", "get_department_resources"]
REPLAN_TOOLS = ["list_alternatives_for_measure", "get_request_status"]


@dataclass(frozen=True)
class Analysis:
    """Il risultato di Traffic o Transit e le sue raccomandazioni pronte per il piano (nello stesso
    ordine di `result.recommendations`, con bersaglio leggibile e gravità del segnale)."""

    result: AgentResult
    candidates: list[PlanCandidate]


@dataclass(frozen=True)
class PlanOutcome:
    result: AgentResult
    chosen: list[PlanCandidate]  # in ordine di piano; la motivazione è quella del piano


@dataclass(frozen=True)
class ReplanOutcome:
    result: AgentResult
    alternative: Alternative | None  # `None`: nessuna va bene, serve una decisione umana
    recommendation: Recommendation | None


@dataclass(frozen=True)
class NoticeOutcome:
    text: str
    text_origin: TextOrigin
    validation: Validation


@dataclass(frozen=True)
class _Asked[D]:
    draft: D
    origin: TextOrigin
    validation: Validation
    key: str
    duration_ms: int


def _distinct[T](items: Sequence[T]) -> list[T]:
    return list(dict.fromkeys(items))


class AgentRunner:
    def __init__(self, llm: LlmClient, config: AgentsConfig, catalog: CatalogConfig) -> None:
        self._llm = llm
        self._config = config
        self._catalog = catalog

    async def _ask[D: FrozenModel](
        self,
        agent: str,
        prompt_name: str,
        payload: dict[str, Any],
        model: type[D],
        parse: Callable[[str, dict[str, Any], AgentsConfig], D],
        fallback: Callable[[dict[str, Any], AgentsConfig], D],
    ) -> _Asked[D]:
        prompt = load_prompt(prompt_name)
        payload = without_run_id(payload)  # la chiave di cache non dipende dall'id del run
        request = LlmRequest(
            agent=agent,
            prompt_version=prompt.label,
            system=prompt.text,
            payload=payload,
            schema=json_schema(model),
            parse=lambda raw: parse(raw, payload, self._config),
        )
        outcome = await self._llm.complete(request)
        draft = outcome.value if outcome.value is not None else fallback(payload, self._config)
        return _Asked(draft, outcome.origin, outcome.validation, outcome.key, outcome.duration_ms)

    def _result(
        self,
        agent: AgentName,
        run_id: str,
        iteration: int,
        asked: _Asked[Any],
        *,
        tools_called: Sequence[str],
        measures: Sequence[Measured],
        text: str,
        assumptions: Sequence[str] = (),
        findings: Sequence[Finding] = (),
        recommendations: Sequence[Recommendation] = (),
    ) -> AgentResult:
        return AgentResult(
            run_id=run_id,
            agent=agent,
            iteration=iteration,
            input_hash=asked.key,
            tools_called=list(tools_called),
            tool_output_ids=[m.id for m in measures],
            findings=list(findings),
            recommendations=list(recommendations),
            data_sources=_distinct([m.source for m in measures]),
            data_kind=_distinct([m.kind for m in measures]),
            assumptions=list(assumptions),
            requires_approval=bool(recommendations),
            text=text,
            text_origin=asked.origin,
            duration_ms=asked.duration_ms,
            validation=asked.validation,
        )

    # --- Event & Demand -------------------------------------------------------------------------

    async def event_demand(self, tools: AgentTools, *, run_id: str, iteration: int) -> AgentResult:
        payload = analysis_input(tools, self._catalog).payload
        payload.pop("signals")  # Event & Demand non ha criticità: solo domanda e contesto
        asked = await self._ask(
            "event_demand",
            "event_demand",
            payload,
            EventDemandDraft,
            parse_event_demand,
            templates.fallback_event_demand,
        )
        return self._result(
            "event_demand",
            run_id,
            iteration,
            asked,
            tools_called=tools.tools_called,
            measures=tools.measures,
            text=asked.draft.text,
            assumptions=asked.draft.assumptions,
        )

    # --- Traffic e Transit ----------------------------------------------------------------------

    async def analyse(self, tools: AgentTools, *, run_id: str, iteration: int) -> Analysis:
        """Traffic o Transit (`tools.agent`): finding sui segnali, raccomandazioni dal catalogo."""
        built = analysis_input(tools, self._catalog)
        asked = await self._ask(
            tools.agent,
            tools.agent,
            built.payload,
            AnalysisDraft,
            parse_analysis,
            templates.fallback_analysis,
        )
        draft = asked.draft
        findings = [
            Finding(
                summary=item.summary,
                severity=(signal := built.signals[item.signal]).severity,
                window=signal.window,
                trigger=signal.trigger,
                target=signal.target,
                evidence_ids=signal.evidence_ids,
                location=signal.location,
            )
            for item in draft.findings
        ]
        recommendations: list[Recommendation] = []
        candidates: list[PlanCandidate] = []
        for index, item in enumerate(draft.recommendations, start=1):
            signal = built.signals[item.signal]
            measure = self._catalog.measure(item.measure_type)
            if measure is None:  # i validatori lo escludono: qui non si dà per scontato
                raise ValueError(f"'{item.measure_type}' non è una misura del catalogo")
            recommendation = Recommendation(
                measure_type=item.measure_type,
                target=signal.target,
                department=measure.department,
                window=signal.window,
                params=signal.measure_params.get(item.measure_type, {}),
                rationale=item.rationale,
                evidence_ids=signal.evidence_ids,
            )
            recommendations.append(recommendation)
            candidates.append(
                PlanCandidate(
                    f"c{index}",
                    recommendation,
                    signal.target_label,
                    signal.severity,
                    signal.location,
                )
            )
        result = self._result(
            tools.agent,
            run_id,
            iteration,
            asked,
            tools_called=tools.tools_called,
            measures=tools.measures,
            text=draft.text,
            assumptions=draft.assumptions,
            findings=findings,
            recommendations=recommendations,
        )
        return Analysis(result, candidates)

    # --- Operations -----------------------------------------------------------------------------

    async def plan(
        self,
        candidates: Sequence[PlanCandidate],
        resources: Sequence[ResourceBalance],
        measures: Sequence[Measured],
        *,
        run_id: str,
        iteration: int,
    ) -> PlanOutcome:
        """PLAN: quali candidati entrano nel piano, in che ordine. I candidati si rinumerano
        (`c1`…) qualunque agente li abbia proposti: l'LLM ne vede una lista sola."""
        numbered = [replace(c, id=f"c{i}") for i, c in enumerate(candidates, start=1)]
        payload = plan_input(numbered, resources, measures, self._config.plan.max_measures)
        asked = await self._ask(
            "operations",
            "operations_plan",
            payload,
            PlanDraft,
            parse_plan,
            templates.fallback_plan,
        )
        by_id = {c.id: c for c in numbered}
        chosen = [
            replace(
                by_id[item.candidate],
                recommendation=by_id[item.candidate].recommendation.model_copy(
                    update={"rationale": item.rationale}
                ),
            )
            for item in asked.draft.plan
        ]
        result = self._result(
            "operations",
            run_id,
            iteration,
            asked,
            tools_called=PLAN_TOOLS,
            measures=measures,
            text=asked.draft.text,
            assumptions=asked.draft.assumptions,
            recommendations=[c.recommendation for c in chosen],
        )
        return PlanOutcome(result, chosen)

    async def replan(
        self,
        rejected: OperationRequest,
        original: Recommendation,
        alternatives: Sequence[Alternative],
        measures: Sequence[Measured],
        *,
        run_id: str,
        iteration: int,
    ) -> ReplanOutcome:
        """REPLAN: l'alternativa da chiedere al posto di una misura rifiutata, o nessuna.
        `alternatives` sono quelle compatibili col bersaglio, nell'ordine del catalogo e senza
        quelle già rifiutate."""
        options = alternative_ids(alternatives)
        payload = replan_input(rejected, options, measures)
        asked = await self._ask(
            "operations",
            "operations_replan",
            payload,
            ReplanDraft,
            parse_replan,
            templates.fallback_replan,
        )
        draft = asked.draft
        chosen = options[draft.choice] if draft.choice is not None else None
        recommendation = (
            Recommendation(
                measure_type=chosen.type,
                target=chosen.target,
                department=chosen.department,
                window=original.window,
                params=dict(chosen.payload),
                rationale=draft.rationale,
                evidence_ids=original.evidence_ids,
            )
            if chosen is not None
            else None
        )
        result = self._result(
            "operations",
            run_id,
            iteration,
            asked,
            tools_called=REPLAN_TOOLS,
            measures=measures,
            text=draft.text,
            recommendations=[recommendation] if recommendation is not None else [],
        )
        return ReplanOutcome(result, chosen, recommendation)

    async def notice(
        self,
        accepted: Sequence[OperationRequest],
        measures: Sequence[Measured],
        hours: Mapping[str, str],
    ) -> NoticeOutcome:
        """Fine run: l'avviso ai cittadini, con le sole misure approvate e i loro orari."""
        payload = notice_input(accepted, measures, hours)
        asked = await self._ask(
            "operations",
            "operations_notice",
            payload,
            NoticeDraft,
            parse_notice,
            templates.fallback_notice,
        )
        return NoticeOutcome(asked.draft.text, asked.origin, asked.validation)
