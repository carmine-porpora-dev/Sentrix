import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.data.tomtom import FLOW_PATH, TOMTOM_BASE_URL, contains_key, error_message, redact
from app.geo import haversine_m
from app.settings import ENV_FILE
from app.settings import load_env_file as load_env
from scripts.common import (
    USER_AGENT,
    add_data_dir_arg,
    atomic_write_text,
    default_data_dir,
    now_rome,
    now_rome_iso,
    write_meta,
)

REQUEST_TIMEOUT_S = 20
PROBE_GLOB = "probe_????????T??????.json"  # solo le sonde, non i loro .meta.json
MAX_BODY_BYTES = 1 << 20  # una risposta Flow Segment Data pesa pochi kB
KEY_VARIABLE = "TOMTOM_API_KEY"
LICENSE = (
    "Dati TomTom Traffic API: si applicano i termini d'uso TomTom. Conservazione dei dati su "
    "disco: consentita dal proprietario (Q2, spech.md 9, opzione A)."
)
# Risposte che non dicono nulla sulla copertura dei punti: chiave rifiutata, quota, errori server.
UNINFORMATIVE_STATUSES = frozenset({401, 403, 429})


@dataclass(frozen=True)
class ProbePoint:
    id: str
    label: str
    lat: float
    lon: float


# Coordinate PROPOSTA di 00 2.4 (correggibili).
PROBE_POINTS: tuple[ProbePoint, ...] = (
    ProbePoint("via_caracciolo", "Via Caracciolo", 40.8325, 14.2330),
    ProbePoint("tangenziale_vomero", "Tangenziale svincolo Vomero", 40.8530, 14.2160),
    ProbePoint("via_marina", "Via Marina", 40.8460, 14.2650),
)


class ProbeError(RuntimeError):
    """Errore dello script. Il messaggio non contiene mai la chiave."""


# --------------------------------------------------------------------------------------
# Chiave
# --------------------------------------------------------------------------------------


def get_key() -> str:
    raw = os.environ.get(KEY_VARIABLE, "").strip()
    if not raw:
        raise ProbeError(
            f"{KEY_VARIABLE} non impostata. Compilala nel file .env alla radice del progetto "
            "(o esportala nell'ambiente)."
        )
    if not re.fullmatch(r"[A-Za-z0-9]+", raw):
        # Non si ripete mai il valore. Caso tipico: incollato un URL o il segnaposto di .env.
        raise ProbeError(
            f"{KEY_VARIABLE} ha un formato non valido: deve essere una sola stringa di lettere e "
            "numeri (hai incollato un URL, uno spazio o il segnaposto?). Valore non mostrato."
        )
    return raw


def scrub(text: str, key: str) -> str:
    """Oscura la chiave e qualsiasi `key=...` in un testo destinato a output o file (la logica è
    quella dell'adattatore: una copia sola)."""
    return redact(text, key)


def scrub_json(value: Any, key: str) -> Any:
    if isinstance(value, str):
        return scrub(value, key)
    if isinstance(value, list):
        return [scrub_json(v, key) for v in value]
    if isinstance(value, dict):
        return {scrub(str(k), key): scrub_json(v, key) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------------------
# Richieste e riepilogo
# --------------------------------------------------------------------------------------


def summarize(raw: Any) -> dict[str, Any] | None:
    """Campi di 00 2.4 da una risposta Flow Segment Data; None se la forma non è quella attesa."""
    data = raw.get("flowSegmentData") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return None
    coordinates = (data.get("coordinates") or {}).get("coordinate") or []
    points = [
        (float(c["latitude"]), float(c["longitude"]))
        for c in coordinates
        if isinstance(c, dict) and "latitude" in c and "longitude" in c
    ]
    return {
        "currentSpeed": data.get("currentSpeed"),
        "freeFlowSpeed": data.get("freeFlowSpeed"),
        "confidence": data.get("confidence"),
        "frc": data.get("frc"),
        "geometry_points": len(points),
        "geometry_length_m": round(
            sum(
                float(haversine_m(p[0], p[1], q)) for p, q in zip(points, points[1:], strict=False)
            ),
            1,
        ),
    }


def _error_message(body: bytes, status: int, key: str) -> str:
    """Messaggio d'errore di TomTom (JSON `error`/`detailedError`), oscurato e accorciato."""
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        payload = None
    return error_message(status, payload, key)


def fetch_point(key: str, point: ProbePoint, *, base_url: str | None = None) -> dict[str, Any]:
    """Interroga un punto. Restituisce sempre un dizionario; non solleva mai e non include l'URL."""
    query = urllib.parse.urlencode({"point": f"{point.lat},{point.lon}", "key": key})
    request = urllib.request.Request(
        f"{base_url or TOMTOM_BASE_URL}{FLOW_PATH}?{query}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    result: dict[str, Any] = {
        "id": point.id, "label": point.label, "lat": point.lat, "lon": point.lon,
        "http_status": None, "ok": False, "error": None, "summary": None, "raw": None,
    }  # fmt: skip
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            result["http_status"] = response.status
            body = response.read(MAX_BODY_BYTES)
    except urllib.error.HTTPError as error:  # prima di URLError: ne è una sottoclasse
        result["http_status"] = error.code
        result["error"] = _error_message(error.read(MAX_BODY_BYTES), error.code, key)
        return result
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)  # mai l'URL: solo il tipo e il motivo
        result["error"] = scrub(f"{type(error).__name__}: {reason}", key)[:200]
        return result

    try:
        raw = scrub_json(json.loads(body.decode("utf-8")), key)
    except ValueError:
        result["error"] = "Risposta non JSON."
        return result
    result["raw"] = raw
    result["summary"] = summarize(raw)
    result["ok"] = result["summary"] is not None
    if not result["ok"]:
        result["error"] = "Risposta senza flowSegmentData."
    return result


# --------------------------------------------------------------------------------------
# Flusso principale
# --------------------------------------------------------------------------------------


def existing_probe(tomtom_dir: Path) -> Path | None:
    """L'ultima sonda salvata che aveva almeno un punto con dati, se esiste."""
    for path in sorted(tomtom_dir.glob(PROBE_GLOB), reverse=True):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("ok_points", 0) > 0:
                return path
        except (OSError, ValueError):
            continue
    return None


def is_informative(status: int | None) -> bool:
    """Una risposta HTTP che dice qualcosa sui punti (dati o assenza di copertura)."""
    return status is not None and status < 500 and status not in UNINFORMATIVE_STATUSES


def print_point(result: dict[str, Any]) -> None:
    label = f"{result['label']:<28}"
    if result["ok"]:
        s = result["summary"]
        print(
            f"  {label} OK  velocità {s['currentSpeed']} km/h (libera {s['freeFlowSpeed']}), "
            f"confidence {s['confidence']}, frc {s['frc']}, geometria {s['geometry_points']} punti "
            f"/ {s['geometry_length_m']} m"
        )
    else:
        print(f"  {label} NO  {result['error']}")


def run(data_dir: Path, key: str, *, force: bool = False, base_url: str | None = None) -> int:
    tomtom_dir = data_dir / "tomtom"
    previous = existing_probe(tomtom_dir)
    if previous is not None and not force:
        print(
            f"Esiste già {previous.name} con dati: salto (usa --force; consuma 3 richieste TomTom)."
        )
        return 0

    print(f"Interrogo TomTom Flow Segment Data su {len(PROBE_POINTS)} punti ...")
    results = [fetch_point(key, point, base_url=base_url) for point in PROBE_POINTS]
    for result in results:
        print_point(result)
    ok_points = sum(r["ok"] for r in results)

    if not any(is_informative(r["http_status"]) for r in results):
        statuses = sorted({r["http_status"] for r in results if r["http_status"] is not None})
        reason = f"codici HTTP {statuses}" if statuses else "nessuna risposta (rete assente?)"
        print(
            "ERRORE: nessuna risposta utile da TomTom (" + reason + "); sonda non salvata. "
            "401/403: chiave rifiutata o Traffic API non abilitata; 429: quota esaurita.",
            file=sys.stderr,
        )
        return 1

    fetched_at = now_rome_iso()
    endpoint = f"{base_url or TOMTOM_BASE_URL}{FLOW_PATH}"
    document = {
        "fetched_at": fetched_at,
        "endpoint": endpoint,
        "ok_points": ok_points,
        "points": results,
    }
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if contains_key(text, key):
        raise ProbeError("La sonda conterrebbe la chiave: NON salvata (errore interno).")
    path = tomtom_dir / f"probe_{now_rome():%Y%m%dT%H%M%S}.json"
    atomic_write_text(path, text)
    meta = write_meta(
        path,
        source_url=endpoint,  # senza query: nessuna chiave
        fetched_at=fetched_at,
        license=LICENSE,
        notes=f"Sonda su {len(results)} punti ({ok_points} con dati). Risposte senza chiave.",
    )
    print(f"Salvato {path}\n        {meta}")
    if ok_points == 0:
        print(
            "ATTENZIONE: nessun punto ha restituito dati (copertura nulla?). Da discutere al "
            "cancello F0-H3.",
            file=sys.stderr,
        )
        return 1
    if ok_points < len(results):
        print(f"Avviso: {len(results) - ok_points} punti su {len(results)} senza dati.")
    return 0


def main(argv: list[str] | None = None, *, env_file: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sonda TomTom Flow Segment Data su 3 punti.")
    parser.add_argument("--force", action="store_true", help="rifà la sonda (3 richieste TomTom)")
    add_data_dir_arg(parser)
    args = parser.parse_args(argv)
    try:
        load_env(env_file or ENV_FILE)
        key = get_key()
        return run(args.data_dir or default_data_dir(), key, force=args.force)
    except ProbeError as error:
        print(f"ERRORE: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
