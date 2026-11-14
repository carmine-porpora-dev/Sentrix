from pathlib import Path

import pytest

from app.data.paths import DataPaths
from scripts import prepare_gtfs, prepare_osm, prepare_pmtiles
from scripts.bootstrap_data import STEPS, Step, bootstrap, main


def _writer(name: str, calls: list[str]) -> Step:
    """Un passo che, come lo script vero, scrive il suo dato dentro `--data-dir`."""

    def step(argv: list[str]) -> int:
        assert argv[0] == "--data-dir" and len(argv) == 2
        paths = DataPaths(Path(argv[1]))
        calls.append(name)
        if name == "osm":
            paths.osm_graph.parent.mkdir(parents=True, exist_ok=True)
            paths.osm_graph.write_text("grafo")
        elif name == "gtfs":
            paths.gtfs_feed.mkdir(parents=True, exist_ok=True)
        else:
            paths.pmtiles.parent.mkdir(parents=True, exist_ok=True)
            paths.pmtiles.write_text("mappa")
        return 0

    return step


def _steps(calls: list[str]) -> dict[str, Step]:
    return {name: _writer(name, calls) for name in STEPS}


def test_con_i_dati_presenti_non_fa_nulla(tmp_path: Path) -> None:
    calls: list[str] = []
    steps = _steps(calls)
    for step in steps.values():
        step(["--data-dir", str(tmp_path)])
    calls.clear()
    present = bootstrap(tmp_path, steps)
    assert calls == []
    assert present == {"osm": True, "gtfs": True, "pmtiles": True}


def test_con_la_cartella_vuota_prepara_tutto_una_volta_sola(tmp_path: Path) -> None:
    calls: list[str] = []
    present = bootstrap(tmp_path / "dati", _steps(calls))  # la cartella non esiste nemmeno
    assert calls == ["osm", "gtfs", "pmtiles"]
    assert present == {"osm": True, "gtfs": True, "pmtiles": True}
    again: list[str] = []
    bootstrap(tmp_path / "dati", _steps(again))
    assert again == []  # idempotente


def test_prepara_solo_cio_che_manca(tmp_path: Path) -> None:
    calls: list[str] = []
    steps = _steps(calls)
    steps["osm"](["--data-dir", str(tmp_path)])
    steps["pmtiles"](["--data-dir", str(tmp_path)])
    calls.clear()
    bootstrap(tmp_path, steps)
    assert calls == ["gtfs"]


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("Overpass non risponde"),
        OSError("rete assente"),
        SystemExit(2),  # un argomento rifiutato da argparse nello script
    ],
    ids=["eccezione", "errore-di-rete", "system-exit"],
)
def test_un_passo_che_fallisce_non_ferma_gli_altri_ne_l_applicazione(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: BaseException
) -> None:
    calls: list[str] = []
    steps = _steps(calls)

    def broken(argv: list[str]) -> int:
        calls.append("gtfs")
        raise failure

    steps["gtfs"] = broken
    present = bootstrap(tmp_path, steps)  # non solleva
    assert calls == ["osm", "gtfs", "pmtiles"]  # il passo dopo il guasto gira lo stesso
    assert present == {"osm": True, "gtfs": False, "pmtiles": True}
    out = capsys.readouterr().out
    assert out.count("gtfs: NON riuscito") == 1  # una sola riga di errore
    assert "mancano: gtfs" in out
    assert "degradato" in out


@pytest.mark.parametrize("exit_code", [0, 1])
def test_uno_script_che_esce_senza_scrivere_il_dato_e_un_fallimento(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], exit_code: int
) -> None:
    steps = _steps([])
    steps["osm"] = lambda argv: exit_code  # esce (anche con 0) e non scrive nulla
    present = bootstrap(tmp_path, steps)
    assert present["osm"] is False  # conta il dato, non il codice di uscita
    assert f"osm: NON riuscito (lo script è uscito con {exit_code} e il dato non c'è)" in (
        capsys.readouterr().out
    )


def test_main_esce_con_zero_se_i_dati_ci_sono_e_con_uno_se_ne_manca_uno(tmp_path: Path) -> None:
    steps = _steps([])
    assert main(["--data-dir", str(tmp_path / "a")], steps) == 0
    steps["pmtiles"] = lambda argv: 1
    assert main(["--data-dir", str(tmp_path / "b")], steps) == 1


def test_usa_gli_script_veri_e_la_stessa_definizione_di_health() -> None:
    assert {
        "osm": prepare_osm.main,
        "gtfs": prepare_gtfs.main,
        "pmtiles": prepare_pmtiles.main,
    } == STEPS
    # i passi hanno esattamente i nomi dei dati di `/api/health` (DataPaths.present)
    assert list(STEPS) == list(DataPaths(Path(".")).present())


@pytest.mark.parametrize("name", list(STEPS))
def test_ogni_script_vero_accetta_data_dir(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        STEPS[name](["--help"])
    assert exit_info.value.code == 0
    assert "--data-dir" in capsys.readouterr().out
