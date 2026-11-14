import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).with_name("prompts")
_HEADER = re.compile(r"\A<!--\s*versione:\s*(\d+)\s*-->[ \t]*\n")
FINGERPRINT_LENGTH = 8


class PromptError(Exception):
    """Un prompt che non c'è o non ha la sua intestazione di versione."""


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str  # senza l'intestazione

    @property
    def label(self) -> str:
        """`nome@versione:impronta`, la «versione del prompt» della chiave della cache."""
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        return f"{self.name}@{self.version}:{digest[:FINGERPRINT_LENGTH]}"


@cache
def load_prompt(name: str) -> Prompt:
    path = PROMPTS_DIR / f"{name}.md"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"Prompt '{name}' non trovato in {PROMPTS_DIR}") from exc
    header = _HEADER.match(raw)
    if header is None:
        raise PromptError(f"{path.name}: manca l'intestazione «<!-- versione: N -->»")
    return Prompt(name=name, version=int(header.group(1)), text=raw[header.end() :].strip() + "\n")
