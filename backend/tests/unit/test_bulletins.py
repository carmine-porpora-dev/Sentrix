import ast
import asyncio
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.clock import ROME
from app.db.repository import (
    NotificationNotFound,
    NotificationStateConflict,
    Repository,
)
from app.models.api import Feature, FeatureCollection
from app.models.emergency_services import EmergencyServicesConfig
from app.notifications.bulletins import (
    BulletinService,
    acknowledge,
    critical_intersections,
    saturated_streets,
)
from app.notifications.templates import (
    BULLETIN_FOOTER,
    BULLETIN_NOTHING,
    BULLETIN_TITLE,
    Listed,
    bulletin_text,
)
from tests.operations_support import make_repo
from tests.support import make_request

NOON = datetime(2026, 11, 14, 12, 0, tzinfo=ROME)
SPANS = {"arrival": "12:00–14:00", "departure": "16:00–18:00"}
THRESHOLD = 0.9


def edge(
    name: str | None, vc: float, window: str, *, closed: bool = False, ev: str | None = None
) -> Feature:
    properties: dict[str, Any] = {"name": name, "vc": vc, "window": window, "closed": closed}
    if ev:
        properties["evidence_id"] = ev
    return Feature(id=f"{window}:{name}:{vc}", geometry=None, properties=properties)


def crossing(label: str, rank: int, window: str, ev: str | None = None) -> Feature:
    properties: dict[str, Any] = {"label": label, "rank": rank, "window": window}
    if ev:
        properties["evidence_id"] = ev
    return Feature(id=f"{window}:{label}", geometry=None, properties=properties)


# --- i destinatari -------------------------------------------------------------------------------


def test_il_file_vero_ha_gli_otto_destinatari_senza_posizioni() -> None:
    config = EmergencyServicesConfig.from_yaml()
    assert [s.id for s in config.services] == [
        "questura_napoli",
        "vigili_del_fuoco_napoli",
        "ospedale_cardarelli",
        "ospedale_del_mare",
        "ospedale_san_paolo",
        "ospedale_pellegrini",
        "ospedale_cto",
        "municipal_police",
    ]
    assert {s.kind for s in config.services} == {"police", "fire", "hospital"}
    assert config.max_listed >= 1
    assert "position" not in type(config.services[0]).model_fields  # decisione del proprietario


def test_un_destinatario_non_ha_una_posizione() -> None:
    text = (
        "max_listed: 5\nservices:\n  - {id: a, name: A, kind: police, position: {lat: 1, lon: 2}}"
    )
    with pytest.raises(ValidationError, match="position"):
        EmergencyServicesConfig.from_yaml_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "max_listed: 5\nservices: []",
        "max_listed: 0\nservices:\n  - {id: a, name: A, kind: police}",
        "max_listed: 5\nservices:\n  - {id: a, name: A, kind: ufo}",
        "max_listed: 5\nservices:\n  - {id: a, name: '', kind: police}",
        "max_listed: 5\nservices:\n  - {id: Maiuscolo, name: A, kind: police}",
        "max_listed: 5\nservices:\n  - {id: a, name: A, kind: police}\n  - {id: a, name: B, kind: fire}",  # noqa: E501
        "services:\n  - {id: a, name: A, kind: police}",
    ],
)
def test_destinatari_non_validi(text: str) -> None:
    with pytest.raises(Exception, match="(?i)validation|duplicat|String|Input|Field|Extra"):
        EmergencyServicesConfig.from_yaml_text(text)


# --- il testo ------------------------------------------------------------------------------------


def text(**changes: Any) -> str:
    fields: dict[str, Any] = {
        "recipient": "Questura di Napoli (sala operativa)",
        "event_name": "Match 2027 — serata di regata",
        "event_date": date(2027, 7, 10),
        "spans": SPANS,
        "closed_roads": ["Via Francesco Caracciolo", "Viale Anton Dohrn"],
        "saturated": [
            Listed("Via Marina", ("arrival", "departure")),
            Listed("Corso Umberto", ("departure",)),
        ],
        "critical_intersections": [Listed("Piazza Vittoria", ("departure",))],
        "transit_disruptions": ["Stazione Arco Mirelli chiusa"],
        "saturation_threshold": THRESHOLD,
        "limit": 12,
    }
    return bulletin_text(**{**fields, **changes})


def test_il_bollettino_ha_destinatario_evento_finestre_e_le_quattro_sezioni() -> None:
    assert text() == (
        "BOLLETTINO VIABILITÀ — SIMULATO\n"
        "A: Questura di Napoli (sala operativa)\n"
        "Evento: Match 2027 — serata di regata (10/07/2027)\n"
        "Arrivo: 12:00–14:00 · Deflusso: 16:00–18:00\n\n"
        "Strade chiuse:\n• Via Francesco Caracciolo\n• Viale Anton Dohrn\n\n"
        "Strade sature (carico oltre il 90% della capacità, stima del modello):\n"
        "• Via Marina — arrivo 12:00–14:00, deflusso 16:00–18:00\n"
        "• Corso Umberto — deflusso 16:00–18:00\n\n"
        "Incroci critici:\n• Piazza Vittoria — deflusso 16:00–18:00\n\n"
        "Trasporto pubblico interrotto:\n• Stazione Arco Mirelli chiusa\n\n" + BULLETIN_FOOTER
    )
    assert text().startswith(BULLETIN_TITLE)


def test_senza_criticita_lo_dice() -> None:
    quiet = text(closed_roads=[], saturated=[], critical_intersections=[], transit_disruptions=[])
    assert BULLETIN_NOTHING in quiet and "Strade chiuse" not in quiet
    assert quiet.startswith(BULLETIN_TITLE) and quiet.endswith(BULLETIN_FOOTER)


def test_le_sezioni_vuote_si_omettono_e_la_soglia_viene_dalla_configurazione() -> None:
    only = text(
        saturated=[], critical_intersections=[], transit_disruptions=[], saturation_threshold=0.85
    )
    assert "Strade chiuse" in only and "sature" not in only and "Incroci" not in only
    assert "oltre l'85%" not in only  # la sezione non c'è
    assert "oltre il 85%" in text(saturation_threshold=0.85)


def test_oltre_il_limite_le_voci_diventano_e_altre_n() -> None:
    many = [Listed(f"Via {i:02d}", ("departure",)) for i in range(20)]
    result = text(saturated=many, closed_roads=[], limit=5)
    assert result.count("• Via ") == 5 and "• e altre 15" in result
    # un elenco che sta nel limite non ha la riga
    assert "e altre" not in text(saturated=many[:5], closed_roads=[], limit=5)


def test_le_strade_chiuse_ripetute_si_scrivono_una_volta() -> None:
    result = text(
        closed_roads=["Via A", " Via A ", "Via B"], saturated=[], critical_intersections=[]
    )
    assert result.count("• Via A") == 1 and "• Via B" in result


def test_il_motore_non_e_una_previsione_e_il_testo_non_lo_chiama_cosi() -> None:
    assert "previsione" not in text().lower() and "previsto" not in text().lower()
    assert "simulat" in text().lower() and "nessun invio a enti reali" in text()


def test_il_testo_e_deterministico() -> None:
    assert text() == text()


# --- le strade sature, raggruppate per nome ----------------------------------------------------


def test_le_strade_sature_si_raggruppano_per_nome_con_le_finestre() -> None:
    layer = FeatureCollection(
        features=[
            edge("Via Marina", 0.95, "arrival", ev="m.a"),
            edge(
                "Via Marina", 1.20, "arrival", ev="m.a2"
            ),  # lo stesso nome e finestra: vale il peggiore
            edge("Via Marina", 0.97, "departure", ev="m.d"),
            edge("Corso Umberto", 1.30, "departure", ev="c.d"),
            edge("Via Lieve", 0.9, "departure"),  # esattamente sulla soglia: non è oltre
            edge("Via Bassa", 0.4, "arrival"),
        ]
    )
    found = saturated_streets(layer, THRESHOLD)
    assert [item for item, _ in found] == [
        Listed("Corso Umberto", ("departure",)),  # la più carica per prima
        Listed("Via Marina", ("arrival", "departure")),
    ]
    assert dict((i.label, ids) for i, ids in found) == {
        "Corso Umberto": ("c.d",),
        "Via Marina": ("m.a2", "m.d"),  # l'arco più carico di ogni finestra, in ordine di finestra
    }


def test_archi_chiusi_senza_nome_o_senza_numero_non_si_elencano() -> None:
    layer = FeatureCollection(
        features=[
            edge("Via Chiusa", 0.0, "departure", closed=True),
            edge(None, 1.5, "departure"),
            edge("   ", 1.5, "departure"),
            edge("Via Senza Finestra", 1.5, "nottata"),
            Feature(
                id="x", geometry=None, properties={"name": "Via Senza vc", "window": "arrival"}
            ),
        ]
    )
    assert saturated_streets(layer, THRESHOLD) == []
    assert saturated_streets(FeatureCollection(features=[]), THRESHOLD) == []


def test_a_parita_di_carico_si_ordina_per_nome() -> None:
    layer = FeatureCollection(
        features=[edge("Via B", 1.0, "arrival"), edge("Via A", 1.0, "arrival")]
    )
    assert [i.label for i, _ in saturated_streets(layer, THRESHOLD)] == ["Via A", "Via B"]


def test_gli_incroci_critici_per_nome_con_tutte_le_finestre() -> None:
    layer = FeatureCollection(
        features=[
            crossing("Piazza Vittoria", 1, "arrival", "e1"),
            crossing("Piazza Sannazaro", 1, "departure", "e2"),
            crossing("Piazza Vittoria", 2, "departure", "e3"),
            crossing("", 3, "departure"),
        ]
    )
    found = critical_intersections(layer)
    assert [i for i, _ in found] == [
        Listed("Piazza Sannazaro", ("departure",)),  # rank 1 anche lei: a parità, per nome
        Listed("Piazza Vittoria", ("arrival", "departure")),
    ]
    assert {i.label: ids for i, ids in found}["Piazza Vittoria"] == ("e1", "e3")


# --- il servizio ---------------------------------------------------------------------------------


CONFIG = EmergencyServicesConfig.from_yaml_text(
    "max_listed: 12\nservices:\n"
    "  - {id: questura, name: Questura, kind: police}\n"
    "  - {id: cto, name: CTO, kind: hospital}\n"
    "  - {id: vvf, name: Vigili del Fuoco, kind: fire}\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_repo(tmp_path, "run_1")  # su Match 2027, con due chiusure e una stazione chiusa


def finish(repo: Repository, run_id: str = "run_1") -> None:
    repo.update_run(run_id, state="DONE", iteration=1, ended_at=NOON)
    repo.put_layer(
        run_id,
        1,
        "edges_vc",
        FeatureCollection(
            features=[
                edge("Riviera di Chiaia", 0.95, "departure", ev="m.vc.1"),
                edge("Via Lieve", 0.5, "departure"),
            ]
        ),
    )
    repo.put_layer(
        run_id,
        1,
        "critical_intersections",
        FeatureCollection(features=[crossing("Piazza Vittoria", 1, "departure", "m.ci.1")]),
    )


def service(repo: Repository, config: EmergencyServicesConfig = CONFIG) -> BulletinService:
    return BulletinService(repo, config, THRESHOLD, clock=lambda: NOON)


async def test_in_done_un_bollettino_per_destinatario_consegnato(repo: Repository) -> None:
    finish(repo)
    created = await service(repo).notify_run("run_1")
    assert [n.recipient_id for n in created] == ["questura", "cto", "vvf"]
    listed = repo.list_notifications("run_1", "emergency_bulletin")
    assert listed == created
    for row in listed:
        assert (row.channel, row.state, row.simulation, row.kind) == (
            "emergency_bulletin",
            "DELIVERED",  # SENT → DELIVERED, subito e simulato
            True,
            "traffic_bulletin",
        )
        assert row.run_id == "run_1" and row.iteration == 1 and row.created_at == NOON
        assert row.recipient_label in {"Questura", "CTO", "Vigili del Fuoco"}


async def test_il_testo_viene_dai_dati_salvati_dell_ultima_iterazione(repo: Repository) -> None:
    finish(repo)
    (questura, *_) = await service(repo).notify_run("run_1")
    assert questura.text.startswith(BULLETIN_TITLE + "\nA: Questura\n")
    assert "Match 2027" in questura.text and "10/07/2027" in questura.text
    assert "• Via Francesco Caracciolo (viale Dohrn – piazza Vittoria)" in questura.text  # chiusa
    departure = repo.get_event("match_2027").window_span("departure")  # type: ignore[union-attr]
    assert f"• Riviera di Chiaia — deflusso {departure}" in questura.text
    assert "Via Lieve" not in questura.text  # sotto la soglia
    assert f"• Piazza Vittoria — deflusso {departure}" in questura.text
    assert "• Stazione Arco Mirelli chiusa per sicurezza" in questura.text
    assert BULLETIN_FOOTER in questura.text
    assert questura.evidence_ids == ["m.vc.1", "m.ci.1"]  # i Measured da cui vengono i dati


async def test_ogni_bollettino_cita_solo_il_destinatario_diverso(repo: Repository) -> None:
    finish(repo)
    a, b, c = await service(repo).notify_run("run_1")
    assert a.text.replace("Questura", "X") == b.text.replace("CTO", "X")
    assert len({a.text, b.text, c.text}) == 3


async def test_le_chiusure_accettate_entrano_nel_bollettino_e_nelle_evidenze(
    repo: Repository,
) -> None:
    finish(repo)
    repo.add_operation_request(
        make_request(
            "c1", run_id="run_1", department="traffic_control", type="close_road", target="e",
            target_label="Via Chiusa Ora", state="ACCEPTED",
        )
    )  # fmt: skip
    (first, *_) = await service(repo).notify_run("run_1")
    assert "• Via Chiusa Ora" in first.text and first.evidence_ids[0] == "c1"


async def test_senza_layer_ne_criticita_il_bollettino_parte_lo_stesso(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "run_1")
    repo.update_run("run_1", state="DONE", iteration=0, ended_at=NOON)
    created = await service(repo).notify_run("run_1")
    assert len(created) == 3 and all("sature" not in n.text for n in created)  # nessun layer


async def test_un_evento_tranquillo_dice_nessuna_criticita(tmp_path: Path) -> None:
    from tests.support import make_event, make_run

    repo = make_repo(tmp_path)
    event = make_event(id="tranquillo")
    repo.add_event(event)
    repo.add_run(make_run("run_q", event_id=event.id, event_revision=event.revision))
    repo.update_run("run_q", state="DONE", iteration=0, ended_at=NOON)
    (first, *_) = await service(repo).notify_run("run_q")
    assert BULLETIN_NOTHING in first.text and first.evidence_ids == []


async def test_il_registro_decisioni_ha_una_voce_sola_senza_invio_esterno(repo: Repository) -> None:
    finish(repo)
    await service(repo).notify_run("run_1")
    entries = [d for d in repo.list_decisions("run_1") if d.actor == "operations"]
    assert len(entries) == 1
    assert "3 servizi (simulato)" in entries[0].decision
    assert (
        "Questura" in entries[0].rationale
        and "Nessun invio verso l'esterno" in entries[0].rationale
    )


async def test_un_run_non_finito_o_inesistente_non_ha_bollettini(repo: Repository) -> None:
    assert await service(repo).notify_run("run_1") == []  # INTAKE
    assert await service(repo).notify_run("fantasma") == []
    assert repo.list_notifications("run_1") == []


async def test_e_idempotente_e_completa_i_destinatari_mancanti(repo: Repository) -> None:
    finish(repo)
    one = EmergencyServicesConfig.from_yaml_text(
        "max_listed: 12\nservices:\n  - {id: questura, name: Questura, kind: police}\n"
    )
    assert len(await service(repo, one).notify_run("run_1")) == 1
    assert await service(repo, one).notify_run("run_1") == []  # già fatto
    rest = await service(repo).notify_run("run_1")  # la lista è cresciuta: arrivano gli altri
    assert [n.recipient_id for n in rest] == ["cto", "vvf"]
    assert len(repo.list_notifications("run_1", "emergency_bulletin")) == 3


async def test_non_solleva_mai(
    repo: Repository, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    finish(repo)

    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("disco pieno")

    monkeypatch.setattr(repo, "add_notifications", boom)
    with caplog.at_level(logging.ERROR):
        assert await service(repo).notify_run("run_1") == []
    assert "RuntimeError" in caplog.text and "Bollettini" in caplog.text


def test_non_importa_ne_usa_un_client_http() -> None:
    source = (Path(__file__).resolve().parents[2] / "app/notifications/bulletins.py").read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {m.split(".")[0] for m in imported} & {"httpx2", "httpx", "requests", "aiohttp"}
    assert not any("whatsapp_client" in m for m in imported)


# --- il ciclo di vita e la conferma di ricezione -----------------------------------------------


async def bulletin_id(repo: Repository) -> int:
    finish(repo)
    (first, *_) = await service(repo).notify_run("run_1")
    return first.id


async def test_la_conferma_porta_a_acknowledged_e_resta_nel_registro(repo: Repository) -> None:
    notification_id = await bulletin_id(repo)
    done = acknowledge(repo, notification_id)
    assert done.state == "ACKNOWLEDGED" and done.id == notification_id
    assert repo.get_notification(notification_id) == done
    assert [n.state for n in repo.list_notifications("run_1", "emergency_bulletin")] == [
        "ACKNOWLEDGED",
        "DELIVERED",
        "DELIVERED",  # gli altri destinatari non cambiano
    ]
    entry = [d for d in repo.list_decisions("run_1") if d.actor == "user"]
    assert len(entry) == 1 and entry[0].decision == "Ricezione del bollettino confermata"
    assert entry[0].rationale == "Questura"


async def test_i_passaggi_sono_in_ordine_e_la_riga_non_cambia(repo: Repository) -> None:
    notification_id = await bulletin_id(repo)
    original = repo.list_notifications("run_1", "emergency_bulletin")[0]
    acknowledge(repo, notification_id)
    assert [(a, b) for a, b, _ in repo.list_notification_events(notification_id)] == [
        ("SENT", "DELIVERED"),
        ("DELIVERED", "ACKNOWLEDGED"),
    ]
    with sqlite3.connect(repo._path) as conn:  # noqa: SLF001
        stored = conn.execute(
            "SELECT state, text FROM notifications WHERE id = ?", (notification_id,)
        ).fetchone()
    assert stored == ("SENT", original.text)  # la riga resta com'è nata: append-only


async def test_una_seconda_conferma_e_un_conflitto_e_non_scrive_nulla(repo: Repository) -> None:
    notification_id = await bulletin_id(repo)
    acknowledge(repo, notification_id)
    with pytest.raises(NotificationStateConflict) as info:
        acknowledge(repo, notification_id)
    assert info.value.found == "ACKNOWLEDGED"
    assert len(repo.list_notification_events(notification_id)) == 2
    assert len([d for d in repo.list_decisions("run_1") if d.actor == "user"]) == 1


async def test_whatsapp_non_si_conferma(repo: Repository) -> None:
    from app.models.notifications import NotificationDraft

    finish(repo)
    row = repo.add_notification(
        NotificationDraft(
            run_id="run_1", iteration=1, channel="whatsapp", recipient_id="whatsapp_to",
            kind="traffic_advisory", text="ciao", state="SENT", simulation=False,
        )
    )  # fmt: skip
    with pytest.raises(NotificationStateConflict):
        acknowledge(repo, row.id)
    assert repo.list_notification_events(row.id) == []


def test_una_notifica_che_non_esiste(repo: Repository) -> None:
    with pytest.raises(NotificationNotFound):
        acknowledge(repo, 424242)
    assert repo.get_notification(424242) is None


async def test_due_conferme_insieme_ne_riescono_una(repo: Repository) -> None:
    notification_id = await bulletin_id(repo)
    results = await asyncio.gather(
        asyncio.to_thread(acknowledge, repo, notification_id),
        asyncio.to_thread(acknowledge, repo, notification_id),
        return_exceptions=True,
    )
    assert sorted(type(r).__name__ for r in results) == [
        "Notification",
        "NotificationStateConflict",
    ]
    assert len(repo.list_notification_events(notification_id)) == 2


async def test_notification_events_e_append_only(repo: Repository) -> None:
    notification_id = await bulletin_id(repo)
    acknowledge(repo, notification_id)
    with sqlite3.connect(repo._path) as conn:  # noqa: SLF001
        for sql in (
            "UPDATE notification_events SET to_state = 'SENT'",
            "DELETE FROM notification_events",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(sql)


async def test_un_secondo_bollettino_per_lo_stesso_destinatario_lo_rifiuta_il_database(
    repo: Repository,
) -> None:
    from app.models.notifications import NotificationDraft

    finish(repo)
    await service(repo).notify_run("run_1")
    again = NotificationDraft(
        run_id="run_1", iteration=1, channel="emergency_bulletin", recipient_id="questura",
        kind="traffic_bulletin", text="doppio", state="SENT", simulation=True,
    )  # fmt: skip
    with pytest.raises(sqlite3.IntegrityError, match="append-only|UNIQUE"):
        repo.add_notification(again)
    with sqlite3.connect(repo._path) as conn, pytest.raises(sqlite3.IntegrityError):  # noqa: SLF001
        conn.execute(
            "INSERT OR REPLACE INTO notifications (run_id, iteration, channel, recipient_id, kind, "
            "text, evidence_ids_json, state, simulation, created_at) VALUES "
            "('run_1', 1, 'emergency_bulletin', 'questura', 'k', 't', '[]', 'SENT', 1, '2026')"
        )


def test_riga_e_passaggi_di_un_bollettino_nascono_nella_stessa_transazione(
    repo: Repository,
) -> None:
    from app.models.notifications import NotificationDraft

    repo.update_run("run_1", state="DONE", iteration=1, ended_at=NOON)
    draft = NotificationDraft(
        run_id="run_1", iteration=1, channel="emergency_bulletin", recipient_id="a",
        kind="traffic_bulletin", text="t", state="SENT", simulation=True,
    )  # fmt: skip
    created = repo.add_notification(draft, then=("DELIVERED", "ACKNOWLEDGED"))
    assert created.state == "ACKNOWLEDGED"
    assert [(a, b) for a, b, _ in repo.list_notification_events(created.id)] == [
        ("SENT", "DELIVERED"),
        ("DELIVERED", "ACKNOWLEDGED"),
    ]
    # un errore a metà non lascia niente: lo stesso destinatario due volte → nessun evento in più
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_notification(draft, then=("DELIVERED",))
    with sqlite3.connect(repo._path) as conn:  # noqa: SLF001
        assert conn.execute("SELECT COUNT(*) FROM notification_events").fetchone()[0] == 2


def test_i_bollettini_di_un_run_si_scrivono_tutti_o_nessuno(repo: Repository) -> None:
    """Chi legge mentre i bollettini nascono non ne vede la metà: una transazione sola."""
    from app.db.repository import NewDecision
    from app.models.notifications import NotificationDraft

    repo.update_run("run_1", state="DONE", iteration=1, ended_at=NOON)

    def draft(recipient: str) -> NotificationDraft:
        return NotificationDraft(
            run_id="run_1", iteration=1, channel="emergency_bulletin", recipient_id=recipient,
            kind="traffic_bulletin", text="t", state="SENT", simulation=True,
        )  # fmt: skip

    note = NewDecision(actor="operations", decision="d", rationale="r")
    with pytest.raises(sqlite3.IntegrityError):  # il terzo è uguale al primo
        repo.add_notifications(
            [draft("a"), draft("b"), draft("a")], then=("DELIVERED",), decision=note
        )
    assert repo.list_notifications("run_1") == []
    assert repo.list_decisions("run_1") == []
    with sqlite3.connect(repo._path) as conn:  # noqa: SLF001
        assert conn.execute("SELECT COUNT(*) FROM notification_events").fetchone()[0] == 0
    ok = repo.add_notifications([draft("a"), draft("b")], then=("DELIVERED",), decision=note)
    assert [n.state for n in ok] == ["DELIVERED", "DELIVERED"]
    assert len(repo.list_decisions("run_1")) == 1  # una voce per il gruppo, non una per riga
