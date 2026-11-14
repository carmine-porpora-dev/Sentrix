from collections.abc import Callable
from typing import get_args

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.deps import Bbox, Ctx, require_session
from app.api.errors import data_unavailable, invalid_field, not_found
from app.api.openapi import errors
from app.data import map_views
from app.data.map_data import MapDataUnavailable
from app.data.paths import DataPaths
from app.models.api import FeatureCollection
from app.models.config import RailKind

router = APIRouter(tags=["network"], dependencies=[Depends(require_session)])


def _check_span(bbox: tuple[float, float, float, float], ctx: Ctx) -> None:
    """400 se il `bbox` è più grande di `network.max_span_deg`: una mappa zoomata troppo fuori non
    deve produrre una risposta di megabyte."""
    west, south, east, north = bbox
    limit = ctx.config.network.max_span_deg
    if max(east - west, north - south) > limit:
        raise invalid_field(
            "bbox", f"area troppo estesa: al massimo {limit} gradi per lato", "bbox_too_large"
        )


def _data(load: Callable[[], FeatureCollection]) -> FeatureCollection:
    try:
        return load()
    except MapDataUnavailable as exc:
        raise data_unavailable("DATA_UNAVAILABLE", exc) from exc


@router.get("/api/network/edges", response_model=FeatureCollection, responses=errors(400, 503))
def network_edges(bbox: Bbox, ctx: Ctx) -> FeatureCollection:
    """Le strade da scegliere con un clic: quelle maggiori (da `tertiary` in su) sempre, tutte le
    altre quando l'area è piccola. Una feature per strada: `edge_key` e `reverse_key` sono i due
    sensi di marcia, da chiudere insieme."""
    _check_span(bbox, ctx)
    return _data(lambda: map_views.network_edges(ctx.map_data.graph(), bbox, ctx.config.network))


@router.get("/api/transit/stops", response_model=FeatureCollection, responses=errors(400, 503))
def transit_stops(bbox: Bbox, ctx: Ctx) -> FeatureCollection:
    """Le fermate GTFS nell'area (la posizione è un dato `real`), con le linee che le servono."""
    _check_span(bbox, ctx)
    return _data(lambda: map_views.transit_stops(ctx.map_data.feed(), bbox, ctx.config.network))


@router.get("/api/transit/lines", response_model=FeatureCollection, responses=errors(503))
def transit_lines(ctx: Ctx) -> FeatureCollection:
    """Le linee di metro e funicolari, come sequenza delle fermate della corsa più lunga: un
    disegno schematico, non il tracciato dei binari."""
    return _data(
        lambda: map_views.transit_lines(
            ctx.map_data.feed(), ctx.map_data.route_classes(), get_args(RailKind)
        )
    )


@router.get(
    "/tiles/napoli.pmtiles",
    response_class=FileResponse,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "File PMTiles"},
        206: {"content": {"application/octet-stream": {}}, "description": "Intervallo richiesto"},
        **errors(404),
    },
)
def pmtiles(ctx: Ctx) -> FileResponse:
    """La mappa di base, con supporto a `Range` (il client PMTiles legge a pezzi). Richiede la
    sessione come le API: il browser la manda da solo, essendo della stessa origine."""
    path = DataPaths(ctx.settings.data_dir).pmtiles
    if not path.is_file():
        raise not_found("Mappa di base non trovata: esegui prima `make data`")
    return FileResponse(path, media_type="application/octet-stream")
