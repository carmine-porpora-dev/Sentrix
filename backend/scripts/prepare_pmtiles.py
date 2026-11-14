import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from app.data.paths import DataPaths
from scripts.common import (
    DOWNLOAD_TIMEOUT_S,
    USER_AGENT,
    DownloadError,
    add_data_dir_arg,
    default_data_dir,
    download_file,
    meta_path_for,
    now_rome,
    now_rome_iso,
    sha256_of,
    write_meta,
)

BBox = tuple[float, float, float, float]  # west, south, east, north

# Area della base map e zoom massimo approvati (00 1).
PMTILES_BBOX: BBox = (14.10, 40.78, 14.35, 40.92)
MAXZOOM = 15
BUILD_URL = "https://build.protomaps.com/{date}.pmtiles"
BUILD_LOOKBACK_DAYS = 10  # oggi + 10 giorni precedenti (00 2.3)
EXTRACT_TIMEOUT_S = 1800  # tetto di sicurezza: l'estrazione normale dura pochi minuti
MAX_BINARY_BYTES = 200 << 20  # difesa: la CLI pesa ~40 MB
PMTILES_MAGIC = b"PMTiles"  # primi 7 byte di ogni file PMTiles
LICENSE = (
    "Dati OpenStreetMap, ODbL 1.0, (c) OpenStreetMap contributors (attribuzione obbligatoria). "
    "Build Protomaps (https://protomaps.com): licenza della build da verificare."
)

# go-pmtiles: versione fissata. Gli sha256 sono quelli calcolati da GitHub per gli asset della
# release v1.31.2 (campo `digest` dell'API), letti senza scaricare i binari. I nomi dei file
# non sono coerenti tra piattaforme (trattino/underscore): vanno scritti esattamente.
GO_PMTILES_VERSION = "1.31.2"
GO_PMTILES_RELEASE_URL = (
    f"https://github.com/protomaps/go-pmtiles/releases/download/v{GO_PMTILES_VERSION}"
)


@dataclass(frozen=True)
class Asset:
    filename: str
    sha256: str

    @property
    def url(self) -> str:
        return f"{GO_PMTILES_RELEASE_URL}/{self.filename}"


ASSETS: dict[tuple[str, str], Asset] = {
    ("Darwin", "arm64"): Asset(
        "go-pmtiles-1.31.2_Darwin_arm64.zip",
        "40528f7f616fcbf91207cd48c8fc023d213f6d86c0cbf1f748732803d1880f3d",
    ),
    ("Darwin", "x86_64"): Asset(
        "go-pmtiles-1.31.2_Darwin_x86_64.zip",
        "1f0dc02eee6c58312dd6c509faee1b5c32f0596568af1bf51f1b034e7a88a65b",
    ),
    ("Linux", "arm64"): Asset(
        "go-pmtiles_1.31.2_Linux_arm64.tar.gz",
        "f8bd47e7ea866863489cad588fbaf2f31f42e5821f7a03f009b3769f05801cb1",
    ),
    ("Linux", "x86_64"): Asset(
        "go-pmtiles_1.31.2_Linux_x86_64.tar.gz",
        "3ed7dbf4ec2e6dfe5e25b6f70d1ffc932729f93c86db353bf514dd71010a312f",
    ),
}
_MACHINE_ALIASES = {"aarch64": "arm64", "amd64": "x86_64", "AMD64": "x86_64"}


# --------------------------------------------------------------------------------------
# La CLI go-pmtiles
# --------------------------------------------------------------------------------------


def select_asset(system: str | None = None, machine: str | None = None) -> Asset:
    system = system or platform.system()
    machine = machine or platform.machine()
    machine = _MACHINE_ALIASES.get(machine, machine)
    asset = ASSETS.get((system, machine))
    if asset is None:
        raise DownloadError(
            f"Nessuna build go-pmtiles fissata per {system}/{machine}. Installa la CLI a mano "
            "(https://github.com/protomaps/go-pmtiles/releases) e passa il percorso con "
            "--pmtiles-bin."
        )
    return asset


def _extract_member(archive: Path, destination: Path) -> None:
    """Copia in `destination` il solo file `pmtiles` dell'archivio (zip o tar.gz)."""
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            members = [
                m for m in zf.infolist() if not m.is_dir() and Path(m.filename).name == "pmtiles"
            ]
            if len(members) != 1:
                raise DownloadError(
                    f"{archive.name}: atteso un solo file 'pmtiles', trovati {len(members)}."
                )
            if members[0].file_size > MAX_BINARY_BYTES:
                raise DownloadError(f"{archive.name}: il file 'pmtiles' è troppo grande.")
            with zf.open(members[0]) as source, destination.open("wb") as out:
                shutil.copyfileobj(source, out)
        return
    with tarfile.open(archive) as tf:
        tar_members = [m for m in tf.getmembers() if m.isfile() and Path(m.name).name == "pmtiles"]
        if len(tar_members) != 1:
            raise DownloadError(
                f"{archive.name}: atteso un solo file 'pmtiles', trovati {len(tar_members)}."
            )
        if tar_members[0].size > MAX_BINARY_BYTES:
            raise DownloadError(f"{archive.name}: il file 'pmtiles' è troppo grande.")
        source_file = tf.extractfile(tar_members[0])
        if source_file is None:
            raise DownloadError(f"{archive.name}: 'pmtiles' non leggibile.")
        with source_file, destination.open("wb") as out:
            shutil.copyfileobj(source_file, out)


def install_pinned_binary(
    tools_dir: Path,
    asset: Asset,
    *,
    download: Callable[[str, Path], dict[str, str]] | None = None,
) -> Path:
    """Scarica l'asset fissato, ne verifica lo sha256 PRIMA di estrarlo e installa `pmtiles`."""
    fetch = download or download_file
    tools_dir.mkdir(parents=True, exist_ok=True)
    archive = tools_dir / asset.filename
    print(f"Scarico go-pmtiles {GO_PMTILES_VERSION} da {asset.url} ...")
    try:
        fetch(asset.url, archive)
        actual = sha256_of(archive)
        if actual != asset.sha256:
            raise DownloadError(
                f"{asset.filename}: sha256 diverso da quello fissato (atteso {asset.sha256}, "
                f"ottenuto {actual}). Archivio rifiutato, non estratto né eseguito."
            )
        target = tools_dir / "pmtiles"
        temp = tools_dir / "pmtiles.part"
        try:
            _extract_member(archive, temp)
            temp.chmod(0o755)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    finally:
        archive.unlink(missing_ok=True)
    return target


def binary_version(binary: Path) -> str | None:
    """Prima riga di `pmtiles version`, oppure None se non si riesce a leggerla."""
    try:
        result = subprocess.run(
            [str(binary), "version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = result.stdout.strip().splitlines()
    return lines[0].strip() if result.returncode == 0 and lines else None


def resolve_binary(
    data_dir: Path,
    explicit: Path | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    install: Callable[[Path, Asset], Path] | None = None,
) -> Path:
    """--pmtiles-bin, poi PATH, poi DATA_DIR/tools/pmtiles, poi download della versione fissata."""
    if explicit is not None:
        if not (explicit.is_file() and os.access(explicit, os.X_OK)):
            raise DownloadError(f"--pmtiles-bin: {explicit} non esiste o non è eseguibile.")
        return explicit
    on_path = which("pmtiles")
    if on_path:
        return Path(on_path)
    local = data_dir / "tools" / "pmtiles"
    if local.is_file() and os.access(local, os.X_OK):
        return local
    return (install or install_pinned_binary)(data_dir / "tools", select_asset())


# --------------------------------------------------------------------------------------
# Build Protomaps
# --------------------------------------------------------------------------------------


def candidate_dates(today: date, lookback: int = BUILD_LOOKBACK_DAYS) -> list[date]:
    """Oggi e i `lookback` giorni precedenti, dal più recente."""
    return [today - timedelta(days=offset) for offset in range(lookback + 1)]


def head_ok(url: str) -> bool:
    """True se l'URL esiste (200). 403/404 = build non disponibile. Altro = errore."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S):
            return True
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):
            return False
        raise DownloadError(f"Controllo build fallito: HTTP {error.code} per {url}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DownloadError(f"Controllo build fallito per {url}: {error}") from error


def find_latest_build(
    today: date, *, head: Callable[[str], bool] | None = None
) -> tuple[date, str]:
    check = head or head_ok
    dates = candidate_dates(today)
    for day in dates:
        url = BUILD_URL.format(date=f"{day:%Y%m%d}")
        if check(url):
            return day, url
    raise DownloadError(
        f"Nessuna build Protomaps trovata tra {dates[-1]:%Y-%m-%d} e {dates[0]:%Y-%m-%d} "
        f"({BUILD_URL.format(date='AAAAMMGG')}). Riprova più tardi."
    )


# --------------------------------------------------------------------------------------
# Estrazione
# --------------------------------------------------------------------------------------


def build_extract_command(
    binary: Path, url: str, output: Path, bbox: BBox, maxzoom: int
) -> list[str]:
    west, south, east, north = bbox
    return [
        str(binary),
        "extract",
        url,
        str(output),
        f"--bbox={west:g},{south:g},{east:g},{north:g}",
        f"--maxzoom={maxzoom}",
    ]


def run_extract(command: list[str]) -> None:
    """Lancia la CLI lasciandole stdout/stderr (barra di avanzamento). Nessuna shell."""
    try:
        result = subprocess.run(command, timeout=EXTRACT_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as error:
        raise DownloadError(f"pmtiles extract oltre il tetto di {EXTRACT_TIMEOUT_S} s.") from error
    except OSError as error:
        raise DownloadError(f"Impossibile eseguire la CLI pmtiles: {error}") from error
    if result.returncode != 0:
        raise DownloadError(f"pmtiles extract terminato con codice {result.returncode}.")


def check_pmtiles_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise DownloadError("L'estrazione è terminata senza produrre il file di output.")
    with path.open("rb") as handle:
        if handle.read(len(PMTILES_MAGIC)) != PMTILES_MAGIC:
            raise DownloadError("Il file prodotto non ha l'intestazione PMTiles: scartato.")


def prepare(
    data_dir: Path,
    *,
    force: bool,
    pmtiles_bin: Path | None = None,
    today: date | None = None,
    head: Callable[[str], bool] | None = None,
) -> int:
    output = DataPaths(data_dir).pmtiles
    if not force and output.is_file() and meta_path_for(output).is_file():
        print(f"{output} esiste già: salto (usa --force per rifare l'estrazione).")
        return 0

    part = output.with_name(output.name + ".part")
    try:
        build_day, url = find_latest_build(today or now_rome().date(), head=head)
        print(f"Build Protomaps più recente: {build_day:%Y-%m-%d} ({url})")
        binary = resolve_binary(data_dir, pmtiles_bin)
        version = binary_version(binary)
        if version is None:
            print("Avviso: versione della CLI pmtiles non rilevata.")
        elif GO_PMTILES_VERSION not in version:
            print(
                f"Avviso: CLI pmtiles '{version}' diversa dalla versione fissata "
                f"{GO_PMTILES_VERSION}."
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        part.unlink(missing_ok=True)
        run_extract(build_extract_command(binary, url, part, PMTILES_BBOX, MAXZOOM))
        check_pmtiles_file(part)
    except DownloadError as error:
        part.unlink(missing_ok=True)  # un eventuale file buono già presente resta intatto
        print(f"ERRORE: {error}", file=sys.stderr)
        return 1

    os.replace(part, output)
    size = output.stat().st_size
    meta = write_meta(
        output,
        source_url=url,
        fetched_at=now_rome_iso(),
        license=LICENSE,
        notes=(
            f"Build Protomaps del {build_day:%Y-%m-%d}; bbox(west,south,east,north)="
            f"{PMTILES_BBOX}; maxzoom {MAXZOOM}; {size} byte; CLI: "
            f"{version or 'versione non rilevata'}."
        ),
    )
    print(f"Salvato {output} ({size / 1e6:.1f} MB)\n        {meta}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estrae la base map PMTiles di Napoli.")
    parser.add_argument("--force", action="store_true", help="rifà l'estrazione anche se esiste")
    add_data_dir_arg(parser)
    parser.add_argument(
        "--pmtiles-bin", type=Path, help="percorso della CLI pmtiles già installata"
    )
    args = parser.parse_args(argv)
    return prepare(
        args.data_dir or default_data_dir(), force=args.force, pmtiles_bin=args.pmtiles_bin
    )


if __name__ == "__main__":
    raise SystemExit(main())
