from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header

from app.api.deps import Ctx, require_session
from app.models.api import LiveFlowResponse

router = APIRouter(prefix="/api/live", tags=["live"], dependencies=[Depends(require_session)])


@router.get("/flow", response_model=LiveFlowResponse)
async def live_flow(
    ctx: Ctx,
    x_view: Annotated[
        Literal["live"] | None,
        Header(
            description="`live` solo dalla vista LIVE: è l'unico caso in cui si può chiamare TomTom"
        ),
    ] = None,
) -> LiveFlowResponse:
    return await ctx.live.flow(live_view=x_view == "live")
