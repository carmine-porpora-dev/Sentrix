import argparse
import math
import os
import re
import shutil
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.data.gtfs import read_table, services_by_date, to_seconds
from app.data.paths import FEED_NAME, DataPaths
from app.geo import haversine_m
from scripts.common import (
    DownloadError,
    add_data_dir_arg,
    default_data_dir,
    download_file,
    meta_path_for,
    now_rome,
    now_rome_iso,
    write_meta,
)

DEFAULT_URL = "https://www.anm.it/google/google-transit.zip"  # candidato di 00 2.2
# Difesa da zip bomb: il feed reale pesa ~60 MB da decompresso.
MAX_UNZIPPED_BYTES = 1 << 30

LICENSE = "Da verificare sul feed (Transitland indica IODL 2.0, spech.md 6.5)"

REQUIRED_FILES = ("agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt")
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "stops.txt": ("stop_id", "stop_name", "stop_lat", "stop_lon"),
    "routes.txt": ("route_id", "route_type"),
    "trips.txt": ("route_id", "service_id", "trip_id"),
    "stop_times.txt": ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
}

# Rotonda Diaz e raggio di 00 2.2.
ROTONDA_DIAZ = (40.8320, 14.2350)
NEAR_RADIUS_M = 800
# Fasce orarie di 00 2.2, in minuti dalla mezzanotte. Si conta per ORA DI PARTENZA dal primo
# capolinea, estremo inferiore incluso e superiore escluso; le due direzioni contano entrambe.
EVENING_WINDOW = (21 * 60, 23 * 60)
AFTERNOON_WINDOW = (12 * 60, 18 * 60)
FRIDAY, SATURDAY = 4, 5  # date.weekday()


@dataclass(frozen=True)
class LineTarget:
    """Una linea cercata per nome E tipo (così 'ASCENSORE CHIAIA', un bus, non è la funicolare)."""

    name: str
    route_types: frozenset[str]
    pattern: re.Pattern[str]


def _target(name: str, route_type: str, pattern: str) -> LineTarget:
    return LineTarget(name, frozenset({route_type}), re.compile(pattern, re.IGNORECASE))


# route_type 1 = metro, 7 = funicolare (00 2.2). Il testo cercato è "<short_name> <long_name>".
LINES_OF_INTEREST: tuple[LineTarget, ...] = (
    _target("Linea 1", "1", r"\bL\s*1\b|\bLINEA\s+(?:L\s*)?1\b"),
    _target("Linea 6", "1", r"\bL\s*6\b|\bLINEA\s+(?:L\s*)?6\b"),
    _target("Funicolare di Chiaia", "7", r"CHIAIA"),
    _target("Funicolare Centrale", "7", r"CENTRALE"),
    _target("Funicolare di Montesanto", "7", r"MONTESANTO"),
    _target("Funicolare di Mergellina", "7", r"MERGELLINA"),
)


class FeedError(DownloadError):
    """Zip o contenuto del feed non utilizzabile."""


# --------------------------------------------------------------------------------------
# Download ed estrazione
# --------------------------------------------------------------------------------------


def check_zip(path: Path) -> None:
    """Rifiuta zip corrotti, troppo grandi decompressi o con percorsi che escono dalla cartella."""
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise FeedError(f"Zip corrotto: il file '{bad}' non supera il controllo CRC.")
            members = archive.infolist()
            if sum(m.file_size for m in members) > MAX_UNZIPPED_BYTES:
                raise FeedError(f"Zip rifiutato: decompresso supera {MAX_UNZIPPED_BYTES} byte.")
            for member in members:
                parts = Path(member.filename).parts
                if Path(member.filename).is_absolute() or ".." in parts:
                    raise FeedError(f"Zip rifiutato: percorso non sicuro '{member.filename}'.")
    except zipfile.BadZipFile as error:
        raise FeedError(f"Zip corrotto o non valido: {path.name} ({error}).") from error


def extract_feed(zip_path: Path, target: Path) -> None:
    """Estrae in una cartella temporanea e poi sostituisce `target`: nessun file vecchio residuo."""
    temp = target.with_name(target.name + ".part")
    shutil.rmtree(temp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(temp)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(temp, target)


# --------------------------------------------------------------------------------------
# Lettura e utilità
# --------------------------------------------------------------------------------------


def _text(value: object) -> str:
    """Testo di una cella; i campi vuoti (NaN) diventano stringa vuota, non 'nan'."""
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _opt(value: object) -> str | None:
    return _text(value) or None


def _column(table: pd.DataFrame, name: str) -> pd.Series:
    """La colonna `name`, o una colonna tutta vuota se il file non la ha (colonne opzionali)."""
    return (
        table[name]
        if name in table.columns
        else pd.Series(pd.NA, index=table.index, dtype="object")
    )


def format_seconds(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}"


# --------------------------------------------------------------------------------------
# Calendario
# --------------------------------------------------------------------------------------


def pick_reference_day(
    service_dates: Iterable[date], weekday: int, today: date
) -> tuple[date, bool] | None:
    """Il primo giorno della settimana `weekday` con servizio da `today` in poi.

    Se il calendario è finito, l'ultimo disponibile (e il flag `from_expired_feed` è True), come
    prevede 00 2.2 per il feed scaduto.
    """
    candidates = sorted(d for d in service_dates if d.weekday() == weekday)
    if not candidates:
        return None
    upcoming = [d for d in candidates if d >= today]
    return (upcoming[0], False) if upcoming else (candidates[-1], True)


# --------------------------------------------------------------------------------------
# Statistiche per linea
# --------------------------------------------------------------------------------------


def trip_bounds(stop_times: pd.DataFrame) -> pd.DataFrame:
    """Per ogni corsa: partenza dal primo capolinea e arrivo all'ultimo, in secondi."""
    table = pd.DataFrame(
        {
            "trip_id": stop_times["trip_id"],
            "seq": pd.to_numeric(stop_times["stop_sequence"], errors="coerce"),
            "dep": to_seconds(stop_times["departure_time"]),
            "arr": to_seconds(stop_times["arrival_time"]),
        }
    ).dropna(subset=["seq"])
    grouped = table.groupby("trip_id")["seq"]
    first = table.loc[grouped.idxmin()].set_index("trip_id")
    last = table.loc[grouped.idxmax()].set_index("trip_id")
    return pd.DataFrame(
        {
            "start_s": first["dep"].fillna(first["arr"]),
            "end_s": last["arr"].fillna(last["dep"]),
        }
    )


def day_stats(
    trips: pd.DataFrame, bounds: pd.DataFrame, route_ids: list[str], service_ids: set[str]
) -> dict[str, Any]:
    selected = trips[trips["route_id"].isin(route_ids) & trips["service_id"].isin(service_ids)]
    timed = bounds.reindex(selected["trip_id"].drop_duplicates()).dropna(subset=["start_s"])
    starts = timed["start_s"]

    def count(window: tuple[int, int]) -> int:
        return int(((starts >= window[0] * 60) & (starts < window[1] * 60)).sum())

    if timed.empty:
        first = last_start = last_end = None
    else:
        first, last_start, last_end = (
            format_seconds(starts.min()),
            format_seconds(starts.max()),
            format_seconds(timed["end_s"].max()),
        )
    return {
        "trips": len(timed),
        "trips_without_times": len(selected) - len(timed),
        "first_start": first,
        "last_start": last_start,
        "last_end": last_end,
        "trips_21_23": count(EVENING_WINDOW),
        "trips_12_18": count(AFTERNOON_WINDOW),
    }


def _route_label(row: Mapping[Any, Any]) -> str:
    return f"{_text(row.get('route_short_name'))} {_text(row.get('route_long_name'))}".strip()


def find_lines(routes: pd.DataFrame) -> list[tuple[LineTarget, pd.DataFrame]]:
    labels = pd.Series(
        [_route_label(row) for row in routes.to_dict("records")], index=routes.index, dtype="object"
    )
    found = []
    for target in LINES_OF_INTEREST:
        mask = routes["route_type"].isin(target.route_types) & labels.str.contains(target.pattern)
        found.append((target, routes[mask]))
    return found


def routes_by_stop(
    stop_ids: Iterable[str], stop_times: pd.DataFrame, trips: pd.DataFrame, routes: pd.DataFrame
) -> pd.DataFrame:
    """Per le fermate date, le linee che le servono (righe uniche).

    Colonne: stop_id, route_id, line, route_type. `line` è il nome breve della linea (o il nome
    lungo, o l'id se mancano).
    """
    names = routes.assign(
        line=_column(routes, "route_short_name")
        .fillna(_column(routes, "route_long_name"))
        .fillna(routes["route_id"])
    )[["route_id", "line", "route_type"]]
    return (
        stop_times[stop_times["stop_id"].isin(list(stop_ids))][["trip_id", "stop_id"]]
        .drop_duplicates()
        .merge(trips[["trip_id", "route_id"]], on="trip_id")
        .merge(names, on="route_id")[["stop_id", "route_id", "line", "route_type"]]
        .drop_duplicates()
    )


def stops_near(
    stops: pd.DataFrame, stop_times: pd.DataFrame, trips: pd.DataFrame, routes: pd.DataFrame
) -> list[dict[str, Any]]:
    lat, lon = stops["stop_lat"].astype(float), stops["stop_lon"].astype(float)
    distance_m = haversine_m(lat, lon, ROTONDA_DIAZ)
    table = stops.assign(distance_m=distance_m)
    near = table[table["distance_m"] <= NEAR_RADIUS_M].sort_values("distance_m")
    served = (
        routes_by_stop(near["stop_id"], stop_times, trips, routes)
        .groupby("stop_id")["line"]
        .agg(lambda s: sorted(set(s)))
    )
    return [
        {
            "stop_id": row["stop_id"],
            "stop_name": _opt(row["stop_name"]),
            "distance_m": round(float(row["distance_m"])),
            "lines": served.get(row["stop_id"], []),
        }
        for row in near.to_dict("records")
    ]


# --------------------------------------------------------------------------------------
# Validazione
# --------------------------------------------------------------------------------------


def validate_feed(feed_dir: Path, today: date) -> dict[str, Any]:
    """Validazione interna minima di 00 2.2. Restituisce un dizionario serializzabile in JSON."""
    errors: list[str] = []
    warnings: list[str] = []
    present = sorted(p.name for p in feed_dir.glob("*.txt"))
    missing = [name for name in REQUIRED_FILES if name not in present]
    has_calendar, has_dates = "calendar.txt" in present, "calendar_dates.txt" in present
    if missing:
        errors.append(f"File obbligatori mancanti: {', '.join(missing)}.")
    if not has_calendar and not has_dates:
        errors.append(
            "Mancano sia calendar.txt sia calendar_dates.txt: nessun calendario del servizio."
        )

    result: dict[str, Any] = {
        "today": today.isoformat(),
        "files": {
            "present": present,
            "missing_required": missing,
            "has_calendar": has_calendar,
            "has_calendar_dates": has_dates,
            "has_feed_info": "feed_info.txt" in present,
        },
        "windows": {
            "evening": "21:00-23:00",
            "afternoon": "12:00-18:00",
            "rule": "ora di partenza dal primo capolinea; inizio incluso, fine esclusa; "
            "entrambe le direzioni",
        },
        "external_validator": {
            "executed": False,
            "reason": "Il validatore MobilityData (java + jar) è opzionale in 00 2.2 e non è "
            "automatizzato in questo script.",
        },
        "errors": errors,
        "warnings": warnings,
    }
    if errors:
        return result

    tables = {name: read_table(feed_dir, name) for name in (*REQUIRED_FILES, "feed_info.txt")}
    tables["calendar.txt"] = read_table(feed_dir, "calendar.txt")
    tables["calendar_dates.txt"] = read_table(feed_dir, "calendar_dates.txt")
    for filename, columns in REQUIRED_COLUMNS.items():
        table = tables[filename]
        assert table is not None  # i file obbligatori esistono (controllato sopra)
        absent = [c for c in columns if c not in table.columns]
        if absent:
            errors.append(f"{filename}: colonne mancanti {', '.join(absent)}.")
    if errors:
        return result
    routes, trips, stops, stop_times = (
        tables["routes.txt"],
        tables["trips.txt"],
        tables["stops.txt"],
        tables["stop_times.txt"],
    )
    assert routes is not None and trips is not None and stops is not None and stop_times is not None

    feed_info = tables["feed_info.txt"]
    result["feed_info"] = (
        {k: _text(v) for k, v in feed_info.iloc[0].dropna().items()}
        if feed_info is not None and len(feed_info)
        else None
    )
    result["counts"] = {
        "routes": len(routes),
        "trips": len(trips),
        "stops": len(stops),
        "stop_times": len(stop_times),
    }

    # --- Calendario ---
    by_date, invalid_dates = services_by_date(tables["calendar.txt"], tables["calendar_dates.txt"])
    if invalid_dates:
        warnings.append(f"{invalid_dates} righe di calendario con date non valide (ignorate).")
    if not by_date:
        errors.append("Il calendario non contiene nessun giorno con servizio.")
        return result
    valid_from, valid_to = min(by_date), max(by_date)
    reference: dict[str, Any] = {}
    for label, weekday in (("friday", FRIDAY), ("saturday", SATURDAY)):
        picked = pick_reference_day(by_date, weekday, today)
        reference[label] = (
            None
            if picked is None
            else {"date": picked[0].isoformat(), "from_expired_feed": picked[1]}
        )
    result["calendar"] = {
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "service_dates": len(by_date),
        "expired": valid_to < today,
        "starts_in_future": valid_from > today,
        "reference_days": reference,
    }

    # --- Linee ---
    result["route_type_counts"] = routes["route_type"].value_counts().to_dict()
    result["routes"] = [
        {
            "route_id": r["route_id"],
            "agency_id": _opt(r.get("agency_id")),
            "short_name": _opt(r.get("route_short_name")),
            "long_name": _opt(r.get("route_long_name")),
            "route_type": r["route_type"],
        }
        for r in routes.to_dict("records")
    ]
    bounds = trip_bounds(stop_times)
    unparsed = int(
        stop_times["departure_time"].notna().sum()
        - to_seconds(stop_times["departure_time"]).notna().sum()
    )
    if unparsed:
        warnings.append(f"{unparsed} orari di partenza non nel formato HH:MM:SS (ignorati).")

    lines: list[dict[str, Any]] = []
    for target, matched in find_lines(routes):
        entry: dict[str, Any] = {
            "name": target.name,
            "found": not matched.empty,
            "routes": [
                {
                    "route_id": r["route_id"],
                    "short_name": _opt(r.get("route_short_name")),
                    "long_name": _opt(r.get("route_long_name")),
                    "route_type": r["route_type"],
                }
                for r in matched.to_dict("records")
            ],
            "days": {},
        }
        if not matched.empty:
            for label, info in reference.items():
                if info is None:
                    continue
                services = by_date[date.fromisoformat(info["date"])]
                entry["days"][label] = {
                    "date": info["date"],
                    **day_stats(trips, bounds, list(matched["route_id"]), services),
                }
        lines.append(entry)
    result["lines_of_interest"] = lines

    result["stops_near_rotonda_diaz"] = {
        "center": list(ROTONDA_DIAZ),
        "radius_m": NEAR_RADIUS_M,
        "stops": stops_near(stops, stop_times, trips, routes),
    }
    return result


# --------------------------------------------------------------------------------------
# Flusso principale
# --------------------------------------------------------------------------------------


def latest_zip(gtfs_dir: Path) -> Path | None:
    zips = sorted(p for p in gtfs_dir.glob(f"{FEED_NAME}_*.zip") if meta_path_for(p).is_file())
    return zips[-1] if zips else None


def print_summary(result: dict[str, Any]) -> None:
    for message in result["errors"]:
        print(f"ERRORE: {message}")
    for message in result["warnings"]:
        print(f"Avviso: {message}")
    if "calendar" not in result:
        return
    cal = result["calendar"]
    print(
        f"Calendario: {cal['valid_from']} -> {cal['valid_to']} "
        f"({cal['service_dates']} giorni con servizio)"
    )
    if cal["expired"]:
        print(
            "ATTENZIONE: calendario SCADUTO. Il motore userà l'ultimo giorno valido "
            "come orario tipo."
        )
    if cal["starts_in_future"]:
        print("Nota: il calendario inizia nel futuro (non è ancora in vigore oggi).")
    counts = result["counts"]
    print(f"Righe: {counts['routes']} linee, {counts['trips']} corse, {counts['stops']} fermate")
    for line in result["lines_of_interest"]:
        if not line["found"]:
            print(f"  {line['name']:<26} NON TROVATA")
            continue
        for label, day in line["days"].items():
            times = (
                f"{day['first_start']}-{day['last_start']} (arrivo ultimo {day['last_end']})"
                if day["trips"]
                else "nessuna corsa"
            )
            print(
                f"  {line['name']:<26} {label[:3]} {day['date']}: {day['trips']:>3} corse, "
                f"{times}, 21-23: {day['trips_21_23']}, 12-18: {day['trips_12_18']}"
            )
    near = result["stops_near_rotonda_diaz"]["stops"]
    print(f"Fermate entro {NEAR_RADIUS_M} m da Rotonda Diaz: {len(near)}")


def prepare(
    data_dir: Path,
    url: str,
    *,
    force: bool,
    today: date | None = None,
    download: Callable[[str, Path], dict[str, str]] | None = None,
) -> int:
    fetch = download or download_file
    today = today or now_rome().date()
    gtfs_dir = DataPaths(data_dir).gtfs_dir
    feed_dir = gtfs_dir / FEED_NAME
    gtfs_dir.mkdir(parents=True, exist_ok=True)

    zip_path = latest_zip(gtfs_dir)
    if force or zip_path is None or not feed_dir.is_dir():
        zip_path = gtfs_dir / f"{FEED_NAME}_{today:%Y%m%d}.zip"
        incoming = gtfs_dir / f"{FEED_NAME}_incoming.zip"
        print(f"Scarico il GTFS da {url} ...")
        try:
            headers = fetch(url, incoming)
            check_zip(incoming)
        except DownloadError as error:  # include FeedError
            incoming.unlink(missing_ok=True)  # i dati buoni già presenti restano intatti
            print(f"ERRORE: {error}", file=sys.stderr)
            return 1
        os.replace(incoming, zip_path)
        extract_feed(zip_path, feed_dir)
        size = zip_path.stat().st_size
        extra = "; ".join(f"{k}: {v}" for k, v in headers.items())
        write_meta(
            zip_path,
            source_url=url,
            fetched_at=now_rome_iso(),
            license=LICENSE,
            notes=f"{size} byte{'; ' + extra if extra else ''}. Estratto in {FEED_NAME}/.",
        )
        print(f"Salvato {zip_path.name} ({size / 1e6:.1f} MB) ed estratto in {feed_dir}")
    else:
        print(
            f"{zip_path.name} ed {FEED_NAME}/ esistono già: download saltato (--force per rifarlo)."
        )

    result = validate_feed(feed_dir, today)
    print_summary(result)
    return 1 if result["errors"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scarica, estrae e valida il GTFS ANM.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"default: {DEFAULT_URL}")
    parser.add_argument("--force", action="store_true", help="riscarica anche se i file esistono")
    add_data_dir_arg(parser)
    args = parser.parse_args(argv)
    return prepare(args.data_dir or default_data_dir(), args.url, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
