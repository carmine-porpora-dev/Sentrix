import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import PASSWORD, SESSION_SECRET, FakeClock, client_from, log_in

PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
}


def _protected_routes() -> list[tuple[str, str]]:
    schema = create_app().openapi()
    found = [
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if "security" in operation
    ]
    return sorted(found)


PROTECTED = _protected_routes()


def test_le_rotte_protette_sono_tutte_tranne_le_quattro_pubbliche() -> None:
    schema = create_app().openapi()
    everything = {(m.upper(), p) for p, ops in schema["paths"].items() for m in ops}
    assert len(everything) == 29  # tutte le operazioni di 06
    assert set(PROTECTED) == everything - PUBLIC
    assert len(PROTECTED) == 25  # non zero per sbaglio


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_senza_sessione_401(client: TestClient, method: str, path: str) -> None:
    url = re.sub(r"\{[^}]+\}", "x", path)
    # Corpo vuoto di proposito: l'accesso si controlla PRIMA della validazione (401, non 400).
    response = client.request(method, url, json={} if method in ("POST", "PUT") else None)
    assert response.status_code == 401, (method, path, response.text)
    assert response.json() == {
        "error": {
            "code": "UNAUTHENTICATED",
            "message": "Accesso richiesto: effettua il login",
            "details": {},
        }
    }


def test_health_non_richiede_sessione(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


# --- login -----------------------------------------------------------------------------------


def test_login_riuscito_imposta_il_cookie_giusto(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("napoli_session=v1.")
    for attribute in ("HttpOnly", "Max-Age=43200", "Path=/", "SameSite=lax"):
        assert attribute in cookie, cookie
    assert "Secure" not in cookie  # in locale si lavora su http
    assert PASSWORD not in response.text + cookie


def test_in_produzione_il_cookie_e_secure(settings: Settings, clock: FakeClock) -> None:
    production = create_app(replace(settings, env="production"), clock=clock)
    with TestClient(production) as c:
        response = c.post("/api/auth/login", json={"password": PASSWORD})
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_con_la_sessione_si_entra(authed: TestClient) -> None:
    assert authed.get("/api/auth/me").json() == {"authenticated": True}
    assert authed.get("/api/events").status_code == 200


def test_me_senza_sessione_e_false_ma_risponde_200(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert (response.status_code, response.json()) == (200, {"authenticated": False})


def test_password_errata(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": "sbagliata"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_PASSWORD"
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").json() == {"authenticated": False}


def test_password_quasi_giusta_e_sbagliata(client: TestClient) -> None:
    for almost in (PASSWORD[:-1], PASSWORD + "x", PASSWORD.upper(), " " + PASSWORD):
        assert client.post("/api/auth/login", json={"password": almost}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"password": ""},
        {"password": 123},
        {"password": None},
        {"password": PASSWORD, "extra": 1},
        [PASSWORD],
    ],
)
def test_corpo_non_valido_400(client: TestClient, body: object) -> None:
    response = client.post("/api/auth/login", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert PASSWORD not in response.text


def test_corpo_non_json_400(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", content=b"password=abc", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400


def test_password_con_caratteri_non_ascii(settings: Settings, clock: FakeClock) -> None:
    unicode_app = create_app(replace(settings, app_password="päss-wörd-€-日本"), clock=clock)
    with TestClient(unicode_app) as c:
        assert c.post("/api/auth/login", json={"password": "päss-wörd-€-日本"}).status_code == 200
        assert c.post("/api/auth/login", json={"password": "pass-word"}).status_code == 401


def test_nessun_segreto_nei_log(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client.post("/api/auth/login", json={"password": "tentativo-errato-fake"})
    client.post("/api/auth/login", json={"password": PASSWORD})
    assert "tentativo-errato-fake" not in caplog.text
    assert PASSWORD not in caplog.text and SESSION_SECRET not in caplog.text


# --- sessione --------------------------------------------------------------------------------


def test_logout_chiude_la_sessione_anche_se_il_cookie_viene_rimandato(
    app: FastAPI, authed: TestClient
) -> None:
    token = authed.cookies.get("napoli_session")
    assert token
    response = authed.post("/api/auth/logout")
    assert (response.status_code, response.json()) == (200, {"authenticated": False})
    assert (
        'napoli_session=""' in response.headers["set-cookie"]
        or "Max-Age=0" in (response.headers["set-cookie"])
    )
    assert authed.get("/api/events").status_code == 401
    # Chi si è copiato il cookie prima del logout non può più usarlo (revoca sul server).
    thief = client_from(app, "10.9.9.9")
    thief.cookies.set("napoli_session", token)
    assert thief.get("/api/auth/me").json() == {"authenticated": False}
    assert thief.get("/api/events").status_code == 401


def test_logout_senza_sessione_non_da_errore(client: TestClient) -> None:
    assert client.post("/api/auth/logout").status_code == 200


def test_cookie_manomesso_401(app: FastAPI, authed: TestClient) -> None:
    token = authed.cookies.get("napoli_session")
    assert token
    version, sid, expires, signature = token.split(".")
    other = client_from(app, "10.1.1.1")
    for forged in (
        f"{version}.{sid}.{int(expires) + 86400}.{signature}",  # scadenza allungata
        f"{version}.altra-sessione.{expires}.{signature}",
        f"{version}.{sid}.{expires}.{signature[::-1]}",
        "garbage",
    ):
        other.cookies.set("napoli_session", forged)
        assert other.get("/api/events").status_code == 401, forged


def test_il_cookie_di_un_altro_server_non_vale(settings: Settings, clock: FakeClock) -> None:
    first = create_app(settings, clock=clock)
    second = create_app(replace(settings, session_secret="fake-un-altro-segreto"), clock=clock)
    with TestClient(first) as a, TestClient(second) as b:
        log_in(a)
        b.cookies.set("napoli_session", a.cookies.get("napoli_session") or "")
        assert b.get("/api/events").status_code == 401


def test_la_sessione_dura_12_ore_esatte(authed: TestClient, clock: FakeClock) -> None:
    clock.advance(12 * 3600 - 1)
    assert authed.get("/api/events").status_code == 200
    clock.advance(1)
    assert authed.get("/api/events").status_code == 401
    assert authed.get("/api/auth/me").json() == {"authenticated": False}


def test_due_sessioni_sono_indipendenti(app: FastAPI, authed: TestClient) -> None:
    second = client_from(app, "10.2.2.2")
    log_in(second)
    authed.post("/api/auth/logout")
    assert second.get("/api/events").status_code == 200


# --- limite dei tentativi --------------------------------------------------------------------


def _fail(client: TestClient) -> int:
    return client.post("/api/auth/login", json={"password": "sbagliata"}).status_code


def test_cinque_errori_poi_429(client: TestClient) -> None:
    assert [_fail(client) for _ in range(5)] == [401] * 5
    response = client.post("/api/auth/login", json={"password": "sbagliata"})
    assert response.status_code == 429
    body = response.json()["error"]
    assert body["code"] == "RATE_LIMITED"
    assert body["details"] == {"retry_after_s": 60}
    assert response.headers["retry-after"] == "60"


def test_dopo_cinque_errori_anche_la_password_giusta_aspetta(client: TestClient) -> None:
    for _ in range(5):
        _fail(client)
    response = client.post("/api/auth/login", json={"password": PASSWORD})
    assert response.status_code == 429  # altrimenti la forza bruta non avrebbe limite
    assert "set-cookie" not in response.headers


def test_il_blocco_finisce_dopo_un_minuto(client: TestClient, clock: FakeClock) -> None:
    for _ in range(5):
        _fail(client)
    clock.advance(59)
    blocked = client.post("/api/auth/login", json={"password": PASSWORD})
    assert (blocked.status_code, blocked.headers["retry-after"]) == (429, "1")
    clock.advance(1)
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200


def test_il_limite_e_per_indirizzo_ip(app: FastAPI, client: TestClient) -> None:
    for _ in range(5):
        _fail(client)
    assert _fail(client) == 429
    elsewhere = client_from(app, "203.0.113.7")
    assert _fail(elsewhere) == 401  # un altro IP non è bloccato
    log_in(elsewhere)


def test_gli_accessi_riusciti_non_consumano_tentativi(client: TestClient) -> None:
    for _ in range(12):
        log_in(client)
    for _ in range(4):
        _fail(client)
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200


def test_quattro_errori_e_poi_un_accesso_lasciano_un_tentativo(client: TestClient) -> None:
    for _ in range(4):
        _fail(client)
    log_in(client)
    assert _fail(client) == 401  # il quinto errore passa ancora (il login riuscito non conta)
    assert _fail(client) == 429


def test_raffica_di_tentativi_in_parallelo(client: TestClient) -> None:
    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(lambda _: _fail(client), range(20)))
    assert statuses.count(401) == 5  # esattamente il limite, non uno di più
    assert statuses.count(429) == 15


# --- accesso non configurato -----------------------------------------------------------------


@pytest.mark.parametrize("missing", ["app_password", "session_secret", "both"])
def test_senza_password_o_segreto_nessuno_entra(
    settings: Settings, clock: FakeClock, missing: str
) -> None:
    changes: dict[str, Any] = {"app_password": None, "session_secret": None}
    if missing != "both":
        changes = {missing: None}
    closed = create_app(replace(settings, **changes), clock=clock)
    with TestClient(closed) as c:
        response = c.post("/api/auth/login", json={"password": PASSWORD})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"
        assert c.get("/api/auth/me").json() == {"authenticated": False}
        assert c.get("/api/events").status_code == 401
        assert "auth" in c.get("/api/health").json()["degraded"]
