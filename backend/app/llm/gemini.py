from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.llm.client import LlmUnavailable


@dataclass
class TokenUsage:
    """Quanto hanno consumato le chiamate riuscite, dai conteggi che il servizio stesso dà (solo
    numeri). `thoughts` sono i token di ragionamento del modello: si pagano come output."""

    calls: int = 0
    prompt: int = 0
    output: int = 0
    thoughts: int = 0

    def add(self, metadata: Any) -> None:
        self.calls += 1
        self.prompt += int(getattr(metadata, "prompt_token_count", 0) or 0)
        self.output += int(getattr(metadata, "candidates_token_count", 0) or 0)
        self.thoughts += int(getattr(metadata, "thoughts_token_count", 0) or 0)


class GeminiBackend:
    def __init__(
        self,
        api_key: str,
        *,
        thinking_level: str | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._thinking_level = thinking_level
        self._max_output_tokens = max_output_tokens
        self._client: Any = None
        self.usage = TokenUsage()

    def _sdk(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

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
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            response_json_schema=dict(schema),
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
            max_output_tokens=self._max_output_tokens,
            thinking_config=(
                types.ThinkingConfig(thinking_level=self._thinking_level.upper())
                if self._thinking_level
                else None
            ),
        )
        try:
            response = await self._sdk().aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise LlmUnavailable(
                f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip()
            ) from exc
        except OSError as exc:  # rete
            raise LlmUnavailable(type(exc).__name__) from exc
        self.usage.add(getattr(response, "usage_metadata", None))
        return response.text or ""
