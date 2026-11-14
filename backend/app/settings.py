import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, get_args

from dotenv import load_dotenv

from app.data.paths import REPO_ROOT, default_data_dir
from app.models.base import Environment, LlmMode, WhatsAppMode, WhatsAppProvider

ENV_FILE = REPO_ROOT / ".env"

# Senza `LLM_MODE` l'applicazione non chiama nessun servizio e non costa niente: i testi sono i
# template. `live` si sceglie, non si eredita per distrazione (spech.md 6.7).
DEFAULT_LLM_MODE: LlmMode = "template"
DEFAULT_LLM_DAILY_CALL_LIMIT = 300
# Richieste a TomTom al giorno (08 6): oltre, LIVE mostra solo lo snapshot.
DEFAULT_TOMTOM_DAILY_LIMIT = 2000
# Conservare l'ultimo dato LIVE su disco (08 5). Q2 (i termini di TomTom lo permettono?) è da
# verificare da parte del proprietario: con `LIVE_SNAPSHOT_PERSIST=false` resta solo in memoria.
DEFAULT_LIVE_SNAPSHOT_PERSIST = True
# Accesso libero (nessuna password): spento di default, così in locale e nei test l'accesso resta
# protetto. Lo accende `PUBLIC_ACCESS=true` (sulla VM lo fa `docker-compose.yml`: regola
# dell'hackathon, 14/11/2026); per tornare alla password basta `PUBLIC_ACCESS=false`.
DEFAULT_PUBLIC_ACCESS = False
# Notifica WhatsApp (spech.md 12.4): spenta di default, così nessun test né avvio locale invia
# niente per distrazione; `WHATSAPP_MODE=live` la accende. Messaggi al giorno: oltre, `SKIPPED`.
DEFAULT_WHATSAPP_MODE: WhatsAppMode = "off"
DEFAULT_WHATSAPP_PROVIDER: WhatsAppProvider = "callmebot"
DEFAULT_WHATSAPP_DAILY_LIMIT = 20


class SettingsError(Exception):
    """Una variabile d'ambiente ha un valore non ammesso."""


def load_env_file(path: Path = ENV_FILE) -> None:
    """Carica il `.env` senza sovrascrivere l'ambiente (quello vero vince)."""
    if path.is_file():
        load_dotenv(path, override=False)


def _value(environ: Mapping[str, str], name: str) -> str | None:
    return environ.get(name, "").strip() or None


def _count(environ: Mapping[str, str], name: str, default: int) -> int:
    """Un intero non negativo (un tetto); vuoto = il predefinito."""
    text = _value(environ, name)
    if text is None:
        return default
    try:
        number = int(text)
    except ValueError as exc:
        raise SettingsError(f"{name}='{text}' non è un intero") from exc
    if number < 0:
        raise SettingsError(f"{name} non può essere negativo")
    return number


def _flag(environ: Mapping[str, str], name: str, default: bool) -> bool:
    """`true` o `false` (senza badare alle maiuscole); vuoto = il predefinito."""
    text = _value(environ, name)
    if text is None:
        return default
    if text.lower() not in ("true", "false"):
        raise SettingsError(f"{name}='{text}' non ammesso: usa 'true' o 'false'")
    return text.lower() == "true"


@dataclass(frozen=True)
class WhatsAppSettings:
    """La notifica WhatsApp (12.4). Numero e chiavi servono al client per spedire, quindi qui ci
    sono, ma **mai nel `repr`**: né loro né i valori accanto (un `print(settings)` non deve poterli
    mostrare). Le variabili che ogni servizio richiede sono in `REQUIRED`."""

    mode: WhatsAppMode = DEFAULT_WHATSAPP_MODE
    provider: WhatsAppProvider = DEFAULT_WHATSAPP_PROVIDER
    daily_limit: int = DEFAULT_WHATSAPP_DAILY_LIMIT
    to: str | None = field(default=None, repr=False)  # WHATSAPP_TO, formato internazionale
    callmebot_apikey: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)
    phone_number_id: str | None = field(default=None, repr=False)
    api_version: str | None = field(default=None, repr=False)
    template: str | None = field(default=None, repr=False)  # facoltativo: senza, testo libero
    template_lang: str | None = field(default=None, repr=False)

    REQUIRED: ClassVar[dict[WhatsAppProvider, tuple[tuple[str, str], ...]]] = {
        "callmebot": (("WHATSAPP_TO", "to"), ("CALLMEBOT_APIKEY", "callmebot_apikey")),
        "meta": (
            ("WHATSAPP_TO", "to"),
            ("WHATSAPP_TOKEN", "token"),
            ("WHATSAPP_PHONE_NUMBER_ID", "phone_number_id"),
            ("WHATSAPP_API_VERSION", "api_version"),
        ),
    }

    def missing(self) -> list[str]:
        """I nomi (mai i valori) delle variabili che il servizio scelto richiede e mancano."""
        return [name for name, attr in self.REQUIRED[self.provider] if not getattr(self, attr)]

    @property
    def configured(self) -> bool:
        """Un messaggio partirebbe davvero: invio acceso e tutto ciò che il servizio richiede."""
        return self.mode == "live" and not self.missing()


def _whatsapp_from_env(source: Mapping[str, str]) -> WhatsAppSettings:
    mode = _value(source, "WHATSAPP_MODE") or DEFAULT_WHATSAPP_MODE
    if mode not in get_args(WhatsAppMode):
        raise SettingsError(f"WHATSAPP_MODE='{mode}' non ammesso: usa 'off' o 'live'")
    provider = _value(source, "WHATSAPP_PROVIDER") or DEFAULT_WHATSAPP_PROVIDER
    if provider not in get_args(WhatsAppProvider):
        raise SettingsError(f"WHATSAPP_PROVIDER='{provider}' non ammesso: usa 'callmebot' o 'meta'")
    return WhatsAppSettings(
        mode=mode,  # type: ignore[arg-type]  # verificato sopra
        provider=provider,  # type: ignore[arg-type]  # verificato sopra
        daily_limit=_count(source, "WHATSAPP_DAILY_LIMIT", DEFAULT_WHATSAPP_DAILY_LIMIT),
        to=_value(source, "WHATSAPP_TO"),
        callmebot_apikey=_value(source, "CALLMEBOT_APIKEY"),
        token=_value(source, "WHATSAPP_TOKEN"),
        phone_number_id=_value(source, "WHATSAPP_PHONE_NUMBER_ID"),
        api_version=_value(source, "WHATSAPP_API_VERSION"),
        template=_value(source, "WHATSAPP_TEMPLATE"),
        template_lang=_value(source, "WHATSAPP_TEMPLATE_LANG"),
    )


@dataclass(frozen=True)
class Settings:
    env: Environment
    data_dir: Path
    app_password: str | None = field(default=None, repr=False)
    session_secret: str | None = field(default=None, repr=False)
    tomtom_key_present: bool = False
    gemini_key_present: bool = False
    gemini_model: str | None = None  # DA DEFINIRE (Q1): lo sceglie il proprietario, non si indovina
    llm_mode: LlmMode = DEFAULT_LLM_MODE
    llm_daily_call_limit: int = DEFAULT_LLM_DAILY_CALL_LIMIT
    tomtom_daily_limit: int = DEFAULT_TOMTOM_DAILY_LIMIT
    live_snapshot_persist: bool = DEFAULT_LIVE_SNAPSHOT_PERSIST
    public_access: bool = DEFAULT_PUBLIC_ACCESS
    whatsapp: WhatsAppSettings = field(default_factory=WhatsAppSettings)

    @property
    def auth_configured(self) -> bool:
        """Senza password e segreto nessuno può entrare: l'accesso è chiuso, non aperto."""
        return bool(self.app_password and self.session_secret)

    @property
    def secure_cookies(self) -> bool:
        return self.env == "production"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if environ is None else environ
        env = _value(source, "ENV") or "local"
        if env not in get_args(Environment):
            raise SettingsError(f"ENV='{env}' non ammesso: usa 'local' o 'production'")
        llm_mode = _value(source, "LLM_MODE") or DEFAULT_LLM_MODE
        if llm_mode not in get_args(LlmMode):
            raise SettingsError(
                f"LLM_MODE='{llm_mode}' non ammesso: usa 'live', 'cache_only' o 'template'"
            )
        limit_text = _value(source, "LLM_DAILY_CALL_LIMIT")
        try:
            limit = int(limit_text) if limit_text else DEFAULT_LLM_DAILY_CALL_LIMIT
        except ValueError as exc:
            raise SettingsError(f"LLM_DAILY_CALL_LIMIT='{limit_text}' non è un intero") from exc
        if limit < 0:
            raise SettingsError("LLM_DAILY_CALL_LIMIT non può essere negativo")
        tomtom_limit = _count(source, "TOMTOM_DAILY_LIMIT", DEFAULT_TOMTOM_DAILY_LIMIT)
        persist = _flag(source, "LIVE_SNAPSHOT_PERSIST", DEFAULT_LIVE_SNAPSHOT_PERSIST)
        public_access = _flag(source, "PUBLIC_ACCESS", DEFAULT_PUBLIC_ACCESS)
        whatsapp = _whatsapp_from_env(source)
        return cls(
            env=env,  # type: ignore[arg-type]  # verificato sopra
            data_dir=default_data_dir(source),
            app_password=_value(source, "APP_PASSWORD"),
            session_secret=_value(source, "SESSION_SECRET"),
            tomtom_key_present=_value(source, "TOMTOM_API_KEY") is not None,
            gemini_key_present=_value(source, "GEMINI_API_KEY") is not None,
            gemini_model=_value(source, "GEMINI_MODEL"),
            llm_mode=llm_mode,  # type: ignore[arg-type]  # verificato sopra
            llm_daily_call_limit=limit,
            tomtom_daily_limit=tomtom_limit,
            live_snapshot_persist=persist,
            public_access=public_access,
            whatsapp=whatsapp,
        )
