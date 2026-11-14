import importlib.metadata as metadata
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = (ROOT / "docs" / "LICENSES.md").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))


def _direct() -> list[str]:
    return [
        re.split(r"[<>=!~\[; ]", spec, maxsplit=1)[0]
        for spec in PYPROJECT["project"]["dependencies"]
    ]


def _backend_section() -> str:
    return DOC.split("## Backend: dipendenze dirette")[1].split("\n## ")[0]


def _row(name: str) -> list[str] | None:
    for line in _backend_section().splitlines():
        if line.startswith(f"| {name} |"):
            return [cell.strip() for cell in line.split("|")[1:-1]]
    return None


def test_ogni_dipendenza_diretta_ha_versione_e_licenza_giuste() -> None:
    for name in _direct():
        meta = metadata.metadata(name)
        license_ = meta.get("License-Expression") or meta.get("License") or ""
        assert _row(name) == [name, metadata.version(name), license_.splitlines()[0]], name


def test_la_pagina_non_elenca_altro() -> None:
    listed = [
        line.split("|")[1].strip()
        for line in _backend_section().splitlines()
        if line.startswith("| ") and not line.startswith(("| Pacchetto", "| ---"))
    ]
    assert sorted(listed) == sorted(_direct())


def test_i_dati_e_i_punti_aperti_sono_dichiarati() -> None:
    for text in (
        "OpenStreetMap",
        "GTFS ANM",
        "TomTom",
        "ODbL 1.0",
        "Da verificare sul feed",
        "## Aperto",
    ):
        assert text in DOC, text
