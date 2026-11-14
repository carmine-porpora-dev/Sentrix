import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.clock import ROME
from app.data.seeds import load_seed_events
from app.db.repository import Repository
from app.models.operations import OperationRequestDraft
from app.operations.center import OperationsCenter
from app.operations.registry import DepartmentRegistry
from tests.support import make_run

T0 = datetime(2026, 11, 11, 10, 0, tzinfo=ROME)


class StepClock:
    """Un orologio che avanza di un secondo a ogni lettura: gli istanti sono distinti e ordinati."""

    def __init__(self) -> None:
        self._now = T0

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


class Sleeps:
    """Un `sleep` che non aspetta: registra i ritardi chiesti e cede il passo agli altri compiti."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)


async def settled(center: Any) -> None:
    """`center.settle()` con un limite: un difetto che lo facesse girare a vuoto è un fallimento."""
    await asyncio.wait_for(center.settle(), timeout=5)


def make_repo(tmp_path: Path, *runs: str) -> Repository:
    """Un database con i due preset (Match 2027 e Regate di settembre) e i run indicati, su
    Match 2027 (revisione 1)."""
    repo = Repository(tmp_path / "ops.sqlite")
    load_seed_events(repo)
    for run_id in runs:
        repo.add_run(make_run(run_id))
    return repo


def make_draft(**changes: Any) -> OperationRequestDraft:
    """Un presidio a un incrocio, nel deflusso, per `run_1` (i campi del server mancano)."""
    fields: dict[str, Any] = {
        "run_id": "run_1",
        "iteration": 1,
        "type": "traffic_post",
        "target": "3550591146",
        "target_label": "Incrocio Piazza Vittoria",
        "window": "departure",
        "priority": "normal",
        "simulation": True,
    }
    return OperationRequestDraft.model_validate({**fields, **changes})


def registry() -> DepartmentRegistry:
    return DepartmentRegistry.from_yaml()


def make_center(
    repo: Repository,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    departments: DepartmentRegistry | None = None,
) -> OperationsCenter:
    """Un Centro operativo di prova: orologio che avanza di un secondo a ogni lettura e un `sleep`
    che non aspetta (registra i ritardi chiesti, `Sleeps`), a meno che non se ne dia un altro."""
    return OperationsCenter(
        repo,
        departments or registry(),
        add_runs_default=4,
        clock=StepClock(),
        sleep=sleep or Sleeps(),
    )
