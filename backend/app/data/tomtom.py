import asyncio
import logging
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from types import TracebackType
from typing import Literal, Self

import httpx2
from pydantic import Field

from app.geo import haversine_m
from app.models.api import LiveSegmentFlow
from app.models.base import FrozenModel
from app.models.geo import GeoPoint
from app.models.live_config import TomTomConfig
from app.models.live_segments import LiveSegment
from app.models.provenance import make_measured, measured_id

# Il trasporto HTTP che un test può sostituire: gli altri moduli lo importano da qui, non da httpx2.
Transport = httpx2.AsyncBaseTransport

TOMTOM_BASE_URL = "https://api.tomtom.com"
FLOW_PATH = "/traffic/services/4/flowSegmentData/absolute/10/json"
SOURCE = "tomtom.flow"
USER_AGENT = "NapoliUrbanOps/0.1"  # generico: nessun dato personale
MAX_ERROR_TEXT = 200  # lunghezza massima del motivo di TomTom riportato in un errore

# Perché non c'è un dato fresco: è il `degraded_reason` che F8 mette in /api/live/flow.
FailureCode = Literal[
    "tomtom_unreachable",  # rete, timeout, 5xx
    "tomtom_rate_limited",  # 429: quota esaurita
    "tomtom_key_rejected",  # 401, 403
    "tomtom_bad_request",  # altri 4xx (per esempio punto troppo lontano da una strada)
    "tomtom_bad_response",  # 200 ma forma o valori inattesi
]

_KEY_IN_TEXT = re.compile(r"(?i)\bkey=[^&\s\"']+")


def redact(text: str, key: str | None = None) -> str:
    """Il testo senza `key=...` e senza il valore della chiave, se noto."""
    cleaned = _KEY_IN_TEXT.sub("key=***", text)
    return cleaned.replace(key, "***") if key else cleaned


_KEY_NOT_REDACTED = re.compile(r"(?i)\bkey=(?!\*\*\*)")


def contains_key(text: str, key: str | None = None) -> bool:
    """Il testo lascia vedere la chiave (o un `key=` non oscurato)? È il controllo da fare su ciò
    che si sta per scrivere o stampare, dopo `redact`."""
    return bool(key and key in text) or _KEY_NOT_REDACTED.search(text) is not None


def error_message(status: int, payload: object, key: str | None = None) -> str:
    """`HTTP 400: motivo di TomTom` da uno stato e dal corpo JSON dell'errore (`detailedError` o
    `error`), oscurato e accorciato. La usano l'adattatore e la sonda: una copia sola."""
    reason = ""
    if isinstance(payload, dict):
        detailed = payload.get("detailedError")
        reason = str(
            (detailed.get("message") if isinstance(detailed, dict) else None)
            or payload.get("error")
            or ""
        )
    text = f"HTTP {status}" + (f": {reason}" if reason else "")
    return redact(text, key)[:MAX_ERROR_TEXT]


class _RedactKeys(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def _protect_loggers() -> None:
    """`httpx2` registra a INFO l'URL di ogni richiesta, chiave compresa: lo si tiene a WARNING e,
    se qualcuno lo alza, il filtro oscura comunque la chiave."""
    for name in ("httpx2", "httpcore"):
        log = logging.getLogger(name)
        log.setLevel(logging.WARNING)
        if not any(isinstance(f, _RedactKeys) for f in log.filters):
            log.addFilter(_RedactKeys())


_protect_loggers()
logger = logging.getLogger(__name__)


class TomTomError(Exception):
    """Un dato non ottenuto. Il messaggio non contiene mai la chiave né l'URL."""

    def __init__(self, code: FailureCode, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class FlowReading(FrozenModel):
    """Ciò che TomTom dice di un segmento (le sole parti che usiamo)."""

    current_speed_kmh: float = Field(ge=0)
    free_flow_speed_kmh: float = Field(gt=0)
    current_travel_time_s: float | None = Field(default=None, ge=0)
    free_flow_travel_time_s: float | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    road_closure: bool
    frc: str | None = None  # classe funzionale della strada (FRC0 = la più importante)
    coordinates: list[tuple[float, float]] = Field(min_length=2)  # (lat, lon) del segmento

    def length_m(self) -> float:
        return sum(
            float(haversine_m(a[0], a[1], b))
            for a, b in zip(self.coordinates, self.coordinates[1:], strict=False)
        )


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError("non è un numero")
    return float(value)


def parse_flow(body: object) -> FlowReading:
    """Il corpo di una risposta 200 di Flow Segment Data; `TomTomError` se la forma è un'altra."""
    data = body.get("flowSegmentData") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise TomTomError("tomtom_bad_response", "risposta senza flowSegmentData")
    try:
        points = [
            (_number(c["latitude"]), _number(c["longitude"]))
            for c in data["coordinates"]["coordinate"]
        ]
        if any(not (-90 <= lat <= 90 and -180 <= lon <= 180) for lat, lon in points):
            raise ValueError("coordinate fuori intervallo")
        optional = {
            "current_travel_time_s": data.get("currentTravelTime"),
            "free_flow_travel_time_s": data.get("freeFlowTravelTime"),
        }
        closure = data.get("roadClosure", False)
        if not isinstance(closure, bool):
            raise ValueError("roadClosure non è un booleano")
        return FlowReading(
            current_speed_kmh=_number(data["currentSpeed"]),
            free_flow_speed_kmh=_number(data["freeFlowSpeed"]),
            confidence=_number(data["confidence"]),
            road_closure=closure,
            frc=str(data["frc"]) if data.get("frc") is not None else None,
            coordinates=points,
            **{k: _number(v) if v is not None else None for k, v in optional.items()},
        )
    except (KeyError, TypeError, ValueError):
        # Pydantic.ValidationError è un ValueError. Niente `from`: nel messaggio non deve finire
        # nulla della risposta.
        raise TomTomError("tomtom_bad_response", "campi mancanti o non validi") from None


class TomTomClient:
    """Un client per l'intera vita dell'applicazione (`aclose()` allo spegnimento)."""

    def __init__(
        self,
        api_key: str,
        config: TomTomConfig,
        *,
        base_url: str = TOMTOM_BASE_URL,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("TOMTOM_API_KEY vuota")
        self._key = api_key
        self._config = config
        self._limit = asyncio.Semaphore(config.max_concurrency)
        self._http = httpx2.AsyncClient(
            base_url=base_url,
            timeout=config.timeout_s,
            transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=False,
        )

    def __repr__(self) -> str:
        url, timeout = str(self._http.base_url), self._config.timeout_s
        return f"TomTomClient(base_url={url!r}, timeout_s={timeout})"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def fetch(self, point: GeoPoint) -> FlowReading:
        """Il segmento che contiene `point`. Riprova dopo un errore di rete o un 5xx, mai dopo un
        4xx. `TomTomError` se alla fine non c'è un dato."""
        params = {"point": f"{point.lat},{point.lon}", "key": self._key}
        failure: TomTomError | None = None
        for _ in range(self._config.retries + 1):
            try:
                async with self._limit:
                    response = await self._http.get(FLOW_PATH, params=params)
            except httpx2.TransportError as error:  # timeout, connessione, TLS...
                failure = TomTomError("tomtom_unreachable", type(error).__name__)
                continue
            if response.status_code >= 500:
                failure = TomTomError(
                    "tomtom_unreachable",
                    f"HTTP {response.status_code}",
                    status=response.status_code,
                )
                continue
            return self._interpret(response)
        assert failure is not None
        logger.warning("TomTom non raggiungibile: %s", failure)
        raise failure

    def _interpret(self, response: httpx2.Response) -> FlowReading:
        status = response.status_code
        if status == 200:
            try:
                body = response.json()
            except ValueError:
                raise TomTomError(
                    "tomtom_bad_response", "risposta non JSON", status=status
                ) from None
            return parse_flow(body)
        if status == 429:
            raise TomTomError("tomtom_rate_limited", "HTTP 429: quota esaurita", status=status)
        if status in (401, 403):
            raise TomTomError(
                "tomtom_key_rejected", f"HTTP {status}: chiave rifiutata", status=status
            )
        if 400 <= status < 500:
            raise TomTomError("tomtom_bad_request", self._http_message(response), status=status)
        raise TomTomError("tomtom_bad_response", f"HTTP {status}", status=status)

    def _http_message(self, response: httpx2.Response) -> str:
        """`HTTP 400: motivo di TomTom`, oscurato e accorciato."""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return error_message(response.status_code, payload, self._key)

    async def fetch_many(
        self, points: Mapping[str, GeoPoint]
    ) -> dict[str, FlowReading | TomTomError]:
        """Tutti i punti, al massimo `max_concurrency` alla volta. Non solleva: ogni punto ha il suo
        dato o il suo errore, così chi chiama usa lo snapshot solo per i tratti che mancano."""

        async def one(point: GeoPoint) -> FlowReading | TomTomError:
            try:
                return await self.fetch(point)
            except TomTomError as error:
                return error

        results = await asyncio.gather(*(one(p) for p in points.values()))
        return dict(zip(points, results, strict=True))


def congestion_class(ratio: float, thresholds: Sequence[float]) -> int:
    """0–3: sotto quante soglie decrescenti (`flow.ratio_classes` di config/live.yaml) cade il
    rapporto velocità attuale ÷ flusso libero (0 = scorrevole, 3 = satura)."""
    return sum(1 for limit in thresholds if ratio < limit)


def to_segment_flow(
    segment: LiveSegment,
    reading: FlowReading,
    fetched_at: datetime,
    ratio_classes: Sequence[float],
) -> LiveSegmentFlow:
    """La lettura di un tratto come la espone l'API (06 7): tre `Measured` e la geometria."""
    extent = f"{reading.length_m():.0f} m"
    shared = [
        f"confidence TomTom: {reading.confidence:g}",
        f"velocità media del segmento TomTom (lungo {extent}), non del solo punto richiesto",
    ]
    if reading.road_closure:
        shared.append("TomTom segnala la strada chiusa (roadClosure)")
    if reading.frc:
        shared.append(f"classe stradale TomTom {reading.frc}")
    inputs = ["tomtom flowSegmentData v4", f"punto {segment.lat:.6f},{segment.lon:.6f}"]

    current = make_measured(
        id=measured_id("live", segment.id, "current_speed"),
        value=reading.current_speed_kmh, unit="km/h", kind="real", source=SOURCE,
        method="Flow Segment Data: velocità attuale", inputs=inputs, assumptions=shared,
        as_of=fetched_at,
    )  # fmt: skip
    free = make_measured(
        id=measured_id("live", segment.id, "free_flow_speed"),
        value=reading.free_flow_speed_kmh, unit="km/h", kind="real", source=SOURCE,
        method="Flow Segment Data: velocità a flusso libero", inputs=inputs, assumptions=shared,
        as_of=fetched_at,
    )  # fmt: skip
    ratio = make_measured(
        id=measured_id("live", segment.id, "ratio"),
        value=round(reading.current_speed_kmh / reading.free_flow_speed_kmh, 3),
        unit="rapporto", kind="estimate", source=SOURCE,
        method="velocità attuale ÷ velocità a flusso libero (derivato)",
        inputs=[current.id, free.id], assumptions=["rapporto 1 = traffico scorrevole"],
        as_of=fetched_at,
    )  # fmt: skip
    return LiveSegmentFlow(
        id=segment.id,
        label=segment.label or segment.id,
        geometry={
            "type": "LineString",
            "coordinates": [[lon, lat] for lat, lon in reading.coordinates],
        },
        current_speed=current,
        free_flow_speed=free,
        ratio=ratio,
        congestion_class=congestion_class(float(ratio.value), ratio_classes),
        fetched_at=fetched_at,
    )
