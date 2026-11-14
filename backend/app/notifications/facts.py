from dataclasses import dataclass

from app.db.repository import Repository
from app.models.event import Event
from app.models.operations import ACTIVE_STATES, OperationRequest
from app.models.run import Run

CLOSE_ROAD = "close_road"  # tipo di richiesta di traffic_control (04): una chiusura accettata
CITIZEN_NOTICE = "citizen_notice"


@dataclass(frozen=True)
class RunFacts:
    run: Run
    event: Event
    closed_roads: list[str]  # chiusure dell'evento (`closed`) e `close_road` accettate
    closing: list[OperationRequest]  # le `close_road` accettate
    transit_disruptions: list[str]
    notice: OperationRequest | None  # l'avviso ai cittadini accettato, se c'è

    @property
    def has_closures_or_disruptions(self) -> bool:
        """Qualcosa di chiuso o interrotto: è ciò che fa partire il messaggio WhatsApp."""
        return bool(self.closed_roads or self.transit_disruptions)

    @property
    def notice_text(self) -> str | None:
        text = self.notice.payload.get("text") if self.notice else None
        return text if isinstance(text, str) else None


def collect_run_facts(repo: Repository, run_id: str) -> RunFacts | None:
    """I fatti di un run **finito** (`DONE`); `None` se il run non c'è, non è finito o ha perso la
    revisione dell'evento."""
    run = repo.get_run(run_id)
    if run is None or run.state != "DONE":
        return None
    event = repo.get_event_revision(run.event_id, run.event_revision)
    if event is None:
        return None
    requests = repo.list_operation_requests(run_id)
    closing = [r for r in requests if r.type == CLOSE_ROAD and r.state in ACTIVE_STATES]
    closed = [c.label for c in event.closures if c.mode == "closed"]
    closed += [r.target_label for r in closing]
    notices = [r for r in requests if r.type == CITIZEN_NOTICE and r.state in ACTIVE_STATES]
    return RunFacts(
        run=run,
        event=event,
        closed_roads=closed,
        closing=closing,
        transit_disruptions=[d.label for d in event.transit_disruptions],
        notice=notices[-1] if notices else None,
    )
