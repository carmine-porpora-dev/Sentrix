from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.frontend import CACHE_HASHED, CACHE_REVALIDATE
from app.main import create_app
from app.settings import Settings
from tests.conftest import FakeClock, engines_with

INDEX = "<!doctype html><title>Sentrix</title>"
ASSET = "console.log('app')"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    folder = tmp_path / "dist"
    (folder / "assets").mkdir(parents=True)
    (folder / "licenses").mkdir()
    (folder / "index.html").write_text(INDEX, encoding="utf-8")
    (folder / "assets" / "index-1a2b3c.js").write_text(ASSET, encoding="utf-8")
    (folder / "licenses" / "OFL.txt").write_text("licenza", encoding="utf-8")
    (tmp_path / "segreto.txt").write_text("fuori da dist", encoding="utf-8")
    return folder


def _client(settings: Settings, clock: FakeClock, frontend_dir: Path) -> Iterator[TestClient]:
    app = create_app(settings, clock=clock, engines=engines_with(()), frontend_dir=frontend_dir)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def web(settings: Settings, clock: FakeClock, dist: Path) -> Iterator[TestClient]:
    yield from _client(settings, clock, dist)


def test_la_radice_e_l_interfaccia_e_non_vuole_la_sessione(web: TestClient) -> None:
    response = web.get("/")
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")


def test_i_file_con_l_hash_si_tengono_per_sempre_il_resto_si_riconferma(web: TestClient) -> None:
    asset = web.get("/assets/index-1a2b3c.js")
    assert (asset.status_code, asset.text) == (200, ASSET)
    assert asset.headers["cache-control"] == CACHE_HASHED
    for path in ("/", "/index.html", "/licenses/OFL.txt"):
        response = web.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == CACHE_REVALIDATE, path


def test_le_api_restano_api(web: TestClient) -> None:
    health = web.get("/api/health")
    assert health.status_code == 200
    assert health.json()["data"]["osm"] is False  # JSON dell'API, non l'interfaccia
    # un'API che non c'è è un errore nel formato comune, non la pagina dell'interfaccia
    missing = web.get("/api/non-esiste")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert web.delete("/api/health").status_code == 405


def test_le_api_vogliono_ancora_la_sessione(web: TestClient) -> None:
    assert web.get("/api/events").status_code == 401
    assert web.get("/tiles/napoli.pmtiles").status_code == 401


def test_un_percorso_che_non_esiste_e_404_nel_formato_comune(web: TestClient) -> None:
    response = web.get("/non-esiste.js")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("path", ["/../segreto.txt", "/%2e%2e/segreto.txt", "/..%2fsegreto.txt"])
def test_non_si_esce_dalla_cartella(web: TestClient, path: str) -> None:
    response = web.get(path)
    assert response.status_code == 404
    assert "fuori da dist" not in response.text


def test_senza_la_cartella_l_app_parte_e_risponde_404(
    settings: Settings, clock: FakeClock, tmp_path: Path
) -> None:
    for client in _client(settings, clock, tmp_path / "non-compilato"):
        assert client.get("/").status_code == 404
        assert client.get("/api/health").status_code == 200
