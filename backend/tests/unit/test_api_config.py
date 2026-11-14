import pytest
import yaml
from pydantic import ValidationError

from app.models.api_config import ApiConfig

VALID = """
session_hours: 12
login_failures: { limit: 5, window_s: 60 }
runs_per_session: { limit: 3, window_s: 60 }
runs_global: { limit: 20, window_s: 3600 }
network:
  major_classes: [primary, secondary]
  detail_max_span_deg: 0.01
  max_span_deg: 0.2
  max_features: 100
"""


def test_i_valori_del_file_sono_quelli_della_spec() -> None:
    config = ApiConfig.from_yaml()
    assert config.session_hours == 12  # 06 1: «durata 12 h»
    assert (config.login_failures.limit, config.login_failures.window_s) == (5, 60)
    assert (config.runs_per_session.limit, config.runs_per_session.window_s) == (3, 60)
    assert (config.runs_global.limit, config.runs_global.window_s) == (20, 3600)


def test_i_limiti_della_mappa_sono_quelli_del_file() -> None:
    network = ApiConfig.from_yaml().network
    assert network.major_classes == ["motorway", "trunk", "primary", "secondary", "tertiary"]
    assert (network.detail_max_span_deg, network.max_span_deg) == (0.012, 0.25)
    assert network.max_features == 4000


def test_il_file_di_esempio_in_questo_test_e_valido() -> None:
    assert ApiConfig.from_yaml_text(VALID).session_hours == 12


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("session_hours: 12", "session_hours: 0"),
        ("session_hours: 12", "session_hours: dodici"),
        ("limit: 5, window_s: 60", "limit: 0, window_s: 60"),
        ("limit: 5, window_s: 60", "limit: 5, window_s: 0"),
        ("limit: 3, window_s: 60", "limit: -1, window_s: 60"),
        ("limit: 3, window_s: 60", "limit: 3"),
        ("limit: 20, window_s: 3600", "limit: 20, window_s: 3600, extra: 1"),
        ("runs_global: { limit: 20, window_s: 3600 }", ""),
        ("major_classes: [primary, secondary]", "major_classes: []"),
        ("detail_max_span_deg: 0.01", "detail_max_span_deg: 0"),
        ("detail_max_span_deg: 0.01", "detail_max_span_deg: 0.3"),  # oltre il massimo
        ("max_span_deg: 0.2", "max_span_deg: 0"),
        ("max_features: 100", "max_features: 0"),
        ("max_features: 100", "max_features: 1.5"),
    ],
)
def test_valori_non_validi_sono_errori(old: str, new: str) -> None:
    assert old in VALID
    with pytest.raises((ValidationError, ValueError)):
        ApiConfig.from_yaml_text(VALID.replace(old, new))


def test_il_dettaglio_puo_arrivare_fino_al_massimo() -> None:
    same = VALID.replace("detail_max_span_deg: 0.01", "detail_max_span_deg: 0.2")
    assert ApiConfig.from_yaml_text(same).network.detail_max_span_deg == 0.2


def test_chiave_duplicata_e_un_errore() -> None:
    with pytest.raises(yaml.YAMLError, match="duplicata"):
        ApiConfig.from_yaml_text(VALID + "session_hours: 24\n")


def test_chiave_in_piu_e_un_errore() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ApiConfig.from_yaml_text(VALID + "rate_limit_runs: 3\n")


def test_hash_dipende_dal_contenuto_non_dai_commenti() -> None:
    base = ApiConfig.from_yaml_text(VALID)
    commented = ApiConfig.from_yaml_text("# un commento\n" + VALID)
    changed = ApiConfig.from_yaml_text(VALID.replace("limit: 3,", "limit: 4,"))
    assert base.content_hash() == commented.content_hash()
    assert base.content_hash() != changed.content_hash()
