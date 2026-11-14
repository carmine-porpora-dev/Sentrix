from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from app.models.base import FrozenModel, RefId, RomeDatetime, Slug, Window
from app.models.geo import GeoPoint

RequestState = Literal[
    "CREATED", "SENT", "RECEIVED", "ACCEPTED", "REJECTED", "IN_PROGRESS", "COMPLETED"
]
Priority = Literal["low", "normal", "high"]
# Una richiesta è una misura in vigore se è accettata, in corso o completata (04 3): il motore la
# applica (02 6), il registro dei dipartimenti ne consuma le risorse (04 2). Un solo posto.
ACTIVE_STATES: frozenset[RequestState] = frozenset({"ACCEPTED", "IN_PROGRESS", "COMPLETED"})
# Attori fissi del log decisioni; un dipartimento virtuale compare con il proprio id (uno slug).
FIXED_ACTORS: tuple[str, ...] = (
    "system", "orchestrator", "event_demand", "traffic", "transit", "operations", "user",
)  # fmt: skip


class OperationRequestDraft(FrozenModel):
    """Ciò che serve per creare una richiesta (corpo di POST /api/vdept/{id}/requests, 06 6): tutto
    tranne l'identificativo, il dipartimento (nel percorso) e l'esito, che aggiunge
    `OperationRequest`."""

    run_id: RefId
    iteration: int = Field(ge=1)  # le richieste nascono nei dispatch: l'iterazione 0 non ha misure
    type: Slug  # tipo di misura dal catalogo
    target: str = Field(min_length=1)
    target_label: str = Field(min_length=1)
    target_geo: GeoPoint | None = None
    window: Window
    priority: Priority
    payload: dict[str, JsonValue] = Field(default_factory=dict)  # es. il testo di un avviso
    alternative_of: RefId | None = None  # action_id della richiesta rifiutata che sostituisce
    # Obbligatorio e sempre True, senza default: una richiesta che non lo dichiara è rifiutata
    # (04 3), e una non simulata è inammissibile.
    simulation: Literal[True]


class OperationRequest(OperationRequestDraft):
    action_id: RefId
    department: Slug
    state: RequestState
    reject_code: str | None = None
    reject_reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "OperationRequest":
        has_code = bool(self.reject_code and self.reject_code.strip())
        has_reason = bool(self.reject_reason and self.reject_reason.strip())
        if self.state == "REJECTED":
            if not (has_code and has_reason):
                raise ValueError("REJECTED richiede reject_code e reject_reason non vuoti")
        elif self.reject_code is not None or self.reject_reason is not None:
            raise ValueError("reject_code e reject_reason hanno senso solo con state REJECTED")
        if self.alternative_of == self.action_id:
            raise ValueError("una richiesta non può essere l'alternativa di se stessa")
        return self


class Decision(FrozenModel):
    """Voce del log decisioni, append-only (il database lo garantisce con trigger, F1-04)."""

    run_id: RefId
    seq: int = Field(ge=1)  # numero progressivo nel run
    at: RomeDatetime
    actor: Slug  # uno di FIXED_ACTORS oppure l'id di un dipartimento virtuale
    decision: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    refs: list[str] = Field(default_factory=list)  # id di Measured, action_id, stati

    @field_validator("refs")
    @classmethod
    def _refs_not_blank(cls, value: list[str]) -> list[str]:
        if any(not ref.strip() for ref in value):
            raise ValueError("i riferimenti non possono essere vuoti")
        return value
