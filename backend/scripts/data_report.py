import argparse
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.data.gtfs import read_table, services_by_date, stops_served_by_routes
from app.data.osm_graph import load_osm_graph
from app.data.paths import DataPaths
from app.data.resolvers import edges_named, match_stops
from app.geo import haversine_m
from scripts.common import (
    add_data_dir_arg,
    atomic_write_text,
    default_data_dir,
    now_rome,
    read_meta,
    sha256_of,
)
from scripts.prepare_gtfs import NEAR_RADIUS_M, latest_zip, routes_by_stop, validate_feed
from scripts.prepare_pmtiles import MAXZOOM, PMTILES_BBOX
from scripts.tomtom_probe import PROBE_GLOB

REPORT_NAME = "data_report.md"

# La demo è il 14/11/2026 (spech.md, D1).
DEMO_DATE = date(2026, 11, 14)
# Esempio di 00 2.5: "Linea 6 senza corse dopo 21:30 il sabato".
EVENING_CUTOFF_MIN = 21 * 60 + 30
# Strade di 00 2.5: si cerca la parte distintiva del nome.
STREETS = ("Via Francesco Caracciolo", "Viale Anton Dohrn")
# Sotto questa quota di archi con corsie/limite OSM pesano soprattutto i valori di riserva.
LOW_COVERAGE_SHARE = 0.5

# Stazioni citate dagli itinerari PROPOSTI in 03-engine-transit.md 2 (Q6), per linea. Quando gli
# itinerari andranno in config/engine.yaml (F3-02) questa tabella sparirà: sarà il dato a guidare.
ITINERARY_STATIONS: dict[str, tuple[str, ...]] = {
    "Linea 1": ("Piscinola", "Garibaldi", "Vanvitelli", "Medaglie d'Oro", "Dante", "Municipio"),
    "Linea 6": ("Municipio", "San Pasquale", "Mostra", "Arco Mirelli", "Mergellina"),
    "Funicolare di Chiaia": ("Cimarosa", "Parco Margherita"),
    "Funicolare di Mergellina": ("Manzoni", "Mergellina"),
}
# Gruppi di config/engine.yaml (03 1, route_classification) -> linee del feed.
ROUTE_GROUPS = {
    "metro_line_1": ("Linea 1",),
    "metro_line_6": ("Linea 6",),
    "funicular": (
        "Funicolare di Chiaia",
        "Funicolare Centrale",
        "Funicolare di Montesanto",
        "Funicolare di Mergellina",
    ),
}
WEEKDAYS_IT = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
# In ordine di urgenza: prima ciò che non va, poi le conferme richieste, poi le informazioni.
LEVELS = ("ATTENZIONE", "DECISIONE", "NOTA")


# --------------------------------------------------------------------------------------
# Formattazione
# --------------------------------------------------------------------------------------


def num(value: float, decimals: int = 0) -> str:
    """Numero all'italiana: 13.507 e 11,7."""
    text = f"{value:,.{decimals}f}"
    return text.translate(str.maketrans(",.", ".,"))


def pct(part: float, whole: float) -> str:
    return f"{num(100 * part / whole, 1)}%" if whole else "-"


def day_label(day: date) -> str:
    return f"{WEEKDAYS_IT[day.weekday()]} {day.isoformat()}"


def size_text(size: int) -> str:
    """Dimensione leggibile: kB sotto 1 MB, MB sopra."""
    return f"{num(size / 1e6, 1)} MB" if size >= 1_000_000 else f"{num(size / 1e3)} kB"


ROUTE_TYPE_NAMES = {"0": "tram", "1": "metro", "3": "bus", "7": "funicolari", "11": "filobus"}


def table(headers: list[str], rows: Iterable[Iterable[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def minutes_of(hhmm: str | None) -> int | None:
    """'25:30' -> 1530 (minuti dalla mezzanotte, anche oltre le 24)."""
    if not hhmm:
        return None
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


@dataclass(frozen=True)
class Issue:
    level: str  # uno di LEVELS
    text: str

    def __post_init__(self) -> None:
        assert self.level in LEVELS, self.level


# --------------------------------------------------------------------------------------
# Lettura degli artefatti
# --------------------------------------------------------------------------------------


def integrity(artifact: Path) -> dict[str, Any]:
    meta = read_meta(artifact)
    return {
        "size": artifact.stat().st_size,
        "fetched_at": meta.get("fetched_at") if meta else None,
        "sha256_ok": (sha256_of(artifact) == meta.get("sha256")) if meta else None,
    }


def osm_stats(graph: Any) -> dict[str, Any]:
    classes: dict[str, dict[str, float]] = defaultdict(
        lambda: {"edges": 0, "lanes": 0, "speed": 0, "km": 0.0}
    )
    for _u, _v, data in graph.edges(data=True):
        row = classes[str(data.get("highway", "(senza classe)"))]
        km = float(data["length_m"]) / 1000
        row["edges"] += 1
        row["lanes"] += "lanes" in data
        row["speed"] += "maxspeed_kmh" in data
        row["km"] += km
    streets: dict[str, dict[str, Any]] = {}
    for label in STREETS:  # stessa regola dei nomi del resolver (app.data.resolvers)
        named = edges_named(graph, label)
        streets[label] = {
            "edges": len(named),
            "km": sum(float(data["length_m"]) for _, data in named) / 1000,
            "names": Counter(str(data.get("name", "")) for _, data in named),
        }
    return {
        "nodes": graph.number_of_nodes(),
        "edges": sum(c["edges"] for c in classes.values()),
        "km": sum(c["km"] for c in classes.values()),
        "lanes": sum(c["lanes"] for c in classes.values()),
        "speed": sum(c["speed"] for c in classes.values()),
        "classes": sorted(classes.items(), key=lambda kv: -kv[1]["edges"]),
        "streets": streets,
    }


def load_osm(data_dir: Path) -> dict[str, Any] | None:
    path = DataPaths(data_dir).osm_graph
    if not path.is_file():
        return None
    graph = load_osm_graph(path)
    return {"stats": osm_stats(graph), "file": integrity(path)}


def station_checks(
    stops: pd.DataFrame,
    stop_times: pd.DataFrame,
    trips: pd.DataFrame,
    route_ids: dict[str, list[str]],
    itineraries: dict[str, tuple[str, ...]] | None = None,
) -> list[dict[str, Any]]:
    """Per ogni stazione degli itinerari: esiste tra le fermate SERVITE da quella linea?"""
    rows = []
    for line, stations in (itineraries or ITINERARY_STATIONS).items():
        ids = route_ids.get(line, [])
        served = stops[stops["stop_id"].isin(stops_served_by_routes(ids, stop_times, trips))]
        for station in stations:
            found = match_stops(station, served) if ids else served.iloc[0:0]
            rows.append(
                {
                    "line": line,
                    "station": station,
                    "line_found": bool(ids),
                    "stops": [
                        {
                            "stop_id": r["stop_id"],
                            "name": str(r["stop_name"]).strip(),
                            "lat": float(r["stop_lat"]),
                            "lon": float(r["stop_lon"]),
                        }
                        for r in found.to_dict("records")
                    ],
                }
            )
    return rows


def interchange_m(
    checks: list[dict[str, Any]], station: str, line_a: str, line_b: str
) -> int | None:
    """Distanza in linea d'aria tra le fermate `station` di due linee (la minima), se esistono."""
    a: list[dict[str, Any]] = next(
        (c["stops"] for c in checks if c["line"] == line_a and c["station"] == station), []
    )
    b: list[dict[str, Any]] = next(
        (c["stops"] for c in checks if c["line"] == line_b and c["station"] == station), []
    )
    distances = [
        float(haversine_m(p["lat"], p["lon"], (q["lat"], q["lon"])))
        for p in a
        for q in b
        if p["stop_id"] != q["stop_id"]
    ]
    return round(min(distances)) if distances else None


def arco_mirelli(
    stops: pd.DataFrame, stop_times: pd.DataFrame, trips: pd.DataFrame, routes: pd.DataFrame
) -> list[dict[str, Any]]:
    """Tutte le fermate con 'Arco Mirelli' nel nome, con le linee che le servono."""
    found = match_stops("Arco Mirelli", stops)
    served = routes_by_stop(found["stop_id"], stop_times, trips, routes)
    return [
        {
            "stop_id": r["stop_id"],
            "name": str(r["stop_name"]).strip(),
            "lines": sorted(set(served[served["stop_id"] == r["stop_id"]]["line"])),
            "metro": bool((served[served["stop_id"] == r["stop_id"]]["route_type"] == "1").any()),
        }
        for r in found.to_dict("records")
    ]


def load_gtfs(data_dir: Path, today: date) -> dict[str, Any] | None:
    paths = DataPaths(data_dir)
    feed_dir = paths.gtfs_feed
    zip_path = latest_zip(paths.gtfs_dir)
    if not feed_dir.is_dir() or zip_path is None:
        return None
    validation = validate_feed(feed_dir, today)
    result: dict[str, Any] = {
        "validation": validation,
        "file": integrity(zip_path),
        "zip": zip_path.name,
    }
    if validation["errors"]:
        return result
    tables = {
        name: read_table(feed_dir, f"{name}.txt")
        for name in ("stops", "routes", "trips", "stop_times", "calendar", "calendar_dates")
    }
    stops, routes, trips, stop_times = (
        tables["stops"],
        tables["routes"],
        tables["trips"],
        tables["stop_times"],
    )
    assert stops is not None and routes is not None and trips is not None and stop_times is not None
    by_date, _ = services_by_date(tables["calendar"], tables["calendar_dates"])
    lines = {entry["name"]: entry for entry in validation["lines_of_interest"]}
    route_ids = {
        name: [r["route_id"] for r in entry["routes"]]
        for name, entry in lines.items()
        if entry["found"]
    }
    checks = station_checks(stops, stop_times, trips, route_ids)
    result.update(
        {
            "demo_covered": DEMO_DATE in by_date,
            "route_ids": route_ids,
            "stations": checks,
            "municipio_interchange_m": interchange_m(checks, "Municipio", "Linea 1", "Linea 6"),
            "arco": arco_mirelli(stops, stop_times, trips, routes),
            "other_metro": sorted(
                {
                    f"{r['short_name'] or r['long_name']} ({r['agency_id']})"
                    for r in validation["routes"]
                    if r["route_type"] == "1"
                    and all(r["route_id"] not in ids for ids in route_ids.values())
                }
            ),
        }
    )
    return result


def read_pmtiles_header(path: Path) -> dict[str, Any] | None:
    """Intestazione PMTiles v3 (127 byte): versione, zoom, area e numero di tile indirizzati."""
    with path.open("rb") as handle:
        head = handle.read(127)
    if len(head) < 127 or head[:7] != b"PMTiles":
        return None
    west, south, east, north = (v / 1e7 for v in struct.unpack("<4i", head[102:118]))
    return {
        "version": head[7],
        "tile_type": head[99],
        "min_zoom": head[100],
        "max_zoom": head[101],
        "bounds": (west, south, east, north),
        "tiles": struct.unpack("<Q", head[72:80])[0],
    }


def load_pmtiles(data_dir: Path) -> dict[str, Any] | None:
    path = DataPaths(data_dir).pmtiles
    if not path.is_file():
        return None
    meta = read_meta(path)
    build = re.search(r"/(\d{8})\.pmtiles", (meta or {}).get("source_url", ""))
    return {
        "file": integrity(path),
        "header": read_pmtiles_header(path),
        "build": datetime.strptime(build.group(1), "%Y%m%d").date() if build else None,
    }


def load_tomtom(data_dir: Path) -> dict[str, Any] | None:
    folder = data_dir / "tomtom"
    probes = sorted(folder.glob(PROBE_GLOB)) if folder.is_dir() else []
    if not probes:
        return None
    try:
        document = json.loads(probes[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"document": document, "name": probes[-1].name, "file": integrity(probes[-1])}


# --------------------------------------------------------------------------------------
# Decisioni
# --------------------------------------------------------------------------------------


def build_issues(
    osm: dict[str, Any] | None,
    gtfs: dict[str, Any] | None,
    tomtom: dict[str, Any] | None,
    pmtiles: dict[str, Any] | None,
) -> list[Issue]:
    issues: list[Issue] = []

    # --- OSM ---
    if osm is None:
        issues.append(
            Issue("ATTENZIONE", "Rete stradale OSM mancante: lancia `scripts.prepare_osm`.")
        )
    else:
        stats = osm["stats"]
        for label, info in stats["streets"].items():
            if info["edges"] == 0:
                issues.append(
                    Issue(
                        "DECISIONE", f"«{label}» non compare nella rete OSM: serve un'alternativa."
                    )
                )
        if stats["edges"] and (
            stats["lanes"] / stats["edges"] < LOW_COVERAGE_SHARE
            or stats["speed"] / stats["edges"] < LOW_COVERAGE_SHARE
        ):
            issues.append(
                Issue(
                    "NOTA",
                    "In OSM la quota di archi con il numero di corsie è "
                    f"{pct(stats['lanes'], stats['edges'])} e con il limite di velocità "
                    f"{pct(stats['speed'], stats['edges'])}: per gli altri il motore usa valori di "
                    "riserva per classe di strada (02 1). Il motore resta un modello macroscopico "
                    "non calibrato.",
                )
            )

    # --- GTFS ---
    if gtfs is None:
        issues.append(Issue("ATTENZIONE", "Feed GTFS mancante: lancia `scripts.prepare_gtfs`."))
    elif gtfs["validation"]["errors"]:
        issues.append(
            Issue(
                "ATTENZIONE",
                "Il feed GTFS non è utilizzabile: " + " ".join(gtfs["validation"]["errors"]),
            )
        )
    else:
        validation = gtfs["validation"]
        cal = validation["calendar"]
        if cal["expired"]:
            issues.append(
                Issue(
                    "ATTENZIONE",
                    f"Il calendario del feed è SCADUTO (ultimo giorno {cal['valid_to']}): il "
                    "motore "
                    "userà l'ultimo giorno valido come «orario tipo».",
                )
            )
        if cal["starts_in_future"]:
            issues.append(
                Issue("NOTA", f"Il feed non è ancora in vigore: inizia il {cal['valid_from']}.")
            )
        if not gtfs["demo_covered"]:
            issues.append(
                Issue(
                    "ATTENZIONE",
                    f"Il calendario NON copre la data della demo ({day_label(DEMO_DATE)}).",
                )
            )
        issues.append(
            Issue(
                "DECISIONE",
                f"Orario tipo (Q5). Il feed copre dal {cal['valid_from']} al {cal['valid_to']}"
                + (
                    f" e include la demo del {DEMO_DATE.isoformat()}"
                    if gtfs["demo_covered"]
                    else ""
                )
                + ". Per un evento con data fuori da questo intervallo (es. le regate di "
                "settembre 2026 "
                "o il Match del 2027) proponiamo di usare come «orario tipo» il giorno valido più "
                "vicino dello stesso tipo (feriale, sabato, festivo), dichiarato STIMA. "
                "Confermi di usare il feed ANM così?",
            )
        )
        for entry in validation["lines_of_interest"]:
            if not entry["found"]:
                if entry["name"] == "Funicolare di Montesanto":
                    issues.append(
                        Issue(
                            "NOTA",
                            "La funicolare di Montesanto non è nel feed ANM (è dell'EAV): "
                            "coerente con "
                            "D17 (EAV fuori dall'MVP). Nessuna azione.",
                        )
                    )
                else:
                    issues.append(
                        Issue(
                            "DECISIONE",
                            f"«{entry['name']}» NON è nel feed: l'MVP la richiede (D17).",
                        )
                    )
                continue
            saturday = entry["days"].get("saturday")
            last = minutes_of(saturday["last_start"]) if saturday else None
            if saturday and last is not None and last < EVENING_CUTOFF_MIN:
                issues.append(
                    Issue(
                        "DECISIONE",
                        f"{entry['name']}: nessuna corsa dopo le 21:30 il sabato (ultima partenza "
                        f"{saturday['last_start']}, ultimo arrivo {saturday['last_end']}, "
                        f"{saturday['trips_21_23']} corse tra le 21 e le 23). Con il feed attuale "
                        "la "
                        "linea non serve la sera: il modello userà questi orari e la misura "
                        "«prolungamento orario» (`extend_hours`) sarà l'unico modo di coprirla. "
                        "Confermi?",
                    )
                )
        issues.append(
            Issue(
                "DECISIONE",
                "Codici linea per `route_classification` (Q5): vedi il blocco «Configurazione "
                "proposta» in fondo. Confermi?",
            )
        )
        # Le linee assenti hanno già la loro segnalazione: qui solo le stazioni di linee presenti.
        missing = [
            f"{c['station']} ({c['line']})"
            for c in gtfs["stations"]
            if c["line_found"] and not c["stops"]
        ]
        if missing:
            issues.append(
                Issue(
                    "DECISIONE",
                    "Itinerari TPL (Q6): queste stazioni NON esistono sulla linea indicata nel "
                    "feed: " + ", ".join(missing) + ". Gli itinerari proposti vanno rivisti.",
                )
            )
        else:
            interchange = gtfs["municipio_interchange_m"]
            issues.append(
                Issue(
                    "DECISIONE",
                    "Itinerari TPL (Q6): tutte le stazioni degli itinerari proposti (03 2) "
                    "esistono "
                    "sulla linea giusta del feed (tabella al punto 2)."
                    + (
                        " «Municipio» della L1 e quella della L6 hanno stop_id diversi ma distano "
                        f"circa {interchange} m in linea d'aria: nel modello l'interscambio andrà "
                        "dichiarato esplicitamente (non sono la stessa fermata)."
                        if interchange is not None
                        else ""
                    )
                    + " Confermi gli itinerari?",
                )
            )
        metro_arco = [a for a in gtfs["arco"] if a["metro"]]
        if not gtfs["arco"]:
            issues.append(
                Issue("DECISIONE", "«Arco Mirelli» NON è nel feed: la chiusura va rivista.")
            )
        elif not metro_arco:
            issues.append(
                Issue(
                    "DECISIONE",
                    "«Arco Mirelli» c'è solo come fermata bus, non come stazione metro.",
                )
            )
        else:
            other = [a["stop_id"] for a in gtfs["arco"] if not a["metro"]]
            issues.append(
                Issue(
                    "NOTA",
                    "Stazione metro «Arco Mirelli» (L6): stop_id "
                    + ", ".join(a["stop_id"] for a in metro_arco)
                    + (
                        f". Fermate bus omonime da non confondere: {', '.join(other)}."
                        if other
                        else "."
                    ),
                )
            )
        if gtfs["other_metro"]:
            issues.append(
                Issue(
                    "NOTA",
                    "Nel feed ci sono altre linee metro fuori dall'MVP: "
                    + ", ".join(gtfs["other_metro"])
                    + " (spech 2.4).",
                )
            )

    # --- TomTom ---
    if tomtom is None:
        issues.append(
            Issue("ATTENZIONE", "Sonda TomTom non eseguita: lancia `scripts.tomtom_probe`.")
        )
    else:
        points = tomtom["document"]["points"]
        without = [p["label"] for p in points if not p["ok"]]
        if without:
            issues.append(
                Issue(
                    "DECISIONE",
                    "TomTom NON copre: " + ", ".join(without) + ". Attivare il taglio n. 4 "
                    "(da 15 a 5 tratti LIVE) o rivedere la vista LIVE (spech 2.5)?",
                )
            )
        else:
            issues.append(
                Issue(
                    "NOTA",
                    f"TomTom copre tutti i {len(points)} punti provati: nessuna azione. Un "
                    "«tratto» "
                    "TomTom può essere lungo oltre 2 km (non coincide con un arco OSM).",
                )
            )

    # --- PMTiles ---
    if pmtiles is None:
        issues.append(
            Issue("ATTENZIONE", "Base map PMTiles mancante: lancia `scripts.prepare_pmtiles`.")
        )
    elif pmtiles["header"] is None:
        issues.append(Issue("ATTENZIONE", "Il file PMTiles non ha un'intestazione valida."))

    # --- Integrità ---
    for label, section in (("OSM", osm), ("GTFS", gtfs), ("TomTom", tomtom), ("PMTiles", pmtiles)):
        if section is not None and section["file"]["sha256_ok"] is False:
            issues.append(
                Issue(
                    "ATTENZIONE",
                    f"{label}: lo sha256 del file non coincide con il suo meta (modificato?).",
                )
            )
    return issues


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------

ADMIN_CHECKS = [
    "**TomTom, conservazione dei dati (Q2):** il proprietario l'ha consentita "
    "(opzione A): le risposte della sonda sono tra le fixture di test (F1-10) e lo snapshot LIVE "
    "può stare su disco (F8-02, spento dal flag `LIVE_SNAPSHOT_PERSIST`). Restano validi i termini "
    "d'uso TomTom: da rileggere se cambiano.",
    "**Licenza del feed GTFS ANM:** non dichiarata nel feed (Transitland indica IODL 2.0): da "
    "verificare.",
    "**Licenza della build Protomaps:** i metadati del file indicano «© OpenStreetMap»; la "
    "licenza della "
    "build va confermata. L'attribuzione «© OpenStreetMap contributors» deve restare sempre "
    "visibile.",
    "**Regolamento dell'hackathon (Q3):** API esterne e proprietà intellettuale, da verificare "
    "prima della "
    "consegna.",
]


def render_issues(issues: list[Issue]) -> list[str]:
    lines = ["## Cosa devi decidere", ""]
    if not issues:
        return lines + ["Nessuna decisione richiesta.", ""]
    for number, issue in enumerate(sorted(issues, key=lambda i: LEVELS.index(i.level)), 1):
        lines.append(f"{number}. **[{issue.level}]** {issue.text}")
    return lines + [""]


def render_osm(osm: dict[str, Any] | None) -> list[str]:
    lines = ["## 1. Rete stradale (OpenStreetMap)", ""]
    if osm is None:
        return lines + ["**NON DISPONIBILE.** Lancia `uv run python -m scripts.prepare_osm`.", ""]
    s = osm["stats"]
    lines += [
        f"- {num(s['nodes'])} incroci (nodi) e {num(s['edges'])} tratti di strada (archi), "
        f"{num(s['km'], 1)} km in tutto.",
        f"- Archi con il numero di corsie in OSM: {num(s['lanes'])} "
        f"({pct(s['lanes'], s['edges'])}).",
        f"- Archi con il limite di velocità in OSM: {num(s['speed'])} "
        f"({pct(s['speed'], s['edges'])}).",
        "",
        *table(
            ["Classe di strada", "Archi", "Con corsie", "Con limite", "Lunghezza (km)"],
            (
                [
                    cls,
                    num(c["edges"]),
                    pct(c["lanes"], c["edges"]),
                    pct(c["speed"], c["edges"]),
                    num(c["km"], 1),
                ]
                for cls, c in s["classes"]
            ),
        ),
        "",
        "Le strade che servono al progetto:",
        "",
    ]
    for label, info in s["streets"].items():
        names = ", ".join(f"«{n}» ({c})" for n, c in info["names"].most_common())
        lines.append(
            f"- **{label}:** "
            + (
                f"{info['edges']} archi, {num(info['km'], 2)} km (nomi in OSM: {names})"
                if info["edges"]
                else "NON TROVATA"
            )
        )
    return lines + [
        "",
        "Un arco con due nomi (OSMnx unisce i tratti consecutivi) è contato in entrambe le strade.",
        "",
    ]


def route_type_lines(routes: list[dict[str, Any]]) -> list[str]:
    """Una riga per tipo di linea: i nomi per i tipi rari, solo il numero per i bus."""
    by_type: dict[str, list[str]] = defaultdict(list)
    for route in routes:
        name = route["short_name"] or route["long_name"] or route["route_id"]
        agency = route["agency_id"]
        by_type[route["route_type"]].append(f"{name} ({agency})" if agency != "ANM" else name)
    lines = []
    for route_type, names in sorted(by_type.items(), key=lambda kv: (kv[0] == "3", len(kv[1]))):
        label = ROUTE_TYPE_NAMES.get(route_type, f"tipo {route_type}")
        lines.append(
            f"- {label}: {len(names)} linee"
            if route_type == "3"
            else f"- {label}: {', '.join(sorted(names))}"
        )
    return lines


def render_gtfs(gtfs: dict[str, Any] | None) -> list[str]:
    lines = ["## 2. Trasporto pubblico (GTFS ANM)", ""]
    if gtfs is None:
        return lines + ["**NON DISPONIBILE.** Lancia `uv run python -m scripts.prepare_gtfs`.", ""]
    v = gtfs["validation"]
    if v["errors"]:
        return lines + ["**Feed non utilizzabile:** " + " ".join(v["errors"]), ""]
    cal, counts = v["calendar"], v["counts"]
    lines += [
        "### Validità del calendario",
        "",
        f"- Il feed contiene {num(counts['routes'])} linee, {num(counts['trips'])} corse e "
        f"{num(counts['stops'])} fermate.",
        f"- Calendario: dal **{cal['valid_from']}** al **{cal['valid_to']}** "
        f"({cal['service_dates']} giorni "
        f"con servizio). Scaduto: **{'SÌ' if cal['expired'] else 'no'}**. Ancora da iniziare: "
        f"{'sì' if cal['starts_in_future'] else 'no'}.",
        f"- Copre la data della demo ({day_label(DEMO_DATE)}): "
        f"**{'sì' if gtfs['demo_covered'] else 'NO'}**.",
        *(
            [
                "- Il feed non ha `calendar.txt`: il servizio è definito solo da "
                "`calendar_dates.txt`."
            ]
            if not v["files"]["has_calendar"]
            else []
        ),
        "",
        "Linee per tipo:",
        "",
        *route_type_lines(v["routes"]),
        "",
        "### Le linee che servono al progetto",
        "",
    ]
    rows = []
    for entry in v["lines_of_interest"]:
        if not entry["found"]:
            rows.append([entry["name"], "**NON TROVATA**", "-", "-", "-", "-", "-"])
            continue
        route = ", ".join(
            f"{r['route_id']} ({r['short_name'] or r['long_name']})" for r in entry["routes"]
        )
        for label in ("friday", "saturday"):
            day = entry["days"].get(label)
            if day:
                rows.append(
                    [
                        entry["name"] if label == "friday" else "",
                        route if label == "friday" else "",
                        f"{'venerdì' if label == 'friday' else 'sabato'} {day['date']}",
                        day["trips"],
                        (
                            f"{day['first_start']}–{day['last_start']} (arrivo {day['last_end']})"
                            if day["trips"]
                            else "nessuna corsa"
                        ),
                        day["trips_21_23"],
                        day["trips_12_18"],
                    ]
                )
    lines += table(
        [
            "Linea",
            "Codice nel feed",
            "Giorno tipo",
            "Corse",
            "Prima–ultima partenza",
            "Corse 21–23",
            "Corse 12–18",
        ],
        rows,
    )
    lines += [
        "",
        "Orari oltre le 24:00 (es. 25:30) sono dopo la mezzanotte. Le corse sono contate per ora "
        "di partenza dal "
        "primo capolinea, in entrambe le direzioni.",
        "",
        "### Stazioni degli itinerari proposti (Q6)",
        "",
        "Per ogni stazione citata in `03-engine-transit.md` 2, la fermata del feed **servita da "
        "quella linea**:",
        "",
        *table(
            ["Linea", "Stazione", "Fermate trovate (stop_id: nome)"],
            (
                [
                    c["line"],
                    c["station"],
                    "; ".join(f"{s['stop_id']}: {s['name']}" for s in c["stops"])
                    or "**NON TROVATA**",
                ]
                for c in gtfs["stations"]
            ),
        ),
        "",
        "### Arco Mirelli",
        "",
    ]
    if gtfs["arco"]:
        lines += table(
            ["stop_id", "Nome", "Linee che la servono", "Tipo"],
            (
                [
                    a["stop_id"],
                    a["name"],
                    ", ".join(a["lines"]),
                    "stazione metro" if a["metro"] else "fermata bus",
                ]
                for a in gtfs["arco"]
            ),
        )
    else:
        lines.append("**NON TROVATA** nel feed.")
    near = v["stops_near_rotonda_diaz"]["stops"]
    lines += [
        "",
        f"### Fermate entro {NEAR_RADIUS_M} m da Rotonda Diaz",
        "",
        f"{len(near)} fermate. Le più vicine:",
        "",
        *table(
            ["stop_id", "Nome", "Distanza (m)", "Linee"],
            (
                [s["stop_id"], s["stop_name"], s["distance_m"], ", ".join(s["lines"][:8])]
                for s in near[:10]
            ),
        ),
        "",
    ]
    return lines


def render_tomtom(tomtom: dict[str, Any] | None) -> list[str]:
    lines = ["## 3. TomTom (traffico in tempo reale)", ""]
    if tomtom is None:
        return lines + ["**NON ESEGUITA.** Lancia `uv run python -m scripts.tomtom_probe`.", ""]
    doc = tomtom["document"]
    rows = []
    for p in doc["points"]:
        s = p["summary"]
        if p["ok"] and s:
            ratio = pct(s["currentSpeed"], s["freeFlowSpeed"]) if s["freeFlowSpeed"] else "-"
            rows.append(
                [
                    p["label"],
                    "dati",
                    f"{s['currentSpeed']} / {s['freeFlowSpeed']} km/h",
                    ratio,
                    s["confidence"],
                    s["frc"],
                    f"{num(s['geometry_length_m'])} m",
                ]
            )
        else:
            rows.append([p["label"], f"**NESSUN DATO** ({p['error']})", "-", "-", "-", "-", "-"])
    return lines + [
        f"Sonda del {doc['fetched_at']} (file `{tomtom['name']}`): {doc['ok_points']} punti su "
        f"{len(doc['points'])} con dati.",
        "",
        *table(
            [
                "Punto",
                "Esito",
                "Velocità attuale / libera",
                "Rapporto",
                "Confidenza",
                "Classe (FRC)",
                "Lunghezza del tratto",
            ],
            rows,
        ),
        "",
        "Il rapporto è velocità attuale ÷ velocità a flusso libero (100% = strada scorrevole).",
        "",
    ]


def render_pmtiles(pmtiles: dict[str, Any] | None) -> list[str]:
    lines = ["## 4. Base map (PMTiles)", ""]
    if pmtiles is None:
        return lines + [
            "**NON DISPONIBILE.** Lancia `uv run python -m scripts.prepare_pmtiles`.",
            "",
        ]
    header, file_info = pmtiles["header"], pmtiles["file"]
    lines += [
        f"- Build Protomaps usata: "
        f"**{pmtiles['build'].isoformat() if pmtiles['build'] else 'sconosciuta'}**.",
        f"- Dimensione: {size_text(file_info['size'])}.",
    ]
    if header:
        west, south, east, north = header["bounds"]
        lines += [
            f"- Zoom {header['min_zoom']}–{header['max_zoom']}; {num(header['tiles'])} tile; area "
            f"(ovest, sud, est, nord): {west}, {south}, {east}, {north}.",
            f"- Richiesto: area {PMTILES_BBOX}, zoom massimo {MAXZOOM}.",
        ]
    return lines + [""]


def render_files(parts: dict[str, dict[str, Any] | None]) -> list[str]:
    rows = []
    for label, section in parts.items():
        if section is None:
            rows.append([label, "mancante", "-", "-", "-"])
            continue
        f = section["file"]
        rows.append(
            [
                label,
                "presente",
                f["fetched_at"] or "meta mancante",
                size_text(f["size"]),
                {True: "ok", False: "**DIVERSO**", None: "meta mancante"}[f["sha256_ok"]],
            ]
        )
    return [
        "## Stato dei file",
        "",
        *table(["Fonte", "File", "Acquisito il", "Dimensione", "Checksum (sha256) = meta"], rows),
        "",
    ]


def render_config(gtfs: dict[str, Any] | None) -> list[str]:
    if gtfs is None or gtfs["validation"]["errors"]:
        return []
    ids = gtfs["route_ids"]
    yaml_lines = ["transit:", "  route_classification:"]
    for key, names in ROUTE_GROUPS.items():
        values = ", ".join(f'"{rid}"' for name in names for rid in ids.get(name, []))
        yaml_lines.append(f"    {key}: {{ route_ids: [{values}] }}")
    return [
        "## Configurazione proposta (Q5)",
        "",
        "Codici linea da copiare in `config/engine.yaml` (F1-01) se confermi il punto relativo:",
        "",
        "```yaml",
        *yaml_lines,
        "```",
        "",
    ]


def summary_line(issues: list[Issue], parts: dict[str, dict[str, Any] | None]) -> str:
    counts = Counter(issue.level for issue in issues)
    text = (
        f"**In breve:** {counts['DECISIONE']} decisioni da prendere, {counts['ATTENZIONE']} "
        f"attenzioni, {counts['NOTA']} note. "
    )
    if any(section is None for section in parts.values()):
        return text + "**Mancano dei dati** (vedi «Stato dei file»)."
    if any(section["file"]["sha256_ok"] is not True for section in parts.values() if section):
        return text + "Tutti i dati sono presenti, ma alcuni checksum non coincidono."
    return text + "Tutti i dati sono presenti e i checksum coincidono."


def build_report(data_dir: Path, today: date | None = None) -> tuple[str, bool]:
    """Restituisce (testo markdown, True se manca almeno un artefatto)."""
    today = today or now_rome().date()
    osm, gtfs = load_osm(data_dir), load_gtfs(data_dir, today)
    tomtom, pmtiles = load_tomtom(data_dir), load_pmtiles(data_dir)
    issues = build_issues(osm, gtfs, tomtom, pmtiles)
    parts = {"Rete OSM": osm, "GTFS ANM": gtfs, "Sonda TomTom": tomtom, "Base map PMTiles": pmtiles}
    lines = [
        "# Report dati — Sentrix (cancello F0)",
        "",
        f"Generato il {now_rome().strftime('%Y-%m-%d %H:%M')} (ora di Roma) da "
        "`scripts/data_report.py`; "
        f"riferimento «oggi» = {day_label(today)}. Cartella dati: `{data_dir}`.",
        "",
        summary_line(issues, parts),
        "",
        *render_issues(issues),
        *render_files(parts),
        *render_osm(osm),
        *render_gtfs(gtfs),
        *render_tomtom(tomtom),
        *render_pmtiles(pmtiles),
        "## Verifiche non tecniche (non dipendono dai dati)",
        "",
        *[f"- {item}" for item in ADMIN_CHECKS],
        "",
        *render_config(gtfs),
    ]
    return "\n".join(lines).rstrip("\n") + "\n", any(section is None for section in parts.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genera il report dati per il cancello F0.")
    add_data_dir_arg(parser)
    args = parser.parse_args(argv)
    data_dir = args.data_dir or default_data_dir()
    text, incomplete = build_report(data_dir)
    target = data_dir / "report" / REPORT_NAME
    atomic_write_text(target, text)
    print(text)
    print(f"Report salvato in {target}", file=sys.stderr)
    if incomplete:
        print("ATTENZIONE: manca almeno un artefatto (vedi il report).", file=sys.stderr)
    return 1 if incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
