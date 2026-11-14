import asyncio
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.notifications import NotificationDraft
from app.settings import Settings, WhatsAppSettings
from tests.conftest import FakeClock, log_in
from tests.orchestrator_support import engines_with
from tests.support import ctx_of, make_run
from tests.unit.test_whatsapp_client import APIKEY, NUMBER, SUCCESS_PAGE, Service

NEW_RUN = {"event_id": "match_2027", "attendance_level": "mid", "manual_response": False}
LIVE = WhatsAppSettings(mode="live", to=NUMBER, callmebot_apikey=APIKEY)


def started(
    settings: Settings, clock: FakeClock, service: Service, whatsapp: WhatsAppSettings = LIVE
) -> FastAPI:
    return create_app(
        replace(settings, whatsapp=whatsapp),
        clock=clock,
        engines=engines_with(()),
        whatsapp_transport=service.transport,
    )


@pytest.fixture
def service() -> Service:
    return Service()


@pytest.fixture
def wa_app(settings: Settings, clock: FakeClock, service: Service) -> FastAPI:
    return started(settings, clock, service)


@pytest.fixture
def wa(wa_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(wa_app) as c:
        log_in(c)
        yield c


def run_to_done(c: TestClient) -> str:
    run_id = c.post("/api/runs", json=NEW_RUN).json()["run_id"]
    wait(lambda: c.get(f"/api/runs/{run_id}").json()["run"]["state"] in ("DONE", "ERROR"))
    assert c.get(f"/api/runs/{run_id}").json()["run"]["state"] == "DONE"
    return run_id


def wait(condition: Any, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("la condizione non si è verificata in tempo")


def notifications(
    c: TestClient, run_id: str, channel: str | None = "whatsapp"
) -> list[dict[str, Any]]:
    """Le notifiche WhatsApp del run (con `channel=None` tutte: ci sono anche i bollettini)."""
    params = {"channel": channel} if channel else {}
    response = c.get(f"/api/runs/{run_id}/notifications", params=params)
    assert response.status_code == 200
    return list(response.json())


# --- l'invio dopo DONE -------------------------------------------------------------------------


def test_a_fine_run_parte_un_messaggio_e_l_endpoint_lo_racconta(
    wa: TestClient, service: Service
) -> None:
    run_id = run_to_done(wa)
    wait(lambda: notifications(wa, run_id))
    (row,) = notifications(wa, run_id)
    assert (row["channel"], row["state"], row["simulation"]) == ("whatsapp", "SENT", False)
    assert row["recipient_label"] == "+39 *** *** **12"
    assert row["text"].startswith("*Sentrix — Avviso viabilità*\n")
    assert len(service.requests) == 1
    assert service.requests[0].url.params["text"] == row["text"]
    assert row["run_id"] == run_id and row["error_code"] is None


def test_il_messaggio_parte_dopo_che_il_run_e_done(wa: TestClient, wa_app: FastAPI) -> None:
    """Il run non aspetta il messaggio: quando il servizio viene chiamato il run è già `DONE`."""
    states: list[str] = []

    def spy(request: httpx2.Request) -> httpx2.Response:
        runs = ctx_of(wa_app).repo.list_runs()
        states.extend(r.state for r in runs)
        return httpx2.Response(200, text=SUCCESS_PAGE)

    ctx_of(wa_app).runs._notifier._transport = httpx2.MockTransport(spy)  # type: ignore[union-attr]  # noqa: SLF001
    run_id = run_to_done(wa)
    wait(lambda: notifications(wa, run_id))
    assert states == ["DONE"]


def test_l_endpoint_non_mostra_il_numero_ne_la_chiave(wa: TestClient) -> None:
    run_id = run_to_done(wa)
    wait(lambda: notifications(wa, run_id))
    everything = (
        wa.get(f"/api/runs/{run_id}/notifications").text
        + wa.get(f"/api/runs/{run_id}/decisions").text
        + wa.get(f"/api/runs/{run_id}").text
        + wa.get(f"/api/runs/{run_id}/export").text
        + wa.get("/api/health").text
    )
    for secret in (NUMBER, NUMBER.lstrip("+"), "3331234512", APIKEY):
        assert secret not in everything


def test_l_esito_e_anche_nel_log_decisioni_e_nell_export(wa: TestClient) -> None:
    run_id = run_to_done(wa)
    wait(lambda: notifications(wa, run_id))
    wait(
        lambda: any(
            d["actor"] == "operations" and d["decision"].startswith("WhatsApp")
            for d in wa.get(f"/api/runs/{run_id}/decisions").json()
        )
    )
    entry = next(
        d
        for d in wa.get(f"/api/runs/{run_id}/decisions").json()
        if d["decision"].startswith("WhatsApp")
    )
    assert entry["decision"] == "WhatsApp inviato" and "+39 *** *** **12" in entry["rationale"]
    exported = wa.get(f"/api/runs/{run_id}/export").json()
    assert any(d["decision"] == "WhatsApp inviato" for d in exported["decisions"])


def test_un_errore_del_servizio_non_fa_fallire_il_run(settings: Settings, clock: FakeClock) -> None:
    failing = Service(httpx2.ConnectError("giù"))
    with TestClient(started(settings, clock, failing)) as c:
        log_in(c)
        run_id = run_to_done(c)
        wait(lambda: notifications(c, run_id))
        (row,) = notifications(c, run_id)
        assert (row["state"], row["error_code"]) == ("FAILED", "unreachable")
        view = c.get(f"/api/runs/{run_id}").json()
        assert view["run"]["state"] == "DONE" and view["run"]["error"] is None
    assert len(failing.requests) == 2  # il primo più un nuovo tentativo


def test_con_l_invio_spento_il_default_e_saltato_senza_chiamare_il_servizio(
    settings: Settings, clock: FakeClock, service: Service
) -> None:
    with TestClient(started(settings, clock, service, WhatsAppSettings())) as c:
        log_in(c)
        run_id = run_to_done(c)
        wait(lambda: notifications(c, run_id))
        (row,) = notifications(c, run_id)
        assert (row["state"], row["error_code"], row["recipient_label"]) == (
            "SKIPPED",
            "mode_off",
            None,
        )
    assert service.requests == []


def test_senza_nessuna_impostazione_il_default_e_spento(
    settings: Settings, clock: FakeClock
) -> None:
    """`Settings` senza `whatsapp`: la configurazione dei test e dell'avvio locale non invia."""
    assert settings.whatsapp.mode == "off" and not settings.whatsapp.configured


def test_un_run_senza_chiusure_non_manda_nulla(
    settings: Settings, clock: FakeClock, service: Service
) -> None:
    with TestClient(started(settings, clock, service)) as c:
        log_in(c)
        repo = ctx_of(c.app).repo  # type: ignore[arg-type]
        event = repo.get_event("match_2027")
        assert event is not None
        quiet = event.model_copy(update={"closures": [], "transit_disruptions": []})
        repo.update_event(quiet)
        run_id = run_to_done(c)
        time.sleep(0.3)  # il tempo che un messaggio ci metterebbe a partire
        assert notifications(c, run_id) == []
    assert service.requests == []


# --- l'endpoint --------------------------------------------------------------------------------


def test_senza_sessione_401(client: TestClient) -> None:
    assert client.get("/api/runs/run_1/notifications").status_code == 401


def test_un_run_che_non_esiste_404(authed: TestClient) -> None:
    response = authed.get("/api/runs/fantasma/notifications")
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


def test_un_run_senza_notifiche_ha_un_elenco_vuoto(app: FastAPI, authed: TestClient) -> None:
    ctx_of(app).repo.add_run(make_run("run_1"))
    assert notifications(authed, "run_1", channel=None) == []


def test_il_filtro_per_canale(app: FastAPI, authed: TestClient) -> None:
    repo = ctx_of(app).repo
    repo.add_run(make_run("run_1"))
    repo.add_notification(
        NotificationDraft(
            run_id="run_1", iteration=1, channel="whatsapp", recipient_id="whatsapp_to",
            recipient_label="+39 *** *** **12", kind="traffic_advisory", text="ciao",
            state="SENT", simulation=False,
        )
    )  # fmt: skip
    assert [n["channel"] for n in notifications(authed, "run_1", channel=None)] == ["whatsapp"]
    assert [n["channel"] for n in notifications(authed, "run_1", channel="whatsapp")] == [
        "whatsapp"
    ]
    assert notifications(authed, "run_1", channel="emergency_bulletin") == []
    assert authed.get("/api/runs/run_1/notifications", params={"channel": "sms"}).status_code == 400


# --- i bollettini ai servizi di emergenza (spech 12.3) -----------------------------------


def bulletins(c: TestClient, run_id: str) -> list[dict[str, Any]]:
    return notifications(c, run_id, channel="emergency_bulletin")


def test_a_fine_run_un_bollettino_simulato_per_ogni_destinatario(wa: TestClient) -> None:
    run_id = run_to_done(wa)
    wait(lambda: bulletins(wa, run_id))
    rows = bulletins(wa, run_id)
    assert [r["recipient_id"] for r in rows] == [
        "questura_napoli",
        "vigili_del_fuoco_napoli",
        "ospedale_cardarelli",
        "ospedale_del_mare",
        "ospedale_san_paolo",
        "ospedale_pellegrini",
        "ospedale_cto",
        "municipal_police",
    ]
    for row in rows:
        assert (row["channel"], row["state"], row["simulation"]) == (
            "emergency_bulletin",
            "DELIVERED",
            True,
        )
        assert row["text"].startswith("BOLLETTINO VIABILITÀ — SIMULATO\n")
        assert f"A: {row['recipient_label']}" in row["text"]
        assert row["error_code"] is None and row["provider_message_id"] is None


def test_il_bollettino_non_manda_nulla_all_esterno(wa: TestClient, service: Service) -> None:
    run_id = run_to_done(wa)
    wait(lambda: bulletins(wa, run_id) and notifications(wa, run_id))
    # l'unica richiesta HTTP uscita è il WhatsApp (uno): i bollettini sono solo righe del database
    assert len(service.requests) == 1


def test_i_bollettini_non_aspettano_il_whatsapp(settings: Settings, clock: FakeClock) -> None:
    """Il servizio WhatsApp è lento (qui 1,5 s): i bollettini sono già lì quando il messaggio non è
    ancora partito, e il WhatsApp parte comunque."""

    async def slow(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(1.5)
        return httpx2.Response(200, text=SUCCESS_PAGE)

    whatsapp = WhatsAppSettings(mode="live", to=NUMBER, callmebot_apikey=APIKEY)
    app = create_app(
        replace(settings, whatsapp=whatsapp),
        clock=clock,
        engines=engines_with(()),
        whatsapp_transport=httpx2.MockTransport(slow),
    )
    with TestClient(app) as c:
        log_in(c)
        run_id = run_to_done(c)
        wait(lambda: bulletins(c, run_id))
        assert notifications(c, run_id) == []  # il WhatsApp è ancora in viaggio
        wait(lambda: notifications(c, run_id))
        assert notifications(c, run_id)[0]["state"] == "SENT"


def test_un_errore_dei_bollettini_non_ferma_run_ne_whatsapp(
    settings: Settings, clock: FakeClock, service: Service, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("rotto")

    monkeypatch.setattr("app.notifications.bulletins.BulletinService._notify", boom)
    with TestClient(started(settings, clock, service)) as c:
        log_in(c)
        run_id = run_to_done(c)
        wait(lambda: notifications(c, run_id))
        assert bulletins(c, run_id) == []
        assert c.get(f"/api/runs/{run_id}").json()["run"]["state"] == "DONE"


def test_senza_il_file_dei_destinatari_l_app_parte_e_i_run_funzionano(
    settings: Settings, clock: FakeClock, service: Service, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    def unreadable(*_: object, **__: object) -> None:
        raise OSError("manca")

    monkeypatch.setattr("app.api.context.EmergencyServicesConfig.from_yaml", unreadable)
    with caplog.at_level("ERROR"), TestClient(started(settings, clock, service)) as c:
        log_in(c)
        assert ctx_of(c.app).runs._bulletins is None  # type: ignore[arg-type]  # noqa: SLF001
        run_id = run_to_done(c)
        wait(lambda: notifications(c, run_id))  # il WhatsApp parte lo stesso
        assert bulletins(c, run_id) == []
    assert "emergency_services.yaml non letto" in caplog.text


def ack(c: TestClient, notification_id: int) -> Any:
    return c.post(f"/api/notifications/{notification_id}/ack")


def test_la_conferma_di_ricezione(wa: TestClient) -> None:
    run_id = run_to_done(wa)
    wait(lambda: bulletins(wa, run_id))
    first, second, *_ = bulletins(wa, run_id)
    response = ack(wa, first["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ACKNOWLEDGED" and body["id"] == first["id"]
    assert body["text"] == first["text"] and body["simulation"] is True
    states = {r["id"]: r["state"] for r in bulletins(wa, run_id)}
    assert states[first["id"]] == "ACKNOWLEDGED" and states[second["id"]] == "DELIVERED"
    decisions = wa.get(f"/api/runs/{run_id}/decisions").json()
    mine = [d for d in decisions if d["actor"] == "user" and "bollettino" in d["decision"]]
    assert [d["rationale"] for d in mine] == [first["recipient_label"]]


def test_una_seconda_conferma_e_un_conflitto_con_lo_stato(wa: TestClient) -> None:
    run_id = run_to_done(wa)
    wait(lambda: bulletins(wa, run_id))
    notification_id = bulletins(wa, run_id)[0]["id"]
    assert ack(wa, notification_id).status_code == 200
    again = ack(wa, notification_id)
    assert again.status_code == 409
    error = again.json()["error"]
    assert error["code"] == "NOT_ACKNOWLEDGEABLE" and error["details"] == {"state": "ACKNOWLEDGED"}


def test_il_whatsapp_non_si_conferma(wa: TestClient) -> None:
    run_id = run_to_done(wa)
    wait(lambda: notifications(wa, run_id))
    whatsapp_id = notifications(wa, run_id)[0]["id"]
    response = ack(wa, whatsapp_id)
    assert response.status_code == 409 and response.json()["error"]["details"] == {"state": "SENT"}


def test_conferma_di_una_notifica_che_non_esiste(authed: TestClient) -> None:
    response = ack(authed, 424242)
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
    assert authed.post("/api/notifications/abc/ack").status_code == 400


def test_conferma_senza_sessione_401(client: TestClient) -> None:
    assert client.post("/api/notifications/1/ack").status_code == 401


def test_i_bollettini_non_mostrano_numero_ne_chiavi(wa: TestClient) -> None:
    run_id = run_to_done(wa)
    wait(lambda: bulletins(wa, run_id) and notifications(wa, run_id))
    everything = (
        wa.get(f"/api/runs/{run_id}/notifications").text + wa.get(f"/api/runs/{run_id}/export").text
    )
    for secret in (NUMBER, NUMBER.lstrip("+"), "3331234512", APIKEY):
        assert secret not in everything
