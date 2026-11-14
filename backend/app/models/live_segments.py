from typing import ClassVar

from pydantic import Field, model_validator

from app.models.base import Slug
from app.models.geo import GeoPoint
from app.models.yamlconfig import CONFIG_DIR, YamlConfig


class LiveSegment(GeoPoint):
    """`{id, label, lat, lon}`: un GeoPoint con un id, e con l'etichetta obbligatoria."""

    id: Slug

    @model_validator(mode="after")
    def _has_label(self) -> "LiveSegment":
        if not (self.label and self.label.strip()):
            raise ValueError("label obbligatoria")
        return self


class LiveSegmentsConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "live_segments.yaml"

    segments: list[LiveSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "LiveSegmentsConfig":
        ids = [s.id for s in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("id di tratto duplicati")
        return self
