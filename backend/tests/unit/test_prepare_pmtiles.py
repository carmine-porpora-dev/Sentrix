import hashlib
import io
import json
import os
import re
import stat
import tarfile
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts import prepare_pmtiles
from scripts.common import DownloadError
from scripts.prepare_pmtiles import (
    ASSETS,
    GO_PMTILES_VERSION,
    PMTILES_BBOX,
    Asset,
    binary_version,
    build_extract_command,
    candidate_dates,
    check_pmtiles_file,
    find_latest_build,
    head_ok,
    install_pinned_binary,
    resolve_binary,
    select_asset,
)
from tests.support import FeedServer

TODAY = date(2026, 11, 7)

FAKE_PMTILES = """#!/bin/sh
case "$1" in
  version) echo "pmtiles {version}, commit deadbeef, built at 2026-07-22T00:00:00Z"; exit 0;;
  extract)
    if [ -n "$FAKE_ARGS_FILE" ]; then printf '%s\\n' "$@" > "$FAKE_ARGS_FILE"; fi
    if [ -n "$FAKE_WRITE_THEN_FAIL" ]; then
      printf 'PMTiles\\003parziale' > "$3"; echo "rete caduta" >&2; exit 4
    fi
    if [ -n "$FAKE_FAIL" ]; then echo "errore simulato" >&2; exit 3; fi
    if [ -n "$FAKE_GARBAGE" ]; then printf 'xxxxxxxxxxxxxxxx' > "$3"; exit 0; fi
    if [ -n "$FAKE_NO_OUTPUT" ]; then exit 0; fi
    printf 'PMTiles\\003fake-tile-data' > "$3"; exit 0;;
esac
exit 1
"""


def make_fake_binary(directory: Path, version: str = GO_PMTILES_VERSION) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "pmtiles"
    binary.write_text(FAKE_PMTILES.replace("{version}", version))
    binary.chmod(0o755)
    return binary


class DaysHead:
    """Finto controllo di rete: 'esiste' solo per i giorni dati; registra gli URL interrogati."""

    def __init__(self, *days: date) -> None:
        self.wanted = {f"{d:%Y%m%d}" for d in days}
        self.calls: list[str] = []

    def __call__(self, url: str) -> bool:
        self.calls.append(url)
        match = re.search(r"/(\d{8})\.pmtiles$", url)
        return match is not None and match.group(1) in self.wanted


# --- Build Protomaps -----------------------------------------------------------------------


def test_candidate_dates_oggi_e_dieci_giorni_prima() -> None:
    days = candidate_dates(date(2026, 11, 7))
    assert len(days) == 11
    assert days[0] == date(2026, 11, 7) and days[-1] == date(2026, 10, 28)  # attraversa il mese
    assert days == sorted(days, reverse=True)


def test_find_latest_build_prende_la_piu_recente_disponibile() -> None:
    head = DaysHead(date(2026, 11, 5), date(2026, 11, 1))
    day, url = find_latest_build(TODAY, head=head)
    assert day == date(2026, 11, 5)
    assert url == "https://build.protomaps.com/20261105.pmtiles"
    assert len(head.calls) == 3  # 7, 6, 5: si ferma alla prima che esiste


def test_find_latest_build_oggi_se_disponibile() -> None:
    day, url = find_latest_build(TODAY, head=DaysHead(TODAY))
    assert day == TODAY and url.endswith("/20261107.pmtiles")


def test_find_latest_build_nessuna_build() -> None:
    with pytest.raises(DownloadError) as info:
        find_latest_build(TODAY, head=DaysHead())
    assert "2026-10-28" in str(info.value) and "2026-11-07" in str(info.value)


def test_head_ok_distingue_esiste_manca_ed_errore(server: FeedServer) -> None:
    assert head_ok(f"{server.url}/feed.zip") is True
    assert head_ok(f"{server.url}/redirect") is True  # segue il redirect
    assert head_ok(f"{server.url}/manca") is False  # 404
    assert head_ok(f"{server.url}/forbidden") is False  # 403
    with pytest.raises(DownloadError, match="HTTP 500"):
        head_ok(f"{server.url}/boom")  # un errore del server non è "build assente"
    with pytest.raises(DownloadError, match="Controllo build fallito"):
        head_ok("http://127.0.0.1:9/x.pmtiles")  # rete non raggiungibile


# --- Scelta e installazione della CLI ------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "machine", "filename"),
    [
        ("Darwin", "arm64", "go-pmtiles-1.31.2_Darwin_arm64.zip"),  # trattino
        ("Darwin", "x86_64", "go-pmtiles-1.31.2_Darwin_x86_64.zip"),
        (
            "Linux",
            "aarch64",
            "go-pmtiles_1.31.2_Linux_arm64.tar.gz",
        ),  # underscore; aarch64 -> arm64
        ("Linux", "x86_64", "go-pmtiles_1.31.2_Linux_x86_64.tar.gz"),
        ("Linux", "AMD64", "go-pmtiles_1.31.2_Linux_x86_64.tar.gz"),
    ],
)
def test_select_asset(system: str, machine: str, filename: str) -> None:
    assert select_asset(system, machine).filename == filename


def test_select_asset_piattaforma_non_supportata() -> None:
    with pytest.raises(DownloadError, match="--pmtiles-bin"):
        select_asset("Windows", "x86_64")


def test_asset_fissati_sono_coerenti() -> None:
    assert len(ASSETS) == 4
    for asset in ASSETS.values():
        assert re.fullmatch(r"[0-9a-f]{64}", asset.sha256)
        assert GO_PMTILES_VERSION in asset.filename
        assert asset.url == (
            f"https://github.com/protomaps/go-pmtiles/releases/download/v{GO_PMTILES_VERSION}/"
            f"{asset.filename}"
        )
    assert len({a.sha256 for a in ASSETS.values()}) == 4


def _archive_with_binary(tmp_path: Path, kind: str, member: str = "pmtiles") -> Path:
    source = make_fake_binary(tmp_path / "src")
    archive = tmp_path / f"served.{kind}"
    if kind == "zip":
        with zipfile.ZipFile(archive, "w") as zf:
            zf.write(source, member)
            zf.writestr("README.md", "x")
    else:
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(source, member)
            info = tarfile.TarInfo("LICENSE")
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    return archive


def _fake_download(archive: Path) -> Callable[[str, Path], dict[str, str]]:
    def download(url: str, target: Path) -> dict[str, str]:
        target.write_bytes(archive.read_bytes())
        return {}

    return download


@pytest.mark.parametrize("kind", ["zip", "tar.gz"])
def test_install_pinned_binary(tmp_path: Path, kind: str) -> None:
    archive = _archive_with_binary(tmp_path, kind)
    asset = Asset(f"go-pmtiles_x.{kind}", hashlib.sha256(archive.read_bytes()).hexdigest())
    tools = tmp_path / "tools"
    binary = install_pinned_binary(tools, asset, download=_fake_download(archive))
    assert binary == tools / "pmtiles"
    assert os.access(binary, os.X_OK) and stat.S_IMODE(binary.stat().st_mode) == 0o755
    assert binary_version(binary) is not None and GO_PMTILES_VERSION in str(binary_version(binary))
    assert sorted(p.name for p in tools.iterdir()) == ["pmtiles"]  # archivio e .part rimossi


def test_install_pinned_binary_trova_il_binario_anche_in_una_sottocartella(tmp_path: Path) -> None:
    archive = _archive_with_binary(tmp_path, "tar.gz", member="go-pmtiles/pmtiles")
    asset = Asset("x.tar.gz", hashlib.sha256(archive.read_bytes()).hexdigest())
    assert install_pinned_binary(tmp_path / "t", asset, download=_fake_download(archive)).is_file()


def test_install_rifiuta_un_archivio_con_hash_diverso_senza_estrarlo(tmp_path: Path) -> None:
    archive = _archive_with_binary(tmp_path, "zip")
    asset = Asset("x.zip", "0" * 64)
    tools = tmp_path / "tools"
    with pytest.raises(DownloadError) as info:
        install_pinned_binary(tools, asset, download=_fake_download(archive))
    assert "sha256 diverso" in str(info.value) and "non estratto né eseguito" in str(info.value)
    assert list(tools.iterdir()) == []  # né binario né archivio


def test_install_rifiuta_un_archivio_senza_il_binario(tmp_path: Path) -> None:
    archive = tmp_path / "vuoto.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("altro.txt", "x")
    asset = Asset("vuoto.zip", hashlib.sha256(archive.read_bytes()).hexdigest())
    with pytest.raises(DownloadError, match="atteso un solo file 'pmtiles', trovati 0"):
        install_pinned_binary(tmp_path / "t", asset, download=_fake_download(archive))
    assert list((tmp_path / "t").iterdir()) == []


def test_install_download_fallito_non_lascia_nulla(tmp_path: Path) -> None:
    def failing(url: str, target: Path) -> dict[str, str]:
        raise DownloadError("rete giù")

    with pytest.raises(DownloadError, match="rete giù"):
        install_pinned_binary(tmp_path / "t", Asset("x.zip", "0" * 64), download=failing)
    assert list((tmp_path / "t").iterdir()) == []


def test_binary_version() -> None:
    assert binary_version(Path("/non/esiste/pmtiles")) is None


def test_binary_version_riga_di_versione(tmp_path: Path) -> None:
    version = binary_version(make_fake_binary(tmp_path, version="9.9.9"))
    assert version is not None and version.startswith("pmtiles 9.9.9")


def test_resolve_binary_ordine_di_ricerca(tmp_path: Path) -> None:
    explicit = make_fake_binary(tmp_path / "esplicito")
    on_path = make_fake_binary(tmp_path / "path")
    local = make_fake_binary(tmp_path / "data" / "tools")
    installed = tmp_path / "scaricato"

    def which(name: str) -> str | None:
        return str(on_path)

    def install(tools: Path, asset: Asset) -> Path:
        return installed

    data = tmp_path / "data"
    assert resolve_binary(data, explicit, which=which, install=install) == explicit
    assert resolve_binary(data, None, which=which, install=install) == on_path
    assert resolve_binary(data, None, which=lambda n: None, install=install) == local
    local.unlink()
    assert resolve_binary(data, None, which=lambda n: None, install=install) == installed


def test_resolve_binary_esplicito_non_valido(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="non esiste o non è eseguibile"):
        resolve_binary(tmp_path, tmp_path / "manca")
    not_exec = tmp_path / "pmtiles"
    not_exec.write_text("x")
    not_exec.chmod(0o644)
    with pytest.raises(DownloadError, match="non esiste o non è eseguibile"):
        resolve_binary(tmp_path, not_exec)


# --- Comando e controlli sul file ----------------------------------------------------------


def test_build_extract_command() -> None:
    command = build_extract_command(
        Path("/bin/pmtiles"), "https://build.protomaps.com/20261107.pmtiles",
        Path("/d/napoli.pmtiles.part"), PMTILES_BBOX, 15,
    )  # fmt: skip
    assert command == [
        "/bin/pmtiles",
        "extract",
        "https://build.protomaps.com/20261107.pmtiles",
        "/d/napoli.pmtiles.part",
        "--bbox=14.1,40.78,14.35,40.92",
        "--maxzoom=15",
    ]


def test_check_pmtiles_file(tmp_path: Path) -> None:
    good = tmp_path / "ok.pmtiles"
    good.write_bytes(b"PMTiles\x03dati")
    check_pmtiles_file(good)
    for name, content in (("vuoto", b""), ("html", b"<html>errore</html>")):
        bad = tmp_path / name
        bad.write_bytes(content)
        with pytest.raises(DownloadError):
            check_pmtiles_file(bad)
    with pytest.raises(DownloadError, match="senza produrre il file"):
        check_pmtiles_file(tmp_path / "manca")


# --- Flusso completo con il finto binario --------------------------------------------------


def _prepare(tmp_path: Path, binary: Path, **kwargs: Any) -> int:
    defaults = {
        "force": False,
        "pmtiles_bin": binary,
        "today": TODAY,
        "head": DaysHead(TODAY),
    }
    return prepare_pmtiles.prepare(tmp_path / "data", **{**defaults, **kwargs})


def test_prepare_flusso_completo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = make_fake_binary(tmp_path / "bin")
    args_file = tmp_path / "args.txt"
    monkeypatch.setenv("FAKE_ARGS_FILE", str(args_file))

    assert _prepare(tmp_path, binary) == 0

    tiles = tmp_path / "data" / "tiles"
    output = tiles / "napoli.pmtiles"
    assert output.read_bytes().startswith(b"PMTiles")
    assert sorted(p.name for p in tiles.iterdir()) == ["napoli.pmtiles", "napoli.pmtiles.meta.json"]
    # La CLI riceve esattamente il comando di 00 2.3 (output verso il file temporaneo).
    assert args_file.read_text().split() == [
        "extract",
        "https://build.protomaps.com/20261107.pmtiles",
        str(tiles / "napoli.pmtiles.part"),
        "--bbox=14.1,40.78,14.35,40.92",
        "--maxzoom=15",
    ]
    meta = json.loads((tiles / "napoli.pmtiles.meta.json").read_text())
    assert set(meta) == {"source_url", "fetched_at", "license", "sha256", "notes"}
    assert meta["source_url"] == "https://build.protomaps.com/20261107.pmtiles"
    assert meta["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "OpenStreetMap" in meta["license"]
    assert "2026-11-07" in meta["notes"] and "maxzoom 15" in meta["notes"]
    assert f"pmtiles {GO_PMTILES_VERSION}" in meta["notes"]


def test_prepare_usa_la_build_piu_recente_disponibile(tmp_path: Path) -> None:
    binary = make_fake_binary(tmp_path / "bin")
    assert _prepare(tmp_path, binary, head=DaysHead(date(2026, 11, 4))) == 0
    meta = json.loads((tmp_path / "data" / "tiles" / "napoli.pmtiles.meta.json").read_text())
    assert meta["source_url"].endswith("/20261104.pmtiles") and "2026-11-04" in meta["notes"]


def test_prepare_idempotente_e_force(tmp_path: Path) -> None:
    binary = make_fake_binary(tmp_path / "bin")
    assert _prepare(tmp_path, binary) == 0
    head = DaysHead(TODAY)
    assert _prepare(tmp_path, binary, head=head) == 0
    assert head.calls == []  # saltato: nemmeno un controllo di rete
    assert _prepare(tmp_path, binary, head=head, force=True) == 0
    assert head.calls == ["https://build.protomaps.com/20261107.pmtiles"]


def test_prepare_file_senza_meta_viene_rifatto(tmp_path: Path) -> None:
    binary = make_fake_binary(tmp_path / "bin")
    _prepare(tmp_path, binary)
    (tmp_path / "data" / "tiles" / "napoli.pmtiles.meta.json").unlink()
    head = DaysHead(TODAY)
    assert _prepare(tmp_path, binary, head=head) == 0
    assert head.calls


@pytest.mark.parametrize(
    "variable", ["FAKE_FAIL", "FAKE_GARBAGE", "FAKE_NO_OUTPUT", "FAKE_WRITE_THEN_FAIL"]
)
def test_prepare_estrazione_fallita_non_lascia_file_ne_rovina_quello_buono(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
) -> None:
    binary = make_fake_binary(tmp_path / "bin")
    assert _prepare(tmp_path, binary) == 0
    tiles = tmp_path / "data" / "tiles"
    before = {p.name: p.read_bytes() for p in tiles.iterdir()}

    monkeypatch.setenv(variable, "1")
    assert _prepare(tmp_path, binary, force=True) == 1
    assert "ERRORE" in capsys.readouterr().err
    assert {
        p.name: p.read_bytes() for p in tiles.iterdir()
    } == before  # nessun .part, file buono intatto


def test_prepare_primo_fallimento_non_crea_nulla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_FAIL", "1")
    assert _prepare(tmp_path, make_fake_binary(tmp_path / "bin")) == 1
    assert list((tmp_path / "data" / "tiles").iterdir()) == []


def test_prepare_nessuna_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    binary = make_fake_binary(tmp_path / "bin")
    assert _prepare(tmp_path, binary, head=DaysHead()) == 1
    assert "Nessuna build Protomaps trovata" in capsys.readouterr().err
    assert not (tmp_path / "data" / "tiles" / "napoli.pmtiles").exists()


def test_prepare_avvisa_se_la_cli_ha_una_versione_diversa(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    binary = make_fake_binary(tmp_path / "bin", version="0.0.1")
    assert _prepare(tmp_path, binary) == 0
    assert "diversa dalla versione fissata" in capsys.readouterr().out


def test_main_con_pmtiles_bin_e_rete_simulata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prepare_pmtiles, "head_ok", lambda url: url.endswith("/20260101.pmtiles"))
    monkeypatch.setattr(
        prepare_pmtiles, "now_rome", lambda: __import__("datetime").datetime(2026, 1, 3)
    )
    binary = make_fake_binary(tmp_path / "bin")
    code = prepare_pmtiles.main(["--data-dir", str(tmp_path / "d"), "--pmtiles-bin", str(binary)])
    assert code == 0
    assert (tmp_path / "d" / "tiles" / "napoli.pmtiles").is_file()


def test_prepare_file_parziale_con_intestazione_valida_ma_cli_fallita(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Caso reale: la rete cade a metà estrazione; il file ha già l'intestazione PMTiles ma è
    # troncato.
    # Solo il codice di uscita della CLI lo rivela: il file NON deve essere accettato.
    monkeypatch.setenv("FAKE_WRITE_THEN_FAIL", "1")
    assert _prepare(tmp_path, make_fake_binary(tmp_path / "bin")) == 1
    assert "codice 4" in capsys.readouterr().err
    assert list((tmp_path / "data" / "tiles").iterdir()) == []
