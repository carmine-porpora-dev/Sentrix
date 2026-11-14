import asyncio
import logging
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.clock import ROME
from app.db.repository import Repository
from app.models.notifications import NotificationDraft
from app.notifications.templates import FOOTER, MAX_CHARS, TITLE
from app.notifications.whatsapp import ACTOR, WhatsAppNotifier
from app.settings import WhatsAppSettings
from tests.operations_support import make_repo
from tests.support import make_event, make_request, make_run
from tests.unit.test_whatsapp_client import APIKEY, NUMBER, SUCCESS_PAGE, Service

LIVE = WhatsAppSettings(mode="live", to=NUMBER, callmebot_apikey=APIKEY)
NOON = datetime(2026, 11, 14, 12, 0, tzinfo=ROME)
NOTICE = "Chiusure dalle 16:00 in via Caracciolo. Linea 6 prolungata fino all'1:30."


def finish(repo: Repository, run_id: str = "run_1", *, notice: bool = True) -> None:
    """Il run è `DONE` e, se serve, ha l'avviso ai cittadini accettato (come in `_finish`)."""
    repo.update_run(run_id, state="DONE", iteration=1, ended_at=NOON)
    if notice:
        repo.add_operation_request(
            make_request(
                f"{run_id}_notice",
                run_id=run_id,
                department="public_comms",
                type="citizen_notice",
                target="all",
                target_label="Cittadini",
                state="ACCEPTED",
                payload={"text": NOTICE},
            )
        )


def notifier(
    repo: Repository, service: Service | None = None, settings: WhatsAppSettings = LIVE
) -> WhatsAppNotifier:
    transport = (service or Service()).transport
    return WhatsAppNotifier(repo, settings, transport=transport, clock=lambda: NOON)


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return make_repo(tmp_path, "run_1")  # su Match 2027: due chiusure e una stazione chiusa


def decisions(repo: Repository, run_id: str = "run_1") -> list[Any]:
    return [d for d in repo.list_decisions(run_id) if d.actor == ACTOR]


def everything_stored(repo: Repository, run_id: str = "run_1") -> str:
    rows = [n.model_dump_json() for n in repo.list_notifications(run_id)]
    rows += [d.model_dump_json() for d in repo.list_decisions(run_id)]
    return "\n".join(rows)


def only_event(repo: Repository, **changes: Any) -> None:
    """Il run `run_1` su un evento di prova con i campi dati (chiusure, linee interrotte)."""
    event = make_event(id="solo_prova", **changes)
    repo.add_event(event)
    repo.add_run(make_run("run_2", event_id=event.id, event_revision=event.revision))


# --- l'invio -----------------------------------------------------------------------------------


async def test_in_done_parte_un_messaggio_e_si_registra_inviato(repo: Repository) -> None:
    finish(repo)
    service = Service()
    row = await notifier(repo, service).notify_run("run_1")
    assert row is not None and row.state == "SENT" and row.error_code is None
    assert (row.channel, row.simulation, row.run_id, row.iteration) == (
        "whatsapp",
        False,
        "run_1",
        1,
    )
    assert row.recipient_label == "+39 *** *** **12"
    assert len(service.requests) == 1
    assert (
        service.requests[0].url.params["text"] == row.text
    )  # quello che è partito è quello salvato
    assert repo.list_notifications("run_1", "whatsapp") == [row]


async def test_il_messaggio_ha_il_formato_della_spec(repo: Repository) -> None:
    finish(repo)
    row = await notifier(repo).notify_run("run_1")
    assert row is not None
    lines = row.text.split("\n")
    assert lines[0] == TITLE == "*Sentrix — Avviso viabilità*"
    assert lines[-1] == FOOTER == "Messaggio automatico di Sentrix"
    assert len(row.text) <= MAX_CHARS == 1024
    assert "Match 2027" in row.text and "10/07/2027" in row.text  # nome e data dell'evento
    assert "• Via Francesco Caracciolo (viale Dohrn – piazza Vittoria)" in row.text
    assert "• Viale Anton Dohrn" in row.text  # strade chiuse
    assert "• Stazione Arco Mirelli chiusa per sicurezza" in row.text  # TPL interrotto
    assert NOTICE in row.text  # l'avviso ai cittadini già generato, così com'è
    assert row.evidence_ids == ["run_1_notice"]


async def test_senza_avviso_ai_cittadini_il_messaggio_parte_lo_stesso(repo: Repository) -> None:
    finish(repo, notice=False)
    row = await notifier(repo).notify_run("run_1")
    assert row is not None and row.state == "SENT" and row.evidence_ids == []
    assert "Misure per i cittadini" not in row.text


async def test_l_avviso_rifiutato_non_entra_nel_messaggio(repo: Repository) -> None:
    finish(repo, notice=False)
    repo.add_operation_request(
        make_request(
            "n1", run_id="run_1", department="public_comms", type="citizen_notice", target="all",
            target_label="Cittadini", state="REJECTED", reject_code="X", reject_reason="no",
            payload={"text": NOTICE},
        )
    )  # fmt: skip
    row = await notifier(repo).notify_run("run_1")
    assert row is not None and NOTICE not in row.text


async def test_l_esito_e_nel_log_decisioni_con_il_numero_mascherato(repo: Repository) -> None:
    finish(repo)
    await notifier(repo).notify_run("run_1")
    (entry,) = decisions(repo)
    assert entry.decision == "WhatsApp inviato"
    assert "+39 *** *** **12" in entry.rationale and "callmebot" in entry.rationale
    assert entry.refs == ["run_1_notice"]


async def test_un_run_non_finito_non_notifica(repo: Repository) -> None:
    service = Service()
    assert await notifier(repo, service).notify_run("run_1") is None  # INTAKE
    repo.update_run("run_1", state="ERROR", error="x", ended_at=NOON)
    assert await notifier(repo, service).notify_run("run_1") is None
    assert await notifier(repo, service).notify_run("fantasma") is None
    assert service.requests == [] and repo.list_notifications("run_1") == []


# --- quando non c'è nulla da dire ---------------------------------------------------------------


async def test_senza_chiusure_ne_linee_interrotte_non_parte_nulla(repo: Repository) -> None:
    only_event(repo)
    finish(repo, "run_2")
    service = Service()
    assert await notifier(repo, service).notify_run("run_2") is None
    assert service.requests == [] and repo.list_notifications("run_2") == []
    assert decisions(repo, "run_2") == []  # nemmeno una voce nel registro


async def test_una_chiusura_dell_evento_basta(repo: Repository) -> None:
    closure = {"label": "Via Prova", "street_names": ["Via Prova"]}
    only_event(repo, closures=[closure])
    finish(repo, "run_2")
    row = await notifier(repo).notify_run("run_2")
    assert row is not None and "• Via Prova" in row.text and "Trasporto pubblico" not in row.text


async def test_basta_una_linea_interrotta(repo: Repository) -> None:
    disruption = {"label": "Fermata Prova chiusa", "stop_name": "Prova", "window": "both"}
    only_event(repo, transit_disruptions=[disruption])
    finish(repo, "run_2")
    row = await notifier(repo).notify_run("run_2")
    assert row is not None and "• Fermata Prova chiusa" in row.text
    assert "Strade chiuse" not in row.text


async def test_una_riduzione_di_capacita_non_e_una_chiusura(repo: Repository) -> None:
    reduction = {
        "label": "Via Ridotta",
        "street_names": ["Via Ridotta"],
        "mode": "capacity_reduction",
        "capacity_factor": 0.5,
    }
    only_event(repo, closures=[reduction])
    finish(repo, "run_2")
    assert await notifier(repo).notify_run("run_2") is None


async def test_una_close_road_accettata_basta_e_una_rifiutata_no(repo: Repository) -> None:
    only_event(repo)
    finish(repo, "run_2")
    for action_id, state in (("c1", "ACCEPTED"), ("c2", "REJECTED")):
        extra: dict[str, Any] = (
            {"reject_code": "X", "reject_reason": "no"} if state == "REJECTED" else {}
        )
        repo.add_operation_request(
            make_request(
                action_id, run_id="run_2", department="traffic_control", type="close_road",
                target=f"edge_{action_id}", target_label=f"Via {action_id}", state=state, **extra,
            )
        )  # fmt: skip
    row = await notifier(repo).notify_run("run_2")
    assert row is not None and "• Via c1" in row.text and "Via c2" not in row.text
    assert "c1" in row.evidence_ids


# --- un messaggio solo per run --------------------------------------------------------------------


async def test_e_idempotente_sul_run(repo: Repository) -> None:
    finish(repo)
    service = Service()
    mine = notifier(repo, service)
    first = await mine.notify_run("run_1")
    assert first is not None
    assert await mine.notify_run("run_1") is None
    assert await notifier(repo, service).notify_run("run_1") is None  # nemmeno da un altro processo
    assert len(service.requests) == 1
    assert len(repo.list_notifications("run_1", "whatsapp")) == 1 and len(decisions(repo)) == 1


async def test_due_notifiche_insieme_per_lo_stesso_run_ne_mandano_una(repo: Repository) -> None:
    finish(repo)
    service = Service()
    mine = notifier(repo, service)
    results = await asyncio.gather(mine.notify_run("run_1"), mine.notify_run("run_1"))
    assert sorted(r is not None for r in results) == [False, True]
    assert len(service.requests) == 1


def test_il_database_rifiuta_un_secondo_messaggio_per_lo_stesso_run(repo: Repository) -> None:
    draft = NotificationDraft(
        run_id="run_1", iteration=0, channel="whatsapp", recipient_id="whatsapp_to", kind="k",
        text="t", state="SENT", simulation=False,
    )  # fmt: skip
    repo.add_notification(draft)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repo.add_notification(draft)


# --- quando non parte --------------------------------------------------------------------------


async def test_con_l_invio_spento_e_saltato_e_non_si_chiama_il_servizio(repo: Repository) -> None:
    finish(repo)
    service = Service()
    off = replace(LIVE, mode="off")
    row = await notifier(repo, service, off).notify_run("run_1")
    assert row is not None and (row.state, row.error_code) == ("SKIPPED", "mode_off")
    assert service.requests == []
    (entry,) = decisions(repo)
    assert entry.decision == "WhatsApp non inviato" and "WHATSAPP_MODE=off" in entry.rationale


@pytest.mark.parametrize(
    ("settings", "named"),
    [
        (WhatsAppSettings(mode="live", to=NUMBER), ["CALLMEBOT_APIKEY"]),
        (WhatsAppSettings(mode="live", callmebot_apikey=APIKEY), ["WHATSAPP_TO"]),
        (WhatsAppSettings(mode="live"), ["WHATSAPP_TO", "CALLMEBOT_APIKEY"]),
        (
            WhatsAppSettings(mode="live", provider="meta", to=NUMBER),
            ["WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_API_VERSION"],
        ),
    ],
)
async def test_con_le_chiavi_mancanti_e_saltato_e_si_dicono_i_nomi(
    repo: Repository, settings: WhatsAppSettings, named: list[str]
) -> None:
    finish(repo)
    service = Service()
    row = await notifier(repo, service, settings).notify_run("run_1")
    assert row is not None and (row.state, row.error_code) == ("SKIPPED", "not_configured")
    assert service.requests == []
    (entry,) = decisions(repo)
    assert all(name in entry.rationale for name in named)
    stored = everything_stored(repo)
    assert APIKEY not in stored and "393331234512" not in stored


async def test_il_tetto_giornaliero_salta_i_messaggi_oltre_il_limite(repo: Repository) -> None:
    repo.add_run(make_run("run_2"))
    repo.add_run(make_run("run_3"))
    for run_id in ("run_1", "run_2", "run_3"):
        finish(repo, run_id)
    service = Service()
    mine = notifier(repo, service, replace(LIVE, daily_limit=2))
    outcomes = [(await mine.notify_run(r)) for r in ("run_1", "run_2", "run_3")]
    assert [o.state for o in outcomes if o] == ["SENT", "SENT", "SKIPPED"]
    assert outcomes[2] is not None and outcomes[2].error_code == "daily_limit"
    assert len(service.requests) == 2
    assert "2 messaggi" in decisions(repo, "run_3")[0].rationale


async def test_il_tetto_conta_i_falliti_ma_non_i_saltati(repo: Repository) -> None:
    for run_id in ("run_2", "run_3", "run_4"):
        repo.add_run(make_run(run_id))
    for run_id in ("run_1", "run_2", "run_3", "run_4"):
        finish(repo, run_id)
    failing = Service(httpx2.Response(400, text="denied"))
    first = await notifier(repo, failing, replace(LIVE, daily_limit=1)).notify_run("run_1")
    assert first is not None and first.state == "FAILED"  # ha impegnato il servizio: conta
    second = await notifier(repo, Service(), replace(LIVE, daily_limit=1)).notify_run("run_2")
    assert second is not None and second.error_code == "daily_limit"
    # un messaggio saltato non consuma il tetto: con l'invio spento non si arriva mai a 1
    off = notifier(repo, Service(), replace(LIVE, mode="off"))
    assert (await off.notify_run("run_3")) is not None
    assert repo.count_whatsapp_attempts("2026-11-14") == 1


async def test_il_tetto_e_del_giorno(repo: Repository) -> None:
    finish(repo)
    one = notifier(repo, settings=replace(LIVE, daily_limit=1))
    await one.notify_run("run_1")
    assert repo.count_whatsapp_attempts("2026-11-14") == 1
    assert repo.count_whatsapp_attempts("2026-11-13") == 0
    assert repo.count_whatsapp_attempts("2026-11-15") == 0


# --- gli errori del servizio ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcomes", "code", "calls"),
    [
        ((httpx2.Response(200, text="ERROR: apikey is invalid"),), "rejected", 1),
        ((httpx2.Response(403, text="denied"),), "rejected", 1),
        ((httpx2.Response(503),), "unreachable", 2),
        ((httpx2.ReadTimeout("t"),), "unreachable", 2),
        ((httpx2.ConnectError("c"),), "unreachable", 2),
    ],
)
async def test_gli_errori_del_servizio_sono_registrati_come_falliti(
    repo: Repository,
    outcomes: tuple[httpx2.Response | Exception, ...],
    code: str,
    calls: int,
) -> None:
    finish(repo)
    service = Service(*outcomes)
    row = await notifier(repo, service).notify_run("run_1")
    assert row is not None and (row.state, row.error_code) == ("FAILED", code)
    assert len(service.requests) == calls
    (entry,) = decisions(repo)
    assert entry.decision == "WhatsApp non inviato" and "callmebot" in entry.rationale
    assert repo.get_run("run_1").state == "DONE"  # type: ignore[union-attr]  # il run non cambia


async def test_un_errore_poi_il_nuovo_tentativo_riesce(repo: Repository) -> None:
    finish(repo)
    service = Service(httpx2.Response(502), httpx2.Response(200, text=SUCCESS_PAGE))
    row = await notifier(repo, service).notify_run("run_1")
    assert row is not None and row.state == "SENT" and len(service.requests) == 2


async def test_un_errore_imprevisto_non_solleva_e_non_lascia_tracce_del_segreto(
    repo: Repository, caplog: pytest.LogCaptureFixture
) -> None:
    finish(repo)
    boom = RuntimeError(f"https://api.callmebot.com/whatsapp.php?phone={NUMBER}&apikey={APIKEY}")
    with caplog.at_level(logging.DEBUG):
        assert await notifier(repo, Service(boom)).notify_run("run_1") is None
    assert "RuntimeError" in caplog.text  # si vede che è successo, non cosa c'era nel messaggio
    assert APIKEY not in caplog.text and "393331234512" not in caplog.text


# --- numero e chiave non escono mai -------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        httpx2.Response(200, text=SUCCESS_PAGE),
        httpx2.Response(200, text=f"ERROR phone {NUMBER} key {APIKEY}"),
        httpx2.Response(500, text=f"{NUMBER} {APIKEY}"),
        httpx2.ConnectError(f"https://x?phone={NUMBER}&apikey={APIKEY}"),
    ],
)
async def test_numero_e_chiave_non_sono_in_database_log_decisioni_e_log(
    repo: Repository, caplog: pytest.LogCaptureFixture, outcome: httpx2.Response | Exception
) -> None:
    finish(repo)
    with caplog.at_level(logging.DEBUG):
        row = await notifier(repo, Service(outcome)).notify_run("run_1")
    assert row is not None
    haystack = everything_stored(repo) + caplog.text
    for secret in (NUMBER, NUMBER.lstrip("+"), APIKEY, "3331234512"):
        assert secret not in haystack
    assert row.recipient_label == "+39 *** *** **12"
