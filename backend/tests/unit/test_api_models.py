import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.repository import Repository
from app.models.api import (
    AgentSummary,
    AuthState,
    CreateRunRequest,
    ErrorBody,
    ErrorResponse,
    Feature,
    FeatureCollection,
    HealthData,
    HealthResponse,
    IterationMetrics,
    LiveFlowResponse,
    LiveSegmentFlow,
    ManualResponse,
    MetricDelta,
    MetricsResponse,
    OperationEvent,
    RequestView,
    ResourceBalance,
    RunExport,
    RunView,
    StateTransition,
    VdeptRegistry,
)
from app.models.event import Event, EventInput
from app.models.operations import OperationRequest, OperationRequestDraft
from app.models.provenance import Measured, make_measured
from tests.support import make_request, make_run
from tests.unit.test_api_events import seed_json

AT = "2026-11-09T10:00:00+01:00"


def measured(index: int = 1) -> Measured:
    return make_measured(
        id=f"m.test.v{index}",
        value=27.0,
        unit="km/h",
        kind="real",
        source="tomtom.flow",
        method="prova",
        inputs=["probe"],
    )


# --- varianti: il contenuto che si scrive e l'entità che si archivia -------------------------


def test_event_e_event_input_dividono_gli_stessi_campi() -> None:
    server = {"revision", "created_at", "updated_at"}
    assert set(Event.model_fields) == set(EventInput.model_fields) | server
    assert not server & set(EventInput.model_fields)
    # lo stesso ordine: i campi del server in coda, come prima della divisione
    assert list(Event.model_fields)[-3:] == ["revision", "created_at", "updated_at"]


def test_event_input_valida_come_event() -> None:
    body = {
        k: v for k, v in seed_json().items() if k not in ("revision", "created_at", "updated_at")
    }
    assert EventInput.model_validate(body).id == "regate_sep_2026"
    for field in ("revision", "created_at", "updated_at"):
        with pytest.raises(ValidationError, match="Extra inputs"):
            EventInput.model_validate({**body, field: 1})
    # le validazioni del contenuto valgono nella variante (non solo nell'entità completa)
    broken = {**body, "resources": body["resources"] + [body["resources"][0]]}
    with pytest.raises(ValidationError, match="una sola voce di risorse"):
        EventInput.model_validate(broken)
    # …e quella che riguarda i campi del server resta nell'entità
    full = {**seed_json(), "updated_at": "2020-01-01T00:00:00+01:00"}
    with pytest.raises(ValidationError, match="updated_at non può precedere"):
        Event.model_validate(full)


def test_operation_request_aggiunge_a_draft_solo_identita_dipartimento_ed_esito() -> None:
    added = set(OperationRequest.model_fields) - set(OperationRequestDraft.model_fields)
    assert added == {"action_id", "department", "state", "reject_code", "reject_reason"}
    assert set(OperationRequestDraft.model_fields) <= set(OperationRequest.model_fields)


def test_simulation_resta_obbligatorio_in_entrambe_le_varianti() -> None:
    base = make_request().model_dump()
    draft = {k: v for k, v in base.items() if k in OperationRequestDraft.model_fields}
    assert OperationRequestDraft.model_validate(draft).simulation is True
    for model, data in ((OperationRequestDraft, draft), (OperationRequest, base)):
        without = {k: v for k, v in data.items() if k != "simulation"}
        with pytest.raises(ValidationError, match="simulation"):
            model.model_validate(without)
        with pytest.raises(ValidationError, match="simulation"):
            model.model_validate({**data, "simulation": False})


def test_una_richiesta_gia_archiviata_si_rilegge_dopo_la_divisione(tmp_path: Any) -> None:
    repo = Repository(tmp_path / "t.db")
    from app.data.seeds import load_seed_events

    load_seed_events(repo)
    repo.add_run(make_run("run_1"))
    request = make_request()
    repo.add_operation_request(request)
    assert repo.get_operation_request("act_1") == request


# --- risposte --------------------------------------------------------------------------------


def roundtrip(model: Any) -> None:
    data = json.loads(model.model_dump_json())
    assert type(model).model_validate(data) == model


def test_le_risposte_si_costruiscono_e_fanno_andata_e_ritorno_in_json() -> None:
    run = make_run("run_1", state="PLAN", iteration=1)
    request = make_request()
    seed = Event.model_validate(seed_json())
    view = RequestView(
        request=request,
        events=[
            OperationEvent(id=1, action_id="act_1", from_state=None, to_state="CREATED", at=AT),
            OperationEvent(
                id=2, action_id="act_1", from_state="CREATED", to_state="SENT", reason="x", at=AT
            ),
        ],
    )
    models = [
        ErrorResponse(error=ErrorBody(code="X", message="m", details={"a": [1, {"b": None}]})),
        AuthState(authenticated=True),
        HealthResponse(
            status="ok",
            env="local",
            data=HealthData(
                osm=True,
                gtfs=True,
                pmtiles=True,
                tomtom_key_present=False,
                gemini_key_present=True,
                whatsapp_configured=False,
                whatsapp_provider="callmebot",
            ),
            degraded=[],
            versions={"python": "3.12"},
        ),
        FeatureCollection(
            features=[
                Feature(
                    geometry={"type": "Point", "coordinates": [14.2, 40.8]}, properties={"a": 1}
                ),
                Feature(id="e1", geometry=None),
            ]
        ),
        view,
        RunView(
            run=run,
            timeline=[StateTransition(state="INTAKE", at=AT)],
            agents=[AgentSummary(agent="traffic", state="done", text="t", text_origin="template")],
            plan=[],
            requests=[view],
            degraded=["tomtom"],
        ),
        MetricsResponse(
            run_id="run_1",
            iteration=1,
            metrics=[measured(1)],
            deltas=[MetricDelta(metric_id="m.test.v1", vs_previous=measured(2), vs_baseline=None)],
        ),
        RunExport(
            event=seed,
            run=run,
            plan=[],
            requests=[view],
            decisions=[],
            metrics=[IterationMetrics(iteration=0, metrics=[measured()])],
        ),
        VdeptRegistry(
            departments=[],
            resources=[
                ResourceBalance(
                    department="municipal_police",
                    window="departure",
                    resource="patrols",
                    total=6,
                    used=1,
                    remaining=5,
                )
            ],
        ),
        LiveFlowResponse(
            segments=[
                LiveSegmentFlow(
                    id="via_caracciolo",
                    label="Via Caracciolo",
                    geometry={"type": "LineString", "coordinates": [[14.2, 40.8], [14.3, 40.9]]},
                    current_speed=measured(1),
                    free_flow_speed=measured(2),
                    ratio=measured(3),
                    congestion_class=1,
                    fetched_at=AT,
                )
            ],
            mode="fresh",
        ),
    ]
    for model in models:
        roundtrip(model)


def test_le_risposte_rifiutano_campi_sconosciuti() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AuthState.model_validate({"authenticated": True, "token": "x"})


def test_corpo_di_creazione_run() -> None:
    body = CreateRunRequest.model_validate({"event_id": "match_2027", "attendance_level": "low"})
    assert body.manual_response is False
    with pytest.raises(ValidationError):
        CreateRunRequest.model_validate({"event_id": "match_2027", "attendance_level": "x"})


@pytest.mark.parametrize(
    ("data", "ok"),
    [
        ({"decision": "accept"}, True),
        ({"decision": "reject", "reject_code": "NO_RESERVE", "reject_reason": "finiti"}, True),
        ({"decision": "reject"}, False),
        ({"decision": "reject", "reject_code": "NO_RESERVE"}, False),
        ({"decision": "reject", "reject_code": "", "reject_reason": "x"}, False),
        ({"decision": "accept", "reject_code": "X"}, False),
        ({"decision": "accept", "reject_reason": ""}, False),
    ],
)
def test_risposta_manuale(data: dict[str, str], ok: bool) -> None:
    if ok:
        assert ManualResponse.model_validate(data).decision == data["decision"]
    else:
        with pytest.raises(ValidationError):
            ManualResponse.model_validate(data)


def test_la_provenienza_dei_delta_e_obbligatoria() -> None:
    """Un delta è un numero come gli altri: o è un `Measured` completo o non c'è."""
    with pytest.raises(ValidationError):
        MetricDelta.model_validate({"metric_id": "m.test.v1", "vs_previous": {"value": 1.5}})
