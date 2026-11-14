from collections.abc import Sequence
from typing import Literal

from pydantic import Field, model_validator

from app.models.base import FrozenModel, Slug
from app.models.geo import GeoPoint

ZoneType = Literal["road_gate", "metro_gate", "arrival_hub", "near", "far"]

# Pesi delle zone e ripartizioni devono sommare a 100 entro questa tolleranza (01 2: "100 ± 0,5").
SUM_TOLERANCE_PCT = 0.5


def check_sum_to_100(values: Sequence[float], what: str) -> None:
    total = sum(values)
    if abs(total - 100) > SUM_TOLERANCE_PCT:
        raise ValueError(f"{what} deve sommare a 100 (± {SUM_TOLERANCE_PCT}), somma {total:g}")


class ModalSplit(FrozenModel):
    """Ripartizione modale di una zona, in percentuale. Il modo «mare» non esiste."""

    car_pct: float = Field(ge=0, le=100)
    transit_pct: float = Field(ge=0, le=100)
    walk_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _sums_to_100(self) -> "ModalSplit":
        check_sum_to_100([self.car_pct, self.transit_pct, self.walk_pct], "La ripartizione modale")
        return self


class Zone(FrozenModel):
    id: Slug
    name: str = Field(min_length=1)
    type: ZoneType
    weight_pct: float = Field(ge=0, le=100)  # quota della domanda totale di persone
    centroid: GeoPoint


def check_zone_set(zones: Sequence[Zone]) -> None:
    """Vincoli su un insieme di zone: id univoci e pesi che sommano a 100."""
    ids = [zone.id for zone in zones]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"id di zona duplicati: {', '.join(duplicates)}")
    check_sum_to_100([zone.weight_pct for zone in zones], "I pesi delle zone")
