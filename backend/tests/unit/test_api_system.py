import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.base import WhatsAppMode, WhatsAppProvider
from app.settings import Settings, WhatsAppSettings
from tests.conftest import PASSWORD, SESSION_SECRET, FakeClock

# --- formato degli errori --------------------------------------------------------------------


def test_rotta_inesistente_404_nel_formato_comune(client: TestClient) -> None:
    response = client.get("/api/non-esiste")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "Risorsa non trovata", "details": {}}
    }


def test_metodo_sbagliato_405(client: TestClient) -> None:
    response = client.delete("/api/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_errore_di_validazione_ha_i_campi_con_il_percorso(authed: TestClient) -> None:
    response = authed.post("/api/runs", json={"event_id": "Non Slug", "attendance_level": "alto"})
    assert response.status_code == 400
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("VALIDATION_ERROR", "La richiesta non è valida")
    paths = {field["path"]: field for field in error["details"]["fields"]}
    assert set(paths) == {"event_id", "attendance_level"}  # senza il prefisso «body»
    assert all(field["message"] and field["type"] for field in paths.values())


def test_errore_su_parametro_di_query(authed: TestClient) -> None:
    response = authed.get("/api/runs/x/metrics", params={"iteration": "tre"})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"][0]["path"] == "iteration"


def test_errore_imprevisto_500_senza_dettagli(
    app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("password-del-database-fake")

    with TestClient(app, raise_server_exceptions=False) as c, caplog.at_level(logging.ERROR):
        response = c.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "Errore interno del server", "details": {}}
    }
    assert "password-del-database-fake" not in response.text  # il dettaglio resta nel log
    assert "password-del-database-fake" in caplog.text


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_la_documentazione_interattiva_non_e_esposta(
    client: TestClient, authed: TestClient, path: str
) -> None:
    assert client.get(path).status_code in (404, 401)
    assert authed.get(path).status_code == 404  # nemmeno con la sessione: il file è il contratto


# --- health ----------------------------------------------------------------------------------


def test_health_senza_dati_e_degradato(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["env"] == "local"
    assert body["data"] == {
        "osm": False,
        "gtfs": False,
        "pmtiles": False,
        "tomtom_key_present": False,
        "gemini_key_present": False,
        "whatsapp_configured": False,
        "whatsapp_provider": "callmebot",
    }
    assert body["degraded"] == ["osm", "gtfs", "pmtiles"]
    assert set(body["versions"]) == {"python", "fastapi", "pydantic", "db_schema"}
    assert body["versions"]["db_schema"] == "1"


def test_health_con_tutti_i_dati_e_ok(settings: Settings, clock: FakeClock) -> None:
    data = settings.data_dir
    (data / "osm").mkdir(parents=True)
    (data / "osm" / "graph_drive.graphml").write_text("x")
    (data / "gtfs" / "anm").mkdir(parents=True)
    (data / "tiles").mkdir()
    (data / "tiles" / "napoli.pmtiles").write_bytes(b"PMTiles")
    full = replace(settings, tomtom_key_present=True, gemini_key_present=True)
    with TestClient(create_app(full, clock=clock)) as c:
        body = c.get("/api/health").json()
    assert body["status"] == "ok" and body["degraded"] == []
    assert body["data"] == {
        "osm": True,
        "gtfs": True,
        "pmtiles": True,
        "tomtom_key_present": True,
        "gemini_key_present": True,
        "whatsapp_configured": False,
        "whatsapp_provider": "callmebot",
    }


@pytest.mark.parametrize("missing", ["osm", "gtfs", "pmtiles"])
def test_health_dice_quale_fonte_manca(settings: Settings, clock: FakeClock, missing: str) -> None:
    data = settings.data_dir
    paths = {
        "osm": data / "osm" / "graph_drive.graphml",
        "gtfs": data / "gtfs" / "anm",
        "pmtiles": data / "tiles" / "napoli.pmtiles",
    }
    for name, path in paths.items():
        if name == missing:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir() if name == "gtfs" else path.write_bytes(b"x")
    with TestClient(create_app(settings, clock=clock)) as c:
        body = c.get("/api/health").json()
    assert (body["status"], body["degraded"]) == ("degraded", [missing])


def _health_data(settings: Settings, clock: FakeClock) -> dict[str, object]:
    with TestClient(create_app(settings, clock=clock)) as c:
        return dict(c.get("/api/health").json()["data"])


@pytest.mark.parametrize(
    ("mode", "provider", "keys", "configured"),
    [
        ("live", "callmebot", {"to": "+393331234512", "callmebot_apikey": "k-fake"}, True),
        ("live", "callmebot", {"to": "+393331234512"}, False),  # manca la chiave
        ("off", "callmebot", {"to": "+393331234512", "callmebot_apikey": "k-fake"}, False),
        ("live", "meta", {"to": "+393331234512", "callmebot_apikey": "k-fake"}, False),
        (
            "live",
            "meta",
            {"to": "+393331234512", "token": "t", "phone_number_id": "1", "api_version": "v21.0"},
            True,
        ),
    ],
)
def test_health_dice_se_whatsapp_e_configurato_e_con_quale_servizio(
    settings: Settings,
    clock: FakeClock,
    mode: WhatsAppMode,
    provider: WhatsAppProvider,
    keys: dict[str, Any],
    configured: bool,
) -> None:
    whatsapp = WhatsAppSettings(mode=mode, provider=provider, **keys)
    data = _health_data(replace(settings, whatsapp=whatsapp), clock)
    assert data["whatsapp_configured"] is configured
    assert data["whatsapp_provider"] == provider


def test_health_non_espone_numero_e_chiavi_di_whatsapp(
    settings: Settings, clock: FakeClock
) -> None:
    whatsapp = WhatsAppSettings(
        mode="live",
        to="+393331234512",
        callmebot_apikey="chiave-fake-123456",
        token="tok-fake-1234",
    )
    with TestClient(create_app(replace(settings, whatsapp=whatsapp), clock=clock)) as c:
        text = c.get("/api/health").text
    for secret in ("393331234512", "chiave-fake-123456", "tok-fake-1234"):
        assert secret not in text


def test_health_non_espone_segreti(settings: Settings, clock: FakeClock) -> None:
    secret_settings = replace(settings, tomtom_key_present=True, gemini_key_present=True)
    with TestClient(create_app(secret_settings, clock=clock)) as c:
        text = c.get("/api/health").text
    for secret in (PASSWORD, SESSION_SECRET, str(settings.data_dir)):
        assert secret not in text


# --- tiles -----------------------------------------------------------------------------------


@pytest.fixture
def tiles_file(settings: Settings) -> bytes:
    content = bytes(range(256)) * 40
    path = settings.data_dir / "tiles" / "napoli.pmtiles"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return content


def test_tiles_richiedono_la_sessione(client: TestClient, tiles_file: bytes) -> None:
    assert client.get("/tiles/napoli.pmtiles").status_code == 401


def test_tiles_file_intero(authed: TestClient, tiles_file: bytes) -> None:
    response = authed.get("/tiles/napoli.pmtiles")
    assert response.status_code == 200
    assert response.content == tiles_file
    assert response.headers["accept-ranges"] == "bytes"


def test_tiles_a_pezzi_con_range(authed: TestClient, tiles_file: bytes) -> None:
    response = authed.get("/tiles/napoli.pmtiles", headers={"Range": "bytes=100-199"})
    assert response.status_code == 206
    assert response.content == tiles_file[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{len(tiles_file)}"
    tail = authed.get("/tiles/napoli.pmtiles", headers={"Range": "bytes=-16"})
    assert tail.status_code == 206 and tail.content == tiles_file[-16:]


def test_tiles_assenti_404(authed: TestClient) -> None:
    response = authed.get("/tiles/napoli.pmtiles")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- LIVE (la logica è provata in test_live_flow.py) ---------------------------------------------


def test_live_senza_chiave_dice_unavailable_e_perche(authed: TestClient) -> None:
    """Nei test non c'è una chiave TomTom: dalla vista LIVE si dice «chiave mancante», e senza
    l'header che la richiesta non viene dalla vista LIVE. Mai un numero inventato (principio 1)."""
    live = authed.get("/api/live/flow", headers={"X-View": "live"})
    assert live.status_code == 200
    assert live.json() == {
        "segments": [],
        "mode": "unavailable",
        "degraded_reason": "tomtom_key_missing",
        "summary": [],
    }
    other = authed.get("/api/live/flow")
    assert other.json() == {
        "segments": [],
        "mode": "unavailable",
        "degraded_reason": "live_view_required",
        "summary": [],
    }


def test_live_rifiuta_un_x_view_sconosciuto(authed: TestClient) -> None:
    assert authed.get("/api/live/flow", headers={"X-View": "altro"}).status_code == 400


def test_live_non_scrive_nulla_su_disco(authed: TestClient, settings: Settings) -> None:
    authed.get("/api/live/flow", headers={"X-View": "live"})
    assert not (settings.data_dir / "tomtom").exists()  # niente snapshot finché non c'è F8


def test_i_dati_non_toccano_la_cartella_dei_dati_oltre_al_database(
    authed: TestClient, settings: Settings
) -> None:
    authed.get("/api/health")
    authed.get("/api/events")
    names = {path.name for path in Path(settings.data_dir).iterdir()}
    assert names <= {"napoli.db", "napoli.db-wal", "napoli.db-shm"}


# --- avvio normale: ambiente e file .env ---------------------------------------------------------


def test_l_avvio_normale_legge_l_ambiente_e_il_file_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Senza impostazioni passate (come con `uvicorn app.main:app`) l'app carica `.env` e poi legge
    l'ambiente; una variabile già nell'ambiente vince su quella del file."""
    loaded: list[bool] = []

    def fake_load_env_file() -> None:
        loaded.append(True)
        monkeypatch.setenv("APP_PASSWORD", "fake-dal-file-env")  # come farebbe load_dotenv
        monkeypatch.setenv("SESSION_SECRET", "fake-segreto-dal-file-env")

    monkeypatch.setattr("app.main.load_env_file", fake_load_env_file)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "dati"))
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TOMTOM_API_KEY", "fake-chiave-tomtom")
    with TestClient(create_app()) as c:
        assert loaded == [True]
        health = c.get("/api/health").json()
        assert health["env"] == "production"
        assert health["data"]["tomtom_key_present"] is True
        assert (tmp_path / "dati" / "napoli.db").is_file()  # il database sta in DATA_DIR
        assert c.post("/api/auth/login", json={"password": "fake-dal-file-env"}).status_code == 200


def test_l_avvio_con_env_non_valido_si_ferma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.load_env_file", lambda: None)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENV", "staging")
    with pytest.raises(Exception, match="staging"), TestClient(create_app()):
        pass
