import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from app.data.osm_graph import load_osm_graph
from app.data.paths import DataPaths
from app.data.resolvers import (
    edge_key,
    edge_point,
    edges_named,
    normalize_name,
    osm_name_parts,
)
from app.geo import haversine_m
from app.models.live_segments import LiveSegmentsConfig
from app.models.yamlconfig import CONFIG_DIR
from scripts.common import add_data_dir_arg, atomic_write_text, default_data_dir

OUTPUT_PATH = CONFIG_DIR / "live_segments.yaml"

DISTINCT_M = 150.0  # distanza minima tra i punti di tratti DIVERSI
SAME_STREET_M = 500.0  # distanza minima tra i due punti dello stesso tratto
JUNCTION_OFFSET_M = 150.0  # distanza dal nodo dello svincolo, lungo la Tangenziale
MAINLINE_NAME = "Tangenziale di Napoli"
MAINLINE_HIGHWAY = "motorway"


@dataclass(frozen=True)
class SegmentSpec:
    id: str
    label: str
    osm_name: str  # nome ESATTO dell'arco in OSM (non sempre uguale all'etichetta della spec)
    points: int = 1
    ramp: str | None = (
        None  # solo per gli svincoli: nome OSM della rampa; `osm_name` è la Tangenziale
    )


# Nell'ordine di 08 2. «Viale Dohrn» non c'è più: per il suo punto, su un arco di 33 m,
# TomTom restituisce lo stesso identico segmento di Via Caracciolo (prova reale, F1-10): una
# richiesta in più a ogni aggiornamento per mostrare la stessa linea due volte.
# Le etichette sono quelle della spec; `osm_name` è come si chiama la strada in OSM (verificato sul
# grafo acquisito: «Via Marina» è «Via Nuova Marina», «Galleria Laziale» è «Galleria di
# Posillipo (Laziale)», «Via Acton» è «Via Ferdinando Acton»).
SEGMENTS: tuple[SegmentSpec, ...] = (
    SegmentSpec("via_caracciolo", "Via Caracciolo", "Via Francesco Caracciolo"),
    SegmentSpec("riviera_chiaia", "Riviera di Chiaia", "Riviera di Chiaia", points=2),
    SegmentSpec("via_partenope", "Via Partenope", "Via Partenope"),
    SegmentSpec("via_posillipo", "Via Posillipo", "Via Posillipo"),
    SegmentSpec("galleria_laziale", "Galleria Laziale", "Galleria di Posillipo (Laziale)"),
    SegmentSpec("galleria_vittoria", "Galleria della Vittoria", "Galleria della Vittoria"),
    SegmentSpec("via_acton", "Via Acton", "Via Ferdinando Acton"),
    SegmentSpec(
        "corso_vittorio_emanuele", "Corso Vittorio Emanuele", "Corso Vittorio Emanuele", points=2
    ),
    SegmentSpec(
        "tangenziale_fuorigrotta",
        "Tangenziale svincolo Fuorigrotta",
        MAINLINE_NAME,
        ramp="Uscita Fuorigrotta",
    ),  # fmt: skip
    SegmentSpec(
        "tangenziale_vomero", "Tangenziale svincolo Vomero", MAINLINE_NAME, ramp="Uscita Vomero"
    ),
    SegmentSpec(
        "tangenziale_capodichino",
        "Tangenziale svincolo Capodichino",
        MAINLINE_NAME,
        ramp="Uscita Capodichino - Secondigliano",
    ),  # fmt: skip
    SegmentSpec("via_marina", "Via Marina", "Via Nuova Marina"),
)


class PickError(Exception):
    """Un tratto non si può costruire con i dati che ci sono."""


@dataclass(frozen=True)
class Picked:
    id: str
    label: str
    lat: float
    lon: float
    edge: str  # arco OSM da cui viene il punto, "u-v-k"
    osm_name: str  # il suo nome OSM, per intero
    length_m: float


# --- scelta ------------------------------------------------------------------------------------


def _exactly_named(
    graph: nx.MultiDiGraph, name: str
) -> list[tuple[tuple[int, int, int], dict[str, object]]]:
    """Gli archi con QUEL nome. `edges_named` ricadrebbe sui nomi che contengono le stesse parole
    quando non ce n'è nessuno esatto («Via Nuova Marina dei Gigli» per «Via Nuova Marina»):
    per scegliere un punto di una strada specifica non è accettabile."""
    wanted = normalize_name(name)
    return [
        (key, data)
        for key, data in edges_named(graph, name)
        if wanted in [normalize_name(part) for part in osm_name_parts(data.get("name"))]
    ]


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distanza tra due punti (lon, lat)."""
    return float(haversine_m(a[1], a[0], (b[1], b[0])))


def _street_points(
    graph: nx.MultiDiGraph, spec: SegmentSpec, taken: list[tuple[float, float]]
) -> list[tuple[tuple[int, int, int], dict[str, object], tuple[float, float]]]:
    named = _exactly_named(graph, spec.osm_name)
    if not named:
        raise PickError(f"{spec.id}: nessun arco OSM chiamato «{spec.osm_name}»")
    ranked = sorted(named, key=lambda kd: (-float(str(kd[1]["length_m"])), kd[0]))
    picked: list[tuple[tuple[int, int, int], dict[str, object], tuple[float, float]]] = []
    for key, data in ranked:
        point = edge_point(graph, key, 0.5)
        if any(_distance_m(point, other) < DISTINCT_M for other in taken):
            continue
        if any(_distance_m(point, p[2]) < SAME_STREET_M for p in picked):
            continue
        picked.append((key, data, point))
        if len(picked) == spec.points:
            return picked
    raise PickError(
        f"{spec.id}: trovo {len(picked)} punti su {spec.points} tra gli archi di «{spec.osm_name}» "
        f"(distanti almeno {DISTINCT_M:.0f} m dagli altri tratti e {SAME_STREET_M:.0f} m tra loro)"
    )


def _junction_point(
    graph: nx.MultiDiGraph, spec: SegmentSpec, taken: list[tuple[float, float]]
) -> tuple[tuple[int, int, int], dict[str, object], tuple[float, float]]:
    assert spec.ramp is not None
    ramps = _exactly_named(graph, spec.ramp)
    if not ramps:
        raise PickError(f"{spec.id}: nessun arco OSM chiamato «{spec.ramp}»")
    best: tuple[float, tuple[int, int, int], dict[str, object], int] | None = None
    for node in sorted({n for (u, v, _), _d in ramps for n in (u, v)}):
        incident = [
            (key, data)
            for u, v, k, data in [
                *graph.in_edges(node, keys=True, data=True),
                *graph.out_edges(node, keys=True, data=True),
            ]
            if (key := (u, v, k))
            and data.get("name") == spec.osm_name
            and data.get("highway") == MAINLINE_HIGHWAY
        ]
        for key, data in incident:
            length = float(str(data["length_m"]))
            if best is None or (length, tuple(-x for x in key)) > (
                best[0],
                tuple(-x for x in best[1]),
            ):
                best = (length, key, data, node)
    if best is None:
        raise PickError(
            f"{spec.id}: la rampa «{spec.ramp}» non si stacca da un arco «{spec.osm_name}» "
            f"({MAINLINE_HIGHWAY})"
        )
    length, key, data, node = best
    fraction = min(JUNCTION_OFFSET_M / length, 0.5)
    # La geometria di un arco va da u a v: se lo svincolo è in v si parte dalla fine.
    point = edge_point(graph, key, fraction if key[0] == node else 1 - fraction)
    if any(_distance_m(point, other) < DISTINCT_M for other in taken):
        raise PickError(f"{spec.id}: il punto dello svincolo coincide con un altro tratto")
    return key, data, point


def pick_segments(
    graph: nx.MultiDiGraph, specs: tuple[SegmentSpec, ...] = SEGMENTS
) -> list[Picked]:
    result: list[Picked] = []
    taken: list[tuple[float, float]] = []
    for spec in specs:
        if spec.ramp is not None:
            found = [_junction_point(graph, spec, taken)]
        else:
            found = _street_points(graph, spec, taken)
        for index, (key, data, (lon, lat)) in enumerate(found, start=1):
            suffix = f" (punto {index})" if spec.points > 1 else ""
            result.append(
                Picked(
                    id=f"{spec.id}_{index}" if spec.points > 1 else spec.id,
                    label=spec.label + suffix,
                    lat=round(lat, 6),
                    lon=round(lon, 6),
                    edge=edge_key(*key),
                    osm_name=str(data.get("name")),
                    length_m=round(float(str(data["length_m"]))),
                )
            )
            taken.append((lon, lat))
    return result


# --- file ---------------------------------------------------------------------------------------


def render_yaml(picked: list[Picked]) -> str:
    lines = ["segments:"]
    for p in picked:
        entry = (
            f"  - {{ id: {p.id}, label: {json.dumps(p.label, ensure_ascii=False)}, "
            f"lat: {p.lat}, lon: {p.lon} }}"
        )
        lines.append(f"{entry}  # arco {p.edge}: «{p.osm_name}», {p.length_m} m")
    return "\n".join(lines) + "\n"


def run(data_dir: Path, output: Path, *, dry_run: bool) -> int:
    graph_path = DataPaths(data_dir).osm_graph
    if not graph_path.is_file():
        print(f"Manca il grafo stradale {graph_path}: esegui prima `make data`.", file=sys.stderr)
        return 2
    graph = load_osm_graph(graph_path)
    try:
        picked = pick_segments(graph)
    except PickError as exc:
        print(f"Tratti non costruibili: {exc}", file=sys.stderr)
        return 1
    text = render_yaml(picked)
    LiveSegmentsConfig.from_yaml_text(text)  # mai scrivere un file che il modello rifiuterebbe
    for p in picked:
        print(f"{p.id:28} ({p.lat:.6f}, {p.lon:.6f})  arco {p.edge}  «{p.osm_name}» {p.length_m} m")
    if dry_run:
        print("--dry-run: il file non è stato scritto.")
    elif output.is_file() and output.read_text(encoding="utf-8") == text:
        print(f"{output}: già aggiornato.")
    else:
        atomic_write_text(output, text)
        print(f"Scritto {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sceglie i tratti LIVE sul grafo OSM locale.")
    add_data_dir_arg(parser)
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_PATH, help="default: config/live_segments.yaml"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="stampa i tratti senza scrivere il file"
    )
    args = parser.parse_args(argv)
    return run(args.data_dir or default_data_dir(), args.output, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
