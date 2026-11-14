import re
from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.conftest import FakeClock
from tests.orchestrator_support import engines_with
from tests.unit.test_api_auth import PROTECTED


def public_app(settings: Settings, clock: FakeClock) -> FastAPI:
    return create_app(replace(settings, public_access=True), clock=clock, engines=engines_with(()))


@pytest.fixture
def public(settings: Settings, clock: FakeClock) -> Iterator[TestClient]:
    with TestClient(public_app(settings, clock)) as client:
        yield client


@pytest.fixture
def public_without_password(settings: Settings, clock: FakeClock) -> Iterator[TestClient]:
    """Come sulla VM se `.env` non avesse né password né segreto: l'accesso libero basta."""
    bare = replace(settings, public_access=True, app_password=None, session_secret=None)
    with TestClient(create_app(bare, clock=clock, engines=engines_with(()))) as client:
        yield client


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_nessuna_rotta_chiede_la_sessione(public: TestClient, method: str, path: str) -> None:
    url = re.sub(r"\{[^}]+\}", "x", path)
    response = public.request(method, url, json={} if method in ("POST", "PUT") else None)
    assert response.status_code != 401, (method, path, response.text)


def test_senza_password_ne_segreto_entrano_tutti(public_without_password: TestClient) -> None:
    assert public_without_password.get("/api/events").status_code == 200
    assert public_without_password.get("/api/auth/me").json() == {
        "authenticated": True,
        "public_access": True,
    }


def test_me_dice_che_l_accesso_e_libero(public: TestClient) -> None:
    assert public.get("/api/auth/me").json() == {"authenticated": True, "public_access": True}


def test_il_login_non_chiede_nulla_e_non_da_nessun_cookie(public: TestClient) -> None:
    for body in ({"password": "qualunque"}, {"password": "sbagliata"}):
        response = public.post("/api/auth/login", json=body)
        assert response.status_code == 200
        assert response.json() == {"authenticated": True, "public_access": True}
        assert "set-cookie" not in response.headers


def test_uscire_non_chiude_nulla(public: TestClient) -> None:
    response = public.post("/api/auth/logout")
    assert response.json() == {"authenticated": True, "public_access": True}
    assert public.get("/api/events").status_code == 200  # ancora aperto


def test_la_mappa_di_base_si_serve_senza_sessione(public: TestClient) -> None:
    """`/tiles/napoli.pmtiles` era dietro la sessione come le API. Senza il file risponde 404 (non
    401): la rotta è raggiunta."""
    assert public.get("/tiles/napoli.pmtiles").status_code in (200, 206, 404)


def test_la_salute_non_segnala_l_accesso_come_degradato(
    public_without_password: TestClient,
) -> None:
    assert "auth" not in public_without_password.get("/api/health").json()["degraded"]


def test_i_limiti_delle_analisi_restano_e_sono_condivisi(public: TestClient) -> None:
    """Senza sessioni il limite «per sessione» (3 al minuto) vale per tutti i visitatori insieme: la
    quarta analisi in un minuto è respinta anche se viene da un altro (il tetto alla spesa resta)"""
    body = {"event_id": "match_2027", "attendance_level": "mid", "manual_response": False}
    codes = [public.post("/api/runs", json=body).status_code for _ in range(4)]
    assert codes[:3] == [202, 202, 202]
    assert codes[3] == 429


def test_con_l_accesso_protetto_nulla_cambia(settings: Settings, clock: FakeClock) -> None:
    """Il predefinito: senza sessione 401, `me` non dice `public_access`."""
    app = create_app(settings, clock=clock, engines=engines_with(()))
    with TestClient(app) as client:
        assert client.get("/api/events").status_code == 401
        # il campo `public_access` non si scrive quando è falso: la risposta è quella di sempre
        assert client.get("/api/auth/me").json() == {"authenticated": False}
        assert client.post("/api/auth/login", json={"password": "sbagliata"}).status_code == 401
