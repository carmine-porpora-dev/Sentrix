import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.models.catalog import CatalogConfig, check_catalog_departments
from app.models.departments import DepartmentsConfig, check_endpoint
from app.models.yamlconfig import CONFIG_DIR
from tests.support import DELETE, mutated

DEPARTMENTS_YAML = CONFIG_DIR / "departments.yaml"
CATALOG_YAML = CONFIG_DIR / "catalog.yaml"


@pytest.fixture
def departments() -> DepartmentsConfig:
    return DepartmentsConfig.from_yaml()


@pytest.fixture
def catalog() -> CatalogConfig:
    return CatalogConfig.from_yaml()


@pytest.fixture
def raw_departments() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(DEPARTMENTS_YAML.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def raw_catalog() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CATALOG_YAML.read_text(encoding="utf-8"))
    return data


def error_text(model: Any, data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        model.model_validate(data)
    return str(info.value)


# --- registro dei dipartimenti: i valori di 04 1 ---------------------------------------------


def test_i_percorsi_di_default_sono_i_file_del_repository() -> None:
    assert DepartmentsConfig.DEFAULT_PATH == DEPARTMENTS_YAML and DEPARTMENTS_YAML.is_file()
    assert CatalogConfig.DEFAULT_PATH == CATALOG_YAML and CATALOG_YAML.is_file()


def test_dipartimenti_come_in_04_1(departments: DepartmentsConfig) -> None:
    table = [(d.id, d.label, d.endpoint, d.request_types) for d in departments.departments]
    assert table == [
        (
            "traffic_control",
            "Controllo Traffico (virtuale)",
            "internal://traffic_control",
            ["close_road", "signal_plan_change", "detour_signage"],
        ),
        (
            "municipal_police",
            "Polizia Municipale (virtuale)",
            "internal://municipal_police",
            ["traffic_post", "crowd_control_post"],
        ),
        (
            "transport_control",
            "Controllo Trasporti (virtuale)",
            "internal://transport_control",
            ["add_runs", "extend_hours", "bus_detour", "stop_suspension"],
        ),
        (
            "public_comms",
            "Comunicazione Pubblica (virtuale)",
            "internal://public_comms",
            ["citizen_notice"],
        ),
    ]
    assert (departments.response_delay_ms, departments.auto_timeout_s) == (1500, 10)
    assert departments.manual_timeout_s == 60


def test_ricerca_di_un_dipartimento(departments: DepartmentsConfig) -> None:
    found = departments.department("municipal_police")
    assert found is not None and found.label == "Polizia Municipale (virtuale)"
    assert departments.department("questura") is None


# --- l'indirizzo: nessun ente reale come destinatario (principio 3) ----------------------------

GOOD_ENDPOINTS = [
    "internal://traffic_control",
    "http://127.0.0.1",
    "http://127.0.0.1/",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8000/vdept/traffic_control",
]
BAD_ENDPOINTS = [
    ("altro dipartimento", "internal://municipal_police"),
    ("schema interno con maiuscole", "INTERNAL://traffic_control"),
    ("percorso su un indirizzo interno", "internal://traffic_control/x"),
    ("barra finale", "internal://traffic_control/"),
    ("query", "internal://traffic_control?x=1"),
    ("frammento", "internal://traffic_control#f"),
    ("senza nome", "internal://"),
    ("senza barre", "internal:traffic_control"),
    ("https su loopback", "https://127.0.0.1"),
    ("schema http in maiuscolo", "HTTP://127.0.0.1"),
    ("loopback con un utente", "http://utente@127.0.0.1"),
    ("loopback come utente e come host", "http://127.0.0.1@127.0.0.1"),
    ("localhost", "http://localhost"),
    ("localhost con porta", "http://localhost:8000"),
    ("ipv6 loopback", "http://[::1]"),
    ("loopback abbreviato", "http://127.1"),
    ("loopback in decimale", "http://2130706433"),
    ("altro indirizzo 127", "http://127.0.0.2"),
    ("dominio che inizia come il loopback", "http://127.0.0.1.nip.io"),
    ("loopback come utente", "http://127.0.0.1@example.com"),
    ("loopback con porta come utente", "http://127.0.0.1:80@example.com"),
    ("host vero", "http://example.com"),
    ("host vero https", "https://www.comune.napoli.it"),
    ("host vero con percorso", "https://www.comune.napoli.it/polizia"),
    ("ftp su loopback", "ftp://127.0.0.1"),
    ("file", "file:///etc/passwd"),
    ("senza schema", "127.0.0.1"),
    ("schema relativo", "//127.0.0.1"),
    ("vuoto", ""),
    ("spazio davanti", " internal://traffic_control"),
    ("spazio dietro", "internal://traffic_control "),
    ("accapo", "http://127.0.0.1\n"),
    ("tabulazione dentro", "http://127.0.0.1\t.example.com"),
    ("porta non numerica", "http://127.0.0.1:abc"),
    ("porta fuori range", "http://127.0.0.1:99999"),
]


@pytest.mark.parametrize("endpoint", GOOD_ENDPOINTS)
def test_indirizzi_ammessi(endpoint: str) -> None:
    check_endpoint(endpoint, "traffic_control")


@pytest.mark.parametrize(("name", "endpoint"), BAD_ENDPOINTS, ids=[b[0] for b in BAD_ENDPOINTS])
def test_indirizzi_non_ammessi(name: str, endpoint: str) -> None:
    with pytest.raises(ValueError):
        check_endpoint(endpoint, "traffic_control")


@pytest.mark.parametrize(("name", "endpoint"), BAD_ENDPOINTS, ids=[b[0] for b in BAD_ENDPOINTS])
def test_un_file_con_un_indirizzo_non_ammesso_non_si_carica(
    raw_departments: dict[str, Any], name: str, endpoint: str
) -> None:
    data = mutated(raw_departments, ("departments", 0, "endpoint"), endpoint)
    assert "departments.0" in error_text(DepartmentsConfig, data)


def test_il_messaggio_dice_cosa_e_ammesso(raw_departments: dict[str, Any]) -> None:
    data = mutated(raw_departments, ("departments", 1, "endpoint"), "https://www.comune.napoli.it")
    message = error_text(DepartmentsConfig, data)
    assert "indirizzo non ammesso" in message and "nessun ente reale come destinatario" in message
    assert "internal://municipal_police" in message and "http://127.0.0.1" in message


# --- registro: altri vincoli -------------------------------------------------------------------

DEPARTMENT_CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    (
        "id non è uno slug",
        ("departments", 0, "id"),
        "Traffic Control",
        "String should match pattern",
    ),
    (
        "nome senza «(virtuale)»",
        ("departments", 1, "label"),
        "Polizia Municipale di Napoli",
        "(virtuale)",
    ),
    ("nome vuoto", ("departments", 0, "label"), "", "at least 1 character"),
    (
        "«(virtuale)» solo all'inizio",
        ("departments", 0, "label"),
        "(virtuale) Controllo Traffico",
        "(virtuale)",
    ),
    ("nessun tipo di richiesta", ("departments", 3, "request_types"), [], "at least 1 item"),
    (
        "tipo duplicato nello stesso dipartimento",
        ("departments", 1, "request_types"),
        ["traffic_post", "traffic_post"],
        "voci duplicate",
    ),
    (
        "tipo gestito da due dipartimenti",
        ("departments", 1, "request_types"),
        ["traffic_post", "add_runs"],
        "è gestito sia da 'municipal_police' sia da 'transport_control'",
    ),
    (
        "tipo non è uno slug",
        ("departments", 1, "request_types", 0),
        "Traffic Post",
        "String should match pattern",
    ),
    ("nessun dipartimento", ("departments",), [], "at least 1 item"),
    ("ritardo negativo", ("response_delay_ms",), -1, "greater than or equal to 0"),
    ("timeout automatico zero", ("auto_timeout_s",), 0, "greater than or equal to 1"),
    ("timeout manuale zero", ("manual_timeout_s",), 0, "greater than or equal to 1"),
    ("timeout manuale in testo", ("manual_timeout_s",), "sessanta", "valid integer"),
    ("manca il ritardo", ("response_delay_ms",), DELETE, "response_delay_ms\n  Field required"),
    (
        "manca il timeout manuale",
        ("manual_timeout_s",),
        DELETE,
        "manual_timeout_s\n  Field required",
    ),
    ("chiave sconosciuta", ("version",), 1, "Extra inputs are not permitted"),
    (
        "chiave sconosciuta nel dipartimento",
        ("departments", 0, "host"),
        "x",
        "Extra inputs are not permitted",
    ),
]


@pytest.mark.parametrize(
    ("name", "path", "value", "fragment"), DEPARTMENT_CASES, ids=[c[0] for c in DEPARTMENT_CASES]
)
def test_registro_non_valido(
    raw_departments: dict[str, Any],
    name: str,
    path: tuple[str | int, ...],
    value: Any,
    fragment: str,
) -> None:
    assert fragment in error_text(DepartmentsConfig, mutated(raw_departments, path, value)), name


def test_id_duplicato(raw_departments: dict[str, Any]) -> None:
    data = mutated(raw_departments, ("departments", 1, "id"), "traffic_control")
    data = mutated(data, ("departments", 1, "endpoint"), "internal://traffic_control")
    assert "id di dipartimento duplicati" in error_text(DepartmentsConfig, data)


def test_il_nome_virtuale_non_dipende_da_maiuscole_e_spazi(raw_departments: dict[str, Any]) -> None:
    data = mutated(raw_departments, ("departments", 0, "label"), "Controllo Traffico (VIRTUALE)  ")
    assert DepartmentsConfig.model_validate(data).departments[0].label.endswith("(VIRTUALE)  ")


def test_ritardo_zero_e_ammesso(raw_departments: dict[str, Any]) -> None:
    assert (
        DepartmentsConfig.model_validate(
            mutated(raw_departments, ("response_delay_ms",), 0)
        ).response_delay_ms
        == 0
    )


# --- catalogo: i valori di 04 6 ----------------------------------------------------------------


def test_misure_come_in_04_6(catalog: CatalogConfig) -> None:
    table = [
        (m.type, m.department, m.target_kind, m.triggers, m.alternatives) for m in catalog.measures
    ]
    assert table == [
        (
            "traffic_post",
            "municipal_police",
            "intersection",
            ["critical_intersection"],
            ["signal_plan_change", "detour_signage"],
        ),
        (
            "signal_plan_change",
            "traffic_control",
            "intersection",
            ["critical_intersection"],
            ["detour_signage"],
        ),
        (
            "detour_signage",
            "traffic_control",
            "edges",
            ["critical_intersection", "saturated_path"],
            [],
        ),
        (
            "extend_hours",
            "transport_control",
            "route",
            ["line_no_service_in_window", "section_overloaded"],
            ["add_runs"],
        ),
        ("add_runs", "transport_control", "route", ["section_overloaded", "stop_overloaded"], []),
        ("stop_suspension", "transport_control", "stop", ["stop_overloaded_unsafe"], []),
        ("crowd_control_post", "municipal_police", "stop", ["stop_overloaded"], ["add_runs"]),
        ("citizen_notice", "public_comms", "none", ["plan_accepted"], []),
    ]


def test_i_tipi_di_criticita_ammessi_sono_i_trigger_del_catalogo(catalog: CatalogConfig) -> None:
    assert catalog.trigger_ids == {
        "critical_intersection",
        "saturated_path",
        "line_no_service_in_window",
        "section_overloaded",
        "stop_overloaded",
        "stop_overloaded_unsafe",
        "plan_accepted",
    }
    assert isinstance(catalog.trigger_ids, frozenset)


def test_ricerca_di_una_misura(catalog: CatalogConfig) -> None:
    found = catalog.measure("signal_plan_change")
    assert found is not None and found.alternatives == ["detour_signage"]
    assert catalog.measure("close_road") is None  # tipo di richiesta, non misura del catalogo


def test_catalogo_e_dipartimenti_sono_coerenti_e_close_road_e_solo_nel_registro(
    catalog: CatalogConfig, departments: DepartmentsConfig
) -> None:
    check_catalog_departments(catalog, departments)  # non solleva
    traffic = departments.department("traffic_control")
    assert traffic is not None and "close_road" in traffic.request_types


CATALOG_CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    ("tipo duplicato", ("measures", 1, "type"), "traffic_post", "tipi di misura duplicati"),
    (
        "alternativa che non esiste",
        ("measures", 0, "alternatives"),
        ["reboot_city"],
        "alternative che non sono misure del catalogo: ['reboot_city']",
    ),
    (
        "misura alternativa di se stessa",
        ("measures", 0, "alternatives"),
        ["traffic_post"],
        "alternativa di se stessa",
    ),
    (
        "alternative duplicate",
        ("measures", 0, "alternatives"),
        ["add_runs", "add_runs"],
        "voci duplicate",
    ),
    ("trigger duplicati", ("measures", 0, "triggers"), ["a", "a"], "voci duplicate"),
    ("nessun trigger", ("measures", 0, "triggers"), [], "at least 1 item"),
    (
        "trigger non è uno slug",
        ("measures", 0, "triggers", 0),
        "Critical Intersection",
        "String should match pattern",
    ),
    ("tipo di bersaglio sconosciuto", ("measures", 0, "target_kind"), "building", "target_kind"),
    (
        "manca il tipo di bersaglio",
        ("measures", 0, "target_kind"),
        DELETE,
        "target_kind\n  Field required",
    ),
    (
        "manca il dipartimento",
        ("measures", 0, "department"),
        DELETE,
        "department\n  Field required",
    ),
    ("tipo non è uno slug", ("measures", 0, "type"), "Traffic Post", "String should match pattern"),
    ("nessuna misura", ("measures",), [], "at least 1 item"),
    ("chiave sconosciuta", ("measures", 0, "window"), "arrival", "Extra inputs are not permitted"),
]


@pytest.mark.parametrize(
    ("name", "path", "value", "fragment"), CATALOG_CASES, ids=[c[0] for c in CATALOG_CASES]
)
def test_catalogo_non_valido(
    raw_catalog: dict[str, Any], name: str, path: tuple[str | int, ...], value: Any, fragment: str
) -> None:
    assert fragment in error_text(CatalogConfig, mutated(raw_catalog, path, value)), name


def test_le_alternative_possono_essere_vuote_e_mancare(raw_catalog: dict[str, Any]) -> None:
    data = copy.deepcopy(raw_catalog)
    del data["measures"][2]["alternatives"]  # detour_signage non ne ha: il default è []
    assert CatalogConfig.model_validate(data).measures[2].alternatives == []


def test_l_ordine_delle_alternative_si_conserva(raw_catalog: dict[str, Any]) -> None:
    data = mutated(
        raw_catalog, ("measures", 0, "alternatives"), ["detour_signage", "signal_plan_change"]
    )
    assert CatalogConfig.model_validate(data).measures[0].alternatives == [
        "detour_signage",
        "signal_plan_change",
    ]


# --- coerenza tra catalogo e registro ----------------------------------------------------------


def test_misura_di_un_dipartimento_che_non_esiste(
    catalog: CatalogConfig, raw_catalog: dict[str, Any], departments: DepartmentsConfig
) -> None:
    broken = CatalogConfig.model_validate(
        mutated(raw_catalog, ("measures", 7, "department"), "questura")
    )
    with pytest.raises(ValueError, match="'citizen_notice': il dipartimento 'questura' non esiste"):
        check_catalog_departments(broken, departments)


def test_misura_che_il_dipartimento_non_dichiara(
    raw_catalog: dict[str, Any], departments: DepartmentsConfig
) -> None:
    broken = CatalogConfig.model_validate(
        mutated(raw_catalog, ("measures", 0, "department"), "traffic_control")
    )
    with pytest.raises(
        ValueError, match="'traffic_post': 'traffic_control' non lo ha tra i suoi request_types"
    ):
        check_catalog_departments(broken, departments)


def test_tutti_i_problemi_sono_riportati_insieme(
    raw_catalog: dict[str, Any], departments: DepartmentsConfig
) -> None:
    data = mutated(
        mutated(raw_catalog, ("measures", 0, "department"), "questura"),
        ("measures", 5, "department"),
        "public_comms",
    )
    with pytest.raises(ValueError) as info:
        check_catalog_departments(CatalogConfig.model_validate(data), departments)
    text = str(info.value)
    assert "'traffic_post': il dipartimento 'questura' non esiste" in text
    assert "'stop_suspension': 'public_comms' non lo ha" in text


def test_un_dipartimento_con_tipi_in_piu_e_ammesso(
    catalog: CatalogConfig, raw_departments: dict[str, Any]
) -> None:
    data = mutated(
        raw_departments, ("departments", 3, "request_types"), ["citizen_notice", "press_release"]
    )
    check_catalog_departments(catalog, DepartmentsConfig.model_validate(data))


# --- caricamento e hash (la base condivisa) ----------------------------------------------------


@pytest.mark.parametrize("model", [DepartmentsConfig, CatalogConfig])
def test_chiave_duplicata_nel_file_e_un_errore(
    model: type[DepartmentsConfig] | type[CatalogConfig],
) -> None:
    text = (
        model.DEFAULT_PATH.read_text(encoding="utf-8")
        + "\n"
        + (
            "response_delay_ms: 1\nresponse_delay_ms: 2\n"
            if model is DepartmentsConfig
            else "measures: []\nmeasures: []\n"
        )
    )
    with pytest.raises(yaml.constructor.ConstructorError, match="chiave duplicata"):
        model.from_yaml_text(text)


@pytest.mark.parametrize("model", [DepartmentsConfig, CatalogConfig])
def test_documento_che_non_e_una_mappa(
    model: type[DepartmentsConfig] | type[CatalogConfig],
) -> None:
    with pytest.raises(
        ValueError,
        match=rf"{re.escape(model.DEFAULT_PATH.name)}: il documento deve essere una mappa",
    ):
        model.from_yaml_text("- uno\n- due\n")


def test_file_mancante(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        CatalogConfig.from_yaml(tmp_path / "non_esiste.yaml")


@pytest.mark.parametrize("model", [DepartmentsConfig, CatalogConfig])
def test_hash_stabile_in_esadecimale_e_indifferente_da_commenti_e_ordine(
    model: type[DepartmentsConfig] | type[CatalogConfig],
) -> None:
    config = model.from_yaml()
    assert re.fullmatch(r"[0-9a-f]{64}", config.content_hash())
    assert config.content_hash() == model.from_yaml(model.DEFAULT_PATH).content_hash()
    raw = yaml.safe_load(model.DEFAULT_PATH.read_text(encoding="utf-8"))
    reordered = yaml.safe_dump(dict(reversed(raw.items())), allow_unicode=True, sort_keys=False)
    assert (
        model.from_yaml_text("# commento nuovo\n" + reordered).content_hash()
        == config.content_hash()
    )


def test_l_hash_cambia_se_cambia_un_valore(
    raw_departments: dict[str, Any],
    raw_catalog: dict[str, Any],
    departments: DepartmentsConfig,
    catalog: CatalogConfig,
) -> None:
    changed_dep = DepartmentsConfig.model_validate(
        mutated(raw_departments, ("auto_timeout_s",), 11)
    )
    changed_cat = CatalogConfig.model_validate(
        mutated(raw_catalog, ("measures", 0, "target_kind"), "edges")
    )
    assert changed_dep.content_hash() != departments.content_hash()
    assert changed_cat.content_hash() != catalog.content_hash()
    assert departments.content_hash() != catalog.content_hash()


def test_la_configurazione_e_immutabile(
    catalog: CatalogConfig, departments: DepartmentsConfig
) -> None:
    with pytest.raises(ValidationError, match="frozen"):
        catalog.measures = []  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        departments.departments[0].endpoint = "http://example.com"  # type: ignore[misc]
