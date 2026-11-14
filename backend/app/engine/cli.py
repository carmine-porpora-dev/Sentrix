import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import get_args

from pydantic import TypeAdapter

from app.clock import now_rome
from app.data.gtfs import GtfsError, load_feed
from app.data.paths import DataPaths, default_data_dir
from app.data.resolvers import ResolveError
from app.data.seeds import DEFAULT_SEEDS_DIR, SeedError, read_seed_events
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.demand import build_demand
from app.engine.graph import GraphError, load_road_graph
from app.engine.measures import MeasureError
from app.engine.metrics import MetricsError
from app.engine.run import RoadEngine, RoadResult, RoadTimings
from app.engine.transit import DisruptionError, TransitConfigError, load_transit_network
from app.engine.transit_metrics import OVERLOAD, SectionRow
from app.engine.transit_run import TransitEngine, TransitResult
from app.models.base import Window
from app.models.config import EngineConfig
from app.models.edge_overrides import EdgeOverrides
from app.models.operations import OperationRequest
from app.models.provenance import Measured
from app.models.run import AttendanceLevel

WINDOW_LABELS: dict[Window, str] = {"arrival": "arrivo", "departure": "deflusso"}
_REQUESTS = TypeAdapter(list[OperationRequest])


class CliError(Exception):
    """Un problema con gli argomenti o con i file indicati (il messaggio dice quale)."""


def load_measures(path: Path | None) -> list[OperationRequest]:
    """Le richieste del file `--measures` (nessuna se non è indicato)."""
    if path is None:
        return []
    try:
        return _REQUESTS.validate_python(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:  # JSON e validazione Pydantic sono ValueError
        raise CliError(f"Misure non leggibili in {path}: {exc}") from exc


def format_value(value: float | int | str) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _columns(header: tuple[str, ...], rows: Sequence[tuple[str, ...]], right: set[int]) -> str:
    """Le righe in colonne allineate: a destra quelle di `right`, le altre a sinistra."""
    widths = [max(len(row[i]) for row in (header, *rows)) for i in range(len(header))]

    def line(row: tuple[str, ...]) -> str:
        cells = [f"{cell:>{widths[i]}}" if i in right else f"{cell:<{widths[i]}}"
                 for i, cell in enumerate(row)]  # fmt: skip
        return "  ".join(cells).rstrip()

    return "\n".join([line(header), *(line(row) for row in rows)])


def _measures_table(measures: Sequence[Measured], marker: str) -> str:
    """Nome (senza il prefisso dell'id, fino a `marker` incluso), valore, unità e kind."""
    rows = [(m.id.split(marker, 1)[1], format_value(m.value), m.unit, m.kind) for m in measures]
    return _columns(("Metrica", "Valore", "Unità", "Kind"), rows, {1})


def format_table(result: RoadResult) -> str:
    """Le metriche stradali di una finestra. Il valore è allineato a destra."""
    return _measures_table(result.metrics.measures, f".road.{result.window}.")


def format_transit_table(result: TransitResult) -> str:
    """Le metriche numeriche del trasporto pubblico di una finestra, come `format_table`. Gli
    itinerari (testo) sono in `format_itineraries`."""
    marker = f".transit.{result.window}."
    numbers = [m for m in result.metrics.measures if not isinstance(m.value, str)]
    return _measures_table(numbers, marker)


def format_itineraries(result: TransitResult) -> str:
    """Come viaggiano le persone TPL di ogni zona (le metriche `itinerary_used.<zona>`)."""
    prefix = f".transit.{result.window}.itinerary_used."
    lines = [
        f"  {m.id.split(prefix, 1)[1]}: {m.value}"
        for m in result.metrics.measures
        if prefix in m.id
    ]
    return "\n".join(["Itinerari per zona:", *lines]) if lines else "Itinerari per zona: nessuna"


def _load_cell(ratio: float | None) -> str:
    if ratio is None:
        return "-"
    return f"{ratio:.2f}" + (" !" if ratio > OVERLOAD else "")


def format_sections(rows: Sequence[SectionRow]) -> str:
    """Le tratte di metro e funicolare con passeggeri: classe, tratta, corse, passeggeri/ora,
    capacità e carico (un `!` se supera 1)."""
    if not rows:
        return "Tratte con passeggeri: nessuna (la domanda TPL non usa metro o funicolari)"
    body = [
        (
            row.route_class,
            f"{row.from_name} → {row.to_name}",
            str(row.trips),
            f"{row.pax_h:.0f}",
            f"{row.capacity_pax_h:.0f}",
            _load_cell(row.load_ratio),
        )
        for row in rows
    ]
    header = ("Linea", "Tratta", "Corse", "Pax/h", "Capacità", "Carico")
    return "Carichi delle tratte:\n" + _columns(header, body, {2, 3, 4, 5})


def format_intersections(result: RoadResult) -> str:
    items = result.metrics.critical_intersections
    if not items:
        return "Incroci critici: nessuno (nessun cammino deviato)"
    lines = ["Incroci critici (bersagli possibili di un presidio):"]
    lines += [
        f"  {item.rank}. {item.label} · nodo {item.node} · v/c {item.vc:.2f} · arco {item.edge_key}"
        for item in items
    ]
    return "\n".join(lines)


def format_timings(timings: RoadTimings) -> str:
    return (
        f"Tempi: R {timings.reference_s:.2f} s, assegnazione {timings.assign_s:.2f} s, "
        f"metriche {timings.metrics_s:.2f} s, totale {timings.total_s:.2f} s"
    )


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run(
    event_id: str,
    level: AttendanceLevel,
    windows: Sequence[Window],
    measures_path: Path | None,
    *,
    data_dir: Path,
    seeds_dir: Path,
) -> int:
    events = {event.id: event for event in read_seed_events(seeds_dir)}
    if event_id not in events:
        raise CliError(
            f"Evento '{event_id}' non trovato in {seeds_dir}. Disponibili: "
            f"{', '.join(events) or '(nessuno)'}"
        )
    event = events[event_id]
    measures = load_measures(measures_path)
    iteration = max((request.iteration for request in measures), default=0)

    paths = DataPaths(data_dir)
    config = EngineConfig.from_yaml()
    graph = load_road_graph(paths.osm_graph, config, EdgeOverrides.from_yaml())
    engine = RoadEngine(graph, config)
    # il feed e gli itinerari si caricano prima di calcolare: un errore esce senza stampare nulla
    transit = TransitEngine(
        load_transit_network(load_feed(paths.gtfs_feed), config.transit), config
    )
    as_of = now_rome()  # un solo istante per tutti i numeri
    results: dict[Window, RoadResult] = {}
    transit_results: dict[Window, TransitResult] = {}
    for window in windows:
        out = engine.run(
            event, level, window, measures, id_prefix=("cli", f"it{iteration}"), as_of=as_of
        )
        results[window] = out.result
        persons: int = getattr(event.attendance, level)
        title = f"{event.name} ({event.id}) · {WINDOW_LABELS[window]} · livello {level}"
        print(f"\n== {title} ({persons} persone) ==")
        if out.result.applied:
            print(f"Misure applicate: {', '.join(out.result.applied)}")
        print(format_table(out.result))
        print(format_intersections(out.result))
        print(format_timings(out.timings))

        demand = build_demand(event, level, window, config, graph)
        by_bus = transit.run(
            event, demand, measures, id_prefix=("cli", f"it{iteration}"), as_of=as_of
        )
        transit_results[window] = by_bus
        print("\nTrasporto pubblico")
        if by_bus.applied:
            print(f"Misure applicate: {', '.join(by_bus.applied)}")
        print(format_transit_table(by_bus))
        print(format_itineraries(by_bus))
        print(format_sections(by_bus.metrics.sections))

    target = paths.out_dir / f"{event.id}_{level}.json"
    payload = {
        "event_id": event.id,
        "level": level,
        "windows": {window: result.model_dump(mode="json") for window, result in results.items()},
        "transit": {
            window: result.model_dump(mode="json") for window, result in transit_results.items()
        },
    }
    _write_atomic(target, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    print(f"\nNota: {STATIC_MODEL_ASSUMPTION}.\nRisultato completo: {target}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.engine.cli",
        description="Calcola le metriche stradali e del trasporto pubblico di un Evento.",
    )
    parser.add_argument("--event", required=True, help="id di un preset di seeds/events/")
    parser.add_argument("--level", required=True, choices=get_args(AttendanceLevel))
    parser.add_argument(
        "--window", choices=(*get_args(Window), "both"), default="both", help="default: both"
    )
    parser.add_argument(
        "--measures", type=Path, help="file JSON con una lista di OperationRequest accettate"
    )
    parser.add_argument(
        "--data-dir", type=Path, help="default: $DATA_DIR oppure <radice del repository>/data"
    )
    parser.add_argument(
        "--seeds-dir", type=Path, default=DEFAULT_SEEDS_DIR, help="default: seeds/events"
    )
    args = parser.parse_args(argv)
    windows: tuple[Window, ...] = get_args(Window) if args.window == "both" else (args.window,)
    try:
        return run(
            args.event,
            args.level,
            windows,
            args.measures,
            data_dir=args.data_dir or default_data_dir(),
            seeds_dir=args.seeds_dir,
        )
    except (
        CliError,
        SeedError,
        GraphError,
        GtfsError,
        TransitConfigError,
        DisruptionError,
        MeasureError,
        ResolveError,
        MetricsError,
    ) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
