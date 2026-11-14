import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.llm.client import LlmUnavailable
from app.llm.factory import build_llm_client, gemini_backend
from app.llm.gemini import GeminiBackend
from app.models.llm_config import MAX_TEMPERATURE, LlmConfig
from app.settings import (
    DEFAULT_LLM_DAILY_CALL_LIMIT,
    DEFAULT_LLM_MODE,
    Settings,
    SettingsError,
)
from tests.llm_support import make_llm_repo

# --- impostazioni --------------------------------------------------------------------------


def test_senza_variabili_non_si_chiama_nessun_servizio() -> None:
    settings = Settings.from_env({})
    assert settings.llm_mode == DEFAULT_LLM_MODE == "template"
    assert settings.llm_daily_call_limit == DEFAULT_LLM_DAILY_CALL_LIMIT == 300
    assert settings.gemini_model is None


def test_variabili_llm_impostate() -> None:
    settings = Settings.from_env(
        {
            "LLM_MODE": "cache_only",
            "GEMINI_MODEL": "un-modello",
            "GEMINI_API_KEY": "fake-gemini",
            "LLM_DAILY_CALL_LIMIT": "50",
        }
    )
    assert (settings.llm_mode, settings.gemini_model, settings.llm_daily_call_limit) == (
        "cache_only",
        "un-modello",
        50,
    )
    assert (
        settings.gemini_key_present
    )  # la chiave non è nelle impostazioni: solo il fatto che ci sia


@pytest.mark.parametrize("mode", ["live", "cache_only", "template"])
def test_le_tre_modalita(mode: str) -> None:
    assert Settings.from_env({"LLM_MODE": mode}).llm_mode == mode


@pytest.mark.parametrize("value", ["Live", "cache", "off", "true"])
def test_una_modalita_non_ammessa_e_un_errore(value: str) -> None:
    with pytest.raises(SettingsError, match=f"LLM_MODE='{value}' non ammesso"):
        Settings.from_env({"LLM_MODE": value})


def test_un_valore_vuoto_vale_il_default() -> None:
    settings = Settings.from_env(
        {"LLM_MODE": "  ", "LLM_DAILY_CALL_LIMIT": "", "GEMINI_MODEL": " "}
    )
    assert (settings.llm_mode, settings.llm_daily_call_limit) == ("template", 300)
    assert settings.gemini_model is None


@pytest.mark.parametrize("value", ["tanti", "1.5", "-3"])
def test_un_tetto_non_valido_e_un_errore(value: str) -> None:
    with pytest.raises(SettingsError, match="LLM_DAILY_CALL_LIMIT"):
        Settings.from_env({"LLM_DAILY_CALL_LIMIT": value})


def test_le_impostazioni_non_conservano_la_chiave_gemini() -> None:
    settings = Settings.from_env({"GEMINI_API_KEY": "fake-chiave-segreta-9"})
    for text in (repr(settings), str(settings), repr(vars(settings))):
        assert "fake-chiave-segreta-9" not in text


# --- config/llm.yaml ---------------------------------------------------------------------------


def test_il_file_di_configurazione_ha_i_valori_della_spec() -> None:
    config = LlmConfig.from_yaml()
    assert (config.timeout_s, config.temperature, config.retries) == (20, 0, 1)
    assert (config.thinking_level, config.max_output_tokens) == ("low", 2048)
    assert config.temperature <= MAX_TEMPERATURE == 0.2


@pytest.mark.parametrize(
    "fields",
    [
        {"timeout_s": 0, "temperature": 0, "retries": 1},
        {"timeout_s": 20, "temperature": 0.5, "retries": 1},
        {"timeout_s": 20, "temperature": -0.1, "retries": 1},
        {"timeout_s": 20, "temperature": 0, "retries": -1},
        {"timeout_s": 20, "temperature": 0, "retries": 4},
        {"timeout_s": 20, "temperature": 0},
        {"timeout_s": 20, "temperature": 0, "retries": 1, "extra": 1},
        {"timeout_s": 20, "temperature": 0, "retries": 1, "thinking_level": "enorme"},
        {"timeout_s": 20, "temperature": 0, "retries": 1, "max_output_tokens": 10},
    ],
)
def test_una_configurazione_non_valida_e_rifiutata(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LlmConfig.model_validate(fields)


# --- il client si costruisce dalle impostazioni --------------------------------------------


def test_il_servizio_si_costruisce_solo_in_live_e_con_la_chiave(tmp_path: Any) -> None:
    repo = make_llm_repo(tmp_path)
    base = {"GEMINI_MODEL": "m", "GEMINI_API_KEY": "fake-k"}

    def build(env: dict[str, str]) -> Any:
        return build_llm_client(Settings.from_env(env), repo, environ=env)

    live = build({**base, "LLM_MODE": "live"})
    assert live.mode == "live" and live._backend is not None
    for env in (
        {**base, "LLM_MODE": "cache_only"},
        {**base, "LLM_MODE": "template"},
        {"GEMINI_MODEL": "m", "LLM_MODE": "live"},  # live senza chiave
        {"GEMINI_MODEL": "m", "LLM_MODE": "live", "GEMINI_API_KEY": "  "},
    ):
        assert build(env)._backend is None, env


# --- adattatore Gemini (con un SDK finto: nessuna chiamata vera) ---------------------------------


class FakeModels:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        await asyncio.sleep(0)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def backend_with(result: Any) -> tuple[GeminiBackend, FakeModels]:
    models = FakeModels(result)
    backend = GeminiBackend("fake-chiave")
    backend._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return backend, models


async def generate(backend: GeminiBackend) -> str:
    return await backend.generate(
        model="un-modello",
        system="Sei un agente.",
        contents='{"x":1}',
        schema={"type": "object"},
        temperature=0.0,
        timeout_s=20,
    )


async def test_la_richiesta_ha_schema_json_temperatura_e_tempo_massimo() -> None:
    backend, models = backend_with(SimpleNamespace(text='{"text": "ok"}'))
    assert await generate(backend) == '{"text": "ok"}'
    (call,) = models.calls
    assert call["model"] == "un-modello" and call["contents"] == '{"x":1}'
    config = call["config"]
    assert config.system_instruction == "Sei un agente."
    assert config.temperature == 0
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == {"type": "object"}
    assert config.http_options.timeout == 20_000  # millisecondi


async def test_il_ragionamento_e_il_tetto_di_risposta_vanno_al_servizio() -> None:
    backend, models = backend_with(SimpleNamespace(text="{}"))
    backend._thinking_level, backend._max_output_tokens = "minimal", 2048
    await generate(backend)
    config = models.calls[0]["config"]
    assert config.thinking_config.thinking_level.value == "MINIMAL"
    assert config.max_output_tokens == 2048


async def test_senza_parametri_si_lascia_il_valore_del_modello() -> None:
    backend, models = backend_with(SimpleNamespace(text="{}"))
    await generate(backend)
    config = models.calls[0]["config"]
    assert config.thinking_config is None and config.max_output_tokens is None


def test_la_fabbrica_passa_i_parametri_di_config_all_adattatore() -> None:
    config = LlmConfig(
        timeout_s=20, temperature=0, retries=1, thinking_level="low", max_output_tokens=512
    )
    backend = gemini_backend("fake-k", config)
    assert (backend._thinking_level, backend._max_output_tokens) == ("low", 512)


async def test_i_token_consumati_si_sommano_dai_conteggi_del_servizio() -> None:
    usage = SimpleNamespace(
        prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=50
    )
    backend, _ = backend_with(SimpleNamespace(text="{}", usage_metadata=usage))
    await generate(backend)
    await generate(backend)
    assert (backend.usage.calls, backend.usage.prompt) == (2, 2000)
    assert (backend.usage.output, backend.usage.thoughts) == (400, 100)


async def test_senza_conteggi_nella_risposta_i_token_restano_zero() -> None:
    backend, _ = backend_with(SimpleNamespace(text="{}"))  # nessun usage_metadata
    await generate(backend)
    assert (backend.usage.calls, backend.usage.prompt, backend.usage.thoughts) == (1, 0, 0)


async def test_una_chiamata_fallita_non_conta_token() -> None:
    backend, _ = backend_with(ConnectionError("rete"))
    with pytest.raises(LlmUnavailable):
        await generate(backend)
    assert backend.usage.calls == 0


async def test_una_risposta_senza_testo_e_una_stringa_vuota() -> None:
    backend, _ = backend_with(SimpleNamespace(text=None))
    assert await generate(backend) == ""  # la valida il parse: sarà «non valida»


async def test_un_errore_del_servizio_non_porta_con_se_il_testo_dell_errore() -> None:
    from google.genai import errors

    secret = "chiave=fake-chiave-segreta in https://servizio?key=fake-chiave-segreta"
    backend, _ = backend_with(errors.ClientError(403, {"error": {"message": secret}}))
    with pytest.raises(LlmUnavailable) as raised:
        await generate(backend)
    assert "fake-chiave-segreta" not in str(raised.value)
    assert str(raised.value) == "ClientError 403"


async def test_un_errore_di_rete_diventa_non_disponibile() -> None:
    backend, _ = backend_with(ConnectionError("dettaglio con fake-chiave-segreta"))
    with pytest.raises(LlmUnavailable) as raised:
        await generate(backend)
    assert str(raised.value) == "ConnectionError"


def test_senza_la_chiave_il_client_vero_non_si_costruisce_prima_del_primo_uso() -> None:
    """L'SDK si importa e si istanzia solo alla prima chiamata: l'applicazione parte senza."""
    backend = GeminiBackend("fake-chiave")
    assert backend._client is None
