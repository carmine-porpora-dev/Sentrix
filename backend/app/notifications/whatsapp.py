import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.clock import now_rome
from app.db.repository import Repository
from app.models.notifications import Notification, NotificationDraft, NotificationState
from app.notifications.facts import collect_run_facts
from app.notifications.templates import advisory_text, mask_phone
from app.notifications.whatsapp_client import Transport, WhatsAppError, build_client
from app.settings import WhatsAppSettings

logger = logging.getLogger(__name__)

ACTOR = "operations"  # l'attore del log decisioni (12.4)
KIND = "traffic_advisory"
RECIPIENT_ID = "whatsapp_to"  # il destinatario è il numero in `.env`, uno solo


@dataclass(frozen=True)
class _Outcome:
    state: NotificationState
    error_code: str | None = None
    message_id: str | None = None
    detail: str = ""  # il motivo, per il log decisioni


class WhatsAppNotifier:
    def __init__(
        self,
        repo: Repository,
        settings: WhatsAppSettings,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] = now_rome,
    ) -> None:
        self._repo = repo
        self._settings = settings
        self._transport = transport
        self._clock = clock
        # un messaggio alla volta: il tetto giornaliero si controlla e si consuma senza corse
        self._lock = asyncio.Lock()

    async def notify_run(self, run_id: str) -> Notification | None:
        """Notifica il run se serve; `None` se non c'è nulla da dire o l'ha già fatto. **Non
        solleva** (tranne la cancellazione): il run è già `DONE`."""
        try:
            async with self._lock:
                return await self._notify(run_id)
        except Exception as exc:
            # solo il tipo: il messaggio di un'eccezione potrebbe contenere un URL
            logger.error(
                "WhatsApp: notifica del run %s non completata (%s)", run_id, type(exc).__name__
            )
            return None

    async def _notify(self, run_id: str) -> Notification | None:
        facts = collect_run_facts(self._repo, run_id)
        if facts is None:
            return None  # il run non c'è o non è finito
        run = facts.run
        if self._repo.list_notifications(run_id, "whatsapp"):
            return None  # un solo messaggio per run
        if not facts.has_closures_or_disruptions:
            return None  # nessuna strada chiusa e nessuna linea interrotta: niente da avvisare
        text = advisory_text(
            event_name=facts.event.name,
            event_date=facts.event.date,
            closed_roads=facts.closed_roads,
            transit_disruptions=facts.transit_disruptions,
            notice=facts.notice_text,
        )
        outcome = await self._deliver(text)
        at = self._clock()  # un solo istante per la riga e per la voce del registro
        notice = facts.notice
        evidence = [r.action_id for r in facts.closing] + ([notice.action_id] if notice else [])
        label = mask_phone(self._settings.to) if self._settings.to else None
        row = self._repo.add_notification(
            NotificationDraft(
                run_id=run_id,
                iteration=run.iteration,
                channel="whatsapp",
                recipient_id=RECIPIENT_ID,
                recipient_label=label,
                kind=KIND,
                text=text,
                evidence_ids=evidence,
                state=outcome.state,
                provider_message_id=outcome.message_id,
                error_code=outcome.error_code,
                simulation=False,
            ),
            at=at,
        )
        sent = outcome.state == "SENT"
        self._repo.append_decision(
            run_id=run_id,
            actor=ACTOR,
            decision="WhatsApp inviato" if sent else "WhatsApp non inviato",
            rationale=(
                f"Avviso viabilità a {label} (servizio {self._settings.provider})"
                if sent
                else outcome.detail
            ),
            refs=evidence,
            at=at,
        )
        return row

    async def _deliver(self, text: str) -> _Outcome:
        """Invia, o dice perché no. Controlli, in ordine: invio acceso, chiavi, tetto del giorno."""
        cfg = self._settings
        if cfg.mode == "off":
            return _Outcome("SKIPPED", "mode_off", detail="Invio disattivato (WHATSAPP_MODE=off)")
        if missing := cfg.missing():
            return _Outcome(
                "SKIPPED", "not_configured", detail=f"Variabili mancanti: {', '.join(missing)}"
            )
        if self._repo.count_whatsapp_attempts(self._clock().date().isoformat()) >= cfg.daily_limit:
            return _Outcome(
                "SKIPPED",
                "daily_limit",
                detail=f"Tetto giornaliero raggiunto ({cfg.daily_limit} messaggi)",
            )
        try:
            result = await build_client(cfg, transport=self._transport).send(text)
        except WhatsAppError as error:
            return _Outcome("FAILED", error.code, detail=f"Servizio {cfg.provider}: {error.detail}")
        return _Outcome("SENT", message_id=result.message_id)
