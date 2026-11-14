import argparse
import math
import os
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import osmnx as ox

# Gli errori di Overpass stanno in un modulo privato di OSMnx (versione fissata in uv.lock).
# Gli errori di rete di `requests` derivano da OSError.
from osmnx._errors import InsufficientResponseError, ResponseStatusCodeError

from app.data.paths import DataPaths
from scripts.common import (
    DownloadError,
    add_data_dir_arg,
    default_data_dir,
    meta_path_for,
    now_rome_iso,
    write_meta,
)

BBox = tuple[float, float, float, float]  # west, south, east, north

# Area di studio approvata: Bagnoli - Capodichino - Piscinola (00 1).
STUDY_AREA_BBOX: BBox = (14.14, 40.80, 14.30, 40.90)
# Tre nuovi tentativi dopo il primo, con attese crescenti (00 2.1).
RETRY_DELAYS_S: tuple[int, ...] = (10, 30, 60)
KMH_PER_MPH = 1.609344

LICENSE = "ODbL 1.0 - (c) OpenStreetMap contributors"

RETRIABLE_ERRORS = (OSError, ResponseStatusCodeError, InsufficientResponseError)


# --------------------------------------------------------------------------------------
# Parser dei tag OSM
# --------------------------------------------------------------------------------------


def _as_list(value: object) -> list[object]:
    """Normalizza un valore OSMnx (scalare, lista, NaN, None) in una lista piatta."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, list | tuple | set | frozenset):
        flat: list[object] = []
        for item in value:
            flat.extend(_as_list(item))
        return flat
    return [value]


def _tokens(value: object) -> list[str]:
    """Come _as_list, ma restituisce stringhe e separa anche i valori OSM `a;b`."""
    tokens: list[str] = []
    for item in _as_list(value):
        tokens.extend(t.strip() for t in str(item).split(";") if t.strip())
    return tokens


_LANES_RE = re.compile(r"\d+(?:\.0+)?")
_MAXSPEED_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?", re.IGNORECASE)


def _lanes_token(token: str) -> int | None:
    if not _LANES_RE.fullmatch(token):
        return None
    lanes = int(float(token))
    return lanes if lanes > 0 else None


def _maxspeed_token(token: str) -> int | None:
    """Solo valori numerici: 'none', 'signals', 'walk', 'IT:urban'... non sono numeri (null)."""
    match = _MAXSPEED_RE.fullmatch(token)
    if match is None:
        return None
    speed = float(match.group(1))
    if (match.group(2) or "").lower() == "mph":
        speed *= KMH_PER_MPH
    kmh = round(speed)
    return kmh if kmh > 0 else None


def _parse(value: object, single: Callable[[str], int | None]) -> tuple[list[int], list[str]]:
    parsed: list[int] = []
    unparsed: list[str] = []
    for token in _tokens(value):
        number = single(token)
        if number is None:
            unparsed.append(token)
        else:
            parsed.append(number)
    return parsed, unparsed


def parse_lanes(value: object) -> int | None:
    """Numero di corsie da un tag `lanes` (stringa, lista, NaN). Più valori -> il minimo.

    OSMnx produce una lista quando fonde segmenti con valori diversi: il minimo è il collo di
    bottiglia che limita la capacità.
    """
    parsed, _ = _parse(value, _lanes_token)
    return min(parsed) if parsed else None


def parse_maxspeed(value: object) -> int | None:
    """Limite in km/h da un tag `maxspeed` ("50", "30 mph", liste). Più valori -> il minimo."""
    parsed, _ = _parse(value, _maxspeed_token)
    return min(parsed) if parsed else None


# --------------------------------------------------------------------------------------
# Arricchimento del grafo
# --------------------------------------------------------------------------------------


@dataclass
class EnrichmentReport:
    edges: int = 0
    lanes_parsed: int = 0
    lanes_unparsed: Counter[str] = field(default_factory=Counter)
    maxspeed_parsed: int = 0
    maxspeed_unparsed: Counter[str] = field(default_factory=Counter)
    missing_highway: int = 0


def _first_str(value: object) -> str | None:
    for item in _as_list(value):
        text = str(item).strip()
        if text:
            return text
    return None


def _join_unique(value: object) -> str | None:
    seen: list[str] = []
    for item in _as_list(value):
        text = str(item).strip()
        if text and text not in seen:
            seen.append(text)
    return "; ".join(seen) if seen else None


def enrich_graph(graph: nx.MultiDiGraph) -> EnrichmentReport:
    """Aggiunge a ogni arco length_m, highway, lanes, maxspeed_kmh, name (00 2.1), in place.

    `maxspeed` (tag grezzo) e `osmid` restano come li ha prodotti OSMnx.
    """
    report = EnrichmentReport()
    for _u, _v, _key, data in graph.edges(keys=True, data=True):
        report.edges += 1
        data["length_m"] = float(data["length"])

        highway = _first_str(data.get("highway"))
        if highway is None:
            report.missing_highway += 1
            data.pop("highway", None)
        else:
            data["highway"] = highway

        lanes, bad_lanes = _parse(data.pop("lanes", None), _lanes_token)
        report.lanes_unparsed.update(bad_lanes)
        if lanes:
            data["lanes"] = min(lanes)
            report.lanes_parsed += 1

        speeds, bad_speeds = _parse(data.get("maxspeed"), _maxspeed_token)
        report.maxspeed_unparsed.update(bad_speeds)
        if speeds:
            data["maxspeed_kmh"] = min(speeds)
            report.maxspeed_parsed += 1

        name = _join_unique(data.pop("name", None))
        if name is not None:
            data["name"] = name
    return report


# --------------------------------------------------------------------------------------
# Download, file e meta
# --------------------------------------------------------------------------------------


def download_graph(bbox: BBox) -> nx.MultiDiGraph:
    # Niente cache di OSMnx: crea ./cache fuori da ogni .gitignore e --force deve riscaricare.
    ox.settings.use_cache = False
    west, south, east, north = bbox
    return ox.graph_from_bbox(
        (west, south, east, north), network_type="drive", simplify=True, retain_all=False
    )


def download_with_retry(
    bbox: BBox,
    *,
    download: Callable[[BBox], nx.MultiDiGraph] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    delays: tuple[int, ...] = RETRY_DELAYS_S,
) -> nx.MultiDiGraph:
    """Scarica il grafo; riprova sugli errori di rete/Overpass con le attese `delays`.

    Gli errori di programmazione o di input (ValueError, KeyError...) non si riprovano.
    `download` (default: download_graph, risolto alla chiamata) serve ai test.
    """
    fetch = download or download_graph
    attempts = len(delays) + 1
    for attempt in range(1, attempts + 1):
        try:
            return fetch(bbox)
        except RETRIABLE_ERRORS as error:
            if attempt == attempts:
                raise DownloadError(
                    f"Overpass non raggiungibile dopo {attempts} tentativi (ultimo errore: "
                    f"{type(error).__name__}: {error}). Riprova più tardi, oppure copia in "
                    f"DATA_DIR/osm/ un grafo già preparato altrove (graph_drive.graphml e il suo "
                    f".meta.json)."
                ) from error
            wait = delays[attempt - 1]
            print(
                f"Tentativo {attempt}/{attempts} fallito ({type(error).__name__}); "
                f"riprovo tra {wait} s."
            )
            sleep(wait)
    raise AssertionError("irraggiungibile")  # pragma: no cover


def _validated_bbox(parser: argparse.ArgumentParser, values: Iterable[float]) -> BBox:
    west, south, east, north = values
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        parser.error("bbox non valido: servono WEST < EAST e SOUTH < NORTH, in gradi.")
    return (west, south, east, north)


def prepare(data_dir: Path, bbox: BBox, *, force: bool) -> int:
    graph_path = DataPaths(data_dir).osm_graph
    if not force and graph_path.exists() and meta_path_for(graph_path).exists():
        print(f"{graph_path} esiste già: salto (usa --force per riscaricare).")
        return 0

    print(f"Scarico il grafo 'drive' da Overpass, bbox {bbox} (può richiedere qualche minuto)...")
    try:
        graph = download_with_retry(bbox)
    except DownloadError as error:
        print(f"ERRORE: {error}", file=sys.stderr)
        return 1
    fetched_at = now_rome_iso()

    report = enrich_graph(graph)
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    temp = graph_path.with_name(graph_path.name + ".part")
    ox.save_graphml(graph, temp)
    os.replace(temp, graph_path)

    nodes = graph.number_of_nodes()
    notes = (
        f"OSMnx {ox.__version__}, network_type=drive, simplify=True, retain_all=False, "
        f"bbox(west,south,east,north)={bbox}; {nodes} nodi, {report.edges} archi. "
        "lanes e maxspeed_kmh assenti (null) dove il tag manca o non è numerico; se OSMnx ha fuso "
        "segmenti con valori diversi si usa il minimo. Valori di riserva NON applicati (li applica "
        "il motore)."
    )
    meta = write_meta(
        graph_path,
        source_url=f"{ox.settings.overpass_url}/interpreter",
        fetched_at=fetched_at,
        license=LICENSE,
        notes=notes,
    )
    print_summary(graph_path, meta, nodes, report)
    return 0


def print_summary(graph_path: Path, meta: Path, nodes: int, report: EnrichmentReport) -> None:
    def pct(count: int) -> str:
        return f"{count} ({100 * count / report.edges:.1f}%)" if report.edges else "0"

    print(f"Salvato {graph_path}\n        {meta}")
    print(f"Nodi: {nodes}  Archi: {report.edges}")
    print(f"Archi con lanes numerico: {pct(report.lanes_parsed)}")
    print(f"Archi con maxspeed numerico: {pct(report.maxspeed_parsed)}")
    for label, counter in (
        ("lanes", report.lanes_unparsed),
        ("maxspeed", report.maxspeed_unparsed),
    ):
        if counter:
            top = ", ".join(f"{value!r}: {count}" for value, count in counter.most_common(5))
            print(f"Valori di {label} non numerici (lasciati null): {top}")
    if report.missing_highway:
        print(f"ATTENZIONE: {report.missing_highway} archi senza 'highway'.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scarica e prepara il grafo stradale OSM (drive).")
    parser.add_argument("--force", action="store_true", help="riscarica anche se i file esistono")
    add_data_dir_arg(parser)
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=STUDY_AREA_BBOX,
        help="default: area di studio approvata (00 1)",
    )
    args = parser.parse_args(argv)
    bbox = _validated_bbox(parser, args.bbox)
    return prepare(args.data_dir or default_data_dir(), bbox, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
