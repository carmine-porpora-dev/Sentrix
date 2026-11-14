import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
OPERATIONS = APP / "operations"

# Moduli (e pacchetti: vale anche per i sottomoduli) che aprono connessioni o inviano richieste.
# `httpx2` è il client del progetto (pyproject); gli altri sono i client e i socket più comuni.
FORBIDDEN = frozenset(
    {
        "httpx",
        "httpx2",
        "requests",
        "urllib.request",
        "urllib3",
        "aiohttp",
        "socket",
        "http.client",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "xmlrpc",
        "websockets",
        "websocket",
        "grpc",
        "paramiko",
        "ssl",
    }
)


def is_forbidden(module: str) -> bool:
    return any(module == name or module.startswith(f"{name}.") for name in FORBIDDEN)


def module_file(module: str) -> Path | None:
    """Il file di un modulo `app.x.y` (o il suo `__init__.py`), se è del progetto."""
    if module != "app" and not module.startswith("app."):
        return None
    base = APP.joinpath(*module.split(".")[1:])
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def imports_of(path: Path) -> list[str]:
    """Ogni modulo che il file importa, anche dentro funzioni (un import tardivo conta)."""
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path}: import relativo, non verificabile"
            base = node.module or ""
            names.append(base)
            names += [f"{base}.{alias.name}" for alias in node.names]
    return names


def closure(start: list[Path]) -> dict[Path, list[str]]:
    """Ogni file `app` raggiungibile dai file di partenza, con i moduli che importa."""
    seen: dict[Path, list[str]] = {}
    queue = list(start)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen[path] = imports_of(path)
        for name in seen[path]:
            target = module_file(name)
            if target is not None and target not in seen:
                queue.append(target)
    return seen


def operations_files() -> list[Path]:
    return sorted(OPERATIONS.glob("*.py"))


def test_il_pacchetto_ha_dei_moduli() -> None:
    names = {path.name for path in operations_files()}
    assert {"__init__.py", "registry.py"} <= names


def test_nessun_modulo_del_pacchetto_importa_una_libreria_di_rete() -> None:
    offences = [
        f"{path.relative_to(APP)}: {name}"
        for path in operations_files()
        for name in imports_of(path)
        if is_forbidden(name)
    ]
    assert offences == []


def test_nemmeno_i_moduli_che_il_pacchetto_importa_la_importano() -> None:
    reached = closure(operations_files())
    assert len(reached) > len(operations_files())  # la chiusura entra nei modelli e nel database
    offences = [
        f"{path.relative_to(APP)}: {name}"
        for path, names in reached.items()
        for name in names
        if is_forbidden(name)
    ]
    assert offences == []


def test_il_pacchetto_non_importa_i_moduli_che_parlano_con_l_esterno() -> None:
    """I dati scaricati, gli agenti con l'LLM, l'API: nessuno di questi serve a un dipartimento."""
    outside = ("app.data", "app.llm", "app.api", "app.agents", "app.orchestrator")
    offences = [
        f"{path.relative_to(APP)}: {name}"
        for path in operations_files()
        for name in imports_of(path)
        if name == "app" or any(name == o or name.startswith(f"{o}.") for o in outside)
    ]
    assert offences == []


# --- il controllo funziona (prova delle regole) -------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import httpx2",
        "import requests",
        "from urllib.request import urlopen",
        "import socket",
        "from http import client",  # `from http import client` è `http.client`
        "def f():\n    import aiohttp",  # un import dentro una funzione
        "from httpx2 import Client",
        "import urllib.request as u",
    ],
)
def test_il_rilevatore_vede_gli_import_vietati(tmp_path: Path, source: str) -> None:
    path = tmp_path / "modulo.py"
    path.write_text(source, encoding="utf-8")
    assert any(is_forbidden(name) for name in imports_of(path)), source


@pytest.mark.parametrize(
    "source", ["import sqlite3", "from urllib.parse import urlsplit", "import asyncio"]
)
def test_il_rilevatore_non_si_allarma_per_gli_import_innocui(tmp_path: Path, source: str) -> None:
    path = tmp_path / "modulo.py"
    path.write_text(source, encoding="utf-8")
    assert not any(is_forbidden(name) for name in imports_of(path)), source
