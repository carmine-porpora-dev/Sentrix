import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.clock import ROME
from app.db.repository import Repository
from app.llm.client import InvalidResponse, LlmBackend, LlmClient, LlmRequest
from app.models.base import LlmMode
from app.models.llm_config import LlmConfig

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}
CONFIG = LlmConfig(timeout_s=0.2, temperature=0, retries=1)


class FakeBackend:
    """Il servizio finto: risponde con ciò che gli si dà, nell'ordine, e ricorda come è stato
    chiamato. Un elemento che è un'eccezione viene sollevato; uno `float` è un'attesa."""

    def __init__(self, *responses: str | Exception | float) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        model: str,
        system: str,
        contents: str,
        schema: Mapping[str, Any],
        temperature: float,
        timeout_s: float,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "system": system,
                "contents": contents,
                "schema": schema,
                "temperature": temperature,
                "timeout_s": timeout_s,
            }
        )
        await asyncio.sleep(0)
        item = self._responses.pop(0) if self._responses else '{"text": "ok"}'
        if isinstance(item, Exception):
            raise item
        if isinstance(item, float):
            await asyncio.sleep(item)
            return '{"text": "tardi"}'
        return item


def parse_text(raw: str) -> str:
    """Un `parse` di prova: il testo è JSON con la chiave `text`, e non può essere vuoto."""
    try:
        text = json.loads(raw)["text"]
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidResponse(f"non è un JSON con 'text': {exc}") from exc
    if not isinstance(text, str) or not text.strip():
        raise InvalidResponse("il campo 'text' è vuoto")
    return text


def make_request(payload: Mapping[str, Any] | None = None, **changes: Any) -> LlmRequest[str]:
    fields: dict[str, Any] = {
        "agent": "traffic",
        "prompt_version": "traffic@1",
        "system": "Sei il Traffic Agent.",
        "payload": {"incrocio": "Piazza Vittoria", "vc": 1.08} if payload is None else payload,
        "schema": SCHEMA,
        "parse": parse_text,
    }
    return LlmRequest(**{**fields, **changes})


def make_client(
    repo: Repository,
    backend: LlmBackend | None,
    *,
    mode: LlmMode = "live",
    model: str | None = "gemini-test",
    limit: int = 100,
    config: LlmConfig = CONFIG,
    clock: Callable[[], datetime] | None = None,
) -> LlmClient:
    return LlmClient(
        mode=mode,
        model=model,
        daily_limit=limit,
        config=config,
        repo=repo,
        backend=backend,
        clock=clock or (lambda: datetime(2026, 11, 11, 10, 0, tzinfo=ROME)),
    )


def make_llm_repo(tmp_path: Path) -> Repository:
    return Repository(tmp_path / "llm.sqlite")
