import ast
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.clock import ROME
from app.models import provenance
from app.models.provenance import Measured, make_measured, measured_id

AS_OF = datetime(2026, 11, 7, 10, 30, tzinfo=ROME)
BACKEND = Path(__file__).resolve().parents[2]


def valid(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "m.run42.it1.od.bagnoli_centrale.time",
        "value": 23.5,
        "unit": "min",
        "kind": "simulated",
        "source": "engine.assign v1",
        "method": "assegnazione incrementale BPR, 4 passi",
        "inputs": ["osm 2026-11-07", "event evt_match_2027 rev 3", "engine.yaml sha:ab12"],
        "assumptions": ["traffico di fondo a quota fissa"],
        "as_of": AS_OF,
    }
    return {**base, **overrides}


# --- make_measured -------------------------------------------------------------------------


def test_make_measured_costruisce_un_valore_completo() -> None:
    m = make_measured(**valid())
    assert m.id == "m.run42.it1.od.bagnoli_centrale.time"
    assert (m.value, m.unit, m.kind) == (23.5, "min", "simulated")
    assert m.source == "engine.assign v1" and m.method.startswith("assegnazione")
    assert m.inputs == ["osm 2026-11-07", "event evt_match_2027 rev 3", "engine.yaml sha:ab12"]
    assert m.assumptions == ["traffico di fondo a quota fissa"]
    assert m.as_of == AS_OF


def test_make_measured_assunzioni_facoltative_e_sequenze_accettate() -> None:
    m = make_measured(**{**valid(), "inputs": ("osm",), "assumptions": ()})
    assert m.inputs == ["osm"] and m.assumptions == []


def test_as_of_omesso_e_adesso_a_roma(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed = datetime(2026, 1, 15, 9, 0, tzinfo=ROME)
    monkeypatch.setattr(provenance, "now_rome", lambda: fixed)
    args = {k: v for k, v in valid().items() if k != "as_of"}
    assert make_measured(**args).as_of == fixed


def test_as_of_viene_normalizzato_a_europe_rome() -> None:
    utc = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)  # luglio: Roma è UTC+2
    m = make_measured(**valid(as_of=utc))
    assert m.as_of == utc  # stesso istante
    assert m.as_of.utcoffset() == timedelta(hours=2) and m.as_of.hour == 14
    winter = make_measured(**valid(as_of=datetime(2026, 11, 7, 9, 0, tzinfo=UTC)))
    assert winter.as_of.utcoffset() == timedelta(hours=1)  # novembre: UTC+1


def test_as_of_senza_fuso_e_rifiutato() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_measured(**valid(as_of=datetime(2026, 11, 7, 10, 30)))


@pytest.mark.parametrize("value", [0, -3, 12, 4.25, 0.0, "congestione alta", "12", ""])
def test_valori_ammessi_e_tipo_conservato(value: float | int | str) -> None:
    m = make_measured(**valid(value=value))
    assert m.value == value and type(m.value) is type(value)  # "12" resta testo, 12 resta int


@pytest.mark.parametrize("value", [True, False, math.nan, math.inf, -math.inf])
def test_valori_non_ammessi(value: object) -> None:
    with pytest.raises(ValidationError):
        make_measured(**valid(value=value))


REJECTED: list[tuple[str, dict[str, Any], str]] = [
    ("unità vuota", {"unit": ""}, "at least 1 character"),
    ("fonte vuota", {"source": ""}, "at least 1 character"),
    ("metodo vuoto", {"method": ""}, "at least 1 character"),
    ("kind sconosciuto", {"kind": "previsione"}, "kind"),
    ("nessun input", {"inputs": []}, "at least 1 item"),
    ("input vuoto", {"inputs": ["osm", "  "]}, "non possono essere vuote"),
    ("assunzione vuota", {"assumptions": [""]}, "non possono essere vuote"),
    ("id senza prefisso m.", {"id": "run42.it1"}, "String should match pattern"),
    ("id con parte vuota", {"id": "m.run42..time"}, "String should match pattern"),
    ("id con spazio", {"id": "m.run 42"}, "String should match pattern"),
    ("id solo prefisso", {"id": "m."}, "String should match pattern"),
    ("id vuoto", {"id": ""}, "String should match pattern"),
]


@pytest.mark.parametrize(("name", "overrides", "fragment"), REJECTED, ids=[r[0] for r in REJECTED])
def test_valori_non_validi_sono_rifiutati(
    name: str, overrides: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(ValidationError) as info:
        make_measured(**valid(**overrides))
    assert fragment in str(info.value), name


def test_i_tre_kind_ammessi() -> None:
    for kind in ("real", "estimate", "simulated"):
        assert make_measured(**valid(kind=kind)).kind == kind


def test_immutabile_e_senza_chiavi_extra() -> None:
    m = make_measured(**valid())
    with pytest.raises(ValidationError, match="frozen"):
        m.value = 1  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        Measured.model_validate({**m.model_dump(), "colore": "rosso"})


def test_json_andata_e_ritorno() -> None:
    m = make_measured(**valid())
    text = m.model_dump_json()
    assert '"as_of":"2026-11-07T10:30:00+01:00"' in text
    assert Measured.model_validate_json(text) == m
    as_text = make_measured(**valid(value="alta"))
    assert Measured.model_validate_json(as_text.model_dump_json()) == as_text


# --- measured_id ---------------------------------------------------------------------------


def test_measured_id_come_nella_spec() -> None:
    assert measured_id("run42", "it1", "od", "bagnoli_centrale", "time") == (
        "m.run42.it1.od.bagnoli_centrale.time"
    )
    assert measured_id("live", "tomtom", "via-caracciolo") == "m.live.tomtom.via-caracciolo"


def test_measured_id_e_deterministico() -> None:
    assert measured_id("run1", "x") == measured_id("run1", "x") != measured_id("run2", "x")


@pytest.mark.parametrize("parts", [(), ("",), ("run 42",), ("a.b",), ("run", ""), ("è",)])
def test_measured_id_parti_non_valide(parts: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="measured_id"):
        measured_id(*parts)


def test_ogni_id_prodotto_da_measured_id_e_accettato() -> None:
    assert make_measured(**valid(id=measured_id("run1", "it0", "stato", "a_b-c"))).id.startswith(
        "m."
    )


# --- «Vietato costruire Measured a mano altrove» (01 1) ------------------------------------


def find_measured_constructions(source: str) -> list[int]:
    """Righe in cui si chiama `Measured(...)` (anche `modulo.Measured(...)`)."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "Measured":
                lines.append(node.lineno)
    return lines


def test_il_controllo_architetturale_funziona() -> None:
    assert find_measured_constructions("x = Measured(id='m.a')") == [1]
    assert find_measured_constructions("import p\nx = p.provenance.Measured(id=1)") == [2]
    assert find_measured_constructions("x = make_measured(id=1)") == []
    assert find_measured_constructions("x = Measured.model_validate(d)") == []
    assert find_measured_constructions("def f(m: Measured) -> Measured: ...") == []


def test_measured_si_costruisce_solo_con_make_measured() -> None:
    allowed = BACKEND / "app" / "models" / "provenance.py"
    offenders = []
    for folder in ("app", "scripts"):
        for path in (BACKEND / folder).rglob("*.py"):
            if path != allowed and find_measured_constructions(path.read_text(encoding="utf-8")):
                offenders.append(path.relative_to(BACKEND).as_posix())
    assert offenders == [], f"Measured costruito a mano in: {offenders}"
    assert find_measured_constructions(allowed.read_text(encoding="utf-8")), (
        "make_measured sparito?"
    )
