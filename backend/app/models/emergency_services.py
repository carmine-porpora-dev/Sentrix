from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.models.base import FrozenModel, Slug
from app.models.yamlconfig import CONFIG_DIR, YamlConfig

ServiceKind = Literal["police", "fire", "hospital"]

ServiceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EmergencyService(FrozenModel):
    id: Slug
    name: ServiceName  # come compare nella scheda e nel bollettino
    kind: ServiceKind


class EmergencyServicesConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "emergency_services.yaml"

    # quante voci al massimo per elenco nel testo (strade chiuse, sature, incroci, linee); le altre
    # diventano «e altre N». Un bollettino con duecento strade non lo legge nessuno.
    max_listed: int = Field(ge=1)
    services: list[EmergencyService] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [service.id for service in self.services]
        if len(set(ids)) != len(ids):
            raise ValueError("id di destinatario duplicati")
        return self
