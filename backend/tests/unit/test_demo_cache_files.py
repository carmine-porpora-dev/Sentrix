import json
import re
from pathlib import Path

import pytest

from app.data.seeds import read_seed_events
from app.db.repository import Repository
from app.llm.cache import (
    DEFAULT_DEMO_CACHE_DIR,
    DEMO_CACHE_VERSION,
    import_demo_cache,
    read_demo_file,
)

SEED_IDS = [event.id for event in read_seed_events()]


def test_gli_eventi_seed_sono_due() -> None:
    assert sorted(SEED_IDS) == ["match_2027", "regate_sep_2026"]


@pytest.mark.parametrize("event_id", SEED_IDS)
def test_ogni_evento_seed_ha_il_suo_file_di_cache_demo(event_id: str) -> None:
    path = DEFAULT_DEMO_CACHE_DIR / f"{event_id}.json"
    assert path.is_file(), (
        f"Manca {path.name}: `cd backend && uv run python -m scripts.warm_demo_cache`"
    )
    file = read_demo_file(path)
    assert (file.version, file.event_id) == (DEMO_CACHE_VERSION, event_id)
    assert file.model.strip()


@pytest.mark.parametrize("event_id", SEED_IDS)
def test_le_voci_sono_risposte_valide_senza_doppioni(event_id: str) -> None:
    file = read_demo_file(DEFAULT_DEMO_CACHE_DIR / f"{event_id}.json")
    assert len(file.entries) >= 5  # domanda, Traffic, Transit, piano, avviso (più le sostituzioni)
    keys = [e.key for e in file.entries]
    assert len(set(keys)) == len(keys) and all(re.fullmatch(r"[0-9a-f]{64}", k) for k in keys)
    for entry in file.entries:
        response = json.loads(entry.response_json)
        assert isinstance(response, dict) and str(response.get("text", "")).strip(), entry.key[:10]


def test_la_cache_demo_si_importa_all_avvio_senza_sovrascrivere(tmp_path: Path) -> None:
    repo = Repository(tmp_path / "demo.sqlite")
    total = sum(len(read_demo_file(DEFAULT_DEMO_CACHE_DIR / f"{e}.json").entries) for e in SEED_IDS)
    assert import_demo_cache(repo) == total  # tutte nuove
    assert import_demo_cache(repo) == 0  # idempotente


def test_i_file_non_contengono_segreti() -> None:
    for event_id in SEED_IDS:
        text = (DEFAULT_DEMO_CACHE_DIR / f"{event_id}.json").read_text(encoding="utf-8")
        assert not re.search(r"AIza[0-9A-Za-z_-]{20,}|api[_-]?key", text, re.IGNORECASE)
