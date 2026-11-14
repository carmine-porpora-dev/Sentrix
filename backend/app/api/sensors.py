from fastapi import APIRouter, Depends

from app.api.deps import Ctx, require_session
from app.api.errors import unavailable
from app.api.openapi import errors
from app.models.sensors import PlannedSensor

router = APIRouter(prefix="/api/sensors", tags=["sensors"], dependencies=[Depends(require_session)])


@router.get("", response_model=list[PlannedSensor], responses=errors(503))
def list_sensors(ctx: Ctx) -> list[PlannedSensor]:
    """I sensori previsti, nell'ordine di `config/sensors.yaml`. 503 se il file non si legge."""
    if ctx.sensors is None:
        # il motivo è già nel log (`load_sensors`); a chi chiede, un messaggio senza percorsi
        message = "L'elenco dei sensori previsti non è disponibile. Riprova più tardi."
        raise unavailable("DATA_UNAVAILABLE", message)
    return ctx.sensors.sensors
