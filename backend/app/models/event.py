import datetime as dt
import re
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from app.models.base import (
    EDGE_KEY_PATTERN,
    ClockTime,
    FrozenModel,
    RomeDatetime,
    Slug,
    Window,
)
from app.models.config import CarDestination
from app.models.demand import ModalSplit, Zone, ZoneType, check_sum_to_100, check_zone_set
from app.models.geo import GeoPoint

_EDGE_KEY = re.compile(EDGE_KEY_PATTERN)


class TimeWindow(FrozenModel):
    start: ClockTime
    end: ClockTime
    peak: ClockTime  # in [start, end)

    @field_validator("end")
    @classmethod
    def _after_start(cls, end: dt.time, info: ValidationInfo) -> dt.time:
        start = info.data.get("start")
        if start is not None and end <= start:
            raise ValueError("la fine deve essere dopo l'inizio")
        return end

    @field_validator("peak")
    @classmethod
    def _peak_inside(cls, peak: dt.time, info: ValidationInfo) -> dt.time:
        start, end = info.data.get("start"), info.data.get("end")
        if start is not None and end is not None and not start <= peak < end:
            raise ValueError("il picco deve cadere tra l'inizio (incluso) e la fine (esclusa)")
        return peak


class AttendanceLevels(FrozenModel):
    """Persone nella giornata/finestra, in tre livelli di scenario."""

    low: int = Field(ge=0)
    mid: int = Field(ge=0)
    high: int = Field(ge=0)
    source_ref: str | None = None  # fonte o "ipotesi di scenario"

    @field_validator("mid")
    @classmethod
    def _mid_not_below_low(cls, mid: int, info: ValidationInfo) -> int:
        if "low" in info.data and mid < info.data["low"]:
            raise ValueError("il livello medio non può essere inferiore al basso")
        return mid

    @field_validator("high")
    @classmethod
    def _high_not_below_mid(cls, high: int, info: ValidationInfo) -> int:
        if "mid" in info.data and high < info.data["mid"]:
            raise ValueError("il livello alto non può essere inferiore al medio")
        return high


class Closure(FrozenModel):
    label: str = Field(min_length=1)  # "Via Francesco Caracciolo (viale Dohrn – piazza Vittoria)"
    street_names: list[str] = Field(default_factory=list)  # nomi OSM per la risoluzione
    # Vincolo spaziale opzionale (ovest, sud, est, nord).
    bbox: tuple[float, float, float, float] | None = None
    edge_keys: list[str] = Field(
        default_factory=list
    )  # "u-v-k" risolti (F1); vuoto = li risolve il resolver
    mode: Literal["closed", "capacity_reduction"] = "closed"
    capacity_factor: float = 0.0  # quota di capacità che resta; usata se capacity_reduction
    source_ref: str | None = None  # es. "Ord. dirigenziale Comune di Napoli n. 1496"

    @field_validator("street_names")
    @classmethod
    def _names_not_blank(cls, value: list[str]) -> list[str]:
        if any(not name.strip() for name in value):
            raise ValueError("i nomi di strada non possono essere vuoti")
        return value

    @field_validator("bbox")
    @classmethod
    def _bbox_valid(
        cls, value: tuple[float, float, float, float] | None
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return value
        west, south, east, north = value
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(
                "bbox deve essere (ovest, sud, est, nord) con ovest < est e sud < nord"
            )
        return value

    @field_validator("edge_keys")
    @classmethod
    def _edge_keys_valid(cls, value: list[str]) -> list[str]:
        bad = [key for key in value if not _EDGE_KEY.fullmatch(key)]
        if bad:
            raise ValueError(f"chiavi arco non valide (attese 'u-v-k'): {bad}")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "Closure":
        if not self.street_names and not self.edge_keys:
            raise ValueError("serve almeno un nome di strada o una chiave arco")
        if self.mode == "closed" and self.capacity_factor != 0:
            raise ValueError("con mode 'closed' il capacity_factor deve essere 0")
        if self.mode == "capacity_reduction" and not 0 < self.capacity_factor < 1:
            raise ValueError(
                "con 'capacity_reduction' il capacity_factor deve essere tra 0 e 1 (esclusi)"
            )
        return self


class TransitDisruption(FrozenModel):
    label: str = Field(min_length=1)  # "Stazione Arco Mirelli chiusa"
    stop_name: str = Field(min_length=1)  # per la risoluzione GTFS
    stop_ids: list[str] = Field(default_factory=list)  # risolti in F1/F3
    window: Literal["arrival", "departure", "both"]
    source_ref: str | None = None


class BackgroundLoad(FrozenModel):
    """Quota della capacità occupata dal traffico di fondo nella fascia di picco (02 4)."""

    arrival_peak_share: float = Field(ge=0, le=1)
    departure_peak_share: float = Field(ge=0, le=1)

    def peak_share(self, window: Window) -> float:
        """La quota della finestra `window`."""
        return self.arrival_peak_share if window == "arrival" else self.departure_peak_share


class DepartmentResources(FrozenModel):
    """Risorse dei dipartimenti virtuali per una finestra (D19: dati dell'Evento)."""

    window: Window
    municipal_police_patrols_total: int = Field(ge=0)
    municipal_police_patrols_committed: int = Field(ge=0)
    traffic_control_signal_changes_max: int = Field(ge=0)
    transport_control_reserve_buses: int = Field(ge=0)
    transport_control_hour_extensions: int = Field(ge=0)

    @field_validator("municipal_police_patrols_committed")
    @classmethod
    def _committed_within_total(cls, committed: int, info: ValidationInfo) -> int:
        total = info.data.get("municipal_police_patrols_total")
        if total is not None and committed > total:
            raise ValueError("le pattuglie impegnate non possono superare quelle totali")
        return committed


class RealMeasure(FrozenModel):
    """Misura adottata davvero dalla città (confronto, opzionale)."""

    label: str = Field(min_length=1)
    measure_type: str = Field(min_length=1)
    target: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)


class EventInput(FrozenModel):
    """Il contenuto di un Evento che l'utente scrive (corpo di POST e PUT, 06 3): tutto tranne i
    campi che decide il server (`revision`, `created_at`, `updated_at`), che aggiunge `Event`."""

    id: Slug
    name: str = Field(min_length=1)
    date: dt.date
    description: str | None = None
    area_center: GeoPoint  # centro dell'area evento
    area_radius_m: int = Field(default=400, ge=1)
    arrival: TimeWindow
    departure: TimeWindow
    attendance: AttendanceLevels
    closures: list[Closure] = Field(default_factory=list)
    transit_disruptions: list[TransitDisruption] = Field(default_factory=list)
    background: BackgroundLoad
    resources: list[DepartmentResources] = Field(min_length=1)  # una per finestra
    # None = default globali di engine.yaml. Qui `CarDestination` (punto + quota), lo stesso modello
    # della configurazione, al posto della tupla (GeoPoint, float) di 01 2: stessa informazione,
    # leggibile in JSON/YAML e dal form dell'Event Manager.
    car_destinations: list[CarDestination] | None = None
    zones_override: list[Zone] | None = None
    modal_split_override: dict[ZoneType, ModalSplit] | None = None  # per TIPO di zona
    car_occupancy: float | None = Field(default=None, gt=0)  # None = default di engine.yaml (2,2)
    real_measures: list[RealMeasure] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)  # elenco fonti dell'evento

    def time_window(self, window: Window) -> TimeWindow:
        """La finestra di arrivo o di deflusso."""
        return self.arrival if window == "arrival" else self.departure

    def window_span(self, window: Window) -> str:
        """«HH:MM–HH:MM» della finestra: l'unico modo in cui entra nei testi."""
        chosen = self.time_window(window)
        return f"{chosen.start:%H:%M}–{chosen.end:%H:%M}"

    @field_validator("resources")
    @classmethod
    def _one_per_window(cls, value: list[DepartmentResources]) -> list[DepartmentResources]:
        windows = [item.window for item in value]
        if len(set(windows)) != len(windows):
            raise ValueError("una sola voce di risorse per finestra (arrival, departure)")
        return value

    @field_validator("car_destinations")
    @classmethod
    def _destinations_sum(cls, value: list[CarDestination] | None) -> list[CarDestination] | None:
        if value is not None:
            if not value:
                raise ValueError(
                    "se presente, almeno una destinazione (altrimenti usa i default: null)"
                )
            check_sum_to_100([item.share_pct for item in value], "Le quote delle destinazioni auto")
        return value

    @field_validator("zones_override")
    @classmethod
    def _zones_valid(cls, value: list[Zone] | None) -> list[Zone] | None:
        if value is not None:
            check_zone_set(value)
        return value


class Event(EventInput):
    """L'entità completa, come si archivia e si restituisce: il contenuto più i campi del server."""

    revision: int = Field(default=1, ge=1)
    created_at: RomeDatetime
    updated_at: RomeDatetime

    @field_validator("updated_at")
    @classmethod
    def _updated_after_created(cls, updated: dt.datetime, info: ValidationInfo) -> dt.datetime:
        created = info.data.get("created_at")
        if created is not None and updated < created:
            raise ValueError("updated_at non può precedere created_at")
        return updated


class EventSummary(FrozenModel):
    """Una riga dell'elenco eventi (GET /api/events, 06 3): `is_seed` è un attributo di
    archiviazione (un preset modificato resta preset), non un campo dell'Evento."""

    id: Slug
    name: str
    date: dt.date
    is_seed: bool
    revision: int
    updated_at: RomeDatetime
