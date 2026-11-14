from typing import ClassVar

from pydantic import Field, model_validator

from app.models.base import FrozenModel
from app.models.yamlconfig import CONFIG_DIR, YamlConfig


class RateRule(FrozenModel):
    """«Al massimo `limit` eventi in `window_s` secondi.»"""

    limit: int = Field(ge=1)
    window_s: int = Field(ge=1)


class NetworkConfig(FrozenModel):
    """Quanto della rete stradale e del TPL si dà alla mappa dell'Event Manager."""

    major_classes: list[str] = Field(min_length=1)
    detail_max_span_deg: float = Field(gt=0)
    max_span_deg: float = Field(gt=0)
    max_features: int = Field(ge=1)

    @model_validator(mode="after")
    def _detail_within_max(self) -> "NetworkConfig":
        if self.detail_max_span_deg > self.max_span_deg:
            raise ValueError("detail_max_span_deg non può superare max_span_deg")
        return self


class ApiConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "api.yaml"

    session_hours: int = Field(ge=1)  # durata del cookie di sessione
    login_failures: RateRule  # tentativi di login ERRATI per IP
    runs_per_session: RateRule  # POST /api/runs, per sessione
    runs_global: RateRule  # POST /api/runs, su tutto il sistema
    network: NetworkConfig  # archi, fermate e linee per la mappa
