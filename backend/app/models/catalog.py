from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from app.models.base import FrozenModel, Slug
from app.models.departments import DepartmentsConfig
from app.models.yamlconfig import CONFIG_DIR, YamlConfig

TargetKind = Literal["intersection", "edges", "route", "stop", "none"]


class Measure(FrozenModel):
    type: Slug
    department: Slug  # id del dipartimento virtuale che la gestisce
    target_kind: TargetKind
    triggers: list[Slug] = Field(min_length=1)  # tipi di finding che la giustificano
    alternatives: list[Slug] = Field(default_factory=list)  # in ordine di preferenza

    @field_validator("triggers", "alternatives")
    @classmethod
    def _no_duplicates(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("voci duplicate")
        return value

    @model_validator(mode="after")
    def _not_its_own_alternative(self) -> "Measure":
        if self.type in self.alternatives:
            raise ValueError("una misura non può essere alternativa di se stessa")
        return self


class CatalogConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "catalog.yaml"

    measures: list[Measure] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "CatalogConfig":
        types = [m.type for m in self.measures]
        if len(set(types)) != len(types):
            raise ValueError("tipi di misura duplicati")
        unknown = sorted({a for m in self.measures for a in m.alternatives if a not in set(types)})
        if unknown:
            raise ValueError(f"alternative che non sono misure del catalogo: {unknown}")
        return self

    def measure(self, measure_type: str) -> Measure | None:
        return next((m for m in self.measures if m.type == measure_type), None)

    @property
    def trigger_ids(self) -> frozenset[str]:
        """I tipi di criticità ammessi in un Finding: quelli che giustificano almeno una misura."""
        return frozenset(t for m in self.measures for t in m.triggers)


def check_catalog_departments(catalog: CatalogConfig, departments: DepartmentsConfig) -> None:
    """Il catalogo e il registro dicono la stessa cosa: ogni misura è gestita da un dipartimento
    che esiste e che dichiara di gestirla. Solleva ValueError con tutti i problemi.

    Nell'altro verso NON si controlla: un dipartimento può gestire tipi che nessun agente propone
    (`close_road` di traffic_control non ha una misura nel catalogo)."""
    problems = []
    for measure in catalog.measures:
        department = departments.department(measure.department)
        if department is None:
            problems.append(f"'{measure.type}': il dipartimento '{measure.department}' non esiste")
        elif measure.type not in department.request_types:
            problems.append(
                f"'{measure.type}': '{measure.department}' non lo ha tra i suoi request_types"
            )
    if problems:
        raise ValueError("catalogo e dipartimenti non coerenti: " + "; ".join(problems))
