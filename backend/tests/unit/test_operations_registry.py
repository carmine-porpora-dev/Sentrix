from typing import Any

import pytest

from app.models.catalog import CatalogConfig
from app.models.departments import Department, DepartmentsConfig
from app.operations.registry import (
    DepartmentRegistry,
    RegistryError,
    UnknownDepartment,
    UnsupportedRequestType,
)


@pytest.fixture(scope="module")
def registry() -> DepartmentRegistry:
    return DepartmentRegistry.from_yaml()


def unvalidated_department(**changes: Any) -> Department:
    """Un dipartimento costruito aggirando i validatori: come se qualcuno avesse scritto il dato
    in un altro modo che non passa dal file YAML."""
    fields: dict[str, Any] = {
        "id": "traffic_control",
        "label": "Controllo Traffico (virtuale)",
        "endpoint": "internal://traffic_control",
        "request_types": ["close_road"],
    }
    return Department.model_construct(**{**fields, **changes})


def config_with(*departments: Department) -> DepartmentsConfig:
    return DepartmentsConfig.model_construct(
        departments=list(departments),
        response_delay_ms=1500,
        auto_timeout_s=10,
        manual_timeout_s=60,
    )


EMPTY_CATALOG = CatalogConfig.model_construct(measures=[])


# --- il registro vero ------------------------------------------------------------------------


def test_il_registro_dei_file_ha_i_quattro_dipartimenti_interni(
    registry: DepartmentRegistry,
) -> None:
    assert [d.id for d in registry.departments] == [
        "traffic_control",
        "municipal_police",
        "transport_control",
        "public_comms",
    ]
    for department in registry.departments:
        assert department.endpoint == f"internal://{department.id}"
        assert department.label.endswith("(virtuale)")


def test_i_tempi_sono_quelli_della_configurazione(registry: DepartmentRegistry) -> None:
    assert registry.response_delay_s == 1.5
    assert registry.auto_timeout_s == 10
    assert registry.manual_timeout_s == 60


@pytest.mark.parametrize(
    ("request_type", "department_id"),
    [
        ("close_road", "traffic_control"),
        ("signal_plan_change", "traffic_control"),
        ("traffic_post", "municipal_police"),
        ("crowd_control_post", "municipal_police"),
        ("add_runs", "transport_control"),
        ("bus_detour", "transport_control"),
        ("citizen_notice", "public_comms"),
    ],
)
def test_ogni_tipo_di_richiesta_ha_il_suo_dipartimento(
    registry: DepartmentRegistry, request_type: str, department_id: str
) -> None:
    assert registry.for_type(request_type).id == department_id
    assert registry.accepting(department_id, request_type).id == department_id


def test_un_tipo_sconosciuto_non_ha_dipartimento(registry: DepartmentRegistry) -> None:
    with pytest.raises(
        UnsupportedRequestType, match="Nessun dipartimento gestisce 'bombardamento'"
    ):
        registry.for_type("bombardamento")


def test_un_dipartimento_gestisce_solo_i_suoi_tipi(registry: DepartmentRegistry) -> None:
    with pytest.raises(UnsupportedRequestType, match="'public_comms' non gestisce 'traffic_post'"):
        registry.accepting("public_comms", "traffic_post")


def test_un_dipartimento_sconosciuto(registry: DepartmentRegistry) -> None:
    with pytest.raises(UnknownDepartment, match="'ente_reale'"):
        registry.department("ente_reale")
    with pytest.raises(UnknownDepartment):
        registry.accepting("ente_reale", "traffic_post")


# --- host rifiutati (principio 3) --------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://questura.napoli.it/api",  # un ente reale
        "http://prefettura.na.it",
        "http://localhost:8000",  # nemmeno localhost: solo 127.0.0.1, e comunque non da qui
        "http://127.0.0.1.evil.example",  # il nome comincia come l'indirizzo giusto
        "http://127.0.0.1@evil.example/",  # il vero host è dopo la chiocciola
        "internal://municipal_police",  # interno ma di un altro dipartimento
        "internal://traffic_control/extra",
        "INTERNAL://traffic_control",
        "ftp://traffic_control",
        "traffic_control",
        "",
    ],
)
def test_un_indirizzo_non_interno_e_un_errore_di_avvio(endpoint: str) -> None:
    config = config_with(unvalidated_department(endpoint=endpoint))
    with pytest.raises(RegistryError, match="registro dei dipartimenti non valido"):
        DepartmentRegistry(config, EMPTY_CATALOG)


def test_loopback_e_ammesso_dalla_configurazione_ma_non_dal_centro_operativo() -> None:
    """La configurazione lo accetta per eventuali prove (04 1), ma nessun codice del pacchetto
    può raggiungerlo: il registro lo dice subito invece di fallire al primo invio."""
    config = config_with(unvalidated_department(endpoint="http://127.0.0.1:9000"))
    with pytest.raises(RegistryError, match="non è interno"):
        DepartmentRegistry(config, EMPTY_CATALOG)


def test_tutti_i_problemi_in_un_solo_messaggio() -> None:
    config = config_with(
        unvalidated_department(endpoint="https://uno.example"),
        unvalidated_department(id="municipal_police", endpoint="https://due.example"),
    )
    with pytest.raises(RegistryError) as raised:
        DepartmentRegistry(config, EMPTY_CATALOG)
    assert "'traffic_control'" in str(raised.value) and "'municipal_police'" in str(raised.value)


def test_il_catalogo_e_il_registro_devono_dire_la_stessa_cosa() -> None:
    catalog = CatalogConfig.from_yaml()
    config = DepartmentsConfig.from_yaml()
    without_police = config.model_copy(
        update={"departments": [d for d in config.departments if d.id != "municipal_police"]}
    )
    with pytest.raises(RegistryError, match="non esiste"):
        DepartmentRegistry(without_police, catalog)
