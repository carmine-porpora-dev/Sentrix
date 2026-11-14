import re
from pathlib import Path

import pytest

from app.data.seeds import read_seed_events

APP = Path(__file__).resolve().parents[2] / "app"
SEED_IDS = [event.id for event in read_seed_events()]
COMPARES_EVENT = re.compile(
    r"\bevent(?:_id)?\s*(?:\.\s*(?:id|name|slug)\s*)?(?:==|!=|\bin\b)\s*[\"'(\[]"
)
SOURCES = sorted(APP.rglob("*.py"))


def code_lines(path: Path) -> list[tuple[int, str]]:
    """Le righe di codice, senza docstring né commenti (lì un esempio con un id va bene)."""
    lines, in_doc = [], False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if text.count('"""') == 1:
            in_doc = not in_doc
            continue
        if in_doc or text.startswith("#") or (text.startswith('"""') and text.endswith('"""')):
            continue
        lines.append((number, raw.split("  #")[0]))
    return lines


def test_ci_sono_i_sorgenti_e_i_preset_da_cercare() -> None:
    assert len(SOURCES) > 50 and len(SEED_IDS) == 2


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(APP)))
def test_il_codice_non_nomina_un_evento_seed_ne_confronta_l_evento(path: Path) -> None:
    for number, line in code_lines(path):
        for seed_id in SEED_IDS:
            assert seed_id not in line, f"{path.name}:{number} nomina l'evento '{seed_id}'"
        assert not COMPARES_EVENT.search(line), (
            f"{path.name}:{number} confronta l'Evento: {line.strip()}"
        )
