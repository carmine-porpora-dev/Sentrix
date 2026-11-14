import argparse
import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.clock import now_rome
from app.data.paths import default_data_dir as default_data_dir  # noqa: PLC0414 (ri-esportata)

USER_AGENT = "NapoliUrbanOps-data-script/0.1"  # generico: nessun dato personale
DOWNLOAD_TIMEOUT_S = 120


class DownloadError(RuntimeError):
    """Download non riuscito (rete, HTTP) o contenuto scaricato non utilizzabile."""


def now_rome_iso() -> str:
    return now_rome().isoformat(timespec="seconds")


def add_data_dir_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir", type=Path, help="default: $DATA_DIR oppure <radice del repository>/data"
    )


def atomic_write_text(path: Path, text: str) -> None:
    """Scrive `text` in `path` passando da un file temporaneo: chi legge non vede mai metà file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        # Dopo il replace non c'è più nulla; se qualcosa fallisce, niente residui.
        temp.unlink(missing_ok=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def meta_path_for(artifact: Path) -> Path:
    return artifact.with_name(artifact.name + ".meta.json")


def write_meta(
    artifact: Path, *, source_url: str, fetched_at: str, license: str, notes: str
) -> Path:
    """Scrive `<artefatto>.meta.json` con i cinque campi di 00-data-sources.md (atomico)."""
    meta = {
        "source_url": source_url,
        "fetched_at": fetched_at,
        "license": license,
        "sha256": sha256_of(artifact),
        "notes": notes,
    }
    target = meta_path_for(artifact)
    atomic_write_text(target, json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return target


def read_meta(artifact: Path) -> dict[str, Any] | None:
    """Il `.meta.json` di un artefatto, o None se manca o non è leggibile."""
    path = meta_path_for(artifact)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def download_file(url: str, target: Path) -> dict[str, str]:
    """Scarica `url` in `target` (via file temporaneo). Restituisce alcune intestazioni HTTP.

    Segue i redirect. Se il server dichiara `Content-Length` e i byte ricevuti sono di meno
    (connessione interrotta a metà) il download è rifiutato. Su qualunque errore non lascia file
    parziali e solleva DownloadError con URL e codice; un `target` già presente resta intatto.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    temp = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            with temp.open("wb") as out:
                shutil.copyfileobj(response, out)
            declared = response.headers.get("Content-Length", "")
            received = temp.stat().st_size
            if declared.isdigit() and int(declared) != received:
                raise DownloadError(
                    f"Download incompleto da {url}: ricevuti {received} byte su {declared}."
                )
            headers = {
                k: v for k in ("Content-Type", "Last-Modified") if (v := response.headers.get(k))
            }
        os.replace(temp, target)
    except urllib.error.HTTPError as error:  # prima di URLError: ne è una sottoclasse
        raise DownloadError(f"Download fallito: HTTP {error.code} per {url}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DownloadError(f"Download fallito per {url}: {error}") from error
    finally:
        # Dopo il replace non c'è più nulla; se qualcosa fallisce, niente residui.
        temp.unlink(missing_ok=True)
    return headers
