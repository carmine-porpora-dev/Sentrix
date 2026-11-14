import argparse
import hashlib
import json
import os
import socket
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from scripts.common import (
    DownloadError,
    add_data_dir_arg,
    atomic_write_text,
    default_data_dir,
    download_file,
    meta_path_for,
    now_rome,
    now_rome_iso,
    read_meta,
    sha256_of,
    write_meta,
)
from tests.support import FeedServer


def test_data_dir_da_ambiente(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert default_data_dir() == tmp_path


@pytest.mark.parametrize("value", ["", None])
def test_data_dir_vuota_o_assente_usa_la_radice_del_repository(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    # Vuota = non impostata (convenzione di .env.example).
    if value is None:
        monkeypatch.delenv("DATA_DIR", raising=False)
    else:
        monkeypatch.setenv("DATA_DIR", value)
    default = default_data_dir()
    assert default.name == "data"
    assert (default.parent / "backend" / "scripts").is_dir()  # la radice del repository


def test_sha256_e_percorso_del_meta(tmp_path: Path) -> None:
    artifact = tmp_path / "dati.bin"
    artifact.write_bytes(b"napoli" * 500_000)  # più di un blocco di lettura da 1 MiB
    assert sha256_of(artifact) == hashlib.sha256(b"napoli" * 500_000).hexdigest()
    assert meta_path_for(artifact) == tmp_path / "dati.bin.meta.json"


def test_write_meta_ha_i_cinque_campi_e_nessun_residuo(tmp_path: Path) -> None:
    artifact = tmp_path / "x.zip"
    artifact.write_bytes(b"abc")
    meta_file = write_meta(
        artifact,
        source_url="https://esempio.it/x.zip",
        fetched_at="2026-11-07T10:00:00+01:00",
        license="licenza di prova",
        notes="nota",
    )
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta == {
        "source_url": "https://esempio.it/x.zip",
        "fetched_at": "2026-11-07T10:00:00+01:00",
        "license": "licenza di prova",
        "sha256": hashlib.sha256(b"abc").hexdigest(),
        "notes": "nota",
    }
    assert not list(tmp_path.glob("*.part"))


def test_orario_di_roma() -> None:
    assert now_rome().utcoffset() in (timedelta(hours=1), timedelta(hours=2))
    assert now_rome_iso().endswith(("+01:00", "+02:00"))


# --- download_file (server locale: vedi conftest.py) ---------------------------------------


def test_download_segue_il_redirect_e_invia_lo_user_agent(
    server: FeedServer, tmp_path: Path
) -> None:
    target = tmp_path / "out.zip"
    headers = download_file(f"{server.url}/redirect", target)  # l'URL ANM reale risponde con un 301
    assert target.read_bytes() == server.zip_bytes
    assert headers["Content-Type"] == "application/zip"
    assert server.user_agents and all(ua.startswith("NapoliUrbanOps") for ua in server.user_agents)
    assert not list(tmp_path.glob("*.part"))


def test_download_404_messaggio_con_url_e_codice(server: FeedServer, tmp_path: Path) -> None:
    with pytest.raises(DownloadError) as info:
        download_file(f"{server.url}/manca", tmp_path / "out.zip")
    assert "HTTP 404" in str(info.value) and f"{server.url}/manca" in str(info.value)
    assert not (tmp_path / "out.zip").exists() and not list(tmp_path.glob("*.part"))


def test_download_server_irraggiungibile(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="Download fallito per http://127.0.0.1:9"):
        download_file("http://127.0.0.1:9/feed.zip", tmp_path / "out.zip")  # porta 9: chiusa


def test_download_non_sovrascrive_il_file_esistente_se_fallisce(
    server: FeedServer, tmp_path: Path
) -> None:
    target = tmp_path / "out.zip"
    target.write_bytes(b"buono")
    with pytest.raises(DownloadError):
        download_file(f"{server.url}/manca", target)
    assert target.read_bytes() == b"buono"


# --- Helper promossi in F0-REF ---------------------------------------------------------------


def test_atomic_write_text_crea_le_cartelle_e_sostituisce(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "file.txt"
    atomic_write_text(target, "uno")
    assert target.read_text(encoding="utf-8") == "uno"
    atomic_write_text(target, "due è più lungo ✓")
    assert target.read_text(encoding="utf-8") == "due è più lungo ✓"
    assert [p.name for p in target.parent.iterdir()] == ["file.txt"]  # nessun .part


def test_atomic_write_text_un_fallimento_non_tocca_il_file_e_non_lascia_residui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "file.txt"
    atomic_write_text(target, "buono")

    def boom(src: object, dst: object) -> None:
        raise OSError("disco pieno")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disco pieno"):
        atomic_write_text(target, "nuovo")
    assert target.read_text(encoding="utf-8") == "buono"
    assert [p.name for p in tmp_path.iterdir()] == ["file.txt"]


def test_read_meta(tmp_path: Path) -> None:
    artifact = tmp_path / "x.bin"
    assert read_meta(artifact) is None  # niente meta
    artifact.write_bytes(b"abc")
    write_meta(artifact, source_url="u", fetched_at="t", license="l", notes="n")
    meta = read_meta(artifact)
    assert meta is not None and meta["source_url"] == "u" and meta["sha256"] == sha256_of(artifact)
    meta_path_for(artifact).write_text("{non json")
    assert read_meta(artifact) is None  # meta corrotto: nessuna eccezione


def test_add_data_dir_arg() -> None:
    parser = argparse.ArgumentParser()
    add_data_dir_arg(parser)
    assert parser.parse_args(["--data-dir", "/x/y"]).data_dir == Path("/x/y")
    assert parser.parse_args([]).data_dir is None


def truncated_server(promised: int, sent: int) -> str:
    """Server grezzo che promette `promised` byte con Content-Length, ne manda `sent` e chiude."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve() -> None:
        connection, _ = listener.accept()
        connection.recv(4096)
        head = f"HTTP/1.1 200 OK\r\nContent-Length: {promised}\r\n\r\n".encode()
        connection.sendall(head + b"x" * sent)
        connection.close()
        listener.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{listener.getsockname()[1]}/f.zip"


def test_download_interrotto_a_meta_viene_rifiutato(tmp_path: Path) -> None:
    target = tmp_path / "out.zip"
    target.write_bytes(b"buono")  # un file precedente non deve essere toccato
    with pytest.raises(DownloadError, match=r"incompleto.*ricevuti 200 byte su 1000"):
        download_file(truncated_server(promised=1000, sent=200), target)
    assert target.read_bytes() == b"buono"
    assert [p.name for p in tmp_path.iterdir()] == ["out.zip"]  # nessun .part


def test_download_con_lunghezza_corretta_e_accettato(tmp_path: Path) -> None:
    target = tmp_path / "out.zip"
    download_file(truncated_server(promised=500, sent=500), target)
    assert target.stat().st_size == 500 and [p.name for p in tmp_path.iterdir()] == ["out.zip"]
