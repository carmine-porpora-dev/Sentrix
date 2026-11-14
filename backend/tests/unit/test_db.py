import ast
import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.clock import ROME
from app.db import repository
from app.db.repository import (
    SCHEMA_VERSION,
    EventExists,
    EventNotFound,
    EventRevisionNotFound,
    Repository,
    RepositoryError,
    SchemaVersionError,
)
from app.models.event import Event
from app.models.operations import Decision, OperationRequest
from app.models.run import Run

BACKEND = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 7, 10, 0, tzinfo=ROME)
EVIDENCE = "m.run1.it1.road.critical_intersection.vc"
# Colonne di una voce dopo (run_id, seq), per scrivere nel log senza passare dal repository.
ROW = "'2026-11-07T10:00:00+01:00', 'user', 'x', 'y', '[]'"

# --- dati di prova -------------------------------------------------------------------------


def event_data(
    event_id: str = "regata", date: str = "2026-09-26", **overrides: Any
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": event_id,
        "name": "Regata di prova",
        "date": date,
        "area_center": {"lat": 40.8320, "lon": 14.2350, "label": "Rotonda Diaz"},
        "arrival": {"start": "12:00", "end": "14:00", "peak": "13:30"},
        "departure": {"start": "16:00", "end": "18:00", "peak": "16:30"},
        "attendance": {"low": 20000, "mid": 40000, "high": 60000},
        "closures": [{"label": "Via Caracciolo", "street_names": ["Via Francesco Caracciolo"]}],
        "background": {"arrival_peak_share": 0.35, "departure_peak_share": 0.40},
        "resources": [
            {
                "window": "arrival",
                "municipal_police_patrols_total": 6,
                "municipal_police_patrols_committed": 3,
                "traffic_control_signal_changes_max": 3,
                "transport_control_reserve_buses": 8,
                "transport_control_hour_extensions": 1,
            }
        ],
        "created_at": "2026-11-07T10:00:00+01:00",
        "updated_at": "2026-11-07T10:00:00+01:00",
    }
    return {**data, **overrides}


def make_event(event_id: str = "regata", date: str = "2026-09-26", **overrides: Any) -> Event:
    return Event.model_validate(event_data(event_id, date, **overrides))


def make_run(run_id: str = "run1", event_id: str = "regata", **overrides: Any) -> Run:
    data: dict[str, Any] = {
        "id": run_id,
        "event_id": event_id,
        "event_revision": 1,
        "attendance_level": "mid",
        "state": "ANALYZE",
        "iteration": 1,
        "replans": 0,
        "started_at": "2026-11-07T10:00:00+01:00",
        "ended_at": None,
        "params_hash": "a" * 64,
        "seed": 42,
        "llm_mode": "cache_only",
        "error": None,
    }
    return Run.model_validate({**data, **overrides})


def request_data(action_id: str = "act1", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "action_id": action_id,
        "run_id": "run1",
        "iteration": 1,
        "department": "municipal_police",
        "type": "traffic_post",
        "target": "node_123",
        "target_label": "Piazza Vittoria",
        "target_geo": {"lat": 40.8345, "lon": 14.2440},
        "window": "arrival",
        "priority": "normal",
        "payload": {"note": "presidio ai varchi"},
        "state": "CREATED",
        "simulation": True,
    }
    return {**data, **overrides}


def make_request(action_id: str = "act1", **overrides: Any) -> OperationRequest:
    return OperationRequest.model_validate(request_data(action_id, **overrides))


# --- fixture -------------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "napoli.db"


@pytest.fixture
def repo(db_path: Path) -> Repository:
    return Repository(db_path)


@pytest.fixture
def populated(repo: Repository) -> Repository:
    """Un evento e due run: i genitori che le chiavi esterne pretendono."""
    repo.add_event(make_event())
    repo.add_run(make_run("run1"))
    repo.add_run(make_run("run2"))
    return repo


@pytest.fixture
def raw(repo: Repository, db_path: Path) -> Iterator[sqlite3.Connection]:
    """Connessione SQLite diretta (con le chiavi esterne attive, come quelle del repository)."""
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


# --- schema: tabelle, colonne, chiavi (01 4) ----------------------------------------------

SPEC_COLUMNS: dict[str, list[str]] = {
    "events": ["id", "name", "json", "revision", "is_seed", "created_at", "updated_at"],
    "runs": [
        "id", "event_id", "event_revision", "attendance_level", "state", "iteration", "replans",
        "params_hash", "seed", "llm_mode", "error", "started_at", "ended_at",
    ],
    "agent_results": [
        "id", "run_id", "agent", "iteration", "input_hash", "json", "duration_ms", "validation",
    ],
    "metrics": ["run_id", "iteration", "metric_id", "json"],
    "layers": ["run_id", "iteration", "layer", "geojson"],
    "operation_requests": [
        "action_id", "run_id", "iteration", "department", "type", "state", "json", "simulation",
    ],
    "operation_events": ["id", "action_id", "from_state", "to_state", "reason", "at"],
    "decisions": ["run_id", "seq", "at", "actor", "decision", "rationale", "refs_json"],
    "llm_cache": ["key", "response_json", "created_at"],
    "live_cache": ["segment_id", "json", "fetched_at"],
    # Non in 01 4: aggiunte su decisione del proprietario (8/11/2026).
    "event_revisions": ["event_id", "revision", "json", "superseded_at"],
    "plan_items": ["run_id", "seq", "json"],
    # Aggiunta in F6-01: il tetto giornaliero delle chiamate LLM (05 1) sopravvive a un riavvio.
    "llm_usage": ["day", "calls"],
    # Aggiunta per la notifica WhatsApp (spech.md 12.2, 14/11/2026).
    "notifications": [
        "id", "run_id", "iteration", "channel", "recipient_id", "recipient_label", "kind", "text",
        "evidence_ids_json", "state", "provider_message_id", "error_code", "simulation",
        "created_at",
    ],
    # Il ciclo di vita del bollettino (spech 12.3, 14/11/2026): `notifications` non si aggiorna.
    "notification_events": ["id", "notification_id", "from_state", "to_state", "at"],
}  # fmt: skip
SPEC_PRIMARY_KEYS: dict[str, list[str]] = {
    "events": ["id"],
    "runs": ["id"],
    "agent_results": ["id"],
    "metrics": ["run_id", "iteration", "metric_id"],
    "layers": ["run_id", "iteration", "layer"],
    "operation_requests": ["action_id"],
    "operation_events": ["id"],
    "decisions": ["run_id", "seq"],
    "llm_cache": ["key"],
    "live_cache": ["segment_id"],
    "event_revisions": ["event_id", "revision"],
    "plan_items": ["run_id", "seq"],
    "llm_usage": ["day"],
    "notifications": ["id"],
    "notification_events": ["id"],
}
NULLABLE = {
    ("runs", "error"),
    ("runs", "ended_at"),
    ("operation_events", "from_state"),
    ("operation_events", "reason"),
    ("notifications", "run_id"),
    ("notifications", "recipient_label"),
    ("notifications", "provider_message_id"),
    ("notifications", "error_code"),
}
FOREIGN_KEYS = {
    ("runs", "event_id", "events", "id"),
    ("agent_results", "run_id", "runs", "id"),
    ("metrics", "run_id", "runs", "id"),
    ("layers", "run_id", "runs", "id"),
    ("operation_requests", "run_id", "runs", "id"),
    ("operation_events", "action_id", "operation_requests", "action_id"),
    ("decisions", "run_id", "runs", "id"),
    ("event_revisions", "event_id", "events", "id"),
    ("plan_items", "run_id", "runs", "id"),
    ("notifications", "run_id", "runs", "id"),
    ("notification_events", "notification_id", "notifications", "id"),
}


def table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def test_ci_sono_le_quindici_tabelle(raw: sqlite3.Connection) -> None:
    names = {
        r[0]
        for r in raw.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    # le 10 di 01 4 più event_revisions, plan_items, llm_usage, notifications e notification_events
    assert names == set(SPEC_COLUMNS)


@pytest.mark.parametrize("table", SPEC_COLUMNS)
def test_colonne_come_nella_spec(raw: sqlite3.Connection, table: str) -> None:
    assert [c["name"] for c in table_info(raw, table)] == SPEC_COLUMNS[table]


@pytest.mark.parametrize("table", SPEC_COLUMNS)
def test_chiave_primaria_come_nella_spec(raw: sqlite3.Connection, table: str) -> None:
    keyed = sorted((c["pk"], c["name"]) for c in table_info(raw, table) if c["pk"])
    assert [name for _, name in keyed] == SPEC_PRIMARY_KEYS[table]


@pytest.mark.parametrize("table", SPEC_COLUMNS)
def test_solo_le_colonne_previste_ammettono_null(raw: sqlite3.Connection, table: str) -> None:
    nullable = {(table, c["name"]) for c in table_info(raw, table) if not c["notnull"]}
    assert nullable == {pair for pair in NULLABLE if pair[0] == table}


def test_tutte_le_tabelle_sono_strict(raw: sqlite3.Connection) -> None:
    rows = raw.execute("PRAGMA table_list").fetchall()
    strict = {r[1]: r[5] for r in rows if r[1] in SPEC_COLUMNS}
    assert strict == dict.fromkeys(SPEC_COLUMNS, 1)


def test_chiavi_esterne_senza_cascata(raw: sqlite3.Connection) -> None:
    found = set()
    for table in SPEC_COLUMNS:
        for fk in raw.execute(f"PRAGMA foreign_key_list({table})"):
            # (id, seq, tabella, da, a, on_update, on_delete, match)
            found.add((table, fk[3], fk[2], fk[4]))
            assert (fk[5], fk[6]) == ("NO ACTION", "NO ACTION"), f"{table}.{fk[3]}"
    assert found == FOREIGN_KEYS


def test_le_colonne_di_runs_sono_i_campi_di_run(raw: sqlite3.Connection) -> None:
    assert {c["name"] for c in table_info(raw, "runs")} == set(Run.model_fields)


def test_i_trigger_sono_quelli_dei_log_append_only(raw: sqlite3.Connection) -> None:
    triggers = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert triggers == {
        *(
            f"{table}_no_{action}"
            for table in ("decisions", "event_revisions", "notifications")
            for action in ("update", "delete", "replace")
        ),
        "notification_events_no_update",
        "notification_events_no_delete",
        "notifications_no_replace_bulletin",  # lo stesso divieto di sostituire, per i bollettini
    }


# --- apertura del database -----------------------------------------------------------------


def test_il_database_e_in_modalita_wal(raw: sqlite3.Connection) -> None:
    assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_il_repository_crea_le_cartelle_mancanti(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "napoli.db"
    Repository(path)
    assert path.is_file()


def test_riaprire_non_perde_i_dati_e_non_rompe_lo_schema(db_path: Path) -> None:
    first = Repository(db_path)
    first.add_event(make_event(), is_seed=True)
    again = Repository(db_path)
    assert again.get_event("regata") == make_event()
    assert [e.id for e in again.list_events()] == ["regata"]


def test_la_versione_dello_schema_e_scritta(raw: sqlite3.Connection) -> None:
    assert SCHEMA_VERSION == 1
    assert raw.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_un_database_con_unaltra_versione_non_si_apre(repo: Repository, db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(SchemaVersionError, match="versione di schema 99"):
        Repository(db_path)


def test_un_database_senza_versione_viene_adottato(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(repository.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()
    Repository(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()


def test_sqlite_troppo_vecchio_e_rifiutato(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setattr(repository.sqlite3, "sqlite_version_info", (3, 36, 9))
    with pytest.raises(RepositoryError, match="troppo vecchio"):
        Repository(db_path)
    assert not db_path.exists()


def test_le_chiavi_esterne_sono_attive(raw: sqlite3.Connection, populated: Repository) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        raw.execute(
            "INSERT INTO runs VALUES ('run9', 'inesistente', 1, 'mid', 'ANALYZE', 1, 0, "
            f"'{'a' * 64}', 42, 'cache_only', NULL, '2026-11-07T10:00:00+01:00', NULL)"
        )
    assert raw.execute("SELECT COUNT(*) FROM runs WHERE id = 'run9'").fetchone()[0] == 0


# --- eventi ----------------------------------------------------------------------------------


def test_evento_andata_e_ritorno(repo: Repository) -> None:
    event = make_event()
    repo.add_event(event)
    assert repo.get_event("regata") == event
    assert repo.get_event("altro") is None


def test_un_evento_con_lo_stesso_id_non_si_aggiunge_due_volte(repo: Repository) -> None:
    repo.add_event(make_event(name="Originale"))
    with pytest.raises(EventExists, match="regata"):
        repo.add_event(make_event(name="Doppione"), is_seed=True)
    stored = repo.get_event("regata")
    assert stored is not None and stored.name == "Originale"
    assert repo.list_events()[0].is_seed is False


def test_elenco_eventi_vuoto(repo: Repository) -> None:
    assert repo.list_events() == []


def test_elenco_eventi_dal_piu_recente_poi_per_id_con_il_flag_preset(repo: Repository) -> None:
    repo.add_event(make_event("zeta", "2026-09-26"))
    repo.add_event(make_event("match", "2027-07-10", name="Match"), is_seed=True)
    repo.add_event(make_event("alfa", "2026-09-26"), is_seed=True)
    rows = repo.list_events()
    assert [(r.id, str(r.date), r.is_seed) for r in rows] == [
        ("match", "2027-07-10", True),
        ("alfa", "2026-09-26", True),
        ("zeta", "2026-09-26", False),
    ]
    assert (rows[0].name, rows[0].revision) == ("Match", 1)
    assert rows[1].updated_at == datetime(2026, 11, 7, 10, 0, tzinfo=ROME)


def test_le_colonne_di_un_evento_coincidono_con_il_suo_json(
    repo: Repository, raw: sqlite3.Connection
) -> None:
    repo.add_event(make_event(revision=3), is_seed=True)
    name, json_text, revision, is_seed, created, updated = raw.execute(
        "SELECT name, json, revision, is_seed, created_at, updated_at FROM events"
    ).fetchone()
    stored = Event.model_validate_json(json_text)
    assert (
        (name, revision, is_seed) == (stored.name, stored.revision, 1) == ("Regata di prova", 3, 1)
    )
    assert (created, updated) == ("2026-11-07T10:00:00+01:00",) * 2


def test_aggiornare_un_evento_incrementa_la_revisione(
    repo: Repository, raw: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.add_event(make_event(), is_seed=True)
    later = datetime(2026, 11, 8, 9, 30, tzinfo=ROME)
    monkeypatch.setattr(repository, "now_rome", lambda: later)
    # Quello che arriva dal client non comanda: revisione e istanti falsi vengono ignorati.
    sent = make_event(
        name="Regata modificata",
        revision=99,
        created_at="2030-01-01T00:00:00+01:00",
        updated_at="2030-01-01T00:00:00+01:00",
    )
    saved = repo.update_event(sent)
    assert (saved.name, saved.revision) == ("Regata modificata", 2)
    assert saved.created_at == datetime(2026, 11, 7, 10, 0, tzinfo=ROME)
    assert saved.updated_at == later
    assert repo.get_event("regata") == saved
    again = repo.update_event(saved)
    assert again.revision == 3
    listed = repo.list_events()[0]  # anche l'elenco vede la revisione e l'istante nuovi
    assert (listed.revision, listed.updated_at, listed.name, listed.is_seed) == (
        3,
        later,
        "Regata modificata",
        True,
    )
    row = raw.execute(
        "SELECT name, revision, is_seed, created_at, updated_at FROM events"
    ).fetchone()
    assert row == (
        "Regata modificata", 3, 1, "2026-11-07T10:00:00+01:00", "2026-11-08T09:30:00+01:00"
    )  # fmt: skip


def test_aggiornare_non_tocca_gli_altri_eventi(repo: Repository) -> None:
    repo.add_event(make_event("a"))
    repo.add_event(make_event("b", name="B"))
    repo.update_event(make_event("a", name="A2"))
    assert repo.get_event("b") == make_event("b", name="B")


def test_aggiornare_un_evento_inesistente(repo: Repository) -> None:
    with pytest.raises(EventNotFound, match="regata"):
        repo.update_event(make_event())
    assert repo.list_events() == []


def test_un_aggiornamento_non_valido_non_lascia_tracce(
    repo: Repository, raw: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.add_event(make_event())
    before = datetime(2020, 1, 1, tzinfo=ROME)  # prima di created_at: il modello lo rifiuta
    monkeypatch.setattr(repository, "now_rome", lambda: before)
    with pytest.raises(ValidationError, match="non può precedere"):
        repo.update_event(make_event(name="Non deve restare"))
    stored = repo.get_event("regata")
    assert stored == make_event()
    assert repo.list_events()[0].revision == 1
    assert raw.execute("SELECT COUNT(*) FROM event_revisions").fetchone()[0] == 0  # niente archivio


# --- revisioni degli eventi (decisione del proprietario: `event_revisions`) -----------------


def test_una_modifica_archivia_la_revisione_sostituita(
    repo: Repository, raw: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = make_event()
    repo.add_event(original)
    assert raw.execute("SELECT COUNT(*) FROM event_revisions").fetchone()[0] == 0
    later = datetime(2026, 11, 8, 9, 30, tzinfo=ROME)
    monkeypatch.setattr(repository, "now_rome", lambda: later)
    second = repo.update_event(make_event(name="Seconda"))
    archived = raw.execute("SELECT event_id, revision, superseded_at FROM event_revisions")
    assert archived.fetchall() == [("regata", 1, "2026-11-08T09:30:00+01:00")]
    assert repo.get_event_revision("regata", 1) == original
    assert repo.get_event_revision("regata", 2) == second
    assert repo.get_event("regata") == second


def test_ogni_revisione_vive_in_un_solo_posto(
    repo: Repository, raw: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repository, "now_rome", lambda: T0.replace(day=8))
    repo.add_event(make_event(), is_seed=True)
    names = ["Prima", "Seconda", "Terza"]
    saved = [repo.update_event(make_event(name=name)) for name in names]
    assert [e.revision for e in saved] == [2, 3, 4]
    archived = raw.execute("SELECT revision FROM event_revisions ORDER BY revision").fetchall()
    assert archived == [(1,), (2,), (3,)]  # la 4, in corso, sta solo in `events`
    history = [repo.get_event_revision("regata", n) for n in (1, 2, 3, 4)]
    assert [e.name if e else None for e in history] == [
        "Regata di prova",
        "Prima",
        "Seconda",
        "Terza",
    ]
    assert history[3] == repo.get_event("regata")


def test_revisione_inesistente(repo: Repository) -> None:
    repo.add_event(make_event())
    assert repo.get_event_revision("regata", 1) == make_event()  # quella in corso, senza archivio
    assert repo.get_event_revision("regata", 2) is None
    assert repo.get_event_revision("regata", 0) is None
    assert repo.get_event_revision("altro", 1) is None
    repo.update_event(make_event(name="Seconda"))  # ora la 1 sta nell'archivio
    assert repo.get_event_revision("altro", 1) is None  # un altro evento non la vede


def test_gli_archivi_di_eventi_diversi_non_si_mescolano(repo: Repository) -> None:
    repo.add_event(make_event("a", name="A"))
    repo.add_event(make_event("b", "2027-07-10", name="B"))
    repo.update_event(make_event("a", name="A2"))
    repo.update_event(
        make_event("b", "2027-07-10", name="B2")
    )  # anche b archivia la sua revisione 1
    repo.update_event(make_event("a", name="A3"))
    assert [repo.get_event_revision("a", n).name for n in (1, 2, 3)] == ["A", "A2", "A3"]  # type: ignore[union-attr]
    assert [repo.get_event_revision("b", n).name for n in (1, 2)] == ["B", "B2"]  # type: ignore[union-attr]
    assert repo.get_event_revision("b", 3) is None


def test_una_revisione_archiviata_non_si_manomette(
    repo: Repository, raw: sqlite3.Connection
) -> None:
    repo.add_event(make_event())
    repo.update_event(make_event(name="Seconda"))
    row = "('regata', 1, '{}', 't')"
    table = "event_revisions"
    attempts = [
        ("UPDATE", "UPDATE event_revisions SET json = '{}'", "UPDATE vietato"),
        ("DELETE di tutto", "DELETE FROM event_revisions", "DELETE vietato"),
        ("DELETE di una riga", "DELETE FROM event_revisions WHERE revision = 1", "DELETE vietato"),
        ("INSERT OR REPLACE", f"INSERT OR REPLACE INTO {table} VALUES {row}", "non si sostituisce"),
        ("REPLACE INTO", f"REPLACE INTO {table} VALUES {row}", "non si sostituisce"),
        (
            "UPSERT",
            f"INSERT INTO {table} VALUES {row} "
            "ON CONFLICT (event_id, revision) DO UPDATE SET json = 'x'",
            "non si sostituisce",
        ),
        ("INSERT OR IGNORE", f"INSERT OR IGNORE INTO {table} VALUES {row}", "non si sostituisce"),
        ("INSERT semplice", f"INSERT INTO {table} VALUES {row}", "non si sostituisce"),
    ]
    for name, sql, message in attempts:
        with pytest.raises(sqlite3.IntegrityError, match="append-only") as info:
            raw.execute(sql)
        assert message in str(info.value), name
    assert repo.get_event_revision("regata", 1) == make_event()


def test_event_revisions_ha_chiave_esterna_e_check(
    raw: sqlite3.Connection, repo: Repository
) -> None:
    repo.add_event(make_event())
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        raw.execute("INSERT INTO event_revisions VALUES ('nessuno', 1, '{}', 't')")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        raw.execute("INSERT INTO event_revisions VALUES ('regata', 0, '{}', 't')")
    raw.execute("INSERT INTO event_revisions VALUES ('regata', 1, '{}', 't')")  # il resto passa


def test_un_evento_con_revisioni_non_si_cancella(raw: sqlite3.Connection, repo: Repository) -> None:
    repo.add_event(make_event())
    repo.update_event(make_event(name="Seconda"))
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        raw.execute("DELETE FROM events WHERE id = 'regata'")


# --- piano (decisione del proprietario: `plan_items`) --------------------------------------


def test_plan_items_schema_chiave_e_modificabilita(
    raw: sqlite3.Connection, populated: Repository
) -> None:
    raw.execute("INSERT INTO plan_items VALUES ('run1', 1, '{\"status\": \"proposed\"}')")
    raw.execute("INSERT INTO plan_items VALUES ('run1', 2, '{}')")
    raw.execute("INSERT INTO plan_items VALUES ('run2', 1, '{}')")  # seq unico nel run, non globale
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        raw.execute("INSERT INTO plan_items VALUES ('run1', 1, '{}')")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        raw.execute("INSERT INTO plan_items VALUES ('nessuno', 1, '{}')")
    # Lo stato di un elemento cambia nel tempo (proposto → accettato...): qui NON è append-only.
    accepted = '{"status": "accepted"}'
    raw.execute("UPDATE plan_items SET json = ? WHERE run_id = 'run1' AND seq = 1", (accepted,))
    assert raw.execute(
        "SELECT json FROM plan_items WHERE run_id = 'run1' AND seq = 1"
    ).fetchone() == ('{"status": "accepted"}',)


INSERT_EVENT = "INSERT INTO events VALUES ('x', 'n', '{{}}', {revision}, {is_seed}, 't', 't')"


@pytest.mark.parametrize(
    ("revision", "is_seed"), [(0, 0), (-1, 1), (1, 2), (1, -1), (2, 5)], ids=str
)
def test_check_degli_eventi(raw: sqlite3.Connection, revision: int, is_seed: int) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        raw.execute(INSERT_EVENT.format(revision=revision, is_seed=is_seed))
    assert raw.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


@pytest.mark.parametrize(("revision", "is_seed"), [(1, 0), (1, 1), (7, 1)], ids=str)
def test_check_degli_eventi_valori_ammessi(
    raw: sqlite3.Connection, revision: int, is_seed: int
) -> None:
    raw.execute(INSERT_EVENT.format(revision=revision, is_seed=is_seed))
    assert raw.execute("SELECT revision, is_seed FROM events").fetchone() == (revision, is_seed)


# --- run -------------------------------------------------------------------------------------


def test_run_andata_e_ritorno(populated: Repository) -> None:
    assert populated.get_run("run1") == make_run("run1")
    assert populated.get_run("nessuno") is None
    done = make_run(
        "run3", state="ERROR", ended_at="2026-11-07T10:01:10+01:00", error="Tempo massimo superato"
    )
    populated.add_run(done)
    assert populated.get_run("run3") == done


def test_storico_dei_run_dal_piu_recente(populated: Repository) -> None:
    populated.add_event(make_event("altro", date="2026-09-27"))
    populated.add_run(make_run("run3", started_at="2026-11-07T12:00:00+01:00"))
    populated.add_run(make_run("run4", event_id="altro", started_at="2026-11-07T11:00:00+01:00"))
    assert [r.id for r in populated.list_runs()] == ["run3", "run4", "run1", "run2"]
    # a pari ora (run1 e run2 partono insieme) decide l'id, così l'ordine non ballerebbe
    assert [r.id for r in populated.list_runs("regata")] == ["run3", "run1", "run2"]
    assert [r.id for r in populated.list_runs("altro")] == ["run4"]
    assert populated.list_runs("nessuno") == []
    assert populated.list_runs("regata") == [
        make_run("run3", started_at="2026-11-07T12:00:00+01:00"),
        make_run("run1"),
        make_run("run2"),
    ]


def test_storico_vuoto(repo: Repository) -> None:
    assert repo.list_runs() == []


def test_il_filtro_dello_storico_non_e_iniettabile(populated: Repository) -> None:
    assert populated.list_runs("regata' OR '1'='1") == []
    assert len(populated.list_runs()) == 2  # la tabella è intatta


def test_il_run_conserva_gli_istanti_con_il_fuso(
    populated: Repository, raw: sqlite3.Connection
) -> None:
    started = raw.execute("SELECT started_at, ended_at FROM runs WHERE id = 'run1'").fetchone()
    assert started == ("2026-11-07T10:00:00+01:00", None)


def test_un_run_deve_avere_un_evento(populated: Repository) -> None:
    with pytest.raises(EventRevisionNotFound, match="'nessuno'.*revisione 1"):
        populated.add_run(make_run("run9", event_id="nessuno"))
    assert populated.get_run("run9") is None


def test_un_run_deve_riferirsi_a_una_revisione_che_esiste(
    populated: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repository, "now_rome", lambda: T0)
    with pytest.raises(EventRevisionNotFound, match="revisione 2"):
        populated.add_run(make_run("run9", event_revision=2))
    populated.update_event(make_event(name="Seconda"))  # ora la 2 è in corso e la 1 è superata
    populated.add_run(make_run("run8", event_revision=1))  # una revisione superata va bene
    populated.add_run(make_run("run9", event_revision=2))
    with pytest.raises(EventRevisionNotFound, match="revisione 3"):
        populated.add_run(make_run("run7", event_revision=3))
    with pytest.raises(EventRevisionNotFound, match="revisione 0"):
        populated.add_run(
            make_run("run6", event_revision=1).model_copy(update={"event_revision": 0})
        )
    assert [populated.get_run(r) is not None for r in ("run8", "run9", "run7", "run6")] == [
        True, True, False, False,
    ]  # fmt: skip


def test_un_run_non_si_aggiunge_due_volte(populated: Repository) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        populated.add_run(make_run("run1", state="DONE", ended_at="2026-11-07T11:00:00+01:00"))
    run = populated.get_run("run1")
    assert run is not None and run.state == "ANALYZE"


# --- richieste operative e CHECK simulation (principio 3) -------------------------------------


def test_richiesta_andata_e_ritorno(populated: Repository, raw: sqlite3.Connection) -> None:
    request = make_request()
    populated.add_operation_request(request)
    assert populated.get_operation_request("act1") == request
    assert populated.get_operation_request("act9") is None
    row = raw.execute(
        "SELECT run_id, iteration, department, type, state, simulation FROM operation_requests"
    ).fetchone()
    assert row == ("run1", 1, "municipal_police", "traffic_post", "CREATED", 1)


@pytest.mark.parametrize("state", ["CREATED", "SENT", "REJECTED", "COMPLETED"])
def test_le_colonne_di_una_richiesta_coincidono_con_il_suo_json(
    populated: Repository, raw: sqlite3.Connection, state: str
) -> None:
    rejection = {"reject_code": "NO_PATROLS", "reject_reason": "Pattuglie esaurite"}
    request = make_request(
        "act5",
        state=state,
        iteration=2,
        department="traffic_control",
        type="close_road",
        **(rejection if state == "REJECTED" else {}),
    )
    populated.add_operation_request(request)
    *columns, json_text = raw.execute(
        "SELECT iteration, department, type, state, json FROM operation_requests"
    ).fetchone()
    stored = OperationRequest.model_validate_json(json_text)
    assert columns == [2, "traffic_control", "close_road", state]
    assert columns == [stored.iteration, stored.department, stored.type, stored.state]


def test_una_richiesta_deve_avere_un_run(populated: Repository) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        populated.add_operation_request(make_request(run_id="nessuno"))


def test_unazione_non_si_registra_due_volte(populated: Repository) -> None:
    populated.add_operation_request(make_request())
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        populated.add_operation_request(make_request(department="traffic_control"))
    stored = populated.get_operation_request("act1")
    assert stored is not None and stored.department == "municipal_police"


def test_il_repository_non_scrive_una_richiesta_non_simulata(populated: Repository) -> None:
    # Un modello che aggira la validazione (model_copy non rivalida) arriva fino al database,
    # e il CHECK lo ferma: seconda linea di difesa dopo `Literal[True]`.
    unsafe = make_request("act7").model_copy(update={"simulation": False})
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        populated.add_operation_request(unsafe)
    assert populated.get_operation_request("act7") is None


INSERT_REQUEST = (
    "INSERT INTO operation_requests "
    "(action_id, run_id, iteration, department, type, state, json, simulation) "
    "VALUES ('actX', 'run1', 1, 'municipal_police', 'traffic_post', 'CREATED', '{{}}', {value})"
)


@pytest.mark.parametrize("value", [0, 2, -1, 1.5])
def test_check_simulation_rifiuta_ogni_valore_diverso_da_1(
    raw: sqlite3.Connection, populated: Repository, value: float
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(INSERT_REQUEST.format(value=value))
    assert raw.execute("SELECT COUNT(*) FROM operation_requests").fetchone()[0] == 0


def test_check_simulation_rifiuta_null_e_testo(
    raw: sqlite3.Connection, populated: Repository
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
        raw.execute(INSERT_REQUEST.format(value="NULL"))
    with pytest.raises(sqlite3.IntegrityError):
        raw.execute(INSERT_REQUEST.format(value="'true'"))


def test_simulation_non_ha_un_default(raw: sqlite3.Connection, populated: Repository) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL constraint failed"):
        raw.execute(
            "INSERT INTO operation_requests (action_id, run_id, iteration, department, type, "
            "state, json) VALUES ('actX', 'run1', 1, 'municipal_police', 'traffic_post', "
            "'CREATED', '{}')"
        )


def test_check_simulation_vale_anche_per_gli_aggiornamenti(
    raw: sqlite3.Connection, populated: Repository
) -> None:
    populated.add_operation_request(make_request())
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        raw.execute("UPDATE operation_requests SET simulation = 0")
    assert raw.execute("SELECT simulation FROM operation_requests").fetchone() == (1,)


def test_check_simulation_ammette_1(raw: sqlite3.Connection, populated: Repository) -> None:
    raw.execute(INSERT_REQUEST.format(value=1))
    assert raw.execute("SELECT simulation FROM operation_requests").fetchone() == (1,)


# --- log decisioni --------------------------------------------------------------------------


def append(
    repo: Repository, run_id: str = "run1", text: str = "Invio richiesta act1", **kw: Any
) -> Decision:
    kwargs: dict[str, Any] = {
        "actor": "orchestrator",
        "rationale": "Il piano contiene una misura",
        "refs": [EVIDENCE, "act1"],
        **kw,
    }
    return repo.append_decision(run_id=run_id, decision=text, **kwargs)


def test_i_numeri_progressivi_partono_da_1_per_ogni_run(populated: Repository) -> None:
    assert [append(populated).seq for _ in range(3)] == [1, 2, 3]
    assert append(populated, "run2").seq == 1
    assert append(populated).seq == 4


def test_decisione_andata_e_ritorno(populated: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "now_rome", lambda: T0)
    first = append(populated, text="Città è più grande — «Napoli»")
    explicit = datetime(2026, 11, 7, 9, 0, tzinfo=ROME)
    second = append(populated, actor="municipal_police", refs=[], at=explicit)
    assert (first.seq, first.at, first.actor, first.refs) == (
        1,
        T0,
        "orchestrator",
        [EVIDENCE, "act1"],
    )
    assert (second.seq, second.at, second.refs) == (2, explicit, [])
    assert populated.list_decisions("run1") == [first, second]
    assert populated.list_decisions("run2") == []
    assert populated.list_decisions("run1")[0].decision == "Città è più grande — «Napoli»"


def test_senza_istante_la_decisione_porta_ladesso_a_roma(populated: Repository) -> None:
    before = datetime.now(ROME)
    entry = append(populated)
    assert before <= entry.at <= datetime.now(ROME)
    assert entry.at.utcoffset() == before.utcoffset()


def test_le_decisioni_si_leggono_in_ordine_di_numero(
    populated: Repository, raw: sqlite3.Connection
) -> None:
    raw.execute(f"INSERT INTO decisions VALUES ('run1', 3, {ROW})")
    raw.execute(f"INSERT INTO decisions VALUES ('run1', 2, {ROW})")
    raw.execute(f"INSERT INTO decisions VALUES ('run1', 10, {ROW})")
    assert [d.seq for d in populated.list_decisions("run1")] == [2, 3, 10]
    assert append(populated).seq == 11


def test_una_decisione_non_valida_non_scrive_niente(populated: Repository) -> None:
    with pytest.raises(ValidationError):
        append(populated, text="")
    with pytest.raises(ValidationError):
        append(populated, actor="Polizia Municipale")
    assert populated.list_decisions("run1") == []
    assert append(populated).seq == 1  # nessun numero consumato


def test_una_decisione_ha_bisogno_del_run(populated: Repository) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        append(populated, "nessuno")


def test_decisioni_in_parallelo_hanno_numeri_unici_e_senza_buchi(populated: Repository) -> None:
    def work(run_id: str) -> list[int]:
        return [append(populated, run_id, f"voce {i}").seq for i in range(25)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(work, "run1" if n % 2 == 0 else "run2") for n in range(8)]
        results = [f.result() for f in futures]
    for run_id, offset in (("run1", 0), ("run2", 1)):
        seqs = sorted(s for n, r in enumerate(results) if n % 2 == offset for s in r)
        assert seqs == list(range(1, 101)), run_id
        assert [d.seq for d in populated.list_decisions(run_id)] == list(range(1, 101))


TAMPERING: list[tuple[str, str, str]] = [
    ("UPDATE di una colonna", "UPDATE decisions SET rationale = 'riscritta'", "UPDATE vietato"),
    ("UPDATE del numero", "UPDATE decisions SET seq = 99", "UPDATE vietato"),
    ("UPDATE di una riga", "UPDATE decisions SET actor = 'user' WHERE seq = 1", "UPDATE vietato"),
    ("DELETE di tutto", "DELETE FROM decisions", "DELETE vietato"),
    (
        "DELETE di una riga",
        "DELETE FROM decisions WHERE run_id = 'run1' AND seq = 1",
        "DELETE vietato",
    ),
    (
        "INSERT OR REPLACE",
        f"INSERT OR REPLACE INTO decisions VALUES ('run1', 1, {ROW})",
        "non si sostituisce",
    ),
    (
        "REPLACE INTO",
        f"REPLACE INTO decisions VALUES ('run1', 1, {ROW})",
        "non si sostituisce",
    ),
    (
        "UPSERT DO UPDATE",
        f"INSERT INTO decisions VALUES ('run1', 1, {ROW}) "
        "ON CONFLICT (run_id, seq) DO UPDATE SET rationale = 'upsert'",
        "non si sostituisce",
    ),
    (
        "INSERT OR IGNORE sullo stesso numero",
        f"INSERT OR IGNORE INTO decisions VALUES ('run1', 1, {ROW})",
        "non si sostituisce",
    ),
    (
        "INSERT semplice sullo stesso numero",
        f"INSERT INTO decisions VALUES ('run1', 1, {ROW})",
        "non si sostituisce",
    ),
]


@pytest.mark.parametrize(("name", "sql", "message"), TAMPERING, ids=[t[0] for t in TAMPERING])
def test_il_log_decisioni_non_si_manomette(
    populated: Repository, raw: sqlite3.Connection, name: str, sql: str, message: str
) -> None:
    append(populated)
    append(populated, text="seconda")
    before = populated.list_decisions("run1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only") as info:
        raw.execute(sql)
    assert message in str(info.value), name
    assert populated.list_decisions("run1") == before


def test_i_trigger_restano_dopo_aver_riaperto_il_database(
    populated: Repository, db_path: Path, raw: sqlite3.Connection
) -> None:
    append(populated)
    Repository(db_path)  # riesegue lo schema
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        raw.execute("DELETE FROM decisions")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        raw.execute("UPDATE decisions SET actor = 'user'")
    assert len(populated.list_decisions("run1")) == 1


def test_il_trigger_non_blocca_le_aggiunte_nuove(
    populated: Repository, raw: sqlite3.Connection
) -> None:
    append(populated)
    raw.execute(f"INSERT INTO decisions VALUES ('run1', 2, {ROW})")
    raw.execute(f"INSERT INTO decisions VALUES ('run2', 1, {ROW})")
    assert [d.seq for d in populated.list_decisions("run1")] == [1, 2]


def test_un_run_con_decisioni_non_si_cancella(
    populated: Repository, raw: sqlite3.Connection
) -> None:
    append(populated)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        raw.execute("DELETE FROM runs WHERE id = 'run1'")
    assert populated.get_run("run1") is not None
    assert len(populated.list_decisions("run1")) == 1


# --- «Accesso solo da db/repository.py» (spech 5) -----------------------------------------


def imports_sqlite(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "sqlite3" for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "sqlite3":
            return True
    return False


def test_il_controllo_degli_import_funziona() -> None:
    assert imports_sqlite("import sqlite3")
    assert imports_sqlite("import os, sqlite3 as db")
    assert imports_sqlite("from sqlite3 import connect")
    assert imports_sqlite("def f():\n    import sqlite3")
    assert not imports_sqlite("import json\nx = 'sqlite3'")


def test_solo_il_repository_importa_sqlite3() -> None:
    allowed = BACKEND / "app" / "db" / "repository.py"
    offenders = []
    for folder in ("app", "scripts"):
        for path in (BACKEND / folder).rglob("*.py"):
            if path != allowed and imports_sqlite(path.read_text(encoding="utf-8")):
                offenders.append(path.relative_to(BACKEND).as_posix())
    assert offenders == [], f"sqlite3 usato fuori da db/repository.py: {offenders}"
    assert imports_sqlite(allowed.read_text(encoding="utf-8")), "il repository non usa più sqlite3?"
