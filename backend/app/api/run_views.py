import re

from app.api.exports import CriticalEdge, critical_edges_csv, metrics_csv
from app.db.repository import Repository
from app.models.agents import AgentName, AgentResult
from app.models.api import (
    AgentState,
    AgentSummary,
    IterationMetrics,
    MetricDelta,
    MetricsResponse,
    RequestView,
    RunExport,
    RunView,
    StateTransition,
)
from app.models.config import EngineConfig
from app.models.provenance import Kind, Measured, make_measured, measured_id
from app.models.run import Run
from app.orchestrator.journal import state_transitions

AGENTS: tuple[AgentName, ...] = ("event_demand", "traffic", "transit", "operations")
# in quali stati del run un agente sta lavorando
ACTIVE_IN: dict[AgentName, frozenset[str]] = {
    "event_demand": frozenset({"ANALYZE"}),
    "traffic": frozenset({"ANALYZE"}),
    "transit": frozenset({"ANALYZE"}),
    "operations": frozenset({"PLAN", "REPLAN"}),
}
DELTA_SOURCE = "orchestrator.delta v1"
_ITERATION_ID = re.compile(r"^m\.([^.]+)\.it\d+\.(.+)$")


def _agent_state(agent: AgentName, result: AgentResult | None, run: Run) -> AgentState:
    if result is not None:
        return "done_fallback" if result.validation == "fallback" else "done"
    if run.state == "ERROR":
        return "error"
    return "running" if run.state in ACTIVE_IN[agent] else "waiting"


def agent_summaries(repo: Repository, run: Run) -> list[AgentSummary]:
    """Un riepilogo per agente, dal suo ultimo risultato."""
    latest: dict[str, AgentResult] = {}
    for written in repo.list_agent_results(run.id):
        latest[written.agent] = written
    summaries = []
    for agent in AGENTS:
        result = latest.get(agent)
        summaries.append(
            AgentSummary(
                agent=agent,
                state=_agent_state(agent, result, run),
                tools_called=result.tools_called if result else [],
                text=result.text if result else None,
                text_origin=result.text_origin if result else None,
                findings=result.findings if result else [],
            )
        )
    return summaries


def request_views(repo: Repository, run_id: str) -> list[RequestView]:
    return [
        RequestView(request=request, events=repo.list_operation_events(request.action_id))
        for request in repo.list_operation_requests(run_id)
    ]


def run_view(repo: Repository, run: Run) -> RunView:
    degraded = (
        ["llm_fallback"]
        if run.llm_mode != "template"
        and any(r.validation == "fallback" for r in repo.list_agent_results(run.id))
        else []
    )
    return RunView(
        run=run,
        timeline=[
            StateTransition(state=state, at=at)
            for state, at in state_transitions(repo.list_decisions(run.id))
        ],
        agents=agent_summaries(repo, run),
        plan=repo.list_plan_items(run.id),
        requests=request_views(repo, run.id),
        degraded=degraded,
    )


# --- metriche e delta ---------------------------------------------------------------------------


def _number(measure: Measured) -> float | None:
    value = measure.value
    return None if isinstance(value, str) else float(value)


def _delta(
    current: Measured, other: Measured | None, label: str, iteration: int
) -> Measured | None:
    """`current − other` come `Measured`: stessa unità, id `m.<run>.it<n>.delta.<label>.<resto>`
    con `n` l'iterazione richiesta (il valore può venire da una finestra copiata: il suo id porta
    l'iterazione in cui fu calcolato), inputs i due valori. `None` se uno dei due non è un numero
    o l'altro manca."""
    match = _ITERATION_ID.match(current.id)
    now, before = _number(current), None if other is None else _number(other)
    if match is None or other is None or now is None or before is None:
        return None
    kind: Kind = current.kind if current.kind == other.kind else "estimate"
    return make_measured(
        id=measured_id(
            match.group(1), f"it{iteration}", "delta", label, *match.group(2).split(".")
        ),
        value=round(now - before, 6),
        unit=current.unit,
        kind=kind,
        source=DELTA_SOURCE,
        method=f"differenza {label}: {current.id} meno {other.id}",
        inputs=[current.id, other.id],
        assumptions=list(current.assumptions),
        as_of=current.as_of,
    )


def _by_key(measures: list[Measured]) -> dict[str, Measured]:
    """Le metriche di un'iterazione per nome senza il prefisso `m.<run>.it<n>.`."""
    keyed = {}
    for measure in measures:
        match = _ITERATION_ID.match(measure.id)
        if match is not None:
            keyed[match.group(2)] = measure
    return keyed


def metrics_response(repo: Repository, run: Run, iteration: int) -> MetricsResponse:
    metrics = repo.list_metrics(run.id, iteration)
    deltas: list[MetricDelta] = []
    if iteration > 0:
        previous = _by_key(repo.list_metrics(run.id, iteration - 1))
        baseline = _by_key(repo.list_metrics(run.id, 0))
        for measure in metrics:
            match = _ITERATION_ID.match(measure.id)
            if match is None or _number(measure) is None:
                continue
            key = match.group(2)
            vs_previous = _delta(measure, previous.get(key), "prev", iteration)
            vs_baseline = _delta(measure, baseline.get(key), "base", iteration)
            if vs_previous or vs_baseline:
                deltas.append(
                    MetricDelta(
                        metric_id=measure.id, vs_previous=vs_previous, vs_baseline=vs_baseline
                    )
                )
    return MetricsResponse(run_id=run.id, iteration=iteration, metrics=metrics, deltas=deltas)


# --- esportazione -------------------------------------------------------------------------------


def _iterations(run: Run) -> range:
    return range(run.iteration + 1)


def run_export(repo: Repository, run: Run) -> RunExport:
    event = repo.get_event_revision(run.event_id, run.event_revision)
    assert event is not None  # il repository lo garantisce alla creazione del run
    return RunExport(
        event=event,
        run=run,
        plan=repo.list_plan_items(run.id),
        requests=request_views(repo, run.id),
        decisions=repo.list_decisions(run.id),
        metrics=[
            IterationMetrics(iteration=i, metrics=repo.list_metrics(run.id, i))
            for i in _iterations(run)
        ],
    )


def metrics_export_csv(repo: Repository, run: Run) -> str:
    return metrics_csv(
        (i, measure) for i in _iterations(run) for measure in repo.list_metrics(run.id, i)
    )


def critical_edges_export_csv(repo: Repository, run: Run) -> str:
    """Gli archi aperti con v/c oltre la soglia critica, per iterazione, dal v/c più alto: dal layer
    `edges_vc` salvato (le due finestre unite)."""
    threshold = EngineConfig.from_yaml().metrics.vc_critical_threshold
    rows: list[CriticalEdge] = []
    for iteration in _iterations(run):
        layer = repo.get_layer(run.id, iteration, "edges_vc")
        found = [
            CriticalEdge(
                iteration,
                str(f.properties["edge_key"]),
                str(f.properties.get("name") or ""),
                float(f.properties["vc"]),  # type: ignore[arg-type]
                float(f.properties.get("length_m") or 0.0),  # type: ignore[arg-type]
            )
            for f in (layer.features if layer else [])
            if not f.properties.get("closed")
            and isinstance(f.properties.get("vc"), int | float)
            and float(f.properties["vc"]) > threshold  # type: ignore[arg-type]
        ]
        rows += sorted(found, key=lambda e: (-e.vc, e.edge_key))
    return critical_edges_csv(rows)
