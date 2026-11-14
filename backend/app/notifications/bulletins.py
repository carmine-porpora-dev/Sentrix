import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime

from app.clock import now_rome
from app.db.repository import NewDecision, NotificationNotFound, Repository
from app.models.api import FeatureCollection
from app.models.base import WINDOWS, Window
from app.models.emergency_services import EmergencyServicesConfig
from app.models.notifications import Notification, NotificationDraft, NotificationState
from app.notifications.facts import RunFacts, collect_run_facts
from app.notifications.templates import Listed, bulletin_text

logger = logging.getLogger(__name__)

ACTOR = "operations"  # l'attore del log decisioni alla consegna (12.4)
ACK_ACTOR = "user"  # la conferma di ricezione la dà una persona
KIND = "traffic_bulletin"
ACKNOWLEDGEABLE: tuple[NotificationState, ...] = ("SENT", "DELIVERED")

# una voce dell'elenco e gli id dei `Measured` da cui viene
Found = tuple[Listed, tuple[str, ...]]


def saturated_streets(layer: FeatureCollection, threshold: float) -> list[Found]:
    """Le strade con almeno un arco aperto oltre `threshold` di v/c, raggruppate per **nome**, con
    le finestre in cui succede; dalla più carica (a parità, per nome). Per ogni strada gli id dei
    `Measured` dell'arco più carico di ciascuna finestra. Gli archi senza nome non si elencano: a
    chi riceve non direbbero niente."""
    worst: dict[tuple[str, Window], tuple[float, str | None]] = {}
    for feature in layer.features:
        props = feature.properties
        name, vc, window = props.get("name"), props.get("vc"), props.get("window")
        if (
            props.get("closed")
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(vc, int | float)
            or vc <= threshold
            or window not in WINDOWS
        ):
            continue
        evidence = props.get("evidence_id")
        key = (name.strip(), window)
        if key not in worst or vc > worst[key][0]:
            worst[key] = (float(vc), evidence if isinstance(evidence, str) else None)
    names = {name for name, _ in worst}
    peak = {name: max(vc for (n, _), (vc, _) in worst.items() if n == name) for name in names}
    found: list[Found] = []
    for name in sorted(names, key=lambda n: (-peak[n], n)):
        present = [w for w in WINDOWS if (name, w) in worst]
        ids = tuple(e for w in present if (e := worst[(name, w)][1]))
        found.append((Listed(name, tuple(present)), ids))
    return found


def critical_intersections(layer: FeatureCollection) -> list[Found]:
    """Gli incroci critici dell'ultima iterazione per nome (lo stesso incrocio in due finestre è una
    voce sola con tutte e due), dal meglio classificato."""
    windows: dict[str, list[Window]] = defaultdict(list)
    rank: dict[str, int] = {}
    evidence_of: dict[str, list[str]] = defaultdict(list)
    for feature in layer.features:  # già nell'ordine arrivo → deflusso (`merge_windows`)
        props = feature.properties
        label, window, position = props.get("label"), props.get("window"), props.get("rank")
        if not isinstance(label, str) or not label.strip() or window not in WINDOWS:
            continue
        label = label.strip()
        if window not in windows[label]:
            windows[label].append(window)
        if isinstance(position, int):
            rank[label] = min(rank.get(label, position), position)
        evidence_id = props.get("evidence_id")
        if isinstance(evidence_id, str):
            evidence_of[label].append(evidence_id)
    ranked = sorted(windows, key=lambda label: (rank.get(label, 10**6), label))
    return [(Listed(label, tuple(windows[label])), tuple(evidence_of[label])) for label in ranked]


class BulletinService:
    def __init__(
        self,
        repo: Repository,
        config: EmergencyServicesConfig,
        saturation_threshold: float,
        *,
        clock: Callable[[], datetime] = now_rome,
    ) -> None:
        self._repo = repo
        self._config = config
        self._threshold = saturation_threshold  # `metrics.vc_critical_threshold` di engine.yaml
        self._clock = clock

    async def notify_run(self, run_id: str) -> list[Notification]:
        """I bollettini del run (uno per destinatario che non l'ha già); `[]` se il run non è
        finito. **Non solleva** (tranne la cancellazione): il run è già `DONE`. Gira in un thread:
        i layer di un run sono grossi e il server non deve fermarsi a leggerli."""
        try:
            return await asyncio.to_thread(self._notify, run_id)
        except Exception as exc:
            logger.error("Bollettini: run %s non completato (%s)", run_id, type(exc).__name__)
            return []

    def _notify(self, run_id: str) -> list[Notification]:
        facts = collect_run_facts(self._repo, run_id)
        if facts is None:
            return []
        have = {n.recipient_id for n in self._repo.list_notifications(run_id, "emergency_bulletin")}
        recipients = [s for s in self._config.services if s.id not in have]
        if not recipients:
            return []  # già fatti: un bollettino per destinatario e per run
        limit = self._config.max_listed
        edges = self._layer(facts, "edges_vc")
        crossings = self._layer(facts, "critical_intersections")
        saturated = saturated_streets(edges, self._threshold)
        critical = critical_intersections(crossings)
        spans = {w: facts.event.window_span(w) for w in WINDOWS}
        evidence = [r.action_id for r in facts.closing]
        evidence += [e for _, ids in (*saturated[:limit], *critical[:limit]) for e in ids]
        evidence = list(dict.fromkeys(evidence))
        at = self._clock()  # un solo istante per tutti i bollettini del run
        drafts = [
            NotificationDraft(
                run_id=run_id,
                iteration=facts.run.iteration,
                channel="emergency_bulletin",
                recipient_id=service.id,
                recipient_label=service.name,
                kind=KIND,
                text=bulletin_text(
                    recipient=service.name,
                    event_name=facts.event.name,
                    event_date=facts.event.date,
                    spans=spans,
                    closed_roads=facts.closed_roads,
                    saturated=[item for item, _ in saturated],
                    critical_intersections=[item for item, _ in critical],
                    transit_disruptions=facts.transit_disruptions,
                    saturation_threshold=self._threshold,
                    limit=limit,
                ),
                evidence_ids=evidence,
                state="SENT",
                simulation=True,
            )
            for service in recipients
        ]
        # tutti i bollettini del run in una transazione sola, con i loro passaggi e la voce del
        # registro: chi legge li vede tutti o nessuno
        created = self._repo.add_notifications(
            drafts,
            at=at,
            then=("DELIVERED",),
            decision=NewDecision(
                actor=ACTOR,
                decision=f"Bollettino viabilità consegnato a {len(drafts)} servizi (simulato)",
                rationale=f"{', '.join(d.recipient_label or d.recipient_id for d in drafts)}. "
                "Nessun invio verso l'esterno.",
                refs=tuple(evidence[:limit]),
            ),
        )
        return created

    def _layer(self, facts: RunFacts, name: str) -> FeatureCollection:
        layer = self._repo.get_layer(facts.run.id, facts.run.iteration, name)
        return layer or FeatureCollection(features=[])


def acknowledge(repo: Repository, notification_id: int) -> Notification:
    """«Conferma ricezione»: porta il bollettino a `ACKNOWLEDGED` e lo scrive nel registro
    (attore `user`). `NotificationNotFound` se non c'è; `NotificationStateConflict` se è già
    confermato o non è un bollettino (WhatsApp non ha un ciclo di vita)."""
    notification = repo.get_notification(notification_id)
    if notification is None:
        raise NotificationNotFound(notification_id)
    return repo.transition_notification(
        notification_id,
        "ACKNOWLEDGED",
        allowed_from=ACKNOWLEDGEABLE,
        decision=NewDecision(
            actor=ACK_ACTOR,
            decision="Ricezione del bollettino confermata",
            rationale=notification.recipient_label or notification.recipient_id,
        ),
    )
