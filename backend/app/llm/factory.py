import os
from collections.abc import Mapping

from app.db.repository import Repository
from app.llm.client import LlmClient
from app.llm.gemini import GeminiBackend
from app.models.llm_config import LlmConfig
from app.settings import Settings


def gemini_backend(api_key: str, config: LlmConfig) -> GeminiBackend:
    """L'adattatore con il ragionamento e il tetto di risposta di `config/llm.yaml`."""
    return GeminiBackend(
        api_key,
        thinking_level=config.thinking_level,
        max_output_tokens=config.max_output_tokens,
    )


def build_llm_client(
    settings: Settings,
    repo: Repository,
    config: LlmConfig | None = None,
    environ: Mapping[str, str] | None = None,
) -> LlmClient:
    """Il servizio si costruisce solo in `live` e solo con la chiave: negli altri casi non c'è
    nessun modo di chiamarlo, per errore o per distrazione. La chiave si legge qui, dall'ambiente,
    e finisce solo nell'adattatore: le `Settings` non la conservano."""
    key = (os.environ if environ is None else environ).get("GEMINI_API_KEY", "").strip()
    config = config or LlmConfig.from_yaml()
    backend = gemini_backend(key, config) if settings.llm_mode == "live" and key else None
    return LlmClient(
        mode=settings.llm_mode,
        model=settings.gemini_model,
        daily_limit=settings.llm_daily_call_limit,
        config=config,
        repo=repo,
        backend=backend,
    )
