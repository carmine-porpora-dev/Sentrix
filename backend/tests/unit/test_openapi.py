import json
from pathlib import Path
from typing import Any

import pytest

from app.main import app
from scripts import export_openapi

# Le 29 operazioni di docs/spec/06-api.md, scritte a mano dalla spec (non lette dal codice).
SPEC_OPERATIONS = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/health"),
    ("GET", "/api/events"),
    ("GET", "/api/events/{event_id}"),
    ("POST", "/api/events"),
    ("PUT", "/api/events/{event_id}"),
    ("POST", "/api/events/{event_id}/reset"),
    ("POST", "/api/events/{event_id}/resolve"),
    ("GET", "/api/network/edges"),
    ("GET", "/api/transit/stops"),
    ("GET", "/api/transit/lines"),
    ("GET", "/tiles/napoli.pmtiles"),
    ("POST", "/api/runs"),
    ("GET", "/api/runs/{run_id}"),
    ("GET", "/api/runs/{run_id}/metrics"),
    ("GET", "/api/runs/{run_id}/layers/{layer}"),
    ("GET", "/api/runs/{run_id}/decisions"),
    ("GET", "/api/runs/{run_id}/notifications"),
    ("POST", "/api/notifications/{notification_id}/ack"),
    ("GET", "/api/runs/{run_id}/export"),  # json e csv: una sola operazione, due formati
    ("GET", "/api/runs"),
    ("GET", "/api/vdept"),
    ("POST", "/api/vdept/{dept_id}/requests"),
    ("GET", "/api/vdept/{dept_id}/requests/{action_id}"),
    ("POST", "/api/vdept/{dept_id}/requests/{action_id}/manual-response"),
    ("GET", "/api/live/flow"),
    ("GET", "/api/sensors"),
}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return app.openapi()


def operations(schema: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
    }


def test_il_file_salvato_e_aggiornato() -> None:
    """Se questo fallisce: `cd backend && uv run python -m scripts.export_openapi`."""
    saved = export_openapi.OPENAPI_PATH.read_text(encoding="utf-8")
    assert saved == export_openapi.render()
    assert json.loads(saved)["openapi"].startswith("3.")


def test_le_operazioni_sono_quelle_della_spec(schema: dict[str, Any]) -> None:
    assert set(operations(schema)) == SPEC_OPERATIONS


def test_gli_id_operazione_sono_nomi_unici(schema: dict[str, Any]) -> None:
    ids = [op["operationId"] for op in operations(schema).values()]
    assert len(ids) == len(set(ids)) == 29
    assert all(i.isidentifier() for i in ids)  # nomi leggibili nei tipi TypeScript generati


def test_nessun_422_il_formato_di_errore_e_uno_solo(schema: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert "ValidationError" not in schema["components"]["schemas"]
    for key, operation in operations(schema).items():
        assert "422" not in operation["responses"], key
        for code, response in operation["responses"].items():
            if code.startswith(("4", "5")):
                ref = response["content"]["application/json"]["schema"]["$ref"]
                assert ref == "#/components/schemas/ErrorResponse", (key, code)


def test_il_400_e_dichiarato_dove_c_e_qualcosa_da_validare(schema: dict[str, Any]) -> None:
    for key, operation in operations(schema).items():
        validated = "requestBody" in operation or bool(operation.get("parameters"))
        assert ("400" in operation["responses"]) == validated, key


def test_error_response_ha_la_forma_della_spec(schema: dict[str, Any]) -> None:
    schemas = schema["components"]["schemas"]
    assert set(schemas["ErrorResponse"]["properties"]) == {"error"}
    assert set(schemas["ErrorBody"]["properties"]) == {"code", "message", "details"}


PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
}


def test_sicurezza_dichiarata_su_tutto_tranne_le_rotte_pubbliche(schema: dict[str, Any]) -> None:
    assert schema["components"]["securitySchemes"] == {
        "APIKeyCookie": {
            "type": "apiKey",
            "in": "cookie",
            "name": "napoli_session",
            "description": "Cookie di sessione ottenuto con POST /api/auth/login",
        }
    }
    for key, operation in operations(schema).items():
        if key in PUBLIC:
            assert "security" not in operation, key
        else:
            assert operation["security"] == [{"APIKeyCookie": []}], key
            assert "401" in operation["responses"], key


def test_codici_di_successo_della_spec(schema: dict[str, Any]) -> None:
    created = {
        ("POST", "/api/events"): "201",
        ("POST", "/api/runs"): "202",
        ("POST", "/api/vdept/{dept_id}/requests"): "201",
    }
    for key, operation in operations(schema).items():
        ok = [code for code in operation["responses"] if code.startswith("2")]
        expected = created.get(key, "200")
        assert expected in ok, (key, ok)


def test_i_limiti_di_frequenza_sono_documentati(schema: dict[str, Any]) -> None:
    ops = operations(schema)
    assert "429" in ops[("POST", "/api/runs")]["responses"]
    assert "429" in ops[("POST", "/api/auth/login")]["responses"]
    assert "503" in ops[("POST", "/api/auth/login")]["responses"]


def test_nessun_contratto_e_senza_logica(schema: dict[str, Any]) -> None:
    """Dopo F7 ogni operazione ha la sua logica: nessuna dichiara più il 501."""
    stubs = {key for key, op in operations(schema).items() if "501" in op["responses"]}
    assert stubs == set()


def test_ogni_riferimento_dello_schema_esiste(schema: dict[str, Any]) -> None:
    text = json.dumps(schema)
    defined = set(schema["components"]["schemas"])
    import re

    for name in re.findall(r'"#/components/schemas/([^"]+)"', text):
        assert name in defined, name


def test_i_tipi_che_il_frontend_genera_ci_sono(schema: dict[str, Any]) -> None:
    names = set(schema["components"]["schemas"])
    assert {
        "Event",
        "EventInput",
        "EventSummary",
        "Run",
        "RunView",
        "PlanItem",
        "OperationRequest",
        "OperationRequestDraft",
        "RequestView",
        "Decision",
        "Measured",
        "MetricsResponse",
        "RunExport",
        "FeatureCollection",
        "VdeptRegistry",
        "LiveFlowResponse",
        "HealthResponse",
        "ErrorResponse",
    } <= names


def test_i_corpi_non_hanno_i_campi_del_server(schema: dict[str, Any]) -> None:
    schemas = schema["components"]["schemas"]
    server_event = {"revision", "created_at", "updated_at"}
    assert not server_event & set(schemas["EventInput"]["properties"])
    assert server_event <= set(schemas["Event"]["properties"])
    request_server = {"action_id", "department", "state", "reject_code", "reject_reason"}
    assert not request_server & set(schemas["OperationRequestDraft"]["properties"])
    assert request_server <= set(schemas["OperationRequest"]["properties"])


def test_simulation_e_obbligatorio_e_solo_true_nel_contratto(schema: dict[str, Any]) -> None:
    for name in ("OperationRequestDraft", "OperationRequest"):
        definition = schema["components"]["schemas"][name]
        assert "simulation" in definition["required"], name
        assert definition["properties"]["simulation"].get("const") is True, name


def test_nessun_valore_di_esempio_o_default_che_somigli_a_un_segreto(
    schema: dict[str, Any],
) -> None:
    text = json.dumps(schema).lower()
    for word in ("app_password", "session_secret", "api_key", "fake-"):
        assert word not in text, word


# --- lo script ---------------------------------------------------------------------------------


def test_lo_script_scrive_e_poi_dice_gia_aggiornato(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "docs" / "openapi.json"
    monkeypatch.setattr(export_openapi, "OPENAPI_PATH", target)
    assert export_openapi.main(["--check"]) == 1  # il file non c'è
    assert not target.exists()  # --check non scrive
    assert export_openapi.main([]) == 0
    assert target.read_text(encoding="utf-8") == export_openapi.render()
    assert "scritto" in capsys.readouterr().out
    assert export_openapi.main([]) == 0
    assert "già aggiornato" in capsys.readouterr().out
    assert export_openapi.main(["--check"]) == 0
    target.write_text("{}", encoding="utf-8")
    assert export_openapi.main(["--check"]) == 1  # vecchio: --check lo segnala senza toccarlo
    assert target.read_text(encoding="utf-8") == "{}"


def test_il_testo_generato_e_deterministico() -> None:
    assert export_openapi.render() == export_openapi.render()
    assert export_openapi.render().endswith("}\n")
