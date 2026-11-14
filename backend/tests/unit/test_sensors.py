import json
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

from app.models.config import RailKind
from app.models.sensors import PlannedSensor, SensorsConfig, SensorType
from app.models.yamlconfig import CONFIG_DIR

TEXTS = {
    "name": "Contapersone — Mergellina",
    "measures": "Persone in uscita per varco",
    "replaces": "I pesi ipotizzati degli arrivi",
}


def sensor(**changes: Any) -> dict[str, Any]:
    """Un contapersone valido, con le modifiche."""
    base: dict[str, Any] = {
        "id": "people_mergellina",
        "type": "people_counter",
        "status": "planned",
        "location": {"lat": 40.83, "lon": 14.22},
        **TEXTS,
    }
    return {**base, **changes}


def without(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in keys}


@pytest.fixture(scope="module")
def real() -> SensorsConfig:
    return SensorsConfig.from_yaml()


# --- il modello ----------------------------------------------------------------------------------


def test_un_sensore_valido() -> None:
    parsed = PlannedSensor.model_validate(sensor())
    assert (parsed.type, parsed.status) == ("people_counter", "planned")
    assert parsed.location is not None and (parsed.location.lat, parsed.location.lon) == (
        40.83,
        14.22,
    )


@pytest.mark.parametrize("status", ["active", "installed", "", None])
def test_lo_stato_e_solo_planned(status: object) -> None:
    with pytest.raises(ValidationError, match="status"):
        PlannedSensor.model_validate(sensor(status=status))


def test_lo_stato_e_obbligatorio() -> None:
    with pytest.raises(ValidationError, match="status"):
        PlannedSensor.model_validate(without(sensor(), "status"))


def test_il_tipo_e_uno_dei_quattro() -> None:
    assert set(get_args(SensorType)) == {"gps_probe", "turnstile", "people_counter", "ramp_counter"}
    with pytest.raises(ValidationError, match="type"):
        PlannedSensor.model_validate(sensor(type="camera"))


@pytest.mark.parametrize("field", ["name", "measures", "replaces"])
@pytest.mark.parametrize("value", ["", "   "])
def test_i_testi_non_sono_vuoti(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        PlannedSensor.model_validate(sensor(**{field: value}))


@pytest.mark.parametrize("field", ["name", "measures", "replaces", "id", "type"])
def test_i_campi_di_base_sono_obbligatori(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        PlannedSensor.model_validate(without(sensor(), field))


@pytest.mark.parametrize("kind", ["people_counter", "ramp_counter"])
def test_contapersone_e_sensori_di_rampa_vogliono_una_posizione(kind: str) -> None:
    with pytest.raises(ValidationError, match="posizione"):
        PlannedSensor.model_validate(without(sensor(type=kind), "location"))


def test_i_tornelli_non_hanno_posizione_e_vogliono_la_classe_di_linea() -> None:
    turnstile = without(sensor(type="turnstile", route_class="metro_line_1"), "location")
    assert PlannedSensor.model_validate(turnstile).route_class == "metro_line_1"
    with pytest.raises(ValidationError, match="location"):
        PlannedSensor.model_validate(sensor(type="turnstile", route_class="metro_line_1"))
    with pytest.raises(ValidationError, match="route_class"):
        PlannedSensor.model_validate(without(turnstile, "route_class"))


def test_le_classi_di_linea_sono_quelle_del_motore() -> None:
    """`route_class` è il tipo `RailKind` di engine.yaml: una classe che non esiste non passa."""
    turnstile = without(sensor(type="turnstile"), "location")
    for kind in get_args(RailKind):
        assert PlannedSensor.model_validate({**turnstile, "route_class": kind})
    with pytest.raises(ValidationError, match="route_class"):
        PlannedSensor.model_validate({**turnstile, "route_class": "tram"})


def test_le_sonde_gps_non_hanno_posizione_ne_linea() -> None:
    probe = without(sensor(type="gps_probe"), "location")
    assert PlannedSensor.model_validate(probe).location is None
    with pytest.raises(ValidationError, match="location"):
        PlannedSensor.model_validate(sensor(type="gps_probe"))
    with pytest.raises(ValidationError, match="route_class"):
        PlannedSensor.model_validate({**probe, "route_class": "funicular"})


def test_route_class_vale_solo_per_i_tornelli() -> None:
    with pytest.raises(ValidationError, match="route_class"):
        PlannedSensor.model_validate(sensor(route_class="metro_line_6"))


@pytest.mark.parametrize("location", [{"lat": 91, "lon": 14}, {"lat": 40, "lon": 181}, {"lat": 40}])
def test_una_posizione_fuori_dal_mondo_non_passa(location: dict[str, float]) -> None:
    with pytest.raises(ValidationError, match="location"):
        PlannedSensor.model_validate(sensor(location=location))


def test_una_chiave_sconosciuta_e_un_errore() -> None:
    """Un refuso non si perde, e un campo di misura (`value`, `kind`…) non entra di nascosto."""
    with pytest.raises(ValidationError, match="value"):
        PlannedSensor.model_validate(sensor(value=12))


# --- il file ------------------------------------------------------------------------------------


def test_il_file_vero_si_carica(real: SensorsConfig) -> None:
    assert SensorsConfig.DEFAULT_PATH == CONFIG_DIR / "sensors.yaml"
    assert len(real.sensors) == 14  # 1 + 3 + 6 + 4: i quattro tipi di 11.5


def test_il_file_vero_ha_i_sensori_di_11_5(real: SensorsConfig) -> None:
    by_type: dict[str, list[PlannedSensor]] = {}
    for s in real.sensors:
        by_type.setdefault(s.type, []).append(s)
    assert {t: len(v) for t, v in by_type.items()} == {
        "gps_probe": 1,
        "turnstile": 3,
        "people_counter": 6,
        "ramp_counter": 4,
    }
    assert {s.route_class for s in by_type["turnstile"]} == set(get_args(RailKind))
    people = " ".join(s.name for s in by_type["people_counter"])
    for place in (
        "Napoli Centrale / Garibaldi",
        "Mergellina",
        "Campi Flegrei",
        "Molo Beverello",
        "Calata Porta di Massa",
        "Stazione Marittima",
    ):
        assert place in people, place
    ramps = " ".join(s.name for s in by_type["ramp_counter"])
    for place in ("Fuorigrotta", "Agnano", "Vomero", "Corso Malta"):
        assert place in ramps, place


def test_il_file_vero_e_tutto_planned_e_senza_numeri_di_misura(real: SensorsConfig) -> None:
    for s in real.sensors:
        assert s.status == "planned"
        dumped = s.model_dump(mode="json")
        # solo i campi di 11.5: nessun valore, unità, natura del dato, fonte o istante
        assert set(dumped) == {
            "id", "type", "name", "status", "location", "route_class", "measures", "replaces",
        }  # fmt: skip


def test_il_file_vero_non_chiama_il_motore_una_previsione(real: SensorsConfig) -> None:
    """Principio 6, e «previsto» è il nome dello stato dei sensori, non un testo dei dati."""
    for s in real.sensors:
        text = f"{s.name} {s.measures} {s.replaces}".lower()
        assert "prevision" not in text and "prevedere" not in text, s.id


def test_le_posizioni_stanno_a_napoli(real: SensorsConfig) -> None:
    for s in real.sensors:
        if s.location:
            assert 14.14 <= s.location.lon <= 14.30 and 40.80 <= s.location.lat <= 40.90, s.id


def test_gli_id_sono_unici(real: SensorsConfig) -> None:
    ids = [s.id for s in real.sensors]
    assert len(ids) == len(set(ids))


def config_text(*entries: dict[str, Any]) -> str:
    return yaml.safe_dump({"sensors": list(entries)}, allow_unicode=True)


def test_id_duplicati_sono_un_errore() -> None:
    with pytest.raises(ValidationError, match="duplicati"):
        SensorsConfig.from_yaml_text(config_text(sensor(), sensor()))


def test_due_voci_di_tornelli_per_la_stessa_linea_sono_un_errore() -> None:
    a = without(sensor(id="t_a", type="turnstile", route_class="funicular"), "location")
    b = {**a, "id": "t_b"}
    with pytest.raises(ValidationError, match="stessa classe"):
        SensorsConfig.from_yaml_text(config_text(a, b))


def test_il_file_non_puo_essere_vuoto() -> None:
    with pytest.raises(ValidationError, match="sensors"):
        SensorsConfig.from_yaml_text("sensors: []")


def test_chiavi_duplicate_nel_file_sono_un_errore(tmp_path: Path) -> None:
    path = tmp_path / "sensors.yaml"
    path.write_text("sensors: []\nsensors: []\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match="duplicata"):
        SensorsConfig.from_yaml(path)


def test_il_contenuto_si_serializza_senza_perdere_nulla(real: SensorsConfig) -> None:
    again = SensorsConfig.model_validate(json.loads(real.model_dump_json()))
    assert again == real
