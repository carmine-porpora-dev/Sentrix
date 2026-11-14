from typing import Literal

from pydantic import Field, model_validator

from app.models.base import FrozenModel, RefId, RomeDatetime, Slug

NotificationChannel = Literal["emergency_bulletin", "whatsapp"]
NotificationState = Literal["SENT", "DELIVERED", "ACKNOWLEDGED", "FAILED", "SKIPPED"]


class NotificationDraft(FrozenModel):
    """Ciò che serve per registrare una notifica: tutto tranne l'identificativo e l'istante, che
    aggiunge il repository."""

    run_id: RefId | None = None
    iteration: int = Field(ge=0)
    channel: NotificationChannel
    recipient_id: Slug
    recipient_label: str | None = None  # il numero WhatsApp solo mascherato (`+39 *** *** **12`)
    kind: Slug
    text: str = Field(min_length=1)
    # ciò su cui si regge il messaggio: gli `action_id` delle richieste da cui viene
    evidence_ids: list[str] = Field(default_factory=list)
    state: NotificationState
    provider_message_id: str | None = None
    error_code: Slug | None = None  # perché non è partita (`SKIPPED`, `FAILED`)
    simulation: bool

    @model_validator(mode="after")
    def _simulation_matches_channel(self) -> "NotificationDraft":
        # Il bollettino è simulato (12.1); WhatsApp è l'unica eccezione approvata: reale.
        if (self.channel == "emergency_bulletin") != self.simulation:
            raise ValueError("simulation è vero solo per il bollettino ai servizi di emergenza")
        return self


class Notification(NotificationDraft):
    id: int = Field(ge=1)
    created_at: RomeDatetime
