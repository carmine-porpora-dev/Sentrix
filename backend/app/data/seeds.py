import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.db.repository import EventExists, Repository
from app.models.event import Event

# <radice del repository>/seeds/events (questo file è backend/app/data/seeds.py)
DEFAULT_SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds" / "events"


class SeedError(Exception):
    """Cartella o file di seed non utilizzabile; il messaggio dice quale file e quale campo."""


@dataclass(frozen=True)
class SeedLoadResult:
    added: tuple[str, ...]  # id dei preset scritti ora nel database
    skipped: tuple[str, ...]  # id già presenti: lasciati com'erano


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # Python tiene in silenzio l'ultima di due chiavi uguali: in un file di dati è quasi sempre un
    # errore di copia e incolla (stessa trappola chiusa per engine.yaml).
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise ValueError(f"chiavi duplicate: {', '.join(duplicated)}")
    return dict(pairs)


def _read_one(path: Path) -> Event:
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, ValueError) as exc:  # JSONDecodeError e UnicodeDecodeError sono ValueError
        raise SeedError(f"{path.name}: {exc}") from exc
    try:
        event = Event.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in err['loc']) or '(radice)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise SeedError(f"{path.name}: {problems}") from exc
    if path.stem != event.id:
        raise SeedError(f"{path.name}: il file deve chiamarsi '{event.id}.json' (come l'id)")
    return event


def read_seed_events(seeds_dir: Path | None = None) -> list[Event]:
    """Legge e valida tutti i preset, in ordine di nome file. Non tocca il database."""
    directory = DEFAULT_SEEDS_DIR if seeds_dir is None else seeds_dir
    if not directory.is_dir():
        raise SeedError(f"Cartella dei seed non trovata: {directory}")
    return [_read_one(path) for path in sorted(directory.glob("*.json"))]


def load_seed_events(repo: Repository, seeds_dir: Path | None = None) -> SeedLoadResult:
    """Scrive nel database i preset che mancano (`is_seed=1`). Idempotente."""
    events = read_seed_events(seeds_dir)  # tutti validi, o nessuna scrittura
    added, skipped = [], []
    for event in events:
        try:
            repo.add_event(event, is_seed=True)
        except EventExists:
            skipped.append(event.id)
        else:
            added.append(event.id)
    return SeedLoadResult(added=tuple(added), skipped=tuple(skipped))
