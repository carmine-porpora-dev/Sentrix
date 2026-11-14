from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.models.config import RouteClassification, VehicleKind

# route_type GTFS dei mezzi di superficie che il modello tratta come «bus» (0 tram, 3 autobus,
# 11 filobus). 1 (metro) e 7 (funicolare) sono classificati dai `route_id` di engine.yaml; la
# metro L2 (route_type 1, non in engine.yaml) resta fuori dal modello.
SURFACE_ROUTE_TYPES = frozenset({"0", "3", "11"})

REQUIRED_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "stops.txt": ("stop_id", "stop_name", "stop_lat", "stop_lon"),
    "routes.txt": ("route_id", "route_type"),
    "trips.txt": ("route_id", "service_id", "trip_id"),
    "stop_times.txt": ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
}
_WEEKDAY_COLUMNS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_NAMES = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


class GtfsError(ValueError):
    """Il feed non è utilizzabile o non contiene ciò che `engine.yaml` si aspetta."""


# --- lettura -------------------------------------------------------------------------------------


def read_table(directory: Path, filename: str) -> pd.DataFrame | None:
    """Legge un file GTFS come testo (nessuna conversione automatica). None se il file manca."""
    path = directory / filename
    if not path.is_file():
        return None
    # utf-8-sig: toglie l'eventuale BOM. Solo la stringa vuota è NaN ('NA' può essere un nome).
    table = pd.read_csv(
        path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig"
    )
    table.columns = pd.Index([str(c).strip() for c in table.columns])
    return table


def parse_gtfs_date(value: object) -> date | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y%m%d").date()
    except ValueError:
        return None


def to_seconds(times: pd.Series) -> pd.Series:
    """'HH:MM:SS' -> secondi dalla mezzanotte. Ore >= 24 valide (25:30:00 = 01:30 dopo)."""
    parts = (
        times.astype("string").str.strip().str.extract(r"^(\d+):(\d{2}):(\d{2})$").astype("float")
    )
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def services_by_date(
    calendar: pd.DataFrame | None, calendar_dates: pd.DataFrame | None
) -> tuple[dict[date, set[str]], int]:
    """Per ogni data i `service_id` attivi: calendar.txt (se c'è) più calendar_dates.txt.

    Restituisce anche il numero di righe con date non valide (ignorate).
    """
    active: defaultdict[date, set[str]] = defaultdict(set)
    invalid = 0
    if calendar is not None:
        for row in calendar.to_dict("records"):
            start, end = (
                parse_gtfs_date(row.get("start_date")),
                parse_gtfs_date(row.get("end_date")),
            )
            if start is None or end is None:
                invalid += 1
                continue
            flags = [str(row.get(column)).strip() == "1" for column in _WEEKDAY_COLUMNS]
            day = start
            while day <= end:
                if flags[day.weekday()]:
                    active[day].add(str(row["service_id"]))
                day += timedelta(days=1)
    if calendar_dates is not None:
        for row in calendar_dates.to_dict("records"):
            day_value = parse_gtfs_date(row.get("date"))
            if day_value is None:
                invalid += 1
                continue
            kind = str(row.get("exception_type")).strip()
            if kind == "1":
                active[day_value].add(str(row["service_id"]))
            elif kind == "2":
                active[day_value].discard(str(row["service_id"]))
    return {d: s for d, s in active.items() if s}, invalid


def stops_served_by_routes(
    route_ids: Iterable[str], stop_times: pd.DataFrame, trips: pd.DataFrame
) -> set[str]:
    """Tutte le fermate toccate da almeno una corsa delle linee date."""
    trip_ids = trips[trips["route_id"].isin(list(route_ids))]["trip_id"]
    return set(stop_times[stop_times["trip_id"].isin(trip_ids)]["stop_id"])


@dataclass(frozen=True, eq=False, slots=True)
class GtfsFeed:
    """Le tabelle del feed che servono al motore, già con i tipi giusti.

    `stops`: stop_id, stop_name, lat, lon (float) e il resto di stops.txt. `routes` e `trips`:
    colonne GTFS originali (testo). `stop_times`: trip_id, stop_id (categorie), seq (int), arr_s e
    dep_s (secondi dalla mezzanotte, anche oltre le 24 ore; NaN se il feed non dà l'orario).
    """

    directory: Path
    stops: pd.DataFrame
    routes: pd.DataFrame
    trips: pd.DataFrame
    stop_times: pd.DataFrame
    service_dates: Mapping[date, frozenset[str]]

    @property
    def valid_from(self) -> date:
        return min(self.service_dates)

    @property
    def valid_to(self) -> date:
        return max(self.service_dates)


_CACHE: dict[str, GtfsFeed] = {}


def load_feed(directory: Path) -> GtfsFeed:
    """Il feed estratto in `directory` (DATA_DIR/gtfs/anm), letto una volta per processo.

    `GtfsError` se manca un file o una colonna obbligatoria, se una data del calendario non è
    valida (altrimenti un giorno sparirebbe in silenzio) o se il calendario è vuoto. Il valore
    restituito è condiviso: non va modificato.
    """
    key = str(directory.resolve())
    if key not in _CACHE:
        _CACHE[key] = _read_feed(directory)
    return _CACHE[key]


def clear_feed_cache() -> None:
    """Svuota la cache di `load_feed` (per i test e per chi sostituisce il feed)."""
    _CACHE.clear()


# Righe di stop_times.txt per blocco: il file reale ha 700.000 righe e, letto tutto come testo,
# costa mezzo gigabyte di picco; a blocchi, convertiti subito, ne bastano poche decine di megabyte.
STOP_TIMES_CHUNK = 100_000


def _read_stop_times(directory: Path) -> pd.DataFrame:
    path = directory / "stop_times.txt"
    if not path.is_file():
        raise GtfsError(f"Nel feed GTFS {directory} manca stop_times.txt.")
    columns = REQUIRED_COLUMNS["stop_times.txt"]
    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    absent = [c for c in columns if c not in {str(h).strip() for h in header}]
    if absent:
        raise GtfsError(f"stop_times.txt: mancano le colonne {', '.join(absent)}.")
    blocks = []
    reader = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        encoding="utf-8-sig",
        usecols=lambda name: str(name).strip() in columns,
        chunksize=STOP_TIMES_CHUNK,
    )
    for raw in reader:
        raw.columns = pd.Index([str(c).strip() for c in raw.columns])
        arrival, departure = to_seconds(raw["arrival_time"]), to_seconds(raw["departure_time"])
        sequence = pd.to_numeric(raw["stop_sequence"], errors="coerce")
        if sequence.isna().any():
            raise GtfsError("stop_times.txt: ci sono righe senza stop_sequence valido.")
        blocks.append(
            pd.DataFrame(
                {
                    "trip_id": raw["trip_id"].astype("string"),
                    "stop_id": raw["stop_id"].astype("string"),
                    "seq": sequence.astype("int32"),
                    "arr_s": arrival.fillna(departure).astype("float32"),
                    "dep_s": departure.fillna(arrival).astype("float32"),
                }
            )
        )
    table = (
        pd.concat(blocks, ignore_index=True)
        if blocks
        else pd.DataFrame(columns=["trip_id", "stop_id", "seq", "arr_s", "dep_s"])
    )
    return table.astype({"trip_id": "category", "stop_id": "category"})


def _read_feed(directory: Path) -> GtfsFeed:
    if not directory.is_dir():
        raise GtfsError(f"Manca il feed GTFS {directory}: esegui `make data`.")
    tables: dict[str, pd.DataFrame] = {}
    for filename in REQUIRED_FILES:
        if filename == "stop_times.txt":
            continue  # a blocchi, più sotto
        table = read_table(directory, filename)
        if table is None:
            raise GtfsError(f"Nel feed GTFS {directory} manca {filename}.")
        absent = [c for c in REQUIRED_COLUMNS[filename] if c not in table.columns]
        if absent:
            raise GtfsError(f"{filename}: mancano le colonne {', '.join(absent)}.")
        tables[filename] = table

    calendar, calendar_dates = (
        read_table(directory, "calendar.txt"),
        read_table(directory, "calendar_dates.txt"),
    )
    if calendar is None and calendar_dates is None:
        raise GtfsError(
            f"Nel feed GTFS {directory} mancano sia calendar.txt sia calendar_dates.txt."
        )
    active, invalid = services_by_date(calendar, calendar_dates)
    if invalid:
        raise GtfsError(f"Il calendario del feed ha {invalid} date non valide.")
    if not active:
        raise GtfsError("Il calendario del feed non ha nessun giorno con servizio.")

    stops = tables["stops.txt"]
    stops = stops.assign(
        lat=pd.to_numeric(stops["stop_lat"], errors="coerce"),
        lon=pd.to_numeric(stops["stop_lon"], errors="coerce"),
    )
    if stops["lat"].isna().any() or stops["lon"].isna().any():
        raise GtfsError("stops.txt: ci sono fermate senza coordinate valide.")

    stop_times = _read_stop_times(directory)
    unknown = set(stop_times["stop_id"].cat.categories) - set(stops["stop_id"])
    if unknown:
        raise GtfsError(
            f"stop_times.txt cita fermate che stops.txt non ha: {', '.join(sorted(unknown)[:5])}"
            + (" …" if len(unknown) > 5 else "")
        )
    return GtfsFeed(
        directory=directory,
        stops=stops,
        routes=tables["routes.txt"],
        trips=tables["trips.txt"],
        stop_times=stop_times,
        service_dates={day: frozenset(ids) for day, ids in active.items()},
    )


# --- calendario ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServiceDay:
    """Quale giorno del feed vale per la data di un Evento."""

    requested: date  # la data dell'Evento
    used: date  # il giorno del feed da cui si prendono le corse
    services: frozenset[str]  # i `service_id` attivi quel giorno
    covered: bool  # True se il feed copre la data richiesta (corse `real`)

    @property
    def assumption(self) -> str | None:
        """La frase da mettere tra le assunzioni quando le corse non sono dati del feed."""
        if self.covered:
            return None
        return (
            f"orario tipo del {self.used:%d/%m/%Y} ({_WEEKDAY_NAMES[self.used.weekday()]}) "
            f"applicato alla data dell'evento ({self.requested:%d/%m/%Y}): il feed non la copre"
        )


def service_day(service_dates: Mapping[date, frozenset[str]], day: date) -> ServiceDay:
    """Il giorno del feed da usare per `day`.

    Se il feed ha servizio in `day`, quello stesso giorno. Altrimenti l'**orario tipo**: tra i
    giorni del feed con lo stesso giorno della settimana, quello del servizio più frequente (a
    parità, il più recente), e da quel servizio l'ultima data. Si guarda il giorno della settimana,
    non solo feriale/sabato/festivo: nel feed reale il venerdì e il sabato hanno più corse della
    metro dal lunedì al giovedì. Il servizio più frequente, e non l'ultimo giorno, perché
    l'ultimo può essere una festività (nel feed attuale, il sabato 26/12). Le festività fuori dal
    feed non sono riconosciute.
    """
    if day in service_dates:
        return ServiceDay(day, day, service_dates[day], covered=True)
    patterns: defaultdict[frozenset[str], list[date]] = defaultdict(list)
    for candidate, services in service_dates.items():
        if candidate.weekday() == day.weekday():
            patterns[services].append(candidate)
    if not patterns:
        raise GtfsError(
            f"Il feed non ha nessun {_WEEKDAY_NAMES[day.weekday()]}: "
            f"non si può scegliere un orario tipo per il {day:%d/%m/%Y}."
        )
    services, dates = max(patterns.items(), key=lambda item: (len(item[1]), max(item[1])))
    return ServiceDay(day, max(dates), services, covered=False)


# --- linee ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteClasses:
    """I `route_id` di ogni classe di linea (le stesse chiavi di `vehicle_capacity`)."""

    by_class: Mapping[VehicleKind, frozenset[str]]

    def ids(self, kind: VehicleKind) -> frozenset[str]:
        return self.by_class[kind]

    def of(self, route_id: str) -> VehicleKind | None:
        """La classe di una linea, `None` se il modello non la considera."""
        for kind, ids in self.by_class.items():
            if route_id in ids:
                return kind
        return None


def classify_routes(feed: GtfsFeed, classification: RouteClassification) -> RouteClasses:
    """Metro L1, metro L6 e funicolari dai `route_id` di engine.yaml; `bus` = ogni altra linea di
    superficie (`SURFACE_ROUTE_TYPES`). `GtfsError` se un `route_id` di engine.yaml non è nel feed
    (ANM ha pubblicato un feed nuovo: rilanciare `scripts.data_report`)."""
    present = set(feed.routes["route_id"])
    configured = {
        "metro_line_1": classification.metro_line_1.route_ids,
        "metro_line_6": classification.metro_line_6.route_ids,
        "funicular": classification.funicular.route_ids,
    }
    missing = {
        kind: sorted(set(ids) - present) for kind, ids in configured.items() if set(ids) - present
    }
    if missing:
        detail = "; ".join(f"{kind}: {', '.join(ids)}" for kind, ids in sorted(missing.items()))
        raise GtfsError(
            f"route_id di engine.yaml (transit.route_classification) non presenti nel feed: "
            f"{detail}. Il feed è cambiato? Rilancia `scripts.data_report`."
        )
    classified = {route_id for ids in configured.values() for route_id in ids}
    surface = feed.routes[feed.routes["route_type"].isin(SURFACE_ROUTE_TYPES)]
    bus = {route_id for route_id in surface["route_id"] if route_id not in classified}
    by_class: dict[VehicleKind, frozenset[str]] = {
        "bus": frozenset(bus),
        "metro_line_1": frozenset(configured["metro_line_1"]),
        "metro_line_6": frozenset(configured["metro_line_6"]),
        "funicular": frozenset(configured["funicular"]),
    }
    return RouteClasses(by_class)
