from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.context import AppContext
from app.api.deps import Authenticated, Ctx, require_session
from app.api.errors import data_unavailable, invalid_field, not_found, rate_limited
from app.api.openapi import errors
from app.api.ratelimit import try_acquire_all
from app.api.run_views import (
    critical_edges_export_csv,
    metrics_export_csv,
    metrics_response,
    run_export,
    run_view,
)
from app.models.api import (
    CreateRunRequest,
    CreateRunResponse,
    FeatureCollection,
    LayerName,
    MetricsResponse,
    RunExport,
    RunView,
)
from app.models.notifications import Notification, NotificationChannel
from app.models.operations import Decision
from app.models.run import Run
from app.orchestrator.service import EnginesUnavailable

router = APIRouter(prefix="/api/runs", tags=["runs"], dependencies=[Depends(require_session)])

Iteration = Annotated[int, Query(ge=0, description="0 = senza misure")]


def limit_run_creation(session: Authenticated, ctx: Ctx) -> None:
    """3 al minuto per sessione e 20 all'ora in tutto (config/api.yaml). Conta ogni tentativo
    autenticato, anche se poi la richiesta è sbagliata: è un tetto alla spesa, non alla riuscita."""
    wait = try_acquire_all(
        [(ctx.run_session_limiter, session.sid), (ctx.run_global_limiter, "*")], ctx.clock
    )
    if wait:
        raise rate_limited("Troppe analisi avviate: riprova tra poco", wait)


def _run_or_404(ctx: AppContext, run_id: str) -> Run:
    run = ctx.repo.get_run(run_id)
    if run is None:
        raise not_found("Run non trovato")
    return run


@router.post(
    "",
    response_model=CreateRunResponse,
    status_code=202,
    dependencies=[Depends(limit_run_creation)],
    responses=errors(404, 429, 503),
)
async def create_run(body: CreateRunRequest, ctx: Ctx) -> CreateRunResponse:
    event = ctx.repo.get_event(body.event_id)
    if event is None:
        raise not_found("Evento non trovato")
    try:
        run = await ctx.runs.start(event, body.attendance_level, manual=body.manual_response)
    except EnginesUnavailable as exc:
        raise data_unavailable("ENGINES_UNAVAILABLE", exc) from exc
    return CreateRunResponse(run_id=run.id)


@router.get("", response_model=list[Run])
def list_runs(ctx: Ctx, event_id: str | None = None) -> list[Run]:
    return ctx.repo.list_runs(event_id)


@router.get("/{run_id}", response_model=RunView, responses=errors(404))
def get_run(run_id: str, ctx: Ctx) -> RunView:
    """Solo letture dal database (polling a 1 s): stati attraversati, agenti, piano, richieste."""
    return run_view(ctx.repo, _run_or_404(ctx, run_id))


def _computed_iteration(ctx: Ctx, run: Run, iteration: int) -> None:
    """404 finché l'iterazione non è calcolata, cioè finché non ha le metriche salvate: oltre
    `run.iteration` non ce ne sono, e la 0 non le ha per tutta l'analisi (come una già contata
    in VERIFY ma non ancora salvata). Una risposta vuota con 200 verrebbe letta come «nessuna
    metrica» e tenuta così: chi legge riprova dopo un 404."""
    if not ctx.repo.has_metrics(run.id, iteration):
        raise not_found(f"L'iterazione {iteration} non è ancora calcolata")


@router.get("/{run_id}/metrics", response_model=MetricsResponse, responses=errors(404))
def run_metrics(run_id: str, iteration: Iteration, ctx: Ctx) -> MetricsResponse:
    run = _run_or_404(ctx, run_id)
    _computed_iteration(ctx, run, iteration)
    return metrics_response(ctx.repo, run, iteration)


@router.get("/{run_id}/layers/{layer}", response_model=FeatureCollection, responses=errors(404))
def run_layer(run_id: str, layer: LayerName, iteration: Iteration, ctx: Ctx) -> FeatureCollection:
    run = _run_or_404(ctx, run_id)
    _computed_iteration(ctx, run, iteration)
    return ctx.repo.get_layer(run_id, iteration, layer) or FeatureCollection(features=[])


@router.get("/{run_id}/decisions", response_model=list[Decision], responses=errors(404))
def run_decisions(run_id: str, ctx: Ctx) -> list[Decision]:
    _run_or_404(ctx, run_id)
    return ctx.repo.list_decisions(run_id)


@router.get("/{run_id}/notifications", response_model=list[Notification], responses=errors(404))
def run_notifications(
    run_id: str, ctx: Ctx, channel: NotificationChannel | None = None
) -> list[Notification]:
    """Le notifiche in uscita del run (spech 12.4), la più vecchia per prima; con `channel` solo
    quelle del canale. Il numero di telefono è sempre mascherato."""
    _run_or_404(ctx, run_id)
    return ctx.repo.list_notifications(run_id, channel)


@router.get(
    "/{run_id}/export",
    response_model=RunExport,
    responses={
        200: {
            "description": "Pacchetto JSON (`format=json`) oppure CSV (`format=csv`)",
            "content": {"text/csv": {"schema": {"type": "string"}}},
        },
        **errors(404),
    },
)
def export_run(
    run_id: str,
    ctx: Ctx,
    format: Literal["json", "csv"] = "json",  # noqa: A002 (nome imposto da 06 5)
    what: Literal["metrics", "critical_edges"] | None = None,
) -> RunExport | Response:
    if format == "csv" and what is None:
        raise invalid_field("what", "con format=csv serve `what`", "missing")
    run = _run_or_404(ctx, run_id)
    if format == "json":
        return run_export(ctx.repo, run)
    text = (
        metrics_export_csv(ctx.repo, run)
        if what == "metrics"
        else critical_edges_export_csv(ctx.repo, run)
    )
    return Response(
        text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_{what}.csv"'},
    )
