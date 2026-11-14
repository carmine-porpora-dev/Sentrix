import ast
from collections import defaultdict
from pathlib import Path

from app.data.tomtom import MAX_ERROR_TEXT, contains_key, error_message, redact
from app.models.api import HealthResponse
from app.models.base import Environment
from app.settings import Settings
from scripts.tomtom_probe import scrub

BACKEND = Path(__file__).resolve().parents[2]


def string_literals(root: Path) -> dict[frozenset[str], list[str]]:
    """Ogni `Literal["a", "b", ...]` di soli testi sotto `root`, per insieme di valori."""
    found: dict[frozenset[str], list[str]] = defaultdict(list)
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Subscript) and "Literal" in ast.unparse(node.value)):
                continue
            items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            values = [
                str(i.value)
                for i in items
                if isinstance(i, ast.Constant) and isinstance(i.value, str)
            ]
            if len(values) == len(items) and len(values) > 1:
                found[frozenset(values)].append(f"{path.name}:{node.lineno}")
    return found


def test_nessun_insieme_di_valori_e_scritto_due_volte() -> None:
    """Se due moduli dicono `Literal["local", "production"]` il giorno che un valore cambia uno
    dei due resta indietro: si scrive un alias in un posto e lo si importa (principio «un dato, un
    posto»). I valori che per significato differiscono (per esempio una finestra più «both») sono
    insiemi diversi e quindi non si confondono."""
    found = string_literals(BACKEND / "app")
    duplicated = {repr(sorted(v)): where for v, where in found.items() if len(where) > 1}
    assert duplicated == {}


def test_il_controllo_sa_riconoscere_una_copia(tmp_path: Path) -> None:
    (tmp_path / "uno.py").write_text(
        'A = Literal["x", "y"]\nD = Literal["solo"]\n', encoding="utf-8"
    )
    (tmp_path / "due.py").write_text(
        'B = Literal["y", "x"]\nC = Literal["z", "w"]\n', encoding="utf-8"
    )
    found = string_literals(tmp_path)
    assert sorted(found[frozenset({"x", "y"})]) == ["due.py:1", "uno.py:1"]  # l'ordine non conta
    assert len(found[frozenset({"z", "w"})]) == 1
    assert frozenset({"solo"}) not in found  # un solo valore non è un insieme da condividere


def test_l_ambiente_e_un_tipo_solo() -> None:
    assert Settings.__annotations__["env"] is Environment
    assert HealthResponse.model_fields["env"].annotation is Environment


def test_come_si_oscura_la_chiave_sta_in_un_posto_solo() -> None:
    holders = []
    for folder in ("app", "scripts"):
        for path in (BACKEND / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "bkey=" in node.value
                ):
                    holders.append(path.relative_to(BACKEND).as_posix())
    assert sorted(set(holders)) == ["app/data/tomtom.py"]  # la sonda la riusa, non la copia
    assert scrub("a?key=SEGRETO&b=1", "SEGRETO") == redact("a?key=SEGRETO&b=1", "SEGRETO")


def test_come_si_riconosce_una_chiave_rimasta_nel_testo() -> None:
    assert contains_key("point=1,2&key=SEGRETO") and contains_key("KEY=abc")
    assert contains_key("c'è SEGRETO qui", "SEGRETO") and not contains_key("c'è altro", "SEGRETO")
    assert not contains_key("point=1,2&key=***&z=1")  # già oscurato
    assert not contains_key("nessuna chiave") and not contains_key("monkey=1 turkey=2")


def test_il_motivo_dell_errore_di_tomtom_si_legge_in_un_posto_solo() -> None:
    assert (
        error_message(400, {"detailedError": {"message": "Point too far"}})
        == "HTTP 400: Point too far"
    )
    assert error_message(403, {"error": "Forbidden"}) == "HTTP 403: Forbidden"
    assert error_message(500, None) == "HTTP 500" and error_message(500, ["x"]) == "HTTP 500"
    assert error_message(400, {"detailedError": {"message": 5}}) == "HTTP 400: 5"
    assert error_message(400, {"detailedError": "testo"}) == "HTTP 400"  # forma inattesa: niente
    secret = error_message(400, {"error": "chiave key=ABC e ABC"}, "ABC")
    assert "ABC" not in secret and "key=***" in secret
    assert len(error_message(400, {"error": "x" * 999})) == MAX_ERROR_TEXT
