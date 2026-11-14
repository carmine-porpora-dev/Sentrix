from app.models.catalog import CatalogConfig, check_catalog_departments
from app.models.departments import INTERNAL_SCHEME, Department, DepartmentsConfig, check_endpoint


class RegistryError(Exception):
    """Il registro non è valido: si scopre all'avvio, mai a metà di un run."""


class UnknownDepartment(RegistryError):
    def __init__(self, department_id: str) -> None:
        super().__init__(f"Dipartimento '{department_id}' non trovato")
        self.department_id = department_id


class UnsupportedRequestType(RegistryError):
    """Il dipartimento non gestisce quel tipo di richiesta (o nessun dipartimento lo gestisce)."""

    def __init__(self, request_type: str, department_id: str | None = None) -> None:
        if department_id is None:
            super().__init__(f"Nessun dipartimento gestisce '{request_type}'")
        else:
            super().__init__(f"Il dipartimento '{department_id}' non gestisce '{request_type}'")
        self.request_type = request_type
        self.department_id = department_id


class DepartmentRegistry:
    """Una vista sulla configurazione (che resta l'unico posto dei dati) con le domande che servono
    al Centro operativo: quale dipartimento gestisce un tipo di richiesta, e quali tempi valgono."""

    def __init__(self, config: DepartmentsConfig, catalog: CatalogConfig) -> None:
        problems: list[str] = []
        for department in config.departments:
            try:
                check_endpoint(department.endpoint, department.id)
            except ValueError as exc:
                problems.append(f"'{department.id}': {exc}")
                continue
            if not department.endpoint.startswith(f"{INTERNAL_SCHEME}://"):
                problems.append(
                    f"'{department.id}': l'indirizzo '{department.endpoint}' non è interno, e il "
                    f"Centro operativo non contatta nessun host (solo '{INTERNAL_SCHEME}://<id>')"
                )
        if problems:
            raise RegistryError("registro dei dipartimenti non valido: " + "; ".join(problems))
        try:
            check_catalog_departments(catalog, config)
        except ValueError as exc:
            raise RegistryError(str(exc)) from exc
        self._config = config
        self._catalog = catalog
        self._by_type = {t: d for d in config.departments for t in d.request_types}

    @classmethod
    def from_yaml(cls) -> "DepartmentRegistry":
        """Il registro dei file `config/departments.yaml` e `config/catalog.yaml`."""
        return cls(DepartmentsConfig.from_yaml(), CatalogConfig.from_yaml())

    @property
    def departments(self) -> list[Department]:
        return list(self._config.departments)

    @property
    def catalog(self) -> CatalogConfig:
        return self._catalog

    @property
    def response_delay_s(self) -> float:
        """Ritardo simulato tra la ricezione e l'esito (per rendere visibile il flusso in demo)."""
        return self._config.response_delay_ms / 1000

    @property
    def auto_timeout_s(self) -> int:
        return self._config.auto_timeout_s

    @property
    def manual_timeout_s(self) -> int:
        return self._config.manual_timeout_s

    def department(self, department_id: str) -> Department:
        department = self._config.department(department_id)
        if department is None:
            raise UnknownDepartment(department_id)
        return department

    def for_type(self, request_type: str) -> Department:
        """Il dipartimento che gestisce un tipo di richiesta (uno solo: lo garantisce la
        configurazione)."""
        department = self._by_type.get(request_type)
        if department is None:
            raise UnsupportedRequestType(request_type)
        return department

    def accepting(self, department_id: str, request_type: str) -> Department:
        """Il dipartimento `department_id`, se gestisce `request_type`."""
        department = self.department(department_id)
        if request_type not in department.request_types:
            raise UnsupportedRequestType(request_type, department_id)
        return department
