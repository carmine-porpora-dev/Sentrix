import re
from typing import ClassVar
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from app.models.base import FrozenModel, Slug
from app.models.yamlconfig import CONFIG_DIR, YamlConfig

INTERNAL_SCHEME = "internal"
LOOPBACK_HOST = "127.0.0.1"  # solo questo indirizzo, scritto così: non localhost, non altri
VIRTUAL_MARK = "(virtuale)"  # i nomi mostrati all'utente dichiarano che il dipartimento è finto

_WHITESPACE_OR_CONTROL = re.compile(r"[\s\x00-\x1f\x7f]")


def check_endpoint(endpoint: str, department_id: str) -> None:
    """Solleva ValueError se `endpoint` non è `internal://<department_id>` né `http://127.0.0.1`
    (con porta e percorso facoltativi). Nessuna abbreviazione dell'indirizzo, nessun utente."""
    if _WHITESPACE_OR_CONTROL.search(endpoint):
        raise ValueError("l'indirizzo non può contenere spazi o caratteri di controllo")
    parts = urlsplit(
        endpoint
    )  # porta in minuscolo lo schema: per questo si controlla anche il testo
    if parts.scheme == INTERNAL_SCHEME and endpoint.startswith(f"{INTERNAL_SCHEME}://"):
        if parts.netloc != department_id or parts.path or parts.query or parts.fragment:
            raise ValueError(
                f"un indirizzo interno è esattamente '{INTERNAL_SCHEME}://{department_id}'"
            )
        return
    if parts.scheme == "http" and endpoint.startswith(f"http://{LOOPBACK_HOST}"):
        try:
            parts.port  # noqa: B018 (solleva ValueError se la porta non è valida)
        except ValueError as exc:
            raise ValueError("porta non valida") from exc
        if parts.hostname == LOOPBACK_HOST and "@" not in parts.netloc:
            return
    raise ValueError(
        f"indirizzo non ammesso: solo '{INTERNAL_SCHEME}://{department_id}' o "
        f"'http://{LOOPBACK_HOST}' (nessun ente reale come destinatario)"
    )


class Department(FrozenModel):
    id: Slug
    label: str = Field(min_length=1)  # mostrato nell'interfaccia
    endpoint: str
    request_types: list[Slug] = Field(min_length=1)  # tipi di richiesta che gestisce

    @field_validator("label")
    @classmethod
    def _says_virtual(cls, value: str) -> str:
        if not value.strip().lower().endswith(VIRTUAL_MARK):
            raise ValueError(f"il nome deve finire con «{VIRTUAL_MARK}»: nessun ente reale")
        return value

    @field_validator("request_types")
    @classmethod
    def _unique_types(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("request_types: voci duplicate")
        return value

    @model_validator(mode="after")
    def _endpoint_is_virtual(self) -> "Department":
        try:
            check_endpoint(self.endpoint, self.id)
        except ValueError as exc:
            raise ValueError(f"endpoint: {exc}") from exc
        return self


class DepartmentsConfig(YamlConfig):
    DEFAULT_PATH: ClassVar = CONFIG_DIR / "departments.yaml"

    departments: list[Department] = Field(min_length=1)
    response_delay_ms: int = Field(ge=0)  # ritardo simulato RECEIVED → esito
    auto_timeout_s: int = Field(ge=1)
    manual_timeout_s: int = Field(ge=1)  # attesa della risposta manuale (04 5)

    @model_validator(mode="after")
    def _consistent(self) -> "DepartmentsConfig":
        ids = [d.id for d in self.departments]
        if len(set(ids)) != len(ids):
            raise ValueError("id di dipartimento duplicati")
        owner: dict[str, str] = {}
        for department in self.departments:
            for request_type in department.request_types:
                if request_type in owner:
                    raise ValueError(
                        f"il tipo di richiesta '{request_type}' è gestito sia da "
                        f"'{owner[request_type]}' sia da '{department.id}'"
                    )
                owner[request_type] = department.id
        return self

    def department(self, department_id: str) -> Department | None:
        return next((d for d in self.departments if d.id == department_id), None)
