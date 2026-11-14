from pathlib import Path
from typing import ClassVar, Literal, get_args

from pydantic import Field, field_validator, model_validator

from app.models.base import ClockTime, FrozenModel, Slug
from app.models.demand import ModalSplit, Zone, ZoneType, check_sum_to_100, check_zone_set
from app.models.geo import GeoPoint
from app.models.yamlconfig import CONFIG_DIR, YamlConfig

DEFAULT_ENGINE_CONFIG_PATH = CONFIG_DIR / "engine.yaml"

# --------------------------------------------------------------------------------------
# Strada (02 1)
# --------------------------------------------------------------------------------------


class AssignmentConfig(FrozenModel):
    steps: int = Field(ge=1)  # passi dell'assegnazione incrementale
    step_share: float = Field(gt=0, le=1)  # quota della matrice auto assegnata a ogni passo

    @model_validator(mode="after")
    def _covers_whole_matrix(self) -> "AssignmentConfig":
        if abs(self.steps * self.step_share - 1) > 1e-9:
            raise ValueError(
                "steps × step_share deve fare 1: i passi devono coprire tutta la matrice"
            )
        return self


class BprConfig(FrozenModel):
    alpha: float = Field(gt=0)
    beta: float = Field(gt=0)


class RoadDefault(FrozenModel):
    """Valori di riserva per una classe di strada OSM (usati solo se OSM non dà lanes/maxspeed)."""

    lanes: int = Field(ge=1)
    speed_kmh: float = Field(gt=0)
    capacity_per_lane: float = Field(gt=0)  # veic/h per corsia; si usa SEMPRE (anche con lanes OSM)


CapacityScope = Literal["incoming_edges", "incoming_edges_favored_direction"]


class CapacityEffect(FrozenModel):
    capacity_factor: float = Field(ge=0)
    scope: CapacityScope | None = None


class PerceivedTimeEffect(FrozenModel):
    perceived_time_factor: float = Field(gt=0)
    scope: Literal["saturated_path_edges"]


class MeasureEffects(FrozenModel):
    """Effetti delle misure stradali sul motore (D19): un campo per tipo, comportamenti diversi."""

    traffic_post: CapacityEffect
    signal_plan_change: CapacityEffect
    detour_signage: PerceivedTimeEffect
    close_road: CapacityEffect

    @field_validator("close_road")
    @classmethod
    def _closure_is_zero(cls, value: CapacityEffect) -> CapacityEffect:
        if value.capacity_factor != 0:
            raise ValueError(
                "close_road deve avere capacity_factor 0: altrimenti non è una chiusura"
            )
        return value


class MetricsConfig(FrozenModel):
    vc_critical_threshold: float = Field(gt=0)
    vc_classes: tuple[float, float, float]  # 3 soglie = 4 classi di colore sulla mappa
    critical_intersections_top_n: int = Field(ge=1)

    @field_validator("vc_classes")
    @classmethod
    def _increasing(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if value[0] <= 0 or not value[0] < value[1] < value[2]:
            raise ValueError("vc_classes deve essere crescente e positivo, es. [0.6, 0.9, 1.1]")
        return value


# --------------------------------------------------------------------------------------
# Domanda (01 2.1)
# --------------------------------------------------------------------------------------


class CarDestination(FrozenModel):
    point: GeoPoint
    share_pct: float = Field(gt=0, le=100)


class ODEndpoint(FrozenModel):
    """Estremo di una coppia O/D: una zona (si usa il suo centroide) oppure un punto."""

    zone: str | None = None
    point: GeoPoint | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ODEndpoint":
        if (self.zone is None) == (self.point is None):
            raise ValueError(
                "un estremo O/D deve avere o `zone` o `point`, non entrambi né nessuno"
            )
        return self


class ODPair(FrozenModel):
    id: Slug  # compare negli id delle metriche: od_time.<id>
    label: str = Field(min_length=1)
    origin: ODEndpoint
    destination: ODEndpoint


class DemandConfig(FrozenModel):
    zones: list[Zone] = Field(min_length=1)
    modal_split_by_type: dict[ZoneType, ModalSplit]
    car_destinations: list[CarDestination] = Field(min_length=1)
    od_pairs: list[ODPair] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "DemandConfig":
        check_zone_set(self.zones)
        missing = set(get_args(ZoneType)) - set(self.modal_split_by_type)
        if missing:
            raise ValueError(f"manca la ripartizione modale per i tipi di zona: {sorted(missing)}")
        check_sum_to_100(
            [d.share_pct for d in self.car_destinations], "Le quote delle destinazioni auto"
        )
        ids = [pair.id for pair in self.od_pairs]
        if len(set(ids)) != len(ids):
            raise ValueError("id delle coppie O/D duplicati")
        zone_ids = {zone.id for zone in self.zones}
        for pair in self.od_pairs:
            for endpoint in (pair.origin, pair.destination):
                if endpoint.zone is not None and endpoint.zone not in zone_ids:
                    raise ValueError(
                        f"coppia O/D '{pair.id}': la zona '{endpoint.zone}' non esiste"
                    )
        return self


# --------------------------------------------------------------------------------------
# Trasporto pubblico (03 1)
# --------------------------------------------------------------------------------------

VehicleKind = Literal["bus", "metro_line_1", "metro_line_6", "funicular"]


class RouteIds(FrozenModel):
    route_ids: list[str] = Field(min_length=1)

    @field_validator("route_ids")
    @classmethod
    def _non_empty_strings(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value) or len(set(value)) != len(value):
            raise ValueError("route_ids: stringhe non vuote e senza duplicati")
        return value


class RouteClassification(FrozenModel):
    """Come riconoscere le linee nel feed GTFS (riempito al cancello F0, report dati)."""

    metro_line_1: RouteIds
    metro_line_6: RouteIds
    funicular: RouteIds

    @model_validator(mode="after")
    def _disjoint(self) -> "RouteClassification":
        seen: dict[str, str] = {}
        for group, ids in self.model_dump().items():
            for route_id in ids["route_ids"]:
                if route_id in seen:
                    raise ValueError(
                        f"route_id '{route_id}' in due gruppi: {seen[route_id]} e {group}"
                    )
                seen[route_id] = group
        return self


# Le classi con un percorso a tratte (metro e funicolari): `bus` non ha itinerari, è la riserva.
RailKind = Literal["metro_line_1", "metro_line_6", "funicular"]


class ItineraryLeg(FrozenModel):
    """Una tratta di un itinerario: si sale in `from_stop_name` e si scende in `to_stop_name`, sulle
    linee della classe `route_class`. I nomi sono quelli del feed (corrispondenza come
    `resolve_stop`) e si risolvono tra le sole fermate servite da quella classe."""

    route_class: RailKind
    from_stop_name: str = Field(min_length=1)
    to_stop_name: str = Field(min_length=1)

    @model_validator(mode="after")
    def _distinct(self) -> "ItineraryLeg":
        if _same_name(self.from_stop_name, self.to_stop_name):
            raise ValueError(
                f"la tratta sale e scende alla stessa fermata («{self.from_stop_name}»)"
            )
        return self


def _same_name(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


class Itinerary(FrozenModel):
    """Come una zona raggiunge l'area evento nell'arrivo (nel deflusso è percorso al contrario).

    `legs` può essere vuoto (solo a piedi). `egress_walk`: dopo l'ultima tratta si va a piedi fino
    all'area evento (le persone contano tra i pedoni); se falso si scende alla fermata dell'area.
    Due tratte consecutive si incontrano nella stazione con lo stesso nome: l'interscambio è
    dichiarato (le due fermate possono avere `stop_id` diversi).
    """

    legs: list[ItineraryLeg]
    egress_walk: bool

    @model_validator(mode="after")
    def _consistent(self) -> "Itinerary":
        if not self.legs and not self.egress_walk:
            raise ValueError("un itinerario senza tratte deve essere a piedi (egress_walk: true)")
        for before, after in zip(self.legs, self.legs[1:], strict=False):
            if not _same_name(before.to_stop_name, after.from_stop_name):
                raise ValueError(
                    f"l'interscambio non è dichiarato: si scende a «{before.to_stop_name}» e si "
                    f"risale a «{after.from_stop_name}» (devono avere lo stesso nome)"
                )
        return self


class TransitConfig(FrozenModel):
    stop_radius_m: float = Field(gt=0)  # fermate "vicine all'area evento"
    redistribution_radius_m: float = Field(gt=0)  # per stazione indisponibile
    walk_detour_factor: float = Field(ge=1)  # distanza a piedi = linea d'aria × fattore
    vehicle_capacity: dict[VehicleKind, int]  # passeggeri per veicolo/convoglio
    vehicle_capacity_sources: dict[VehicleKind, str]  # fonte di ogni capacità (kind=estimate)
    route_classification: RouteClassification
    extend_hours_default_end: ClockTime  # fine per extend_hours se non specificata
    add_runs_default: int = Field(ge=1)  # corse aggiuntive per richiesta add_runs
    # Per ogni zona di `demand.zones`, gli itinerari in ordine di preferenza (03 2); lista vuota =
    # nessun itinerario TPL: la domanda va sul bus. Se nessuno è disponibile, va sul bus lo stesso.
    itineraries: dict[Slug, list[Itinerary]]

    @model_validator(mode="after")
    def _capacities(self) -> "TransitConfig":
        kinds = set(get_args(VehicleKind))
        for name in ("vehicle_capacity", "vehicle_capacity_sources"):
            present = set(getattr(self, name))
            if present != kinds:
                raise ValueError(
                    f"{name}: attese le chiavi {sorted(kinds)}, trovate {sorted(present)}"
                )
        if any(capacity <= 0 for capacity in self.vehicle_capacity.values()):
            raise ValueError("vehicle_capacity: le capacità devono essere positive")
        if any(not source.strip() for source in self.vehicle_capacity_sources.values()):
            raise ValueError("vehicle_capacity_sources: ogni capacità ha una fonte")
        return self


# --------------------------------------------------------------------------------------
# Radice
# --------------------------------------------------------------------------------------


class EngineConfig(YamlConfig):
    DEFAULT_PATH: ClassVar[Path] = DEFAULT_ENGINE_CONFIG_PATH

    version: Literal[1]
    seed: int = Field(ge=0)  # registrato nei run anche se il motore è deterministico
    time_slice_minutes: int = Field(ge=1)
    assignment: AssignmentConfig
    bpr: BprConfig
    car_occupancy_default: float = Field(gt=0)  # persone per auto
    node_snap_max_distance_m: float = Field(gt=0)  # distanza massima punto → nodo stradale (01 6)
    road_defaults: dict[str, RoadDefault]
    measure_effects: MeasureEffects
    metrics: MetricsConfig
    demand: DemandConfig
    transit: TransitConfig

    @model_validator(mode="after")
    def _itineraries_cover_the_zones(self) -> "EngineConfig":
        zone_ids = {zone.id for zone in self.demand.zones}
        listed = set(self.transit.itineraries)
        if listed != zone_ids:
            problems = []
            if zone_ids - listed:
                problems.append(f"mancano le zone {sorted(zone_ids - listed)}")
            if listed - zone_ids:
                problems.append(f"zone che non esistono {sorted(listed - zone_ids)}")
            raise ValueError(
                "transit.itineraries: " + "; ".join(problems) + " (una voce per ogni zona di "
                "demand.zones; lista vuota = solo bus)"
            )
        return self

    @field_validator("road_defaults")
    @classmethod
    def _has_default(cls, value: dict[str, RoadDefault]) -> dict[str, RoadDefault]:
        if "default" not in value:
            raise ValueError("road_defaults deve avere la chiave 'default' (classe non prevista)")
        return value
