import asyncio
import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from app.clock import ROME
from app.data.paths import DataPaths
from app.data.tomtom import FlowReading, TomTomClient, Transport, to_segment_flow
from app.models.api import LiveFlowResponse, LiveSegmentFlow
from app.models.geo import GeoPoint
from app.models.live_config import LiveConfig
from app.models.live_segments import LiveSegment, LiveSegmentsConfig
from app.models.provenance import Measured, make_measured, measured_id
from app.settings import Settings

logger = logging.getLogger(__name__)

# `degraded_reason` che non vengono da TomTom (quelli di TomTom sono `tomtom.FailureCode`).
KEY_MISSING = "tomtom_key_missing"
LIVE_VIEW_REQUIRED = "live_view_required"
NO_DATA = "no_data"
DAILY_LIMIT = "tomtom_daily_limit"
SUMMARY_SOURCE = "live.summary v1"


class LiveFlowService:
    def __init__(
        self,
        segments: Sequence[LiveSegment],
        client: TomTomClient | None,
        *,
        ttl_s: float,
        clock: Callable[[], float],
        ratio_classes: Sequence[float],
        daily_limit: int,
        snapshot_path: Path | None = None,
    ) -> None:
        self._segments = tuple(segments)
        self._client = client
        self._ttl_s = ttl_s
        self._clock = clock
        self._ratio_classes = tuple(ratio_classes)
        self._daily_limit = daily_limit
        self._day: date | None = None  # il giorno (di Roma) a cui si riferisce `_used`
        self._used = 0  # tratti chiesti a TomTom oggi
        self._snapshot_path = snapshot_path
        self._last: dict[str, LiveSegmentFlow] = {}  # l'ultimo dato valido, per id di tratto
        # quando (secondo l'orologio) è stato preso: non si ricava da `fetched_at`, arrotondato al
        # microsecondo, perché il confronto con `ttl_s` sia esatto
        self._taken: dict[str, float] = {}
        self._lock = asyncio.Lock()  # un solo aggiornamento alla volta: chi aspetta trova il dato
        if snapshot_path is not None:
            self._last = self._read_snapshot(snapshot_path)
            self._taken = {i: flow.fetched_at.timestamp() for i, flow in self._last.items()}

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    # --- l'endpoint -----------------------------------------------------------------------------

    async def flow(self, *, live_view: bool) -> LiveFlowResponse:
        """I tratti, aggiornandoli da TomTom solo se `live_view` e se qualcuno è scaduto."""
        reason: str | None = None
        fetched = 0
        if self._stale(self._clock()):
            if live_view:
                async with self._lock:
                    now = self._clock()
                    stale = self._stale(now)  # chi ci ha preceduto può aver già aggiornato
                    if stale:
                        fetched, reason = await self._refresh(stale, now)
            else:
                reason = LIVE_VIEW_REQUIRED
        return self._response(fetched, reason)

    # --- dettagli -------------------------------------------------------------------------------

    def _fresh(self, segment_id: str, now: float) -> bool:
        taken = self._taken.get(segment_id)
        return taken is not None and now - taken < self._ttl_s

    def _stale(self, now: float) -> list[LiveSegment]:
        return [s for s in self._segments if not self._fresh(s.id, now)]

    async def _refresh(self, stale: Sequence[LiveSegment], now: float) -> tuple[int, str | None]:
        """Chiede a TomTom i tratti scaduti: quanti sono arrivati e, se qualcuno no, perché."""
        if self._client is None:
            return 0, KEY_MISSING
        at = datetime.fromtimestamp(now, ROME)
        if at.date() != self._day:  # un giorno nuovo: il contatore riparte
            self._day, self._used = at.date(), 0
        batch = list(stale)[: max(0, self._daily_limit - self._used)]
        skipped = len(stale) - len(batch)
        if not batch:
            logger.warning("LIVE: soglia giornaliera TomTom raggiunta (%d)", self._daily_limit)
            return 0, DAILY_LIMIT
        self._used += len(batch)
        points = {s.id: GeoPoint(lat=s.lat, lon=s.lon) for s in batch}
        results = await self._client.fetch_many(points)
        by_id = {s.id: s for s in batch}
        fetched = 0
        reason: str | None = None
        for segment_id, result in results.items():
            if isinstance(result, FlowReading):
                self._taken[segment_id] = now
                self._last[segment_id] = to_segment_flow(
                    by_id[segment_id], result, at, self._ratio_classes
                )
                fetched += 1
            else:
                reason = reason or result.code
        if fetched:
            self._write_snapshot()
        reason = reason or (DAILY_LIMIT if skipped else None)
        if reason:
            logger.warning(
                "LIVE: %d tratti su %d non aggiornati (%s)",
                len(stale) - fetched,
                len(stale),
                reason,
            )
        return fetched, reason

    # --- lo snapshot su disco -------------------------------------------------------------------

    @staticmethod
    def _read_snapshot(path: Path) -> dict[str, LiveSegmentFlow]:
        """L'ultimo dato per tratto dal file; vuoto se non c'è o non si legge."""
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            flows = [LiveSegmentFlow.model_validate(item) for item in document["segments"]]
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("LIVE: lo snapshot %s non si legge, lo si ignora", path.name)
            return {}
        return {flow.id: flow for flow in flows}

    def _write_snapshot(self) -> None:
        """Riscrive il file in modo atomico; un errore di disco non ferma LIVE."""
        path = self._snapshot_path
        if path is None:
            return
        document = {
            "segments": [
                self._last[s.id].model_dump(mode="json")
                for s in self._segments
                if s.id in self._last
            ]
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(
                dir=path.parent, prefix=".snapshot-", suffix=".tmp"
            )
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as out:
                    json.dump(document, out, ensure_ascii=False, indent=1)
                Path(temporary).replace(path)
            except BaseException:
                with contextlib.suppress(OSError):
                    Path(temporary).unlink()
                raise
        except OSError:
            logger.warning("LIVE: lo snapshot non si scrive su disco (%s)", path.name)

    def _response(self, fetched: int, reason: str | None) -> LiveFlowResponse:
        now = self._clock()
        segments = [self._last[s.id] for s in self._segments if s.id in self._last]
        if not segments:
            return LiveFlowResponse(
                segments=[], mode="unavailable", degraded_reason=reason or NO_DATA
            )
        summary = summarize(segments, total=len(self._segments))
        if all(self._fresh(s.id, now) for s in self._segments):
            return LiveFlowResponse(
                segments=segments, mode="fresh" if fetched else "cached", summary=summary
            )
        return LiveFlowResponse(
            segments=segments,
            mode="snapshot",
            degraded_reason=reason or NO_DATA,
            summary=summary,
        )


def summarize(segments: Sequence[LiveSegmentFlow], *, total: int) -> list[Measured]:
    """I numeri della fascia LIVE, dai tratti che hanno un dato (`total` sono quelli di config).

    Nessun dato in più di quelli di TomTom: una media semplice, due conteggi e il tratto più lento.
    Ognuno dice da quali misure viene (`inputs`) e porta l'ora del dato più recente che usa (lo
    snapshot è più vecchio: lo dice quell'ora). Media e conteggi sono STIME (derivati); il tratto
    più lento è la sua velocità REALE. Senza tratti, nessun numero.
    """
    if not segments:
        return []
    as_of = max(s.fetched_at for s in segments)
    speeds = [float(s.current_speed.value) for s in segments]
    ratios = [float(s.ratio.value) for s in segments]
    slowest = min(segments, key=lambda s: (float(s.current_speed.value), s.id))
    of_total = f"{len(segments)} tratti su {total}"
    note = "media semplice: non pesa la lunghezza dei tratti né il traffico che portano"

    def derived(
        part: str, value: float, unit: str, method: str, inputs: list[str], *, mean: bool = False
    ) -> Measured:
        return make_measured(
            id=measured_id("live", "summary", part),
            value=value,
            unit=unit,
            kind="estimate",
            source=SUMMARY_SOURCE,
            method=method,
            inputs=inputs,
            assumptions=[of_total, note] if mean else [of_total],
            as_of=as_of,
        )

    slowed = [s for s in segments if s.congestion_class >= 1]
    return [
        derived(
            "mean_speed",
            round(sum(speeds) / len(speeds), 1),
            "km/h",
            "media della velocità attuale dei tratti",
            [s.current_speed.id for s in segments],
            mean=True,
        ),
        derived(
            "mean_ratio",
            round(sum(ratios) / len(ratios), 3),
            "rapporto",
            "media del rapporto velocità attuale ÷ flusso libero dei tratti",
            [s.ratio.id for s in segments],
            mean=True,
        ),
        derived(
            "slowed_count",
            len(slowed),
            "n",
            "tratti sotto la prima soglia del rapporto (classi di config/live.yaml)",
            [s.ratio.id for s in segments],
        ),
        make_measured(
            id=measured_id("live", "summary", "slowest_speed"),
            value=float(slowest.current_speed.value),
            unit="km/h",
            kind="real",
            source=slowest.current_speed.source,
            method=f"velocità attuale del tratto più lento: {slowest.label}",
            inputs=[slowest.current_speed.id],
            assumptions=[of_total, *slowest.current_speed.assumptions],
            as_of=slowest.fetched_at,
        ),
        derived(
            "covered_count",
            len(segments),
            "n",
            "tratti che hanno un dato",
            [s.current_speed.id for s in segments],
        ),
    ]


def build_live_flow(
    settings: Settings,
    clock: Callable[[], float],
    *,
    config: LiveConfig | None = None,
    segments: Sequence[LiveSegment] | None = None,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> LiveFlowService:
    """Il servizio con i tratti di `config/live_segments.yaml`. La chiave si legge qui,
    dall'ambiente (come per Gemini: le `Settings` non la conservano) e finisce solo
    nell'adattatore; senza chiave il client non esiste e LIVE mostra lo snapshot. I test
    passano un `transport` finto."""
    config = config or LiveConfig.from_yaml()
    chosen = segments if segments is not None else LiveSegmentsConfig.from_yaml().segments
    key = (os.environ if environ is None else environ).get("TOMTOM_API_KEY", "").strip()
    client = (
        TomTomClient(key, config.tomtom, transport=transport)
        if settings.tomtom_key_present and key
        else None
    )
    return LiveFlowService(
        chosen,
        client,
        ttl_s=config.flow.cache_ttl_s,
        clock=clock,
        ratio_classes=config.flow.ratio_classes,
        daily_limit=settings.tomtom_daily_limit,
        snapshot_path=DataPaths(settings.data_dir).live_snapshot
        if settings.live_snapshot_persist
        else None,
    )
