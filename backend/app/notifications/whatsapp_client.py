import html
import logging
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import quote, quote_plus

import httpx2

from app.settings import WhatsAppSettings

# Il trasporto HTTP che un test può sostituire: gli altri moduli lo importano da qui, non da httpx2.
Transport = httpx2.AsyncBaseTransport

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
META_BASE_URL = "https://graph.facebook.com"
USER_AGENT = "NapoliUrbanOps/0.1"  # generico: nessun dato personale
TIMEOUT_S = 15.0  # il servizio gratuito è condiviso e può essere lento (12.4)
RETRIES = 1  # un solo nuovo tentativo, solo su errore di rete o 5xx (12.4)
MAX_DETAIL = 200  # lunghezza massima del motivo del servizio riportato in un errore
DEFAULT_TEMPLATE_LANG = "it"

ErrorCode = Literal["unreachable", "rejected"]

# I nomi dei parametri che portano il numero, la chiave o il testo in un URL o in un corpo.
_SECRET_PARAMS = re.compile(r"(?i)\b(phone|apikey|text|access_token)=[^&\s\"'<>]+")
_TAGS = re.compile(r"<[^>]*>")
_SPACES = re.compile(r"\s+")
# CallMeBot risponde 200 anche con un messaggio d'errore nella pagina: lo riconosciamo dalle parole.
_ERROR_WORDS = re.compile(r"(?i)\b(error|invalid|incorrect|wrong|denied)\b")


def _variants(secret: str) -> set[str]:
    """Il segreto e le forme in cui può ricomparire: in un URL, senza il `+`, solo cifre."""
    digits = re.sub(r"\D", "", secret)
    forms = {secret, secret.lstrip("+"), quote(secret, safe=""), quote_plus(secret)}
    return {form for form in forms | {digits} if len(form) >= 4}


def scrub(text: str, *secrets: str | None) -> str:
    """`text` senza i segreti noti (in tutte le loro forme) e senza i parametri `phone=`, `apikey=`,
    `text=`, `access_token=`. Va chiamata su tutto ciò che viene da un servizio o da un URL."""
    cleaned = _SECRET_PARAMS.sub(lambda m: f"{m.group(1).lower()}=***", text)
    for secret in sorted({v for s in secrets if s for v in _variants(s)}, key=len, reverse=True):
        cleaned = cleaned.replace(secret, "***")
    return cleaned


class _RedactParams(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = ()
        return True


def _protect_loggers() -> None:
    """`httpx2` registra a INFO l'URL di ogni richiesta, numero e chiave compresi: lo si tiene a
    WARNING e, se qualcuno lo alza, il filtro oscura comunque i parametri."""
    for name in ("httpx2", "httpcore"):
        log = logging.getLogger(name)
        log.setLevel(logging.WARNING)
        if not any(isinstance(f, _RedactParams) for f in log.filters):
            log.addFilter(_RedactParams())


_protect_loggers()
logger = logging.getLogger(__name__)


class WhatsAppError(Exception):
    """Un messaggio non partito. Il motivo (`detail`) non contiene mai numero, chiave né URL."""

    def __init__(self, code: ErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SendResult:
    message_id: str | None  # l'identificativo del servizio, se ne dà uno (CallMeBot no)


class WhatsAppClient(Protocol):
    async def send(self, text: str) -> SendResult:
        """Spedisce `text` al numero configurato; `WhatsAppError` se non parte."""
        ...


def _readable(body: str) -> str:
    """Il testo di una pagina o di un corpo, senza tag né a capo."""
    return _SPACES.sub(" ", html.unescape(_TAGS.sub(" ", body))).strip()


class _Sender:
    """Ciò che i due servizi hanno in comune: la richiesta con il nuovo tentativo e il modo di dire
    perché è fallita senza mai riportare l'URL."""

    def __init__(self, secrets: tuple[str, ...], transport: Transport | None) -> None:
        self._secrets = secrets
        self._transport = transport

    def _clean(self, text: str) -> str:
        return scrub(text, *self._secrets)

    async def _request(self, request: httpx2.Request) -> httpx2.Response:
        """La risposta del servizio, tranne i 5xx e gli errori di rete: quelli si riprovano una
        volta e, se persistono, diventano `unreachable`."""
        failure = "nessun tentativo"
        async with httpx2.AsyncClient(
            timeout=TIMEOUT_S,
            transport=self._transport,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        ) as http:
            for _ in range(RETRIES + 1):
                try:
                    response = await http.send(request)
                except httpx2.TransportError as error:  # timeout, connessione, TLS...
                    failure = type(error).__name__
                    continue
                if response.status_code >= 500:
                    failure = f"HTTP {response.status_code}"
                    continue
                return response
        logger.warning("WhatsApp non raggiungibile: %s", failure)
        raise WhatsAppError("unreachable", failure)


class CallMeBotClient(_Sender):
    """`GET https://api.callmebot.com/whatsapp.php?phone=…&text=…&apikey=…` (12.4). Invia solo al
    numero che ha attivato la chiave: è il limite del servizio gratuito."""

    def __init__(
        self,
        to: str,
        apikey: str,
        *,
        base_url: str = CALLMEBOT_URL,
        transport: Transport | None = None,
    ) -> None:
        super().__init__((to, apikey), transport)
        self._to = to
        self._apikey = apikey
        self._base_url = base_url

    def __repr__(self) -> str:
        return f"CallMeBotClient(base_url={self._base_url!r})"

    async def send(self, text: str) -> SendResult:
        request = httpx2.Request(
            "GET",
            self._base_url,
            params={"phone": self._to, "text": text, "apikey": self._apikey},
        )
        response = await self._request(request)
        # la pagina può ripetere il messaggio: le sue parole non sono un errore del servizio
        page = _readable(response.text).replace(_readable(text), "…")
        detail = self._clean(page)[:MAX_DETAIL]
        if response.status_code != 200:
            raise WhatsAppError(
                "rejected", f"HTTP {response.status_code}" + (f": {detail}" if detail else "")
            )
        if _ERROR_WORDS.search(page):
            raise WhatsAppError("rejected", detail)
        return SendResult(message_id=None)


class MetaClient(_Sender):
    """WhatsApp Cloud API (Fase B, predisposto, mai provato su un servizio vero):
    `POST https://graph.facebook.com/<versione>/<id numero>/messages`. Con un modello approvato
    (`template`) il testo è il suo unico parametro; senza, testo libero (finestra di 24 ore)."""

    def __init__(
        self,
        settings: WhatsAppSettings,
        *,
        base_url: str = META_BASE_URL,
        transport: Transport | None = None,
    ) -> None:
        assert settings.to and settings.token and settings.phone_number_id and settings.api_version
        super().__init__((settings.to, settings.token), transport)
        self._to = settings.to.lstrip("+")
        self._token = settings.token
        self._url = f"{base_url}/{settings.api_version}/{settings.phone_number_id}/messages"
        self._template = settings.template
        self._lang = settings.template_lang or DEFAULT_TEMPLATE_LANG

    def __repr__(self) -> str:
        return "MetaClient()"

    def _body(self, text: str) -> dict[str, object]:
        body: dict[str, object] = {"messaging_product": "whatsapp", "to": self._to}
        if self._template is None:
            return {**body, "type": "text", "text": {"body": text}}
        # un parametro di modello non può avere a capo: il testo va su una riga
        flat = _SPACES.sub(" ", text)
        return {
            **body,
            "type": "template",
            "template": {
                "name": self._template,
                "language": {"code": self._lang},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": flat}]}],
            },
        }

    async def send(self, text: str) -> SendResult:
        request = httpx2.Request(
            "POST",
            self._url,
            json=self._body(text),
            headers={"Authorization": f"Bearer {self._token}"},
        )
        response = await self._request(request)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code == 200 and isinstance(payload, dict):
            messages = payload.get("messages")
            if isinstance(messages, list) and messages and isinstance(messages[0], dict):
                return SendResult(message_id=str(messages[0].get("id") or "") or None)
        reason = ""
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            reason = str(payload["error"].get("message") or "")
        raise WhatsAppError(
            "rejected",
            self._clean(f"HTTP {response.status_code}" + (f": {reason}" if reason else ""))[
                :MAX_DETAIL
            ],
        )


def build_client(
    settings: WhatsAppSettings, *, transport: Transport | None = None
) -> WhatsAppClient:
    """Il client del servizio scelto. Presuppone `settings.missing() == []` (lo verifica chi
    chiama: senza, non si costruisce nulla)."""
    if settings.provider == "meta":
        return MetaClient(settings, transport=transport)
    assert settings.to and settings.callmebot_apikey
    return CallMeBotClient(settings.to, settings.callmebot_apikey, transport=transport)
