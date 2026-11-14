from typing import ClassVar

from pydantic import Field, model_validator

from app.models.base import FrozenModel
from app.models.yamlconfig import CONFIG_DIR, YamlConfig


class TomTomConfig(FrozenModel):
    timeout_s: float = Field(gt=0)  # attesa massima per richiesta
    retries: int = Field(ge=0)  # tentativi in più dopo errore di rete, timeout o 5xx
    max_concurrency: int = Field(ge=1)  # richieste in parallelo


class FlowConfig(FrozenModel):
    cache_ttl_s: int = Field(gt=0)  # età massima di un tratto per riusarlo senza richiamare TomTom
    # soglie (decrescenti, in (0, 1]) del rapporto velocità ÷ flusso libero tra le quattro classi
    ratio_classes: tuple[float, float, float]

    @model_validator(mode="after")
    def _descending(self) -> "FlowConfig":
        first, second, third = self.ratio_classes
        if not (1 >= first > second > third > 0):
            raise ValueError("ratio_classes: tre soglie decrescenti tra 0 e 1")
        return self


class LiveConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "live.yaml"

    tomtom: TomTomConfig
    flow: FlowConfig
