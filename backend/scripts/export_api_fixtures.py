import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

from pydantic import TypeAdapter

from app.api.exports import critical_edges_csv, metrics_csv
from app.data.paths import REPO_ROOT
from app.models.api import (
    AuthState,
    CreateRunResponse,
    ErrorBody,
    ErrorResponse,
    FeatureCollection,
    HealthData,
    HealthResponse,
    LayerName,
    LiveFlowResponse,
    MetricsResponse,
    RequestView,
    RunExport,
    RunView,
    VdeptRegistry,
)
from app.models.event import Event, EventSummary
from app.models.notifications import Notification
from app.models.operations import Decision
from app.models.run import Run
from app.models.sensors import PlannedSensor, SensorsConfig
from scripts.common import atomic_write_text
from scripts.fixture_world import (
    END,
    FRAME_TIMES,
    LEVEL,
    METRICS_AT,
    T0,
    World,
    at,
)

OUTPUT_DIR = REPO_ROOT / "frontend" / "src" / "api" / "fixtures"
MANIFEST = "manifest.json"
LAYERS: tuple[LayerName, ...] = get_args(LayerName)  # l'elenco è del tipo, non una copia

FIELD_ERROR = {
    "path": "arrival.peak",
    "message": "il picco deve cadere nella finestra",
    "type": "value_error",
}
# (stato HTTP, nome del file, codice, messaggio, dettagli): un esempio per ogni errore del contratto
ERRORS: tuple[tuple[int, str, str, str, dict[str, Any]], ...] = (
    (400, "validation", "VALIDATION_ERROR", "La richiesta non è valida", {"fields": [FIELD_ERROR]}),
    (401, "unauthenticated", "UNAUTHENTICATED", "Accesso richiesto: effettua il login", {}),
    (404, "not_found", "NOT_FOUND", "Evento non trovato", {}),
    (409, "conflict", "EVENT_EXISTS", "Esiste già un evento con questo id", {}),
    (429, "rate_limited", "RATE_LIMITED", "Troppe analisi avviate: riprova tra poco",
     {"retry_after_s": 42}),
    (500, "internal", "INTERNAL_ERROR", "Errore interno del server", {}),
    (501, "not_implemented", "NOT_IMPLEMENTED", "L'avvio di un'analisi non è ancora disponibile",
     {"planned_in": "F6-07"}),
    (503, "auth_not_configured", "AUTH_NOT_CONFIGURED",
     "L'accesso non è configurato su questo server", {}),
)  # fmt: skip

HUMAN_NOTE = (
    "Rifiutata (NO_EXTENSION_LEFT) e nessuna alternativa nel catalogo: serve una decisione umana"
)
RUN_TIMEOUT = "Tempo massimo di 120 s superato durante ANALYZE: il motore stradale non ha risposto"

# Il modello con cui si valida ogni fixture JSON. Il nome è quello che compare nel manifest e che
# un test confronta con lo schema della risposta nell'OpenAPI.
SCHEMAS: dict[str, TypeAdapter[Any]] = {
    "HealthResponse": TypeAdapter(HealthResponse),
    "AuthState": TypeAdapter(AuthState),
    "list[EventSummary]": TypeAdapter(list[EventSummary]),
    "Event": TypeAdapter(Event),
    "FeatureCollection": TypeAdapter(FeatureCollection),
    "CreateRunResponse": TypeAdapter(CreateRunResponse),
    "list[Run]": TypeAdapter(list[Run]),
    "RunView": TypeAdapter(RunView),
    "MetricsResponse": TypeAdapter(MetricsResponse),
    "list[Decision]": TypeAdapter(list[Decision]),
    "list[Notification]": TypeAdapter(list[Notification]),
    "Notification": TypeAdapter(Notification),
    "RunExport": TypeAdapter(RunExport),
    "VdeptRegistry": TypeAdapter(VdeptRegistry),
    "RequestView": TypeAdapter(RequestView),
    "LiveFlowResponse": TypeAdapter(LiveFlowResponse),
    "list[PlannedSensor]": TypeAdapter(list[PlannedSensor]),
    "ErrorResponse": TypeAdapter(ErrorResponse),
}
CSV = "text/csv"


@dataclass
class Fixture:
    path: str  # relativo a OUTPUT_DIR
    schema: str  # chiave di SCHEMAS, oppure CSV
    text: str
    # (operationId, stato HTTP) delle operazioni di cui è la risposta
    operations: list[tuple[str, int]] = field(default_factory=list)
    note: str = ""


def _json(schema: str, value: Any) -> str:
    """Il valore validato dal modello dello schema e scritto in JSON stabile."""
    adapter = SCHEMAS[schema]
    # `AuthState`: l'API omette `public_access` se l'accesso è protetto, e le fixture sono le sue
    # risposte vere (anche per i test del client mock, che le confrontano così come sono)
    data = adapter.dump_python(value, mode="json", exclude_defaults=schema == "AuthState")
    adapter.validate_json(json.dumps(data))  # come lo leggerà il client: i validatori girano tutti
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def build() -> dict[str, Fixture]:
    """Tutte le fixture, per percorso. Deterministico: nessun orologio, nessun caso."""
    world = World()
    out: dict[str, Fixture] = {}

    def add(
        path: str,
        schema: str,
        value: Any,
        ops: list[tuple[str, int]] | None = None,
        note: str = "",
    ) -> None:
        assert path not in out, path
        out[path] = Fixture(path, schema, _json(schema, value), ops or [], note)

    # --- sistema e accesso ---
    health = HealthData(
        osm=True,
        gtfs=True,
        pmtiles=True,
        tomtom_key_present=True,
        gemini_key_present=True,
        whatsapp_configured=True,
        whatsapp_provider="callmebot",
    )
    versions = {"python": "3.12.13", "fastapi": "0.162.1", "pydantic": "2.14.3", "db_schema": "1"}
    add(
        "health.json",
        "HealthResponse",
        HealthResponse(status="ok", env="local", data=health, degraded=[], versions=versions),
        [("health", 200)],
        "tutto presente",
    )
    gap = health.model_copy(update={"osm": False})
    add(
        "health_degraded.json",
        "HealthResponse",
        HealthResponse(
            status="degraded", env="local", data=gap, degraded=["osm"], versions=versions
        ),
        [("health", 200)],
        "grafo stradale assente: banner di modalità degradata",
    )
    add("auth_state_authenticated.json", "AuthState", AuthState(authenticated=True),
        [("login", 200), ("me", 200)], "dopo il login")  # fmt: skip
    add("auth_state_anonymous.json", "AuthState", AuthState(authenticated=False),
        [("logout", 200), ("me", 200)], "senza sessione")  # fmt: skip
    add("auth_state_public.json", "AuthState", AuthState(authenticated=True, public_access=True),
        [("login", 200), ("logout", 200), ("me", 200)], "accesso libero")  # fmt: skip

    # --- eventi (i due preset sono quelli veri) ---
    from app.data.seeds import read_seed_events

    seeds = read_seed_events()
    summaries = [
        EventSummary(id=e.id, name=e.name, date=e.date, is_seed=True, revision=e.revision,
                     updated_at=e.updated_at)
        for e in seeds
    ]  # fmt: skip
    add("events_list.json", "list[EventSummary]", summaries, [("list_events", 200)])
    for seed in seeds:
        ops = [("get_event", 200)] if seed.id == world.event.id else []
        add(f"event_{seed.id}.json", "Event", seed, ops, "preset: dati veri")
    match = world.event
    copy = match.model_copy(
        update={"id": f"{match.id}_copia", "name": f"{match.name} (copia)", "created_at": at(0),
                "updated_at": at(0), "revision": 1}
    )  # fmt: skip
    add(
        "event_created.json",
        "Event",
        copy,
        [("create_event", 201)],
        "evento dell'utente, revisione 1",
    )
    updated = copy.model_copy(update={"revision": 2, "updated_at": at(60)})
    add("event_updated.json", "Event", updated,
        [("update_event", 200)], "dopo una modifica: revisione 2")  # fmt: skip
    add("event_reset.json", "Event", match.model_copy(update={"revision": 3}),
        [("reset_event", 200)], "preset ripristinato: nuova revisione")  # fmt: skip
    add("event_resolve_preview.json", "FeatureCollection", world.resolve_preview(),
        [("resolve_event", 200)], "chiusure e punti di Match 2027 agganciati ai nodi")  # fmt: skip

    # --- rete e riferimenti (schematici) ---
    add("network_edges.json", "FeatureCollection", world.network_edges(), [("network_edges", 200)])
    add(
        "transit_stops.json", "FeatureCollection", world.layer("stops", 0), [("transit_stops", 200)]
    )
    add(
        "transit_lines.json",
        "FeatureCollection",
        world.layer("sections", 0),
        [("transit_lines", 200)],
    )

    # --- run: elenco, creazione, fotogrammi del polling ---
    add("run_created.json", "CreateRunResponse", CreateRunResponse(run_id=world.run_id),
        [("create_run", 202)])  # fmt: skip
    other = next(e for e in seeds if e.id != world.event.id)
    older = Run(
        id=f"run_mock_{other.id}_errore", event_id=other.id, event_revision=other.revision,
        attendance_level="high", state="ERROR", iteration=0, replans=0,
        started_at=at(-86_400), ended_at=at(-86_400 + 120), params_hash="a" * 64, seed=42,
        llm_mode="cache_only", error="Tempo massimo di 120 s superato durante l'analisi",
    )  # fmt: skip
    add(
        "runs_list.json", "list[Run]", [world.run(), older], [("list_runs", 200)], "dal più recente"
    )
    sequence = []
    names = ("intake", "analyze_event_demand", "analyze_traffic_transit", "reconcile", "plan",
             "dispatch", "await_sent", "await_outcomes", "verify_it1", "replan",
             "dispatch_alternative",
             "await_alternative", "verify_it2", "done")  # fmt: skip
    for step, (t, name) in enumerate(zip(FRAME_TIMES, names, strict=True)):
        view = world.run_view(t)
        view_path, dec_path = (
            f"run_view/step_{step:02d}_{name}.json",
            f"run_decisions/step_{step:02d}.json",
        )
        add(view_path, "RunView", view, [("get_run", 200)], f"stato {view.run.state}, t={t} s")
        add(dec_path, "list[Decision]", world.decisions(t), [("run_decisions", 200)])
        done = [it for it, ready in METRICS_AT.items() if ready <= t]
        sequence.append(
            {
                "step": step, "t_seconds": t, "state": view.run.state,
                "run_view": view_path, "decisions": dec_path,
                "iterations_available": done,
            }
        )  # fmt: skip

    # varianti per gli stati d'errore dell'interfaccia (07 8)
    final = world.run_view(END + 1)
    hdr_plan = [
        p.model_copy(update={"status": "human_decision_required", "note": HUMAN_NOTE})
        if p.seq == 3 else p
        for p in final.plan
    ]  # fmt: skip
    hdr_requests = []
    for item in final.requests:
        if item.request.action_id == "act_003":
            rejected = item.request.model_copy(update={
                "state": "REJECTED", "reject_code": "NO_EXTENSION_LEFT",
                "reject_reason": "Nessun prolungamento orario residuo"})  # fmt: skip
            item = item.model_copy(update={"request": rejected})
        hdr_requests.append(item)
    add("run_view_variant_human_decision.json", "RunView",
        final.model_copy(update={"plan": hdr_plan, "requests": hdr_requests}),
        [], "schermata 9: decisione umana richiesta")  # fmt: skip
    failed = world.run_view(30).run.model_copy(update={
        "state": "ERROR", "ended_at": at(125), "error": RUN_TIMEOUT})  # fmt: skip
    broken = world.run_view(15)
    add("run_view_variant_error.json", "RunView",
        broken.model_copy(update={"run": failed, "agents": [
            a.model_copy(update={"state": "error"}) if a.agent == "traffic" else a
            for a in broken.agents]}),
        [], "schermata 11: run in errore")  # fmt: skip
    degraded = final.model_copy(update={"degraded": ["gtfs"]})
    add("run_view_variant_degraded.json", "RunView", degraded,
        [], "fonte non disponibile: banner con il nome")  # fmt: skip

    # --- metriche, livelli, decisioni, esportazione ---
    for it in (0, 1, 2):
        add(f"run_metrics/iteration_{it}.json", "MetricsResponse", world.metrics_response(it),
            [("run_metrics", 200)], "iterazione 0 = senza misure")  # fmt: skip
        for layer in LAYERS:
            add(f"run_layers/{layer}_it{it}.json", "FeatureCollection", world.layer(layer, it),
                [("run_layer", 200)])  # fmt: skip
    add("run_export.json", "RunExport", world.run_export(), [("export_run", 200)], "format=json")
    metrics_rows = [(it, m) for it in (0, 1, 2) for m in world.metrics(it)]
    for path, text, note in (
        ("run_export_metrics.csv", metrics_csv(metrics_rows), "format=csv&what=metrics"),
        ("run_export_critical_edges.csv", critical_edges_csv(world.critical_edge_rows()),
         "format=csv&what=critical_edges"),
    ):  # fmt: skip
        out[path] = Fixture(path, CSV, text, [("export_run", 200)], note)

    # --- notifiche in uscita (spech 12.4): l'esito WhatsApp di un run finito ---
    add("run_notifications.json", "list[Notification]", world.notifications(),
        [("run_notifications", 200)],
        "WhatsApp inviato e un bollettino consegnato per destinatario (esempio)")  # fmt: skip
    bulletin = next(n for n in world.notifications() if n.channel == "emergency_bulletin")
    add("notification_acknowledged.json", "Notification",
        bulletin.model_copy(update={"state": "ACKNOWLEDGED"}), [("ack_notification", 200)],
        "dopo «Conferma ricezione»")  # fmt: skip

    # --- dipartimenti virtuali ---
    add("vdept_registry.json", "VdeptRegistry", world.registry(), [("vdept_registry", 200)],
        "registro e risorse residue a fine run")  # fmt: skip
    rejected_view = world.request_view("act_002")
    assert rejected_view is not None
    add("vdept_request.json", "RequestView", rejected_view, [("get_vdept_request", 200)],
        "richiesta rifiutata con le sue transizioni")  # fmt: skip
    created = world.request_view("act_001", 30)
    assert created is not None
    add("vdept_request_created.json", "RequestView", created, [("create_vdept_request", 201)],
        "appena creata (CREATED)")  # fmt: skip
    accepted = world.request_view("act_004")
    assert accepted is not None
    add("vdept_manual_response.json", "RequestView", accepted, [("manual_response", 200)],
        "dopo la risposta manuale «accetta»")  # fmt: skip

    # --- LIVE ---
    for mode in ("fresh", "cached", "snapshot", "unavailable"):
        add(f"live_flow_{mode}.json", "LiveFlowResponse", world.live_flow(mode),
            [("live_flow", 200)], f"mode={mode}")  # fmt: skip

    # --- sensori previsti (spech.md 11.5): il file vero, senza numeri né dati simulati ---
    add("sensors.json", "list[PlannedSensor]", SensorsConfig.from_yaml().sensors,
        [("list_sensors", 200)], "config/sensors.yaml: nessun numero, nessun dato")  # fmt: skip

    # --- errori (formato comune, 06 intestazione) ---
    for status, name, code, message, details in ERRORS:
        error = ErrorBody(code=code, message=message, details=details)
        add(
            f"errors/{status}_{name}.json",
            "ErrorResponse",
            ErrorResponse(error=error),
            [],
            f"HTTP {status}",
        )

    out[MANIFEST] = Fixture(MANIFEST, "manifest", _manifest(out, sequence, world), [], "")
    return out


def _manifest(fixtures: dict[str, Fixture], sequence: list[dict[str, Any]], world: World) -> str:
    operations: dict[str, list[dict[str, Any]]] = {}
    for fixture in fixtures.values():
        for operation, status in fixture.operations:
            operations.setdefault(operation, []).append(
                {
                    "status": status,
                    "file": fixture.path,
                    "schema": fixture.schema,
                    "note": fixture.note,
                }
            )
    errors = {
        path.split("/")[1].split("_")[0]: path
        for path in sorted(fixtures)
        if path.startswith("errors/")
    }
    manifest = {
        "generated_by": "backend/scripts/export_api_fixtures.py",
        "notice": (
            "DATI DI ESEMPIO per il mock del frontend (06 8). I numeri non sono risultati del "
            "motore: ogni Measured ha fonte «mock.fixture» e lo dichiara nelle assunzioni. "
            "L'interfaccia in modalità mock deve dirlo."
        ),
        "scenario": {
            "event_id": world.event.id,
            "run_id": world.run_id,
            "attendance_level": LEVEL,
            "started_at": T0.isoformat(),
        },  # fmt: skip
        "operations": dict(sorted(operations.items())),
        "run_sequence": sequence,
        "errors": errors,
        "binary": {"pmtiles": "GET /tiles/napoli.pmtiles: nessuna fixture, si serve il file vero"},
        "files": {path: fixtures[path].schema for path in sorted(fixtures) if path != MANIFEST},
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def validate(directory: Path) -> list[str]:
    """Riapre i file SALVATI e li valida con i modelli: i problemi trovati, uno per riga."""
    problems: list[str] = []
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    for path, schema in manifest["files"].items():
        target = directory / path
        if not target.is_file():
            problems.append(f"{path}: manca")
            continue
        if schema == CSV:
            continue  # intestazioni e righe le verifica un test
        try:
            SCHEMAS[schema].validate_json(target.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 (si riporta qualunque errore di validazione)
            problems.append(f"{path}: {schema}: {str(exc).splitlines()[0]}")
    return problems


def _read(file: Path) -> str | None:
    return file.read_text(encoding="utf-8") if file.is_file() else None


def _generated_before(target: Path) -> set[str]:
    """I file che l'ultima generazione in `target` dichiara (dal suo manifest)."""
    try:
        return set(json.loads((target / MANIFEST).read_text(encoding="utf-8"))["files"])
    except (OSError, ValueError, KeyError):
        return set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="non scrive: verifica che siano aggiornate"
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR, help="cartella di destinazione")
    args = parser.parse_args(argv)
    fixtures = build()
    target: Path = args.output
    wanted = {path: f.text for path, f in fixtures.items()}
    changed = [path for path, text in wanted.items() if _read(target / path) != text]
    # I file generati in passato e non più prodotti sono «da togliere»; gli altri non si toccano.
    stale = sorted(
        path for path in _generated_before(target) - set(wanted) if (target / path).is_file()
    )
    if args.check:
        if changed or stale:
            names = changed + stale
            shown = ", ".join(names[:5]) + (", …" if len(names) > 5 else "")
            print(
                f"{target}: {len(names)} file non aggiornati ({shown}): "
                "esegui `uv run python -m scripts.export_api_fixtures`",
                file=sys.stderr,
            )
            return 1
        print(f"{target}: aggiornate ({len(wanted)} file)")
        return 0
    for path in stale:
        (target / path).unlink()
    for path in changed:
        atomic_write_text(target / path, wanted[path])
    problems = validate(target)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"{target}: {len(wanted)} file ({len(changed)} scritti), tutti validi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
