from typing import Literal

from pydantic import Field, model_validator

from app.models.agents import Recommendation
from app.models.base import FrozenModel, LlmMode, RefId, RomeDatetime, Sha256, Slug

RunState = Literal[
    "INTAKE",
    "ANALYZE",
    "RECONCILE",
    "PLAN",
    "DISPATCH",
    "AWAIT",
    "REPLAN",
    "VERIFY",
    "DONE",
    "ERROR",
]
# «Decisione umana richiesta» non è uno stato del run: è lo stato di un PlanItem.
FINAL_STATES: frozenset[str] = frozenset({"DONE", "ERROR"})
MAX_REPLANS = 3  # massimo 3 ripianificazioni (spech 2.1, 05)

AttendanceLevel = Literal["low", "mid", "high"]  # livello di affluenza usato dal run

PlanStatus = Literal[
    "proposed", "accepted", "rejected", "replaced", "human_decision_required", "discarded"
]
# Stati di un elemento di piano che hanno già una richiesta inviata (e quindi un action_id).
SENT_STATUSES: frozenset[str] = frozenset({"accepted", "rejected", "replaced"})


class PlanItem(FrozenModel):
    seq: int = Field(ge=1)
    recommendation: Recommendation
    action_id: RefId | None = None  # la richiesta inviata, se inviata
    status: PlanStatus
    replaced_by: int | None = Field(default=None, ge=1)  # seq dell'alternativa
    note: str | None = None  # es. motivo dello scarto in RECONCILE

    @model_validator(mode="after")
    def _consistent(self) -> "PlanItem":
        if self.status in SENT_STATUSES and self.action_id is None:
            raise ValueError(
                f"con status '{self.status}' serve l'action_id della richiesta inviata"
            )
        if self.status in ("proposed", "discarded") and self.action_id is not None:
            raise ValueError(f"con status '{self.status}' la richiesta non è stata inviata")
        if self.status == "replaced":
            if self.replaced_by is None or self.replaced_by == self.seq:
                raise ValueError("con status 'replaced' serve replaced_by, diverso da seq")
        elif self.replaced_by is not None:
            raise ValueError("replaced_by ha senso solo con status 'replaced'")
        if self.status == "discarded" and not (self.note and self.note.strip()):
            raise ValueError("uno scarto va motivato: serve la nota")
        return self


class Run(FrozenModel):
    id: RefId
    event_id: Slug
    event_revision: int = Field(ge=1)
    attendance_level: AttendanceLevel
    state: RunState
    iteration: int = Field(ge=0)  # 0 = senza misure
    replans: int = Field(ge=0, le=MAX_REPLANS)
    started_at: RomeDatetime
    ended_at: RomeDatetime | None = None
    # Hash di engine.yaml + catalog.yaml + departments.yaml + evento.
    params_hash: Sha256
    # Nessun default qui: il seed è in engine.yaml (unica fonte), chi crea il run lo copia da lì.
    seed: int = Field(ge=0)
    llm_mode: LlmMode
    error: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "Run":
        finished = self.state in FINAL_STATES
        if finished != (self.ended_at is not None):
            raise ValueError("ended_at è valorizzato se e solo se il run è DONE o ERROR")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at non può precedere started_at")
        has_error = bool(self.error and self.error.strip())
        if (self.state == "ERROR") != has_error:
            raise ValueError("error è valorizzato se e solo se lo stato è ERROR")
        return self
