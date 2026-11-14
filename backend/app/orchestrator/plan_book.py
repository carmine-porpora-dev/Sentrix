from dataclasses import dataclass, field
from typing import Any

from app.agents.payloads import PlanCandidate
from app.db.repository import Repository
from app.models.run import PlanItem


@dataclass
class PlanBook:
    repo: Repository
    run_id: str
    items: dict[int, PlanItem] = field(default_factory=dict)
    meta: dict[int, PlanCandidate] = field(default_factory=dict)  # seq → candidato d'origine
    pending: list[int] = field(default_factory=list)  # gli elementi da inviare in questo giro
    replaces: dict[int, str] = field(default_factory=dict)  # seq → action_id che sostituisce
    actions: dict[int, str] = field(default_factory=dict)  # seq → action_id inviata
    refused: set[tuple[str, str]] = field(default_factory=set)  # (tipo, bersaglio) già rifiutati

    def add(self, candidate: PlanCandidate, *, status: str, note: str | None = None) -> int:
        seq = max(self.items, default=0) + 1
        item = PlanItem.model_validate(
            {"seq": seq, "recommendation": candidate.recommendation, "status": status, "note": note}
        )
        self.items[seq] = item
        self.meta[seq] = candidate
        self.repo.put_plan_item(self.run_id, item)
        return seq

    def propose(self, candidate: PlanCandidate, *, replaces: str | None = None) -> int:
        """Un elemento da inviare nel prossimo giro (`replaces`: l'azione che sostituisce)."""
        seq = self.add(candidate, status="proposed")
        self.pending.append(seq)
        if replaces is not None:
            self.replaces[seq] = replaces
        return seq

    def update(self, seq: int, **changes: Any) -> None:
        item = PlanItem.model_validate({**self.items[seq].model_dump(), **changes})
        self.items[seq] = item
        self.repo.put_plan_item(self.run_id, item)
