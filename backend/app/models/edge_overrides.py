from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import Field, StringConstraints, model_validator

from app.models.base import EDGE_KEY_PATTERN, FrozenModel
from app.models.yamlconfig import CONFIG_DIR, YamlConfig

DEFAULT_EDGE_OVERRIDES_PATH = CONFIG_DIR / "edge_overrides.yaml"

EdgeKeyStr = Annotated[str, StringConstraints(pattern=rf"^{EDGE_KEY_PATTERN}$")]


class EdgeOverride(FrozenModel):
    edge_key: EdgeKeyStr  # "u-v-k"; deve esistere nel grafo (lo controlla engine.graph)
    lanes: int | None = Field(default=None, ge=1)  # per senso di marcia
    speed_kmh: float | None = Field(default=None, gt=0)
    reason: str = Field(min_length=1)  # perché il dato OSM non va bene

    @model_validator(mode="after")
    def _changes_something(self) -> "EdgeOverride":
        if self.lanes is None and self.speed_kmh is None:
            raise ValueError("una correzione deve cambiare almeno `lanes` o `speed_kmh`")
        if not self.reason.strip():
            raise ValueError("la ragione della correzione non può essere vuota")
        return self


class EdgeOverrides(YamlConfig):
    DEFAULT_PATH: ClassVar[Path] = DEFAULT_EDGE_OVERRIDES_PATH

    version: Literal[1]
    overrides: list[EdgeOverride]

    @model_validator(mode="after")
    def _unique_keys(self) -> "EdgeOverrides":
        keys = [item.edge_key for item in self.overrides]
        duplicated = sorted({key for key in keys if keys.count(key) > 1})
        if duplicated:
            raise ValueError(f"archi corretti più di una volta: {duplicated}")
        return self
