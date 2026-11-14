from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.models.edge_overrides import DEFAULT_EDGE_OVERRIDES_PATH, EdgeOverride, EdgeOverrides

YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "edge_overrides.yaml"

VALID: dict[str, Any] = {
    "version": 1,
    "overrides": [
        {"edge_key": "1-2-0", "lanes": 3, "reason": "tag lanes mancante, 3 corsie viste sul posto"},
        {"edge_key": "2-1-0", "speed_kmh": 30, "reason": "zona 30 non mappata"},
    ],
}


def error_text(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        EdgeOverrides.model_validate(data)
    return str(info.value)


def test_il_file_del_repository_e_vuoto_e_valido() -> None:
    assert DEFAULT_EDGE_OVERRIDES_PATH == YAML_PATH and YAML_PATH.is_file()
    loaded = EdgeOverrides.from_yaml()
    assert loaded.version == 1
    assert loaded.overrides == []  # «vuoto di default» (02 2)


def test_una_correzione_valida_si_legge_da_yaml() -> None:
    loaded = EdgeOverrides.from_yaml_text(yaml.safe_dump(VALID))
    first, second = loaded.overrides
    assert (first.edge_key, first.lanes, first.speed_kmh) == ("1-2-0", 3, None)
    assert (second.edge_key, second.lanes, second.speed_kmh) == ("2-1-0", None, 30.0)
    assert first.reason.startswith("tag lanes mancante")


def test_l_hash_cambia_con_il_contenuto_non_con_i_commenti() -> None:
    plain = EdgeOverrides.from_yaml_text(yaml.safe_dump(VALID))
    commented = EdgeOverrides.from_yaml_text("# commento\n" + yaml.safe_dump(VALID))
    other = EdgeOverrides.model_validate(
        {**VALID, "overrides": [{**VALID["overrides"][0], "lanes": 4}, VALID["overrides"][1]]}
    )
    assert plain.content_hash() == commented.content_hash()
    assert plain.content_hash() != other.content_hash()


@pytest.mark.parametrize(
    "key", ["", "1-2", "1-2-3-4", "a-2-0", "-1-2-0", "1-2-0 ", "1-2-x", "12 - 3 - 0"]
)
def test_la_chiave_deve_essere_u_v_k(key: str) -> None:
    with pytest.raises(ValidationError, match="edge_key"):
        EdgeOverride(edge_key=key, lanes=2, reason="r")


def test_deve_cambiare_almeno_una_cosa() -> None:
    with pytest.raises(ValidationError, match="almeno `lanes` o `speed_kmh`"):
        EdgeOverride(edge_key="1-2-0", reason="r")


@pytest.mark.parametrize("reason", ["", "   ", "\n"])
def test_la_ragione_e_obbligatoria_e_non_vuota(reason: str) -> None:
    with pytest.raises(ValidationError, match="reason|ragione"):
        EdgeOverride(edge_key="1-2-0", lanes=2, reason=reason)


def test_la_ragione_non_si_puo_omettere() -> None:
    with pytest.raises(ValidationError, match="reason"):
        EdgeOverride.model_validate({"edge_key": "1-2-0", "lanes": 2})


@pytest.mark.parametrize(
    ("field", "value"), [("lanes", 0), ("lanes", -1), ("speed_kmh", 0), ("speed_kmh", -10)]
)
def test_corsie_e_velocita_devono_essere_positive(field: str, value: float) -> None:
    with pytest.raises(ValidationError, match=field):
        EdgeOverride.model_validate({"edge_key": "1-2-0", "reason": "r", field: value})


def test_lo_stesso_arco_non_si_corregge_due_volte() -> None:
    twice = [VALID["overrides"][0], {**VALID["overrides"][1], "edge_key": "1-2-0"}]
    assert "archi corretti più di una volta: ['1-2-0']" in error_text({**VALID, "overrides": twice})


def test_una_chiave_sconosciuta_e_un_errore() -> None:
    bad = {**VALID["overrides"][0], "capacity_vph": 5000}  # la capacità non si corregge
    assert "capacity_vph" in error_text({**VALID, "overrides": [bad]})
    assert "extra" in error_text({**VALID, "oops": 1}).lower()


def test_la_versione_e_obbligatoria_e_vale_uno() -> None:
    assert "version" in error_text({"overrides": []})
    assert "version" in error_text({"version": 2, "overrides": []})


def test_un_documento_che_non_e_una_mappa_e_un_errore() -> None:
    with pytest.raises(ValueError, match="mappa di sezioni"):
        EdgeOverrides.from_yaml_text("- 1\n- 2\n")
