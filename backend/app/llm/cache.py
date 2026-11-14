import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.data.paths import REPO_ROOT
from app.db.repository import Repository
from app.models.base import FrozenModel

DEFAULT_DEMO_CACHE_DIR = REPO_ROOT / "demo_cache"
DEMO_CACHE_VERSION = 1


class DemoCacheError(Exception):
    """Un file della cache demo non si può leggere o non ha il formato previsto."""


def canonical_json(value: Any) -> str:
    """JSON senza spazi e con le chiavi ordinate: lo stesso valore, lo stesso testo."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_key(model: str, prompt_version: str, schema: Mapping[str, Any], payload: Any) -> str:
    """sha256(modello + versione del prompt + schema + input canonico JSON), in esadecimale."""
    text = canonical_json(
        {"model": model, "prompt_version": prompt_version, "schema": schema, "input": payload}
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DemoEntry(FrozenModel):
    key: str
    response_json: str


class DemoCacheFile(FrozenModel):
    version: int
    event_id: str
    model: str  # il modello con cui le voci sono state registrate: fa parte della chiave
    entries: list[DemoEntry]


def read_demo_file(path: Path) -> DemoCacheFile:
    try:
        return DemoCacheFile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise DemoCacheError(f"Cache demo non leggibile in {path.name}: {exc}") from exc


def import_demo_cache(repo: Repository, directory: Path = DEFAULT_DEMO_CACHE_DIR) -> int:
    """Copia le voci dei file `*.json` di `directory` in `llm_cache`, senza sovrascrivere. Dice
    quante ne ha scritte. Una cartella che non c'è è una cache demo vuota (non un errore: si
    crea con `warm_demo_cache.py`)."""
    if not directory.is_dir():
        return 0
    written = 0
    for path in sorted(directory.glob("*.json")):
        file = read_demo_file(path)
        if file.version != DEMO_CACHE_VERSION:
            raise DemoCacheError(
                f"{path.name}: versione {file.version}, questa applicazione legge la "
                f"{DEMO_CACHE_VERSION}"
            )
        for entry in file.entries:
            written += repo.put_llm_response(entry.key, entry.response_json, overwrite=False)
    return written


def export_demo_cache(
    repo: Repository, *, event_id: str, model: str, keys: Iterable[str]
) -> DemoCacheFile:
    """Le voci di `llm_cache` con queste chiavi, nell'ordine in cui sono date e senza doppioni.
    Una chiave che non c'è è un errore: la cache demo non deve avere buchi in silenzio."""
    entries: list[DemoEntry] = []
    missing: list[str] = []
    for key in dict.fromkeys(keys):
        response = repo.get_llm_response(key)
        if response is None:
            missing.append(key)
        else:
            entries.append(DemoEntry(key=key, response_json=response))
    if missing:
        raise DemoCacheError(
            f"Voci non presenti in llm_cache: {', '.join(k[:12] for k in missing)}"
        )
    return DemoCacheFile(
        version=DEMO_CACHE_VERSION, event_id=event_id, model=model, entries=entries
    )
