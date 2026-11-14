import ast
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.db.repository import Repository
from app.models.notifications import NotificationDraft
from app.notifications.templates import (
    FOOTER,
    MAX_CHARS,
    NOTICE_HEADING,
    TITLE,
    advisory_text,
    mask_phone,
)
from tests.operations_support import make_repo

BACKEND = Path(__file__).resolve().parents[2]
DAY = date(2027, 7, 10)


def text(**changes: object) -> str:
    fields: dict[str, object] = {
        "event_name": "Match 2027 — serata di regata",
        "event_date": DAY,
        "closed_roads": ["Via Francesco Caracciolo", "Viale Anton Dohrn"],
        "transit_disruptions": ["Stazione Arco Mirelli chiusa"],
        "notice": "Chiusure dalle 16:00.",
    }
    return advisory_text(**{**fields, **changes})  # type: ignore[arg-type]


# --- il numero mascherato ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "masked"),
    [
        ("+393331234512", "+39 *** *** **12"),
        ("+39 333 123 4512", "+39 *** *** **12"),
        ("393331234512", "+39 *** *** **12"),
        ("+14155550199", "+** *** *** **99"),  # un altro prefisso non si lascia intravedere
    ],
)
def test_il_numero_si_maschera_lasciando_le_ultime_due_cifre(number: str, masked: str) -> None:
    assert mask_phone(number) == masked


# --- il testo ----------------------------------------------------------------------------------


def test_il_testo_ha_titolo_evento_strade_tpl_avviso_e_chiusura() -> None:
    assert text() == (
        "*Sentrix — Avviso viabilità*\n"
        "Evento: Match 2027 — serata di regata (10/07/2027)\n\n"
        "Strade chiuse:\n• Via Francesco Caracciolo\n• Viale Anton Dohrn\n\n"
        "Trasporto pubblico (TPL):\n• Stazione Arco Mirelli chiusa\n\n"
        f"{NOTICE_HEADING}\nChiusure dalle 16:00.\n\n"
        "Messaggio automatico di Sentrix"
    )


def test_la_prima_riga_e_in_grassetto_e_l_ultima_la_chiusura() -> None:
    lines = text().split("\n")
    assert lines[0] == TITLE and TITLE.startswith("*") and TITLE.endswith("*")
    assert lines[-1] == FOOTER


def test_il_testo_e_deterministico() -> None:
    assert text() == text()


def test_le_sezioni_vuote_si_omettono() -> None:
    only_roads = text(transit_disruptions=[], notice=None)
    assert "Trasporto pubblico" not in only_roads and NOTICE_HEADING not in only_roads
    only_transit = text(closed_roads=[], notice="")
    assert "Strade chiuse" not in only_transit and "Trasporto pubblico (TPL):" in only_transit


def test_le_voci_ripetute_si_scrivono_una_volta() -> None:
    twice = text(closed_roads=["Via A", " Via A ", "Via B", "Via A"])
    assert twice.count("• Via A") == 1 and "• Via B" in twice


def test_l_avviso_ai_cittadini_si_riporta_cosi_com_e() -> None:
    notice = "Linea 6 prolungata fino all'1:30; chiusure dalle 16:00."
    assert notice in text(notice=notice)


def test_mai_oltre_1024_caratteri_con_molte_voci_e_un_avviso_lungo() -> None:
    for roads, lines in ((0, 1), (3, 3), (60, 30), (400, 400)):
        result = advisory_text(
            event_name="E" * 500,
            event_date=DAY,
            closed_roads=[f"Via numero {i} con un nome piuttosto lungo" for i in range(roads)],
            transit_disruptions=[f"Linea {i} interrotta" for i in range(lines)],
            notice="Avviso molto lungo. " * 200,
        )
        assert len(result) <= MAX_CHARS == 1024, (roads, lines, len(result))
        assert result.startswith(TITLE) and result.endswith(FOOTER)


def test_le_voci_che_non_stanno_diventano_e_altre_n() -> None:
    many = [f"Via {i:03d}" for i in range(200)]
    result = text(closed_roads=many, notice=None)
    shown = result.count("• Via ")
    assert 0 < shown < 200
    assert f"• e altre {200 - shown}" in result
    assert len(result) <= MAX_CHARS


def test_l_avviso_troppo_lungo_si_accorcia_su_una_parola_e_il_resto_resta() -> None:
    result = text(notice="parola " * 400)
    assert "…" in result and len(result) <= MAX_CHARS
    assert "Via Francesco Caracciolo" in result and "Stazione Arco Mirelli" in result


def test_un_avviso_senza_posto_si_omette_invece_di_ridursi_a_poche_lettere() -> None:
    result = text(closed_roads=[f"Via con un nome molto molto lungo numero {i}" for i in range(18)])
    assert len(result) <= MAX_CHARS
    assert NOTICE_HEADING not in result and "Stazione Arco Mirelli chiusa" in result


# --- il modello e la tabella ------------------------------------------------------------------


def draft(**changes: object) -> NotificationDraft:
    fields: dict[str, object] = {
        "run_id": "run_1",
        "iteration": 1,
        "channel": "whatsapp",
        "recipient_id": "whatsapp_to",
        "recipient_label": "+39 *** *** **12",
        "kind": "traffic_advisory",
        "text": "ciao",
        "state": "SENT",
        "simulation": False,
    }
    return NotificationDraft(**{**fields, **changes})


def test_whatsapp_e_reale_e_il_bollettino_e_simulato() -> None:
    assert draft().simulation is False
    assert draft(channel="emergency_bulletin", simulation=True).simulation is True
    with pytest.raises(ValidationError, match="simulation"):
        draft(simulation=True)  # un WhatsApp «simulato» sarebbe una bugia
    with pytest.raises(ValidationError, match="simulation"):
        draft(channel="emergency_bulletin", simulation=False)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_repo(tmp_path, "run_1")


def test_la_riga_si_scrive_e_si_rilegge_uguale(repo: Repository) -> None:
    row = repo.add_notification(draft(evidence_ids=["a1", "a2"], error_code=None))
    assert row.id == 1 and row.created_at.tzinfo is not None
    assert repo.list_notifications("run_1") == [row]
    assert repo.list_notifications("run_1", "whatsapp") == [row]
    assert repo.list_notifications("run_1", "emergency_bulletin") == []
    assert repo.list_notifications("run_2") == []
    assert row.evidence_ids == ["a1", "a2"] and row.simulation is False


def test_la_tabella_e_append_only(repo: Repository) -> None:
    repo.add_notification(draft())
    with sqlite3.connect(repo._path) as conn:  # noqa: SLF001 (si prova il database, non l'API)
        for sql in (
            "UPDATE notifications SET state = 'FAILED'",
            "DELETE FROM notifications",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(sql)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "INSERT OR REPLACE INTO notifications (run_id, iteration, channel, recipient_id, "
                "kind, text, evidence_ids_json, state, simulation, created_at) VALUES "
                "('run_1', 0, 'whatsapp', 'x', 'k', 't', '[]', 'SENT', 0, '2026-11-14')"
            )


def test_il_database_rifiuta_un_bollettino_non_simulato(repo: Repository) -> None:
    with sqlite3.connect(repo._path) as conn, pytest.raises(sqlite3.IntegrityError):  # noqa: SLF001
        conn.execute(
            "INSERT INTO notifications (run_id, iteration, channel, recipient_id, kind, text, "
            "evidence_ids_json, state, simulation, created_at) VALUES "
            "('run_1', 0, 'emergency_bulletin', 'x', 'k', 't', '[]', 'SENT', 0, '2026-11-14')"
        )


def test_la_tabella_si_aggiunge_a_un_database_gia_esistente(repo: Repository) -> None:
    """Sulla VM il database c'è già, senza `notifications`: all'avvio la tabella nasce e i dati
    che c'erano restano (stessa `SCHEMA_VERSION`: nessuna migrazione)."""
    with sqlite3.connect(repo._path) as conn:  # noqa: SLF001
        conn.execute("DROP TABLE notifications")
    reopened = Repository(repo._path)  # noqa: SLF001
    assert reopened.get_run("run_1") is not None  # il resto dei dati non è stato toccato
    assert reopened.list_notifications("run_1") == []
    assert reopened.add_notification(draft()).id == 1


# --- architettura ------------------------------------------------------------------------------


def _strings(path: Path) -> list[str]:
    return [
        n.value
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_gli_indirizzi_di_whatsapp_stanno_solo_nel_client() -> None:
    holders = sorted(
        path.relative_to(BACKEND).as_posix()
        for folder in ("app", "scripts")
        for path in (BACKEND / folder).rglob("*.py")
        if any("api.callmebot.com" in s or "graph.facebook.com" in s for s in _strings(path))
    )
    assert holders == ["app/notifications/whatsapp_client.py"]


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_operations_non_importa_le_notifiche() -> None:
    """`operations/` resta senza client HTTP e senza il modulo che ne ha uno (spech 12.1)."""
    for path in (BACKEND / "app" / "operations").rglob("*.py"):
        assert not any(m.startswith("app.notifications") for m in _imports(path)), path.name


def test_i_motori_e_gli_agenti_non_conoscono_le_notifiche() -> None:
    """Nessun numero, prompt o motore dipende dalle notifiche: la cache demo resta valida."""
    for folder in ("engine", "agents", "llm", "operations", "data"):
        for path in (BACKEND / "app" / folder).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "app.notifications" not in source, path.relative_to(BACKEND)
