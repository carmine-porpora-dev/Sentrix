import json
import sqlite3
from collections.abc import Collection, Generator, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.clock import now_rome
from app.models.agents import AgentResult
from app.models.api import FeatureCollection, OperationEvent
from app.models.event import Event, EventSummary
from app.models.notifications import (
    Notification,
    NotificationChannel,
    NotificationDraft,
    NotificationState,
)
from app.models.operations import Decision, OperationRequest
from app.models.provenance import Measured
from app.models.run import PlanItem, Run

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
# Versione dello schema, scritta in `PRAGMA user_version`. Un database con un'altra versione non si
# apre: un volume di produzione con uno schema diverso va migrato, non usato alla cieca.
SCHEMA_VERSION = 1
MIN_SQLITE_VERSION = (3, 37, 0)  # tabelle STRICT
BUSY_TIMEOUT_S = 5.0  # attesa di un altro scrittore prima di «database is locked»

_RUN_COLUMNS = tuple(Run.model_fields)  # le colonne di `runs` sono i campi di `Run` (01 4)
_INSERT_RUN = (
    f"INSERT INTO runs ({', '.join(_RUN_COLUMNS)}) "
    f"VALUES ({', '.join(':' + name for name in _RUN_COLUMNS)})"
)


class RepositoryError(Exception):
    """Base degli errori del repository."""


class EventExists(RepositoryError):
    def __init__(self, event_id: str) -> None:
        super().__init__(f"Esiste già un evento con id '{event_id}'")


class EventNotFound(RepositoryError):
    def __init__(self, event_id: str) -> None:
        super().__init__(f"Evento '{event_id}' non trovato")


class EventRevisionNotFound(RepositoryError):
    def __init__(self, event_id: str, revision: int) -> None:
        super().__init__(f"Evento '{event_id}': la revisione {revision} non esiste")


class SchemaVersionError(RepositoryError):
    pass


class RequestNotFound(RepositoryError):
    def __init__(self, action_id: str) -> None:
        super().__init__(f"Richiesta '{action_id}' non trovata")


class StateConflict(RepositoryError):
    """La richiesta non era più nello stato che chi la modifica si aspettava: qualcun altro l'ha
    già fatta avanzare (una risposta manuale e un timeout che arrivano insieme)."""

    def __init__(self, action_id: str, expected: str, found: str) -> None:
        super().__init__(f"Richiesta '{action_id}': attesa in {expected}, è in {found}")
        self.action_id = action_id
        self.expected = expected
        self.found = found


class NotificationNotFound(RepositoryError):
    def __init__(self, notification_id: int) -> None:
        super().__init__(f"Notifica {notification_id} non trovata")
        self.notification_id = notification_id


class NotificationStateConflict(RepositoryError):
    """La notifica non era nello stato giusto per questo passaggio (già confermata, o di un canale
    che non ha un ciclo di vita): `found` è lo stato in cui è."""

    def __init__(self, notification_id: int, found: str) -> None:
        super().__init__(f"Notifica {notification_id}: è in {found}")
        self.notification_id = notification_id
        self.found = found


@dataclass(frozen=True)
class NewDecision:
    """Una voce del log da scrivere nella stessa transazione di un'altra scrittura."""

    actor: str
    decision: str
    rationale: str
    refs: tuple[str, ...] = ()


def _event_revision_row(
    conn: sqlite3.Connection, event_id: str, revision: int
) -> sqlite3.Row | None:
    """Una sola istruzione, quindi una sola istantanea: la revisione è in `events` se è quella in
    corso, in `event_revisions` se è stata superata (mai in tutte e due)."""
    row: sqlite3.Row | None = conn.execute(
        "SELECT json FROM events WHERE id = :id AND revision = :rev "
        "UNION ALL SELECT json FROM event_revisions WHERE event_id = :id AND revision = :rev",
        {"id": event_id, "rev": revision},
    ).fetchone()
    return row


class Repository:
    def __init__(self, path: Path) -> None:
        if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
            needed = ".".join(map(str, MIN_SQLITE_VERSION))
            raise RepositoryError(
                f"SQLite {sqlite3.sqlite_version} è troppo vecchio: serve almeno la {needed}"
            )
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise SchemaVersionError(
                    f"Il database {path} ha la versione di schema {version}, "
                    f"questa applicazione usa la {SCHEMA_VERSION}: serve una migrazione"
                )
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # --- connessioni -------------------------------------------------------------------------

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_S, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")  # per connessione, non per database
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _writer(self) -> Generator[sqlite3.Connection]:
        """Una transazione di scrittura: tutto o niente."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    # --- eventi ------------------------------------------------------------------------------

    def add_event(self, event: Event, *, is_seed: bool = False) -> None:
        with self._writer() as conn:
            if conn.execute("SELECT 1 FROM events WHERE id = ?", (event.id,)).fetchone():
                raise EventExists(event.id)
            conn.execute(
                "INSERT INTO events (id, name, json, revision, is_seed, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.name,
                    event.model_dump_json(),
                    event.revision,
                    int(is_seed),
                    event.created_at.isoformat(),
                    event.updated_at.isoformat(),
                ),
            )

    def get_event(self, event_id: str) -> Event | None:
        with self._connection() as conn:
            row = conn.execute("SELECT json FROM events WHERE id = ?", (event_id,)).fetchone()
        return Event.model_validate_json(row["json"]) if row else None

    def list_events(self) -> list[EventSummary]:
        """Dall'evento più recente (per data), a pari data per id: il primo è quello che si apre."""
        with self._connection() as conn:
            rows = conn.execute("SELECT json, is_seed FROM events").fetchall()
        summaries = []
        for row in rows:
            event = Event.model_validate_json(row["json"])
            summaries.append(
                EventSummary(
                    id=event.id,
                    name=event.name,
                    date=event.date,
                    is_seed=bool(row["is_seed"]),
                    revision=event.revision,
                    updated_at=event.updated_at,
                )
            )
        by_id = sorted(summaries, key=lambda s: s.id)
        return sorted(by_id, key=lambda s: s.date, reverse=True)  # stabile: a pari data per id

    def get_event_revision(self, event_id: str, revision: int) -> Event | None:
        """L'evento com'era in una data revisione: quella in corso o una già superata."""
        with self._connection() as conn:
            row = _event_revision_row(conn, event_id, revision)
        return Event.model_validate_json(row["json"]) if row else None

    def update_event(self, event: Event) -> Event:
        """Salva il nuovo contenuto: `revision` +1 e `updated_at` = adesso li decide il repository
        (06 3, «PUT: revision += 1»), `created_at` e `is_seed` restano quelli archiviati.
        La revisione sostituita passa in `event_revisions` nella stessa transazione, così i run
        che l'hanno usata ritrovano l'evento com'era. Restituisce l'evento come è stato salvato."""
        with self._writer() as conn:
            row = conn.execute(
                "SELECT revision, created_at, json FROM events WHERE id = ?", (event.id,)
            ).fetchone()
            if row is None:
                raise EventNotFound(event.id)
            saved = Event.model_validate(
                {
                    **event.model_dump(mode="json"),
                    "revision": row["revision"] + 1,
                    "created_at": row["created_at"],
                    "updated_at": now_rome().isoformat(),
                }
            )
            conn.execute(
                "INSERT INTO event_revisions (event_id, revision, json, superseded_at) "
                "VALUES (?, ?, ?, ?)",
                (event.id, row["revision"], row["json"], saved.updated_at.isoformat()),
            )
            conn.execute(
                "UPDATE events SET name = ?, json = ?, revision = ?, updated_at = ? WHERE id = ?",
                (
                    saved.name,
                    saved.model_dump_json(),
                    saved.revision,
                    saved.updated_at.isoformat(),
                    saved.id,
                ),
            )
        return saved

    # --- run ---------------------------------------------------------------------------------

    def add_run(self, run: Run) -> None:
        """Il run deve riferirsi a una revisione dell'evento che esiste (la chiave esterna sul solo
        id non lo garantisce): senza, l'export non potrebbe ritrovare l'evento usato."""
        with self._writer() as conn:
            if _event_revision_row(conn, run.event_id, run.event_revision) is None:
                raise EventRevisionNotFound(run.event_id, run.event_revision)
            conn.execute(_INSERT_RUN, run.model_dump(mode="json"))

    def get_run(self, run_id: str) -> Run | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return Run.model_validate(dict(row)) if row else None

    def list_runs(self, event_id: str | None = None) -> list[Run]:
        """Lo storico, dal più recente; con `event_id` solo i run di quell'evento."""
        where, params = ("WHERE event_id = ? ", (event_id,)) if event_id else ("", ())
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs {where}ORDER BY started_at DESC, id",  # noqa: S608 (fisso)
                params,
            ).fetchall()
        return [Run.model_validate(dict(row)) for row in rows]

    def update_run(self, run_id: str, **changes: Any) -> Run:
        """Cambia stato, iterazione, ripianificazioni, errore o fine di un run. Il risultato deve
        restare un `Run` valido (un run `DONE` ha `ended_at`, uno `ERROR` il suo errore): se non lo
        è, nulla cambia."""
        with self._writer() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise LookupError(f"Run '{run_id}' non trovato")
            current = Run.model_validate(dict(row)).model_dump(mode="json")
            updated = Run.model_validate({**current, **changes})
            conn.execute(
                "UPDATE runs SET state = :state, iteration = :iteration, replans = :replans, "
                "error = :error, ended_at = :ended_at WHERE id = :id",
                updated.model_dump(mode="json"),
            )
        return updated

    # --- risultati degli agenti, piano, metriche e layer -------------------------------------

    def add_agent_result(self, result: AgentResult) -> None:
        """Il risultato di un agente per un'iterazione (anche più d'uno: Operations ne ha uno per
        PLAN e uno per ogni REPLAN)."""
        with self._writer() as conn:
            conn.execute(
                "INSERT INTO agent_results (run_id, agent, iteration, input_hash, json, "
                "duration_ms, validation) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    result.run_id,
                    result.agent,
                    result.iteration,
                    result.input_hash,
                    result.model_dump_json(),
                    result.duration_ms,
                    result.validation,
                ),
            )

    def list_agent_results(self, run_id: str) -> list[AgentResult]:
        """Nell'ordine in cui sono stati scritti."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT json FROM agent_results WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return [AgentResult.model_validate_json(row["json"]) for row in rows]

    def put_plan_item(self, run_id: str, item: PlanItem) -> None:
        """Aggiunge l'elemento o ne sostituisce lo stato (stesso `seq`)."""
        with self._writer() as conn:
            conn.execute(
                "INSERT INTO plan_items (run_id, seq, json) VALUES (?, ?, ?) "
                "ON CONFLICT (run_id, seq) DO UPDATE SET json = excluded.json",
                (run_id, item.seq, item.model_dump_json()),
            )

    def list_plan_items(self, run_id: str) -> list[PlanItem]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT json FROM plan_items WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        return [PlanItem.model_validate_json(row["json"]) for row in rows]

    def put_metrics(self, run_id: str, iteration: int, measures: Iterable[Measured]) -> None:
        """Le metriche di un'iterazione; riscriverle sostituisce quelle con lo stesso id."""
        with self._writer() as conn:
            conn.executemany(
                "INSERT INTO metrics (run_id, iteration, metric_id, json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (run_id, iteration, metric_id) DO UPDATE SET json = excluded.json",
                [(run_id, iteration, m.id, m.model_dump_json()) for m in measures],
            )

    def has_metrics(self, run_id: str, iteration: int) -> bool:
        """Se le metriche dell'iterazione sono già salvate: è ciò che la rende «calcolata»."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM metrics WHERE run_id = ? AND iteration = ? LIMIT 1",
                (run_id, iteration),
            ).fetchone()
        return row is not None

    def list_metrics(self, run_id: str, iteration: int) -> list[Measured]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT json FROM metrics WHERE run_id = ? AND iteration = ? ORDER BY rowid",
                (run_id, iteration),
            ).fetchall()
        return [Measured.model_validate_json(row["json"]) for row in rows]

    def put_layer(self, run_id: str, iteration: int, name: str, layer: FeatureCollection) -> None:
        with self._writer() as conn:
            conn.execute(
                "INSERT INTO layers (run_id, iteration, layer, geojson) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (run_id, iteration, layer) DO UPDATE SET geojson = excluded.geojson",
                (run_id, iteration, name, layer.model_dump_json()),
            )

    def get_layer(self, run_id: str, iteration: int, name: str) -> FeatureCollection | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT geojson FROM layers WHERE run_id = ? AND iteration = ? AND layer = ?",
                (run_id, iteration, name),
            ).fetchone()
        return FeatureCollection.model_validate_json(row["geojson"]) if row else None

    def list_layer_names(self, run_id: str, iteration: int) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT layer FROM layers WHERE run_id = ? AND iteration = ? ORDER BY layer",
                (run_id, iteration),
            ).fetchall()
        return [row["layer"] for row in rows]

    # --- richieste operative -----------------------------------------------------------------

    def add_operation_request(
        self, request: OperationRequest, *, at: datetime | None = None, reason: str | None = None
    ) -> None:
        """Registra la richiesta e la riga di creazione di `operation_events` (`from_state` NULL),
        nella stessa transazione: una richiesta senza la sua storia non esiste."""
        with self._writer() as conn:
            conn.execute(
                "INSERT INTO operation_requests "
                "(action_id, run_id, iteration, department, type, state, json, simulation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.action_id,
                    request.run_id,
                    request.iteration,
                    request.department,
                    request.type,
                    request.state,
                    request.model_dump_json(),
                    int(request.simulation),  # il CHECK del database rifiuta tutto tranne 1
                ),
            )
            self._insert_operation_event(conn, request.action_id, None, request.state, reason, at)

    @staticmethod
    def _insert_operation_event(
        conn: sqlite3.Connection,
        action_id: str,
        from_state: str | None,
        to_state: str,
        reason: str | None,
        at: datetime | None,
    ) -> OperationEvent:
        moment = at or now_rome()
        cursor = conn.execute(
            "INSERT INTO operation_events (action_id, from_state, to_state, reason, at) "
            "VALUES (?, ?, ?, ?, ?)",
            (action_id, from_state, to_state, reason, moment.isoformat()),
        )
        return OperationEvent(
            id=cursor.lastrowid or 0,
            action_id=action_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            at=moment,
        )

    def transition_operation_request(
        self,
        updated: OperationRequest,
        *,
        from_state: str,
        reason: str | None = None,
        decision: NewDecision | None = None,
        at: datetime | None = None,
    ) -> OperationEvent:
        """Porta la richiesta a `updated.state`: aggiorna la richiesta, scrive la riga di
        `operation_events` e, se c'è, la decisione, **tutto o niente**. Se la richiesta non è più in
        `from_state` solleva `StateConflict` e non scrive niente: due transizioni contemporanee
        (la risposta manuale e il timeout) non riescono entrambe. Che la transizione sia consentita
        lo decide chi chiama (`operations.lifecycle`), non il database."""
        moment = at or now_rome()
        with self._writer() as conn:
            row = conn.execute(
                "SELECT state FROM operation_requests WHERE action_id = ?", (updated.action_id,)
            ).fetchone()
            if row is None:
                raise RequestNotFound(updated.action_id)
            if row["state"] != from_state:
                raise StateConflict(updated.action_id, from_state, row["state"])
            conn.execute(
                "UPDATE operation_requests SET state = ?, json = ? WHERE action_id = ?",
                (updated.state, updated.model_dump_json(), updated.action_id),
            )
            event = self._insert_operation_event(
                conn, updated.action_id, from_state, updated.state, reason, moment
            )
            if decision is not None:
                self._insert_decision(
                    conn,
                    run_id=updated.run_id,
                    actor=decision.actor,
                    decision=decision.decision,
                    rationale=decision.rationale,
                    refs=decision.refs,
                    at=moment,
                )
        return event

    def list_operation_events(self, action_id: str) -> list[OperationEvent]:
        """Le transizioni di una richiesta, in ordine."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM operation_events WHERE action_id = ? ORDER BY id", (action_id,)
            ).fetchall()
        return [OperationEvent.model_validate(dict(row)) for row in rows]

    def list_operation_requests(self, run_id: str) -> list[OperationRequest]:
        """Le richieste di un run nell'ordine in cui sono nate."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT json FROM operation_requests WHERE run_id = ? ORDER BY rowid", (run_id,)
            ).fetchall()
        return [OperationRequest.model_validate_json(row["json"]) for row in rows]

    def get_operation_request(self, action_id: str) -> OperationRequest | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT json FROM operation_requests WHERE action_id = ?", (action_id,)
            ).fetchone()
        return OperationRequest.model_validate_json(row["json"]) if row else None

    # --- cache LLM e tetto giornaliero (F6-01) -----------------------------------------------

    def get_llm_response(self, key: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT response_json FROM llm_cache WHERE key = ?", (key,)
            ).fetchone()
        return str(row["response_json"]) if row else None

    def put_llm_response(
        self, key: str, response_json: str, *, overwrite: bool = True, at: datetime | None = None
    ) -> bool:
        """Registra una risposta. Con `overwrite=False` una voce già presente non si tocca (la cache
        demo non sostituisce ciò che il run ha già registrato). Dice se ha scritto."""
        verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
        with self._writer() as conn:
            cursor = conn.execute(
                f"{verb} INTO llm_cache (key, response_json, created_at) VALUES (?, ?, ?)",  # noqa: S608
                (key, response_json, (at or now_rome()).isoformat()),
            )
        return cursor.rowcount > 0

    def llm_calls(self, day: str) -> int:
        with self._connection() as conn:
            row = conn.execute("SELECT calls FROM llm_usage WHERE day = ?", (day,)).fetchone()
        return int(row["calls"]) if row else 0

    def try_count_llm_call(self, day: str, limit: int) -> bool:
        """Conta una chiamata LLM del giorno se il tetto non è raggiunto, in una transazione sola
        (due agenti in parallelo non superano il tetto insieme). `False` = tetto raggiunto."""
        with self._writer() as conn:
            row = conn.execute("SELECT calls FROM llm_usage WHERE day = ?", (day,)).fetchone()
            calls = int(row["calls"]) if row else 0
            if calls >= limit:
                return False
            conn.execute(
                "INSERT INTO llm_usage (day, calls) VALUES (?, 1) "
                "ON CONFLICT (day) DO UPDATE SET calls = calls + 1",
                (day,),
            )
        return True

    # --- log decisioni -----------------------------------------------------------------------

    def append_decision(
        self,
        *,
        run_id: str,
        actor: str,
        decision: str,
        rationale: str,
        refs: Iterable[str] = (),
        at: datetime | None = None,
    ) -> Decision:
        """Aggiunge una voce in coda al log del run. Il numero progressivo lo assegna il
        repository dentro la transazione: gli agenti girano in parallelo (Traffic ∥ Transit) e
        due chiamate contemporanee non devono contendersi lo stesso numero."""
        with self._writer() as conn:
            return self._insert_decision(
                conn,
                run_id=run_id,
                actor=actor,
                decision=decision,
                rationale=rationale,
                refs=refs,
                at=at,
            )

    @staticmethod
    def _insert_decision(
        conn: sqlite3.Connection,
        *,
        run_id: str,
        actor: str,
        decision: str,
        rationale: str,
        refs: Iterable[str],
        at: datetime | None,
    ) -> Decision:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM decisions WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        entry = Decision(
            run_id=run_id,
            seq=seq,
            at=at or now_rome(),
            actor=actor,
            decision=decision,
            rationale=rationale,
            refs=list(refs),
        )
        conn.execute(
            "INSERT INTO decisions (run_id, seq, at, actor, decision, rationale, refs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.run_id,
                entry.seq,
                entry.at.isoformat(),
                entry.actor,
                entry.decision,
                entry.rationale,
                json.dumps(entry.refs, ensure_ascii=False),
            ),
        )
        return entry

    def list_decisions(self, run_id: str) -> list[Decision]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM decisions WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        return [
            Decision(
                run_id=row["run_id"],
                seq=row["seq"],
                at=row["at"],
                actor=row["actor"],
                decision=row["decision"],
                rationale=row["rationale"],
                refs=json.loads(row["refs_json"]),
            )
            for row in rows
        ]

    # --- notifiche in uscita (12.2) ----------------------------------------------------------

    def add_notification(
        self,
        draft: NotificationDraft,
        *,
        at: datetime | None = None,
        then: Sequence[NotificationState] = (),
        decision: NewDecision | None = None,
    ) -> Notification:
        """Registra una notifica (append-only); vedi `add_notifications`."""
        return self.add_notifications([draft], at=at, then=then, decision=decision)[0]

    def add_notifications(
        self,
        drafts: Sequence[NotificationDraft],
        *,
        at: datetime | None = None,
        then: Sequence[NotificationState] = (),
        decision: NewDecision | None = None,
    ) -> list[Notification]:
        """Registra delle notifiche (append-only) **in una transazione sola**: chi legge le vede
        tutte o nessuna (i bollettini di un run non compaiono a gruppi). Un secondo messaggio
        WhatsApp per lo stesso run, o un secondo bollettino per lo stesso destinatario, è un errore
        del database, non una sostituzione, e non lascia scritto niente. `then`: gli stati che
        seguono subito (il bollettino nasce `SENT` e passa a `DELIVERED`), nella stessa transazione.
        `decision`: la voce del registro, una sola per tutto il gruppo."""
        created = at or now_rome()
        out: list[Notification] = []
        with self._writer() as conn:
            for draft in drafts:
                cursor = conn.execute(
                    "INSERT INTO notifications (run_id, iteration, channel, recipient_id, "
                    "recipient_label, kind, text, evidence_ids_json, state, provider_message_id, "
                    "error_code, simulation, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        draft.run_id,
                        draft.iteration,
                        draft.channel,
                        draft.recipient_id,
                        draft.recipient_label,
                        draft.kind,
                        draft.text,
                        json.dumps(draft.evidence_ids, ensure_ascii=False),
                        draft.state,
                        draft.provider_message_id,
                        draft.error_code,
                        int(draft.simulation),
                        created.isoformat(),
                    ),
                )
                new_id = cursor.lastrowid
                assert new_id is not None
                state: NotificationState = draft.state
                for following in then:
                    conn.execute(
                        "INSERT INTO notification_events "
                        "(notification_id, from_state, to_state, at) VALUES (?, ?, ?, ?)",
                        (new_id, state, following, created.isoformat()),
                    )
                    state = following
                out.append(
                    Notification(
                        id=new_id, created_at=created, **{**draft.model_dump(), "state": state}
                    )
                )
            run_ids = {d.run_id for d in drafts if d.run_id is not None}
            if decision is not None and len(run_ids) == 1:
                self._insert_decision(
                    conn,
                    run_id=run_ids.pop(),
                    actor=decision.actor,
                    decision=decision.decision,
                    rationale=decision.rationale,
                    refs=decision.refs,
                    at=created,
                )
        return out

    # lo stato corrente: quello dell'ultimo passaggio, o della riga se non ce ne sono
    _NOTIFICATION_SELECT = (
        "SELECT n.*, COALESCE((SELECT e.to_state FROM notification_events e "
        "WHERE e.notification_id = n.id ORDER BY e.id DESC LIMIT 1), n.state) AS current_state "
        "FROM notifications n"
    )

    @staticmethod
    def _notification(row: sqlite3.Row) -> Notification:
        return Notification(
            id=row["id"],
            run_id=row["run_id"],
            iteration=row["iteration"],
            channel=row["channel"],
            recipient_id=row["recipient_id"],
            recipient_label=row["recipient_label"],
            kind=row["kind"],
            text=row["text"],
            evidence_ids=json.loads(row["evidence_ids_json"]),
            state=row["current_state"],
            provider_message_id=row["provider_message_id"],
            error_code=row["error_code"],
            simulation=bool(row["simulation"]),
            created_at=row["created_at"],
        )

    def get_notification(self, notification_id: int) -> Notification | None:
        with self._connection() as conn:
            row = conn.execute(
                f"{self._NOTIFICATION_SELECT} WHERE n.id = ?",  # noqa: S608 (testo fisso)
                (notification_id,),
            ).fetchone()
        return self._notification(row) if row else None

    def list_notifications(
        self, run_id: str, channel: NotificationChannel | None = None
    ) -> list[Notification]:
        """Le notifiche del run, la più vecchia per prima, ognuna nel suo stato corrente."""
        query = f"{self._NOTIFICATION_SELECT} WHERE n.run_id = ?"  # noqa: S608 (testo fisso)
        params: tuple[str, ...] = (run_id,)
        if channel is not None:
            query += " AND n.channel = ?"
            params += (channel,)
        with self._connection() as conn:
            rows = conn.execute(query + " ORDER BY n.id", params).fetchall()
        return [self._notification(row) for row in rows]

    def transition_notification(
        self,
        notification_id: int,
        to_state: NotificationState,
        *,
        allowed_from: Collection[NotificationState],
        decision: NewDecision | None = None,
        at: datetime | None = None,
    ) -> Notification:
        """Porta la notifica a `to_state`: scrive la riga di `notification_events` e, se c'è, la
        voce del registro, **tutto o niente**. Se la notifica non esiste solleva
        `NotificationNotFound`; se lo stato corrente non è in `allowed_from` (già confermata, o
        senza ciclo di vita come WhatsApp) `NotificationStateConflict` e non scrive nulla: due
        conferme insieme non riescono entrambe."""
        moment = at or now_rome()
        with self._writer() as conn:
            row = conn.execute(
                f"{self._NOTIFICATION_SELECT} WHERE n.id = ?",  # noqa: S608 (testo fisso)
                (notification_id,),
            ).fetchone()
            if row is None:
                raise NotificationNotFound(notification_id)
            current = row["current_state"]
            if row["channel"] != "emergency_bulletin" or current not in allowed_from:
                raise NotificationStateConflict(notification_id, current)
            conn.execute(
                "INSERT INTO notification_events (notification_id, from_state, to_state, at) "
                "VALUES (?, ?, ?, ?)",
                (notification_id, current, to_state, moment.isoformat()),
            )
            if decision is not None and row["run_id"] is not None:
                self._insert_decision(
                    conn,
                    run_id=row["run_id"],
                    actor=decision.actor,
                    decision=decision.decision,
                    rationale=decision.rationale,
                    refs=decision.refs,
                    at=moment,
                )
        updated = self.get_notification(notification_id)
        assert updated is not None
        return updated

    def list_notification_events(self, notification_id: int) -> list[tuple[str, str, str]]:
        """I passaggi di stato di una notifica, in ordine: (da, a, istante ISO)."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT from_state, to_state, at FROM notification_events "
                "WHERE notification_id = ? ORDER BY id",
                (notification_id,),
            ).fetchall()
        return [(r["from_state"], r["to_state"], r["at"]) for r in rows]

    def count_whatsapp_attempts(self, day: str) -> int:
        """I messaggi WhatsApp che hanno impegnato il servizio in un giorno (`AAAA-MM-GG`, Europe/
        Rome): inviati o falliti, non quelli saltati. È il conteggio del tetto giornaliero."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE channel = 'whatsapp' "
                "AND state IN ('SENT', 'FAILED') AND created_at LIKE ?",
                (f"{day}%",),
            ).fetchone()
        return int(row[0])
