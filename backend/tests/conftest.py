import threading
import time
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.orchestrator_support import engines_with
from tests.support import GTFS_FIXTURE, FeedServer


@pytest.fixture
def server(tmp_path: Path) -> Iterator[FeedServer]:
    zip_path = tmp_path / "served.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(GTFS_FIXTURE.glob("*.txt")):
            archive.write(path, path.name)
    info = FeedServer(url="", zip_bytes=zip_path.read_bytes())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (nome imposto da BaseHTTPRequestHandler)
            info.user_agents.append(self.headers.get("User-Agent", ""))
            self._route(send_body=True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._route(send_body=False)

        def _route(self, *, send_body: bool) -> None:
            if self.path == "/redirect":
                self.send_response(301)
                self.send_header("Location", "/feed.zip")
                self.end_headers()
            elif self.path == "/feed.zip":
                self._send(200, info.zip_bytes, "application/zip", send_body)
            elif self.path == "/garbage":
                self._send(200, b"<html>not a zip</html>", "text/html", send_body)
            elif self.path == "/forbidden":
                self.send_error(403)
            elif self.path == "/boom":
                self.send_error(500)
            else:
                self.send_error(404)

        def _send(self, status: int, body: bytes, content_type: str, send_body: bool) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if send_body:
                self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # silenzia il log
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    info.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    yield info
    httpd.shutdown()
    httpd.server_close()


# --- API -----------------------------------------------------------------------------------------
# Valori finti ("fake": parola d'ordine di gitleaks per i segreti di prova).
PASSWORD = "fake-app-password"
SESSION_SECRET = "fake-session-secret"


class FakeClock:
    """Orologio che avanza solo quando lo si dice: sessioni e limiti si provano senza attese."""

    def __init__(self) -> None:
        self.now = time.time()  # il cookie del client scade con l'ora vera: si parte da lì

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        env="local",
        data_dir=tmp_path / "data",
        app_password=PASSWORD,
        session_secret=SESSION_SECRET,
    )


@pytest.fixture
def app(settings: Settings, clock: FakeClock) -> FastAPI:
    # motori finti senza criticità: un run parte, non ha nulla da fare e finisce subito
    return create_app(settings, clock=clock, engines=engines_with(()))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Client senza sessione. L'app parte (database e preset) una volta sola, qui."""
    with TestClient(app) as test_client:
        yield test_client


def client_from(app: FastAPI, host: str) -> TestClient:
    """Un altro client sulla STESSA app già avviata (stessi limiti, sessioni e database), con un
    altro indirizzo IP e un altro cookie jar. Senza `with`: l'avvio non si ripete."""
    return TestClient(app, client=(host, 40000))


def log_in(test_client: TestClient) -> None:
    response = test_client.post("/api/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200, response.text


@pytest.fixture
def authed(client: TestClient) -> TestClient:
    log_in(client)
    return client
