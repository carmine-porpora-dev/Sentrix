import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.clock import now_rome
from app.db.repository import Repository
from app.llm.cache import cache_key, canonical_json
from app.models.agents import TextOrigin, Validation
from app.models.base import LlmMode
from app.models.llm_config import LlmConfig

logger = logging.getLogger(__name__)


# Perché si è ripiegato sui testi di riserva senza che fosse una scelta (`LlmOutcome.degraded`).
DEGRADED_REASONS = (
    "cache_miss",  # cache_only e la voce non c'è
    "cache_invalid",  # cache_only e la voce c'è ma non passa più i validatori
    "budget",  # tetto giornaliero raggiunto
    "timeout",  # nessuna risposta entro `timeout_s`
    "llm_error",  # il servizio ha risposto con un errore
    "invalid_response",  # risposta non valida anche dopo il nuovo tentativo
    "not_configured",  # `live` senza chiave o senza modello
)

RETRY_PROMPT = (
    "\n\nLa risposta precedente non era valida: {error}\n"
    "Correggi e rispondi di nuovo, solo con JSON conforme allo schema."
)


class InvalidResponse(ValueError):
    """Il testo dell'LLM non è una risposta accettabile; il messaggio dice perché (finisce nel
    prompt del nuovo tentativo, quindi non deve contenere segreti)."""


class LlmUnavailable(Exception):
    """Il servizio non ha risposto: rete, errore del servizio, chiave rifiutata."""


class LlmBackend(Protocol):
    """Chi parla davvero con il modello (Gemini; nei test uno finto)."""

    async def generate(
        self,
        *,
        model: str,
        system: str,
        contents: str,
        schema: Mapping[str, Any],
        temperature: float,
        timeout_s: float,
    ) -> str: ...


@dataclass(frozen=True)
class LlmRequest[T]:
    agent: str  # per il log
    prompt_version: str  # es. «traffic@1»: entra nella chiave della cache
    system: str  # il prompt (testo), versionato in `agents/prompts/`
    payload: Mapping[str, Any]  # l'input: gli output degli strumenti, con i loro id
    schema: Mapping[str, Any]  # lo schema JSON dell'output (entra nella chiave)
    parse: Callable[[str], T]  # testo → valore validato, o `InvalidResponse`


@dataclass(frozen=True)
class LlmOutcome[T]:
    """`value` è `None` quando bisogna usare i testi di riserva (`origin == "template"`)."""

    value: T | None
    origin: TextOrigin
    validation: Validation
    degraded: str | None  # uno di DEGRADED_REASONS; `None` se non c'è stato un guasto
    key: str
    duration_ms: int
    calls: int  # chiamate fatte al servizio


class LlmClient:
    def __init__(
        self,
        *,
        mode: LlmMode,
        model: str | None,
        daily_limit: int,
        config: LlmConfig,
        repo: Repository,
        backend: LlmBackend | None = None,
        clock: Callable[[], datetime] = now_rome,
    ) -> None:
        self._mode = mode
        self._model = model
        self._daily_limit = daily_limit
        self._config = config
        self._repo = repo
        self._backend = backend
        self._clock = clock

    @property
    def mode(self) -> LlmMode:
        return self._mode

    @property
    def model(self) -> str:
        return self._model or ""

    def key_for(self, request: LlmRequest[Any]) -> str:
        return cache_key(self.model, request.prompt_version, request.schema, request.payload)

    async def complete[T](self, request: LlmRequest[T]) -> LlmOutcome[T]:
        started = time.perf_counter()
        key = self.key_for(request)

        def done(
            value: T | None,
            origin: TextOrigin,
            validation: Validation,
            degraded: str | None = None,
            calls: int = 0,
        ) -> LlmOutcome[T]:
            elapsed = int((time.perf_counter() - started) * 1000)
            logger.info(
                "llm agent=%s mode=%s esito=%s/%s degraded=%s chiamate=%d chiave=%s ms=%d",
                request.agent,
                self._mode,
                origin,
                validation,
                degraded or "-",
                calls,
                key[:12],
                elapsed,
            )
            return LlmOutcome(value, origin, validation, degraded, key, elapsed, calls)

        if self._mode == "template":
            return done(None, "template", "fallback")

        cached = self._repo.get_llm_response(key)
        cache_problem = "cache_miss"
        if cached is not None:
            try:
                return done(request.parse(cached), "llm_cache", "ok")
            except InvalidResponse as exc:
                logger.warning("llm cache: voce %s non più valida: %s", key[:12], exc)
                cache_problem = "cache_invalid"
        if self._mode == "cache_only":
            return done(None, "template", "fallback", cache_problem)

        if not self._model or self._backend is None:
            logger.warning("llm live senza modello o senza chiave: testi di riserva")
            return done(None, "template", "fallback", "not_configured")
        return await self._call(request, key, done)

    async def _call[T](
        self,
        request: LlmRequest[T],
        key: str,
        done: Callable[..., LlmOutcome[T]],
    ) -> LlmOutcome[T]:
        assert self._backend is not None and self._model is not None  # verificato da `complete`
        contents = canonical_json(request.payload)
        calls = 0
        error = ""
        for attempt in range(self._config.retries + 1):
            day = self._clock().date().isoformat()
            if not self._repo.try_count_llm_call(day, self._daily_limit):
                return done(None, "template", "fallback", "budget", calls)
            calls += 1
            try:
                async with asyncio.timeout(self._config.timeout_s):
                    text = await self._backend.generate(
                        model=self._model,
                        system=request.system,
                        contents=contents + (RETRY_PROMPT.format(error=error) if attempt else ""),
                        schema=request.schema,
                        temperature=self._config.temperature,
                        timeout_s=self._config.timeout_s,
                    )
            except TimeoutError:
                return done(None, "template", "fallback", "timeout", calls)
            except LlmUnavailable as exc:
                logger.warning("llm %s: servizio non disponibile: %s", request.agent, exc)
                return done(None, "template", "fallback", "llm_error", calls)
            try:
                value = request.parse(text)
            except InvalidResponse as exc:
                error = str(exc)
                continue
            self._repo.put_llm_response(key, text)
            return done(value, "llm", "retried" if attempt else "ok", None, calls)
        logger.warning("llm %s: risposta non valida anche dopo il nuovo tentativo", request.agent)
        return done(None, "template", "fallback", "invalid_response", calls)
