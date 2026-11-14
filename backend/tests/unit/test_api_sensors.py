import ast
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.data.paths import REPO_ROOT
from app.main import create_app
from app.models.sensors import PlannedSensor, SensorsConfig
from app.settings import Settings
from tests.conftest import FakeClock, log_in
from tests.orchestrator_support import engines_with

PATH = "/api/sensors"


def test_senza_sessione_401(client: TestClient) -> None:
    response = client.get(PATH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_con_la_sessione_l_elenco_e_quello_del_file(authed: TestClient) -> None:
    response = authed.get(PATH)
    assert response.status_code == 200
    body = response.json()
    expected = SensorsConfig.from_yaml().sensors
    assert [s["id"] for s in body] == [s.id for s in expected]  # nell'ordine del file
    assert [PlannedSensor.model_validate(s) for s in body] == expected  # lo stesso modello


def test_la_risposta_non_ha_numeri_ne_misure(authed: TestClient) -> None:
    """11.5: nessun `Measured`, nessun valore: tipo, stato, posto, cosa misura, cosa sostituisce."""
    for item in authed.get(PATH).json():
        assert set(item) == {
            "id", "type", "name", "status", "location", "route_class", "measures", "replaces",
        }  # fmt: skip
        assert item["status"] == "planned"
        location = item["location"]
        assert location is None or set(location) == {"lat", "lon", "label"}


def test_solo_lettura(authed: TestClient) -> None:
    for method in ("post", "put", "delete", "patch"):
        response = authed.request(method.upper(), PATH, json={})
        assert response.status_code == 405, method
        assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_non_serve_l_header_live_e_non_cambia_tra_due_richieste(authed: TestClient) -> None:
    assert authed.get(PATH).json() == authed.get(PATH, headers={"X-View": "live"}).json()


def test_il_contratto_descrive_l_operazione() -> None:
    operation = create_app().openapi()["paths"][PATH]["get"]
    assert operation["operationId"] == "list_sensors"
    assert operation["security"] == [{"APIKeyCookie": []}]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/PlannedSensor"},
        "title": schema["title"],
    }
    assert {"401", "503"} <= set(operation["responses"])


# --- un file illeggibile non ferma il server -----------------------------------------------------


@pytest.fixture(params=["rotto", "mancante", "valori_non_validi"])
def broken(
    request: pytest.FixtureRequest,
    settings: Settings,
    clock: FakeClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    path = tmp_path / "sensors.yaml"
    if request.param == "rotto":
        path.write_text("sensors: [\n  { id: x", encoding="utf-8")
    elif request.param == "valori_non_validi":
        path.write_text("sensors:\n  - { id: x, type: camera }\n", encoding="utf-8")
    monkeypatch.setattr(SensorsConfig, "DEFAULT_PATH", path)  # `mancante`: il file non esiste
    app = create_app(settings, clock=clock, engines=engines_with(()))
    with TestClient(app) as client:
        log_in(client)
        yield client


def test_con_il_file_illeggibile_il_server_parte_e_solo_i_sensori_rispondono_503(
    broken: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = broken.get(PATH)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DATA_UNAVAILABLE"
    assert "sensori" in error["message"]
    assert "/" not in error["message"] and "yaml" not in error["message"].lower()  # nessun percorso


def test_con_il_file_illeggibile_scenario_e_live_funzionano(broken: TestClient) -> None:
    assert broken.get("/api/health").status_code == 200
    assert broken.get("/api/events").status_code == 200
    live = broken.get("/api/live/flow", headers={"X-View": "live"})
    assert live.status_code == 200  # senza chiave TomTom: «unavailable», ma risponde
    assert live.json()["mode"] == "unavailable"


def test_il_problema_si_legge_nel_log(
    settings: Settings,
    clock: FakeClock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "sensors.yaml"
    path.write_text("sensors: []\n", encoding="utf-8")  # vuoto: non valido
    monkeypatch.setattr(SensorsConfig, "DEFAULT_PATH", path)
    app = create_app(settings, clock=clock, engines=engines_with(()))
    with caplog.at_level(logging.ERROR, logger="app.api.context"), TestClient(app):
        pass
    assert any("sensors.yaml" in record.getMessage() for record in caplog.records)


# --- il motore non legge i sensori: la cache demo resta valida ----------------------------------

# I moduli che decidono i numeri, i prompt e le richieste: i sensori previsti non devono entrarci,
# né nel codice né nell'hash dei run (`params_hash`) né nelle chiavi della cache LLM.
PROTECTED_PACKAGES = ("engine", "agents", "llm", "orchestrator", "operations")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


@pytest.mark.parametrize("package", PROTECTED_PACKAGES)
def test_motore_agenti_llm_orchestratore_e_operations_non_importano_i_sensori(package: str) -> None:
    files = sorted((REPO_ROOT / "backend" / "app" / package).rglob("*.py"))
    assert files  # non zero per sbaglio
    for file in files:
        offending = {m for m in imported_modules(file) if "sensors" in m}
        assert not offending, (file.name, offending)


def test_i_sensori_non_entrano_nell_hash_dei_run() -> None:
    """`params_hash` è l'hash dei file di config che decidono il risultato: non c'è `sensors`."""
    source = (REPO_ROOT / "backend" / "app" / "orchestrator" / "service.py").read_text("utf-8")
    assert "sensors" not in source
