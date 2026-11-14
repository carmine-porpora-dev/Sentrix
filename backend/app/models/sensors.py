from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.models.base import FrozenModel, Slug
from app.models.config import RailKind
from app.models.geo import GeoPoint
from app.models.yamlconfig import CONFIG_DIR, YamlConfig

SensorType = Literal["gps_probe", "turnstile", "people_counter", "ramp_counter"]

# Testo che si legge a schermo: mai vuoto (un popup senza «cosa misurerà» non dice nulla).
SensorText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PlannedSensor(FrozenModel):
    """Un sensore (o una famiglia di sensori) che il prodotto avrà, non ancora attivo.

    Dove sta dipende dal tipo, e le regole sono del dominio (non c'è una posizione da inventare):
    - `people_counter` e `ramp_counter`: un punto (`location`), preso dal feed GTFS o dalle rampe
      del grafo OSM (la fonte è nel commento di ogni voce di `config/sensors.yaml`);
    - `turnstile`: nessuna posizione. Sta nelle stazioni delle linee di `GET /api/transit/lines`, e
      `route_class` dice quali (metro di Linea 1, di Linea 6, funicolari): la posizione di una
      stazione vive in un posto solo, il feed;
    - `gps_probe`: nessuna posizione (bus e flotte comunali coprono tutta la rete).
    """

    id: Slug
    type: SensorType
    name: SensorText
    status: Literal["planned"]
    location: GeoPoint | None = None
    # per `turnstile`: la classe delle linee in cui stanno i tornelli (le classi di `engine.yaml`)
    route_class: RailKind | None = None
    measures: SensorText  # che cosa misurerà
    replaces: SensorText  # quale stima del modello sostituirà (spech.md 11.2)

    @model_validator(mode="after")
    def _where_it_is(self) -> Self:
        if self.type in ("people_counter", "ramp_counter"):
            if self.location is None:
                raise ValueError(f"{self.type}: la posizione (location) è obbligatoria")
        elif self.location is not None:
            raise ValueError(f"{self.type}: non ha una posizione propria (location va tolta)")
        if self.type == "turnstile":
            if self.route_class is None:
                raise ValueError("turnstile: serve route_class (le linee in cui stanno i tornelli)")
        elif self.route_class is not None:
            raise ValueError(f"{self.type}: route_class vale solo per i tornelli")
        return self


class SensorsConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "sensors.yaml"

    sensors: list[PlannedSensor] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [s.id for s in self.sensors]
        if len(set(ids)) != len(ids):
            raise ValueError("id di sensore duplicati")
        classes = [s.route_class for s in self.sensors if s.type == "turnstile"]
        if len(set(classes)) != len(classes):
            raise ValueError("più di una voce di tornelli per la stessa classe di linea")
        return self
