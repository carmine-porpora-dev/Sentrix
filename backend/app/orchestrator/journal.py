from collections.abc import Sequence
from datetime import datetime

from app.db.repository import Repository
from app.models.operations import Decision
from app.models.run import Run

ENTER = "Passo a "  # le voci del registro che segnano un cambio di stato
FAILED = "Run interrotto"


def state_transitions(decisions: Sequence[Decision]) -> list[tuple[str, datetime]]:
    """Gli stati attraversati con l'orario, dal registro decisioni."""
    return [
        (d.refs[0], d.at)
        for d in decisions
        if (d.actor == "orchestrator" and d.decision.startswith(ENTER))
        or (d.actor == "system" and d.decision == FAILED)
    ]


class Journal:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def log(
        self, run_id: str, actor: str, decision: str, rationale: str, refs: Sequence[str] = ()
    ) -> None:
        self._repo.append_decision(
            run_id=run_id, actor=actor, decision=decision, rationale=rationale, refs=list(refs)
        )

    def enter(self, run_id: str, state: str, why: str) -> Run:
        """Il run passa a `state`: lo stato nel database e la voce nel registro."""
        run = self._repo.update_run(run_id, state=state)
        self.log(run_id, "orchestrator", f"{ENTER}{state}", why, [state])
        return run

    def fail(self, run_id: str, message: str, ended_at: datetime) -> Run:
        self.log(run_id, "system", FAILED, message, ["ERROR"])
        return self._repo.update_run(run_id, state="ERROR", error=message, ended_at=ended_at)
