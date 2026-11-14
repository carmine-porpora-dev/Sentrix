import json
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import tomtom_probe
from scripts.tomtom_probe import (
    PROBE_POINTS,
    ProbeError,
    existing_probe,
    fetch_point,
    get_key,
    load_env,
    scrub,
    scrub_json,
    summarize,
)

FAKE_KEY = "FAKEKEY0123456789abcdefFAKEKEY01"  # finta: "fake" nel valore, vedi .gitleaks.toml
POINT_KEYS = [f"{p.lat},{p.lon}" for p in PROBE_POINTS]

GOOD = {
    "flowSegmentData": {
        "frc": "FRC3",
        "currentSpeed": 23,
        "freeFlowSpeed": 41,
        "currentTravelTime": 15,
        "freeFlowTravelTime": 9,
        "confidence": 0.97,
        "roadClosure": False,
        "coordinates": {
            "coordinate": [
                {"latitude": 40.8320, "longitude": 14.2350},
                {"latitude": 40.8330, "longitude": 14.2352},
            ]
        },
        "@version": "4",
    }
}
NO_ROAD = {
    "error": "Point too far from nearest existing road segment",
    "detailedError": {"code": "INVALID_REQUEST", "message": "Point too far from nearest road"},
}


@dataclass
class FakeTomTom:
    url: str = ""
    requests: list[dict[str, str]] = field(default_factory=list)
    default: tuple[int, bytes] = (200, json.dumps(GOOD).encode())
    by_point: dict[str, tuple[int, bytes]] = field(default_factory=dict)

    def reply(self, status: int, payload: object) -> tuple[int, bytes]:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return status, body


@pytest.fixture
def tomtom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeTomTom]:
    state = FakeTomTom()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (nome imposto da BaseHTTPRequestHandler)
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            state.requests.append({"path": parsed.path, **query})
            status, body = state.by_point.get(query.get("point", ""), state.default)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # silenzia il log
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{httpd.server_address[1]}"
    threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True).start()
    # Rete di sicurezza: nessun test può leggere il vero .env o parlare con TomTom.
    monkeypatch.setattr(tomtom_probe, "TOMTOM_BASE_URL", state.url)
    monkeypatch.setattr(tomtom_probe, "ENV_FILE", tmp_path / "nessun.env")
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    yield state
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Orologio che avanza di un secondo a ogni lettura: nomi di file sempre distinti."""
    current = {"t": datetime(2026, 11, 7, 17, 0, 0, tzinfo=tomtom_probe.now_rome().tzinfo)}

    def fake_now() -> datetime:
        current["t"] += timedelta(seconds=1)
        return current["t"]

    monkeypatch.setattr(tomtom_probe, "now_rome", fake_now)


def assert_no_key(*texts: str) -> None:
    for text in texts:
        assert FAKE_KEY not in text, "la chiave è uscita in un testo"
        assert not re.search(r"(?i)\bkey=(?!\*\*\*)", text), "frammento 'key=' non oscurato"


def saved_probes(data_dir: Path) -> list[Path]:
    tomtom_dir = data_dir / "tomtom"
    return sorted(tomtom_dir.glob(tomtom_probe.PROBE_GLOB)) if tomtom_dir.exists() else []


# --- Chiave ----------------------------------------------------------------------------------


def test_get_key_valida(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOMTOM_API_KEY", f"  {FAKE_KEY}  ")
    assert get_key() == FAKE_KEY


@pytest.mark.parametrize("value", [None, "", "   "])
def test_get_key_mancante(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is not None:
        monkeypatch.setenv("TOMTOM_API_KEY", value)
    with pytest.raises(ProbeError, match=r"non impostata.*\.env"):
        get_key()


@pytest.mark.parametrize(
    "value",
    [
        "INCOLLA_QUI_LA_CHIAVE_TOMTOM",  # il segnaposto di .env
        f"https://api.tomtom.com/x?key={FAKE_KEY}&point=1,2",  # incollato un URL
        f"{FAKE_KEY} {FAKE_KEY}",
        f"'{FAKE_KEY}'",
    ],
)
def test_get_key_formato_non_valido_senza_ripetere_il_valore(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("TOMTOM_API_KEY", value)
    with pytest.raises(ProbeError) as info:
        get_key()
    message = str(info.value)
    assert "formato non valido" in message and "Valore non mostrato" in message
    assert value not in message and FAKE_KEY not in message


def test_load_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(f"TOMTOM_API_KEY={FAKE_KEY}\n")
    load_env(env)
    assert get_key() == FAKE_KEY
    # Una variabile già impostata nell'ambiente non viene sovrascritta dal file.
    monkeypatch.setenv("TOMTOM_API_KEY", "fakeAmbiente123")
    load_env(env)
    assert get_key() == "fakeAmbiente123"
    load_env(tmp_path / "manca.env")  # file assente: nessun errore


def test_load_env_valore_vuoto_equivale_a_non_impostata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("TOMTOM_API_KEY=\n")
    load_env(env)
    with pytest.raises(ProbeError, match="non impostata"):
        get_key()


# --- Oscuramento -----------------------------------------------------------------------------


def test_scrub() -> None:
    assert FAKE_KEY not in scrub(f"errore con {FAKE_KEY} dentro", FAKE_KEY)
    assert scrub("GET /x?point=1,2&key=abc123&z=1", FAKE_KEY) == "GET /x?point=1,2&key=***&z=1"
    assert scrub("KEY=abc123", FAKE_KEY) == "key=***"  # anche in maiuscolo
    assert scrub("nessuna chiave qui", FAKE_KEY) == "nessuna chiave qui"


def test_scrub_json_ricorsivo() -> None:
    cleaned = scrub_json(
        {"a": [f"x {FAKE_KEY}", {"b": f"key={FAKE_KEY}", f"chiave {FAKE_KEY}": 1}], "n": 5},
        FAKE_KEY,
    )
    assert_no_key(json.dumps(cleaned))
    assert cleaned["n"] == 5


# --- Riepilogo -------------------------------------------------------------------------------


def test_summarize() -> None:
    summary = summarize(GOOD)
    assert summary == {
        "currentSpeed": 23,
        "freeFlowSpeed": 41,
        "confidence": 0.97,
        "frc": "FRC3",
        "geometry_points": 2,
        "geometry_length_m": 112.5,  # 112,46 m con una formula indipendente
    }


@pytest.mark.parametrize("raw", [None, [], {}, {"flowSegmentData": "x"}, NO_ROAD])
def test_summarize_forma_inattesa(raw: object) -> None:
    assert summarize(raw) is None


def test_summarize_senza_coordinate() -> None:
    summary = summarize({"flowSegmentData": {"currentSpeed": 10}})
    assert summary is not None
    assert (summary["geometry_points"], summary["geometry_length_m"]) == (0, 0.0)
    assert summary["freeFlowSpeed"] is None


# --- Richieste -------------------------------------------------------------------------------


def test_fetch_point_invia_chiave_e_punto_ma_non_li_restituisce(tomtom: FakeTomTom) -> None:
    result = fetch_point(FAKE_KEY, PROBE_POINTS[0])
    assert result["ok"] and result["http_status"] == 200 and result["error"] is None
    assert tomtom.requests == [
        {
            "path": "/traffic/services/4/flowSegmentData/absolute/10/json",
            "point": "40.8325,14.233",
            "key": FAKE_KEY,
        }
    ]
    assert_no_key(json.dumps(result))


# --- Flusso completo ---------------------------------------------------------------------------


def test_run_successo(
    tomtom: FakeTomTom, tmp_path: Path, clock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 0
    out = capsys.readouterr()
    assert_no_key(out.out, out.err)

    assert [r["point"] for r in tomtom.requests] == POINT_KEYS  # i 3 punti di 00 2.4, nell'ordine
    assert all(r["key"] == FAKE_KEY for r in tomtom.requests)

    (probe,) = saved_probes(tmp_path)
    assert re.fullmatch(r"probe_\d{8}T\d{6}\.json", probe.name)
    text = probe.read_text(encoding="utf-8")
    assert_no_key(text)
    document = json.loads(text)
    assert document["ok_points"] == 3
    assert (
        document["endpoint"] == f"{tomtom.url}/traffic/services/4/flowSegmentData/absolute/10/json"
    )
    assert [p["id"] for p in document["points"]] == [p.id for p in PROBE_POINTS]
    assert all(
        p["ok"] and p["summary"]["currentSpeed"] == 23 and p["raw"] == GOOD
        for p in document["points"]
    )

    meta = json.loads(Path(f"{probe}.meta.json").read_text(encoding="utf-8"))
    assert set(meta) == {"source_url", "fetched_at", "license", "sha256", "notes"}
    assert "key" not in meta["source_url"] and "?" not in meta["source_url"]
    assert "Q2" in meta["license"]
    assert_no_key(json.dumps(meta))
    assert "OK" in out.out and "geometria 2 punti / 112.5 m" in out.out


def test_run_un_punto_senza_copertura(
    tomtom: FakeTomTom, tmp_path: Path, clock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    tomtom.by_point[POINT_KEYS[1]] = tomtom.reply(400, NO_ROAD)
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 0  # 2 su 3 hanno dati
    out = capsys.readouterr()
    assert_no_key(out.out, out.err)
    assert "1 punti su 3 senza dati" in out.out
    (probe,) = saved_probes(tmp_path)
    points = json.loads(probe.read_text(encoding="utf-8"))["points"]
    assert [p["ok"] for p in points] == [True, False, True]
    assert points[1]["http_status"] == 400
    assert points[1]["error"] == "HTTP 400: Point too far from nearest road"
    assert points[1]["summary"] is None


def test_run_copertura_nulla_salva_la_prova_ma_esce_con_1(
    tomtom: FakeTomTom, tmp_path: Path, clock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    tomtom.default = tomtom.reply(400, NO_ROAD)
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 1
    err = capsys.readouterr().err
    assert "copertura nulla" in err
    assert len(saved_probes(tmp_path)) == 1  # la prova che manca la copertura va conservata
    assert json.loads(saved_probes(tmp_path)[0].read_text(encoding="utf-8"))["ok_points"] == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_run_chiave_rifiutata_quota_o_server_non_salva_nulla(
    tomtom: FakeTomTom,
    tmp_path: Path,
    status: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tomtom.default = tomtom.reply(
        status, {"error": f"Rifiutata, chiave {FAKE_KEY} non valida: key={FAKE_KEY}"}
    )
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 1
    out = capsys.readouterr()
    assert_no_key(out.out, out.err)
    assert "nessuna risposta utile" in out.err and "sonda non salvata" in out.err
    assert saved_probes(tmp_path) == [] and not (tmp_path / "tomtom").exists()


def test_run_rete_assente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Porta chiusa su localhost: l'errore di connessione non deve mostrare l'URL (che ha la chiave).
    assert tomtom_probe.run(tmp_path, FAKE_KEY, base_url="http://127.0.0.1:9") == 1
    out = capsys.readouterr()
    assert_no_key(out.out, out.err)
    assert "rete assente" in out.err and saved_probes(tmp_path) == []
    # Il messaggio dice il motivo in chiaro, non l'URL: "URLError: [Errno 61] Connection refused".
    assert re.search(r"URLError: \[Errno \d+\] Connection refused", out.out)


def test_run_risposta_200_non_json(
    tomtom: FakeTomTom, tmp_path: Path, clock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    tomtom.default = tomtom.reply(200, b"<html>manutenzione</html>")
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 1
    assert "Risposta non JSON" in capsys.readouterr().out
    assert json.loads(saved_probes(tmp_path)[0].read_text(encoding="utf-8"))["ok_points"] == 0


def test_run_il_server_che_ripete_la_chiave_non_la_fa_finire_su_disco(
    tomtom: FakeTomTom, tmp_path: Path, clock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    leaky = json.loads(json.dumps(GOOD))
    leaky["flowSegmentData"]["note"] = f"richiesta con key={FAKE_KEY}"
    leaky[f"eco_{FAKE_KEY}"] = FAKE_KEY
    tomtom.default = tomtom.reply(200, leaky)
    tomtom.by_point[POINT_KEYS[1]] = tomtom.reply(400, {"error": f"punto errato (key={FAKE_KEY})"})
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 0
    out = capsys.readouterr()
    assert_no_key(out.out, out.err, saved_probes(tmp_path)[0].read_text(encoding="utf-8"))
    assert "***" in saved_probes(tmp_path)[0].read_text(encoding="utf-8")


def test_run_ultima_difesa_se_l_oscuramento_fallisse(
    tomtom: FakeTomTom, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaky = json.loads(json.dumps(GOOD))
    leaky["flowSegmentData"]["note"] = FAKE_KEY
    tomtom.default = tomtom.reply(200, leaky)
    monkeypatch.setattr(tomtom_probe, "scrub_json", lambda value, key: value)  # oscuramento rotto
    with pytest.raises(ProbeError, match="NON salvata"):
        tomtom_probe.run(tmp_path, FAKE_KEY)
    assert saved_probes(tmp_path) == []


def test_run_idempotente_e_force(
    tomtom: FakeTomTom, tmp_path: Path, clock: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 0
    assert len(tomtom.requests) == 3
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 0
    assert len(tomtom.requests) == 3  # nessuna richiesta: la quota non si spreca
    assert "salto" in capsys.readouterr().out
    assert tomtom_probe.run(tmp_path, FAKE_KEY, force=True) == 0
    assert len(tomtom.requests) == 6 and len(saved_probes(tmp_path)) == 2


def test_una_sonda_senza_dati_non_blocca_la_successiva(
    tomtom: FakeTomTom, tmp_path: Path, clock: None
) -> None:
    tomtom.default = tomtom.reply(400, NO_ROAD)
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 1
    assert existing_probe(tmp_path / "tomtom") is None
    tomtom.default = tomtom.reply(200, GOOD)
    assert tomtom_probe.run(tmp_path, FAKE_KEY) == 0  # non salta: la prima non aveva dati
    assert existing_probe(tmp_path / "tomtom") is not None


def test_existing_probe_ignora_file_corrotti(tmp_path: Path) -> None:
    tomtom_dir = tmp_path / "tomtom"
    tomtom_dir.mkdir()
    (tomtom_dir / "probe_20260101T000000.json").write_text("{non json")
    assert existing_probe(tomtom_dir) is None


# --- CLI -------------------------------------------------------------------------------------


def test_main_senza_chiave_esce_con_1_senza_traceback(
    tomtom: FakeTomTom, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tomtom_probe.main(["--data-dir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ERRORE: TOMTOM_API_KEY non impostata") and "Traceback" not in err
    assert tomtom.requests == []


def test_main_con_chiave_nel_file_env(
    tomtom: FakeTomTom,
    tmp_path: Path,
    clock: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = tmp_path / "prova.env"
    env.write_text(f"TOMTOM_API_KEY={FAKE_KEY}\n")
    monkeypatch.setattr(tomtom_probe, "ENV_FILE", env)
    assert tomtom_probe.main(["--data-dir", str(tmp_path / "d")]) == 0
    out = capsys.readouterr()
    assert_no_key(out.out, out.err)
    assert all(r["key"] == FAKE_KEY for r in tomtom.requests) and len(tomtom.requests) == 3
    assert len(saved_probes(tmp_path / "d")) == 1
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)  # (dotenv l'ha scritta nell'ambiente)


def test_main_chiave_malformata_non_viene_ripetuta(
    tomtom: FakeTomTom,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pasted = f"https://api.tomtom.com/traffic/x?key={FAKE_KEY}"
    monkeypatch.setenv("TOMTOM_API_KEY", pasted)
    assert tomtom_probe.main(["--data-dir", str(tmp_path)]) == 1
    out = capsys.readouterr()
    assert_no_key(out.out, out.err)
    assert pasted not in out.err and tomtom.requests == []


def test_i_tre_punti_sono_quelli_della_spec() -> None:
    # 00-data-sources.md 2.4 (coordinate PROPOSTA): scritte qui a mano, non derivate dal codice.
    assert [(p.label, p.lat, p.lon) for p in PROBE_POINTS] == [
        ("Via Caracciolo", 40.8325, 14.2330),
        ("Tangenziale svincolo Vomero", 40.8530, 14.2160),
        ("Via Marina", 40.8460, 14.2650),
    ]
