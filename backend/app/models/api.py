from typing import Literal

from pydantic import Field, JsonValue, model_validator

from app.models.agents import AgentName, Finding, TextOrigin
from app.models.base import (
    Environment,
    FrozenModel,
    RefId,
    RomeDatetime,
    Slug,
    WhatsAppProvider,
    Window,
)
from app.models.departments import Department
from app.models.event import Event
from app.models.operations import Decision, OperationRequest, RequestState
from app.models.provenance import Measured, MeasuredId
from app.models.run import AttendanceLevel, PlanItem, Run, RunState

# --- errori (06, intestazione) -------------------------------------------------------------------


class ErrorBody(FrozenModel):
    code: str  # STRINGA_MAIUSCOLA stabile: il frontend decide in base a questa
    message: str  # testo leggibile in italiano
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ErrorResponse(FrozenModel):
    error: ErrorBody


# --- autenticazione (06 1) ----------------------------------------------------------------------


class LoginRequest(FrozenModel):
    password: str = Field(min_length=1)


class AuthState(FrozenModel):
    authenticated: bool
    # Accesso libero (`PUBLIC_ACCESS`): nessuna password e nessuna sessione, l'interfaccia non
    # mostra né il login né l'uscita. Assente (`None`) quando l'accesso è protetto: le risposte
    # dell'API lo omettono (`response_model_exclude_defaults`), come prima che esistesse.
    public_access: bool | None = None


# --- sistema (06 2) -----------------------------------------------------------------------------


class HealthData(FrozenModel):
    osm: bool
    gtfs: bool
    pmtiles: bool
    tomtom_key_present: bool
    gemini_key_present: bool
    whatsapp_configured: bool  # un messaggio partirebbe davvero (invio acceso e chiavi complete)
    whatsapp_provider: WhatsAppProvider  # il servizio scelto, mai numero né chiavi


class HealthResponse(FrozenModel):
    """Nessun segreto: solo se le chiavi ci sono, mai i valori."""

    status: Literal["ok", "degraded"]
    env: Environment
    data: HealthData
    degraded: list[str]  # nomi delle fonti o funzioni non disponibili
    versions: dict[str, str]


# --- GeoJSON (06 3-5) ---------------------------------------------------------------------------


class Feature(FrozenModel):
    type: Literal["Feature"] = "Feature"
    id: str | int | None = None
    geometry: dict[str, JsonValue] | None
    properties: dict[str, JsonValue] = Field(default_factory=dict)


class FeatureCollection(FrozenModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[Feature]


# --- run (06 5) ---------------------------------------------------------------------------------

LayerName = Literal[
    "edges_vc",
    "closures",
    "critical_intersections",
    "stops",
    "sections",
    "event_area",
    "requests",
]
# Stati di un agente nella timeline (07 6).
AgentState = Literal["waiting", "running", "done", "done_fallback", "error"]


class CreateRunRequest(FrozenModel):
    event_id: Slug
    attendance_level: AttendanceLevel
    manual_response: bool = False  # i dipartimenti aspettano la risposta manuale (04 5)


class CreateRunResponse(FrozenModel):
    run_id: RefId


class AgentSummary(FrozenModel):
    agent: AgentName
    state: AgentState
    tools_called: list[str] = Field(default_factory=list)
    text: str | None = None
    text_origin: TextOrigin | None = None
    # Il pannello Agenti mostra i finding con i link alle evidenze (07 6): vanno nel contratto.
    findings: list[Finding] = Field(default_factory=list)


class StateTransition(FrozenModel):
    state: RunState
    at: RomeDatetime


class OperationEvent(FrozenModel):
    """Una transizione di stato di una richiesta (tabella `operation_events`, 01 4)."""

    id: int = Field(ge=1)
    action_id: RefId
    from_state: RequestState | None = None  # assente alla creazione
    to_state: RequestState
    reason: str | None = None
    at: RomeDatetime


class RequestView(FrozenModel):
    """Una richiesta con le sue transizioni (06 5 `requests`, 6)."""

    request: OperationRequest
    events: list[OperationEvent] = Field(default_factory=list)


class RunView(FrozenModel):
    """Per il polling a 1 s: solo letture dal database, nessun calcolo (06 5)."""

    run: Run  # stato, iterazione, replans, error...
    timeline: list[StateTransition]
    agents: list[AgentSummary]
    plan: list[PlanItem]
    requests: list[RequestView]
    degraded: list[str]


class MetricDelta(FrozenModel):
    """Differenze di una metrica rispetto all'iterazione precedente e alla 0: sono numeri anch'essi,
    quindi `Measured` con la loro provenienza."""

    metric_id: MeasuredId
    vs_previous: Measured | None = None
    vs_baseline: Measured | None = None


class MetricsResponse(FrozenModel):
    run_id: RefId
    iteration: int = Field(ge=0)  # 0 = senza misure
    metrics: list[Measured]
    deltas: list[MetricDelta]


class IterationMetrics(FrozenModel):
    iteration: int = Field(ge=0)
    metrics: list[Measured]


class RunExport(FrozenModel):
    """Pacchetto JSON di un run (06 5 export): evento nella revisione usata, run, piano, richieste
    con eventi, decisioni, metriche di tutte le iterazioni con provenienza."""

    event: Event
    run: Run
    plan: list[PlanItem]
    requests: list[RequestView]
    decisions: list[Decision]
    metrics: list[IterationMetrics]


# --- dipartimenti virtuali (06 6) ---------------------------------------------------------------


class ResourceBalance(FrozenModel):
    """Una risorsa di un dipartimento in una finestra.

    `used` = già impegnata dall'evento + assegnata nel run (04 2: libere = totale − impegnate −
    assegnate); `remaining` = `total` − `used`."""

    department: Slug
    window: Window
    resource: Slug
    total: int = Field(ge=0)
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)


class VdeptRegistry(FrozenModel):
    departments: list[Department]
    resources: list[ResourceBalance] = Field(default_factory=list)  # solo con ?run_id=


class ManualResponse(FrozenModel):
    decision: Literal["accept", "reject"]
    reject_code: str | None = None
    reject_reason: str | None = None

    @model_validator(mode="after")
    def _reject_is_motivated(self) -> "ManualResponse":
        has_code = bool(self.reject_code and self.reject_code.strip())
        has_reason = bool(self.reject_reason and self.reject_reason.strip())
        if self.decision == "reject" and not (has_code and has_reason):
            raise ValueError("un rifiuto richiede reject_code e reject_reason non vuoti")
        if self.decision == "accept" and (
            self.reject_code is not None or self.reject_reason is not None
        ):
            raise ValueError("reject_code e reject_reason hanno senso solo con decision 'reject'")
        return self


# --- LIVE (06 7, 08) ----------------------------------------------------------------------------

LiveMode = Literal["fresh", "cached", "snapshot", "unavailable"]


class LiveSegmentFlow(FrozenModel):
    id: Slug
    label: str
    geometry: dict[str, JsonValue]  # le coordinate restituite da TomTom (LineString)
    current_speed: Measured
    free_flow_speed: Measured
    ratio: Measured
    # 0 scorrevole, 1 rallentata, 2 intensa, 3 satura: dal rapporto (soglie in config/live.yaml)
    congestion_class: int = Field(ge=0, le=3)
    fetched_at: RomeDatetime


class LiveFlowResponse(FrozenModel):
    segments: list[LiveSegmentFlow]
    mode: LiveMode
    degraded_reason: str | None = None
    # i numeri della fascia LIVE, calcolati dai tratti (media, conteggi): vuoto senza tratti
    summary: list[Measured] = Field(default_factory=list)
