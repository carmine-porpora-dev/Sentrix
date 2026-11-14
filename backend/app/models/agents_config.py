from typing import ClassVar

from pydantic import Field, field_validator, model_validator

from app.models.base import FrozenModel
from app.models.yamlconfig import CONFIG_DIR, YamlConfig


class ToolsConfig(FrozenModel):
    top_congested_edges: int = Field(ge=0)
    top_overloaded_stops: int = Field(ge=0)


class Thresholds(FrozenModel):
    """Da `warning_at` in su è un'attenzione, da `critical_at` in su è critico."""

    warning_at: float = Field(gt=0)
    critical_at: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "Thresholds":
        if not self.warning_at < self.critical_at:
            raise ValueError("warning_at deve essere minore di critical_at")
        return self


class SeverityConfig(FrozenModel):
    road: Thresholds  # rapporto v/c
    transit: Thresholds  # carico = passeggeri/ora ÷ capacità
    stop_unsafe_load: float = Field(gt=0)

    @model_validator(mode="after")
    def _unsafe_above_critical(self) -> "SeverityConfig":
        if self.stop_unsafe_load <= self.transit.critical_at:
            raise ValueError("stop_unsafe_load deve superare il carico critico del TPL")
        return self


class LabelsConfig(FrozenModel):
    route_classes: dict[str, str] = Field(
        min_length=1
    )  # classe di linea → come si chiama nei testi
    measures: dict[str, str] = Field(min_length=1)  # tipo di misura → come si chiama nei testi


class PlanConfig(FrozenModel):
    max_measures: int = Field(ge=1)


class RunConfig(FrozenModel):
    timeout_s: int = Field(ge=1)


class LanguageConfig(FrozenModel):
    forbidden_when_simulated: list[str] = Field(min_length=1)

    @field_validator("forbidden_when_simulated")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        words = [word.strip().lower() for word in value]
        if any(not word or " " in word for word in words):
            raise ValueError("ogni voce è una parola sola, non vuota")
        if len(set(words)) != len(words):
            raise ValueError("voci duplicate")
        return words


class NumbersConfig(FrozenModel):
    decimals: int = Field(ge=0, le=6)
    percent_units: list[str] = Field(min_length=1)  # unità che si possono scrivere in percentuale


class AgentsConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "agents.yaml"

    tools: ToolsConfig
    severity: SeverityConfig
    labels: LabelsConfig
    plan: PlanConfig
    run: RunConfig
    language: LanguageConfig
    numbers: NumbersConfig
