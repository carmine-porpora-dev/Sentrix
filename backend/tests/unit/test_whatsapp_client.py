import logging
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.notifications.whatsapp_client import (
    CALLMEBOT_URL,
    RETRIES,
    TIMEOUT_S,
    CallMeBotClient,
    MetaClient,
    WhatsAppError,
    build_client,
    scrub,
)
from app.settings import WhatsAppSettings

NUMBER = "+393331234512"
APIKEY = "ck-fake-7391846"
TOKEN = "EAAfake-token-0987654"
TEXT = (
    "*Sentrix — Avviso viabilità*\nEvento: Prova (10/07/2027)\n\nStrade chiuse:\n• Via Caracciolo"
)
SUCCESS_PAGE = "<html><body><p><b>Message queued.</b> You will receive it in a few seconds.</p>"

Handler = Callable[[httpx2.Request], Any]


class Service:
    """Un servizio finto: registra le richieste e risponde con l'esito scelto, una dopo l'altra
    (l'ultimo si ripete)."""

    def __init__(self, *outcomes: httpx2.Response | Exception) -> None:
        self.outcomes = list(outcomes) or [httpx2.Response(200, text=SUCCESS_PAGE)]
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        outcome = self.outcomes[min(len(self.requests), len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self)


def callmebot(service: Service) -> CallMeBotClient:
    return CallMeBotClient(NUMBER, APIKEY, transport=service.transport)


def meta_settings(**changes: str | None) -> WhatsAppSettings:
    fields: dict[str, Any] = {
        "mode": "live",
        "provider": "meta",
        "to": NUMBER,
        "token": TOKEN,
        "phone_number_id": "104567890",
        "api_version": "v21.0",
    }
    return WhatsAppSettings(**{**fields, **changes})


def meta(service: Service, **changes: str | None) -> MetaClient:
    return MetaClient(meta_settings(**changes), transport=service.transport)


# --- CallMeBot: la richiesta -------------------------------------------------------------------


async def test_callmebot_manda_una_get_con_numero_testo_e_chiave() -> None:
    service = Service()
    result = await callmebot(service).send(TEXT)
    assert result.message_id is None  # CallMeBot non dà un identificativo
    (request,) = service.requests
    assert request.method == "GET"
    assert (
        str(request.url).split("?")[0] == CALLMEBOT_URL == "https://api.callmebot.com/whatsapp.php"
    )
    assert dict(request.url.params) == {"phone": NUMBER, "text": TEXT, "apikey": APIKEY}


async def test_il_testo_e_url_encoded() -> None:
    service = Service()
    await callmebot(service).send(TEXT)
    query = str(service.requests[0].url).split("?", 1)[1]
    assert "\n" not in query and " " not in query and "—" not in query  # niente di crudo
    assert "%0A" in query  # gli a capo
    assert "%2B393331234512" in query  # il «+» del numero


async def test_il_timeout_e_di_15_secondi_e_il_nuovo_tentativo_uno() -> None:
    assert (TIMEOUT_S, RETRIES) == (15.0, 1)
    service = Service()
    await callmebot(service).send(TEXT)
    assert service.requests[0].extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), 15.0
    )


# --- CallMeBot: gli esiti ----------------------------------------------------------------------


async def test_200_e_inviato_anche_se_la_pagina_ripete_il_messaggio() -> None:
    """Una via chiamata «Error» non è un errore del servizio: il testo che CallMeBot ripete si
    toglie prima di cercare le parole d'errore."""
    text = "*Sentrix*\nVia Error Invalid"
    page = httpx2.Response(200, text=f"<p>Message to be sent: {text.replace(chr(10), ' ')}</p>")
    assert (await callmebot(Service(page)).send(text)).message_id is None


@pytest.mark.parametrize(
    "body",
    [
        "ERROR: apikey is invalid",
        "<html><b>APIKey is invalid</b> or incorrect phone number</html>",
        "Wrong api key",
    ],
)
async def test_200_con_un_messaggio_d_errore_e_rifiutato(body: str) -> None:
    with pytest.raises(WhatsAppError) as info:
        await callmebot(Service(httpx2.Response(200, text=body))).send(TEXT)
    assert info.value.code == "rejected" and info.value.detail


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
async def test_un_4xx_e_rifiutato_e_non_si_riprova(status: int) -> None:
    service = Service(httpx2.Response(status, text="denied"))
    with pytest.raises(WhatsAppError) as info:
        await callmebot(service).send(TEXT)
    assert info.value.code == "rejected" and f"HTTP {status}" in info.value.detail
    assert len(service.requests) == 1


async def test_un_5xx_si_riprova_una_volta_poi_e_irraggiungibile() -> None:
    service = Service(httpx2.Response(503), httpx2.Response(502))
    with pytest.raises(WhatsAppError) as info:
        await callmebot(service).send(TEXT)
    assert info.value.code == "unreachable" and info.value.detail == "HTTP 502"
    assert len(service.requests) == 2  # il primo più UN nuovo tentativo


async def test_un_5xx_poi_200_e_inviato() -> None:
    service = Service(httpx2.Response(500), httpx2.Response(200, text=SUCCESS_PAGE))
    await callmebot(service).send(TEXT)
    assert len(service.requests) == 2


@pytest.mark.parametrize(
    "error",
    [httpx2.ReadTimeout("t"), httpx2.ConnectTimeout("t"), httpx2.ConnectError("c")],
)
async def test_timeout_o_rete_giu_si_riprova_una_volta_poi_e_irraggiungibile(
    error: Exception,
) -> None:
    service = Service(error)
    with pytest.raises(WhatsAppError) as info:
        await callmebot(service).send(TEXT)
    assert info.value.code == "unreachable" and info.value.detail == type(error).__name__
    assert len(service.requests) == 2


async def test_un_errore_di_rete_poi_200_e_inviato() -> None:
    service = Service(httpx2.ConnectError("c"), httpx2.Response(200, text=SUCCESS_PAGE))
    await callmebot(service).send(TEXT)
    assert len(service.requests) == 2


async def test_un_reindirizzamento_non_si_segue() -> None:
    """Un 3xx verso un altro host porterebbe numero e chiave altrove: è un rifiuto."""
    service = Service(httpx2.Response(302, headers={"Location": "https://altro.example/x"}))
    with pytest.raises(WhatsAppError) as info:
        await callmebot(service).send(TEXT)
    assert info.value.code == "rejected" and len(service.requests) == 1


# --- Meta (predisposto) ------------------------------------------------------------------------


async def test_meta_manda_una_post_con_testo_libero_e_token_nell_intestazione() -> None:
    service = Service(httpx2.Response(200, json={"messages": [{"id": "wamid.fake123"}]}))
    result = await meta(service).send(TEXT)
    assert result.message_id == "wamid.fake123"
    (request,) = service.requests
    assert request.method == "POST"
    assert str(request.url) == "https://graph.facebook.com/v21.0/104567890/messages"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.read() and httpx2.Response(200, content=request.read()).json() == {
        "messaging_product": "whatsapp",
        "to": NUMBER.lstrip("+"),
        "type": "text",
        "text": {"body": TEXT},
    }


async def test_meta_con_un_modello_manda_il_testo_come_parametro_su_una_riga() -> None:
    service = Service(httpx2.Response(200, json={"messages": [{"id": "wamid.x"}]}))
    await meta(service, template="avviso_viabilita", template_lang="it").send(TEXT)
    body = httpx2.Response(200, content=service.requests[0].read()).json()
    assert body["type"] == "template"
    assert body["template"]["name"] == "avviso_viabilita"
    assert body["template"]["language"] == {"code": "it"}
    (parameter,) = body["template"]["components"][0]["parameters"]
    assert "\n" not in parameter["text"] and "Via Caracciolo" in parameter["text"]


async def test_meta_senza_lingua_usa_italiano() -> None:
    service = Service(httpx2.Response(200, json={"messages": [{"id": "wamid.x"}]}))
    await meta(service, template="avviso").send(TEXT)
    body = httpx2.Response(200, content=service.requests[0].read()).json()
    assert body["template"]["language"] == {"code": "it"}


async def test_meta_errore_del_servizio_senza_il_token() -> None:
    error = {"error": {"message": f"Invalid OAuth access token {TOKEN}", "code": 190}}
    service = Service(httpx2.Response(401, json=error))
    with pytest.raises(WhatsAppError) as info:
        await meta(service).send(TEXT)
    assert info.value.code == "rejected" and "HTTP 401" in info.value.detail
    assert TOKEN not in info.value.detail and TOKEN not in str(info.value)


async def test_meta_200_senza_messaggi_e_rifiutato() -> None:
    with pytest.raises(WhatsAppError) as info:
        await meta(Service(httpx2.Response(200, json={}))).send(TEXT)
    assert info.value.code == "rejected"


async def test_meta_5xx_si_riprova_una_volta() -> None:
    service = Service(httpx2.Response(500), httpx2.Response(200, json={"messages": [{"id": "w"}]}))
    assert (await meta(service).send(TEXT)).message_id == "w"
    assert len(service.requests) == 2
    failing = Service(httpx2.ReadTimeout("t"))
    with pytest.raises(WhatsAppError) as info:
        await meta(failing).send(TEXT)
    assert info.value.code == "unreachable" and len(failing.requests) == 2


# --- la scelta del servizio --------------------------------------------------------------------


def test_build_client_sceglie_il_servizio() -> None:
    callmebot_settings = WhatsAppSettings(mode="live", to=NUMBER, callmebot_apikey=APIKEY)
    assert isinstance(build_client(callmebot_settings), CallMeBotClient)
    assert isinstance(build_client(meta_settings()), MetaClient)


def test_i_client_non_mostrano_numero_e_chiave_nel_repr() -> None:
    texts = [repr(CallMeBotClient(NUMBER, APIKEY)), repr(MetaClient(meta_settings()))]
    for text in texts:
        for secret in (NUMBER, NUMBER.lstrip("+"), APIKEY, TOKEN):
            assert secret not in text


# --- numero e chiave non escono mai ------------------------------------------------------------


def test_scrub_toglie_i_segreti_in_ogni_forma() -> None:
    url = f"{CALLMEBOT_URL}?phone=%2B393331234512&text=ciao&apikey={APIKEY}"
    cleaned = scrub(url, NUMBER, APIKEY)
    assert APIKEY not in cleaned and "393331234512" not in cleaned and "ciao" not in cleaned
    assert "apikey=***" in cleaned and "phone=***" in cleaned
    plain = scrub(f"numero {NUMBER} / {NUMBER.lstrip('+')} / chiave {APIKEY}", NUMBER, APIKEY)
    assert plain == "numero *** / *** / chiave ***"
    assert scrub("nessun segreto qui", NUMBER, APIKEY) == "nessun segreto qui"
    assert scrub("ciao", None, "") == "ciao"  # i valori mancanti non cancellano nulla


async def test_il_motivo_del_servizio_non_riporta_numero_e_chiave() -> None:
    page = f"<p>ERROR: phone {NUMBER} / key {APIKEY} not allowed</p>"
    with pytest.raises(WhatsAppError) as info:
        await callmebot(Service(httpx2.Response(200, text=page))).send(TEXT)
    for secret in (NUMBER, NUMBER.lstrip("+"), APIKEY):
        assert secret not in info.value.detail and secret not in str(info.value)


async def test_gli_errori_di_rete_non_riportano_l_url(caplog: pytest.LogCaptureFixture) -> None:
    secret_url = f"{CALLMEBOT_URL}?phone={NUMBER}&apikey={APIKEY}"
    service = Service(httpx2.ConnectError(f"connessione a {secret_url} rifiutata"))
    with caplog.at_level(logging.DEBUG), pytest.raises(WhatsAppError) as info:
        await callmebot(service).send(TEXT)
    everything = caplog.text + info.value.detail + str(info.value)
    assert APIKEY not in everything and "393331234512" not in everything
    assert "apikey" not in everything.lower()


@pytest.mark.parametrize("name", ["httpx2", "httpcore"])
def test_i_log_dei_client_http_restano_a_warning(name: str) -> None:
    assert logging.getLogger(name).level == logging.WARNING


async def test_anche_con_httpx2_a_info_l_url_nei_log_e_oscurato(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`httpx2` registra l'URL di ogni richiesta a INFO. Se qualcuno lo alza, il filtro oscura
    comunque numero e chiave (come per TomTom)."""
    log = logging.getLogger("httpx2")
    before = log.level
    log.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.INFO, logger="httpx2"):
            await callmebot(Service()).send(TEXT)
    finally:
        log.setLevel(before)
    assert any(r.name == "httpx2" for r in caplog.records)  # il log c'è davvero
    assert APIKEY not in caplog.text and "393331234512" not in caplog.text
    assert "Via+Caracciolo" not in caplog.text and "text=***" in caplog.text
