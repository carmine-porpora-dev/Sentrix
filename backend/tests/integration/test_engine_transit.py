import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, get_args

import networkx as nx
import pytest

from app.data.seeds import read_seed_events
from app.engine.cli import main as cli_main
from app.engine.demand import Demand, build_demand
from app.engine.transit import TransitNetwork, disrupted_stops
from app.engine.transit_loads import assign_transit
from app.engine.transit_run import TransitEngine, TransitResult
from app.models.base import WINDOWS, Window
from app.models.config import EngineConfig
from app.models.event import Event
from app.models.run import AttendanceLevel
from tests.integration.conftest import FEED_PATH
from tests.transit_world import assert_persons_conserved, real_transit_fingerprint, req

pytestmark = pytest.mark.realdata

LEVELS: tuple[AttendanceLevel, ...] = get_args(AttendanceLevel)  # low, mid, high
SEED_IDS = sorted(event.id for event in read_seed_events())
AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
PREFIX = ("t", "it0")
BACKEND = Path(__file__).resolve().parents[2]
# Un calcolo costa ~0,1 s (2,6 s una tantum per feed e itinerari): oltre 2 s qualcosa è cambiato.
RUN_BUDGET_S = 2.0

RunKey = tuple[str, AttendanceLevel, Window]


@pytest.fixture(scope="module")
def engine(transit_network: TransitNetwork, road_config: EngineConfig) -> TransitEngine:
    return TransitEngine(transit_network, road_config)


@pytest.fixture(scope="module")
def demands(
    road_graph: nx.MultiDiGraph, road_config: EngineConfig, seed_events: dict[str, Event]
) -> dict[RunKey, Demand]:
    return {
        (event_id, level, window): build_demand(
            seed_events[event_id], level, window, road_config, road_graph
        )
        for event_id in SEED_IDS
        for level in LEVELS
        for window in WINDOWS
    }


@pytest.fixture(scope="module")
def runs(
    engine: TransitEngine, demands: dict[RunKey, Demand], seed_events: dict[str, Event]
) -> dict[RunKey, TransitResult]:
    """Dodici calcoli (2 preset × 3 livelli × 2 finestre), uno per volta, condivisi dai test."""
    return {
        key: engine.run(seed_events[key[0]], demand, (), id_prefix=PREFIX, as_of=AS_OF)
        for key, demand in demands.items()
    }


def metric(result: TransitResult, name: str) -> float | int | str:
    return next(m.value for m in result.metrics.measures if m.id.endswith(f".{name}"))


# --- itinerari e interruzioni sul feed vero -------------------------------------------------------


def test_gli_itinerari_di_engine_yaml_si_risolvono_sul_feed_vero(
    transit_network: TransitNetwork, road_config: EngineConfig
) -> None:
    resolved = transit_network.itineraries
    assert set(resolved) == {zone.id for zone in road_config.demand.zones}
    assert sum(len(itineraries) for itineraries in resolved.values()) == 15
    for itineraries in resolved.values():
        for itinerary in itineraries:
            for leg in itinerary.legs:
                assert leg.board.stop_ids and leg.alight.stop_ids
    # Fuorigrotta scende ad Arco Mirelli: le due banchine del feed sono quelle dell'interruzione
    leg = resolved["fuorigrotta"][0].legs[0]
    assert (leg.route_class, leg.alight.name) == ("metro_line_6", "Arco Mirelli")
    assert leg.alight.stop_ids == {"6236", "6237"}


def test_l_interruzione_del_match_e_arco_mirelli_solo_nell_arrivo(
    transit_network: TransitNetwork, seed_events: dict[str, Event]
) -> None:
    feed = transit_network.feed
    match = seed_events["match_2027"]
    assert disrupted_stops(feed, match, "arrival") == {"6236", "6237"}
    assert disrupted_stops(feed, match, "departure") == frozenset()
    assert disrupted_stops(feed, seed_events["regate_sep_2026"], "arrival") == frozenset()


# --- i dodici calcoli -----------------------------------------------------------------------------


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_ogni_calcolo_e_coerente(
    runs: dict[RunKey, TransitResult],
    demands: dict[RunKey, Demand],
    transit_network: TransitNetwork,
    road_config: EngineConfig,
    seed_events: dict[str, Event],
    event_id: str,
    level: AttendanceLevel,
    window: Window,
) -> None:
    key = (event_id, level, window)
    result, demand = runs[key], demands[key]
    ids = [m.id for m in result.metrics.measures]
    assert len(ids) == len(set(ids)) and all(
        i.startswith(f"m.t.it0.transit.{window}.") for i in ids
    )
    names = {i.split(f".transit.{window}.", 1)[1] for i in ids}
    zones = {z.zone_id for z in demand.zones if z.transit_persons > 0}
    assert names == {
        "stops_overloaded",
        "sections_overloaded",
        *(f"max_section_load.{k}" for k in ("metro_line_1", "metro_line_6", "funicular")),
        *(f"trips_in_window.{k}" for k in ("metro_line_1", "metro_line_6", "funicular")),
        "walk_people",
        *(f"itinerary_used.{z}" for z in zones),
    }
    # i due preset sono fuori dal feed: orario tipo, e le corse sono una stima
    assert {m.kind for m in result.metrics.measures if "trips_in_window" in m.id} == {"estimate"}
    assert all(
        m.source == "engine.transit v1" and m.as_of == AS_OF for m in result.metrics.measures
    )
    # le persone non si perdono né si contano due volte
    loads = assign_transit(
        transit_network, road_config.transit, seed_events[event_id], demand,
        road_config.time_slice_minutes,
    )  # fmt: skip
    assert_persons_conserved(loads, demand)
    # una fermata chiusa non ha un carico; le tratte con passeggeri hanno capacità
    for row in result.metrics.sections:
        assert row.pax_h > 0 and row.capacity_pax_h > 0 and row.load_ratio is not None
        assert row.load_ratio == pytest.approx(row.pax_h / row.capacity_pax_h)
        # le zone che la riempiono sommano al suo carico, e sono zone con domanda TPL
        assert sum(pax for _, pax in row.by_zone) == pytest.approx(row.pax_h)
        assert {zone for zone, _ in row.by_zone} <= zones
    # il numero in evidenza dice da chi è fatto: ogni classe con passeggeri elenca le sue zone
    for kind in ("metro_line_1", "metro_line_6", "funicular"):
        top = next(m for m in result.metrics.measures if m.id.endswith(f"max_section_load.{kind}"))
        rows = [r for r in result.metrics.sections if r.route_class == kind]
        if rows:
            fill = next(i for i in top.inputs if i.startswith("passeggeri sulla tratta più carica"))
            listed = max(rows, key=lambda r: r.load_ratio or 0.0).by_zone
            assert all(f"{zone} " in fill for zone, _ in listed)
            assert "primo itinerario disponibile" in top.method
        else:
            assert top.value == 0.0 and "primo itinerario" not in top.method


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("event_id", SEED_IDS)
def test_con_piu_affluenza_i_passeggeri_crescono_in_proporzione(
    runs: dict[RunKey, TransitResult],
    demands: dict[RunKey, Demand],
    event_id: str,
    window: Window,
) -> None:
    """La disponibilità degli itinerari non dipende dal livello: le persone TPL sono proporzionali
    all'affluenza (stessa fascia, stesse quote) e con loro i passeggeri di ogni tratta."""
    totals = []
    for level in LEVELS:
        key = (event_id, level, window)
        pax = sum(r.pax_h for r in runs[key].metrics.sections)
        totals.append((demands[key].attendance, demands[key].transit_persons, pax))
    for (a0, p0, x0), (a1, p1, x1) in zip(totals, totals[1:], strict=False):
        assert a0 < a1 and p0 < p1 and x0 < x1
        assert p1 / a1 == pytest.approx(p0 / a0, rel=1e-9)
        assert x1 / a1 == pytest.approx(x0 / a0, rel=1e-9)


def test_un_calcolo_costa_meno_del_budget(
    engine: TransitEngine, demands: dict[RunKey, Demand], seed_events: dict[str, Event]
) -> None:
    for key, demand in demands.items():
        started = time.perf_counter()
        engine.run(seed_events[key[0]], demand, (), id_prefix=PREFIX, as_of=AS_OF)
        assert time.perf_counter() - started < RUN_BUDGET_S, key


# --- il Match con e senza Arco Mirelli ------------------------------------------------------------


def loads_report(label: str, result: TransitResult) -> None:
    print(f"\n-- {label}")
    for row in result.metrics.sections:
        if row.route_class != "funicular":
            flag = " !" if row.load_ratio is not None and row.load_ratio > 1 else ""
            print(
                f"   {row.route_class:<13} {row.from_name} → {row.to_name:<20} "
                f"{row.trips} corse · {row.pax_h:7.0f} / {row.capacity_pax_h:6.0f} pax/h = "
                f"{row.load_ratio:.2f}{flag}"
            )


def l1_l6(result: TransitResult) -> list[tuple[Any, ...]]:
    return [
        (r.route_class, r.from_name, r.to_name, r.trips, r.pax_h, r.capacity_pax_h)
        for r in result.metrics.sections
        if r.route_class in ("metro_line_1", "metro_line_6")
    ]


def test_match_arrivo_con_e_senza_arco_mirelli(
    engine: TransitEngine,
    demands: dict[RunKey, Demand],
    seed_events: dict[str, Event],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Il Match (livello mid, arrivo) con l'interruzione di Arco Mirelli e senza, sull'orario tipo.

    Il 19/12 la L6 non ha corse alle 13:30–14:00: la chiusura non cambia nessun carico (le zone
    della L6 vanno già sul bus). Con `extend_hours` sulla L6 le corse ci sono e la zona di
    Fuorigrotta, che scende ad Arco Mirelli, passa all'itinerario successivo solo se la fermata è
    chiusa: le tratte che arrivano ad Arco Mirelli restano scariche."""
    match = seed_events["match_2027"]
    free = match.model_copy(update={"transit_disruptions": []})
    demand = demands[("match_2027", "mid", "arrival")]
    extend = req("e1", "extend_hours", "metro_line_6", payload={"until": "23:59"})
    results = {
        (label, with_extend): engine.run(
            event, demand, (extend,) if with_extend else (), id_prefix=PREFIX, as_of=AS_OF
        )
        for label, event in (("con", match), ("senza", free))
        for with_extend in (False, True)
    }
    with capsys.disabled():
        for (label, with_extend), result in results.items():
            suffix = " + extend_hours L6" if with_extend else ""
            loads_report(f"Match 2027 · arrivo · mid · {label} Arco Mirelli{suffix}", result)

    def closed(result: TransitResult) -> set[str]:
        stops = result.metrics.layers["stops"].features
        return {str(f.id) for f in stops if f.properties["closed"]}

    assert closed(results[("con", False)]) == {"6236", "6237"}
    assert closed(results[("senza", False)]) == set()
    # con la L6 ferma la chiusura non cambia niente, né sulla L1 né sulla L6
    assert l1_l6(results[("con", False)]) == l1_l6(results[("senza", False)])
    assert metric(results[("con", False)], "trips_in_window.metro_line_6") == 0
    # la L1 non ha niente a che fare con Arco Mirelli: uguale in tutti e quattro i casi
    l1 = {k: [r for r in l1_l6(v) if r[0] == "metro_line_1"] for k, v in results.items()}
    assert len({repr(rows) for rows in l1.values()}) <= 2  # extend_hours non tocca la L1
    assert l1[("con", False)] == l1[("senza", False)]
    assert l1[("con", True)] == l1[("senza", True)] == l1[("con", False)]
    # con le corse della L6: senza la chiusura Fuorigrotta scende ad Arco Mirelli, con la chiusura
    # no
    with_stop, without_stop = results[("con", True)], results[("senza", True)]
    assert str(metric(without_stop, "itinerary_used.fuorigrotta")).startswith(
        "itinerario 1: Mostra → Arco Mirelli (metro_line_6)"
    )
    assert not str(metric(with_stop, "itinerary_used.fuorigrotta")).startswith("itinerario 1")
    arrives = [r for r in l1_l6(without_stop) if r[2] == "ARCO MIRELLI"]
    assert arrives and arrives[0][4] > 0
    assert not [r for r in l1_l6(with_stop) if r[2] == "ARCO MIRELLI"]
    reasons = next(
        m.assumptions
        for m in with_stop.metrics.measures
        if m.id.endswith("itinerary_used.fuorigrotta")
    )
    assert "itinerario 1: fermata indisponibile (Arco Mirelli)" in reasons
    # le corse della L6 sono ora una simulazione (le ha aggiunte la misura)
    assert {
        m.kind for m in with_stop.metrics.measures if m.id.endswith("trips_in_window.metro_line_6")
    } == {"simulated"}  # noqa: E501


def run_cli(args: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    assert cli_main(args) == 0
    return capsys.readouterr().out


def test_la_cli_stampa_i_carichi_l1_e_l6_con_e_senza_arco_mirelli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    road_graph_path: Path,
    seed_events: dict[str, Event],
) -> None:
    """La riga di comando sul Match: i carichi di L1 e L6 stampati, con la chiusura (il preset) e
    senza (lo stesso Evento senza interruzioni, in una cartella di preset a parte)."""
    data, seeds = tmp_path / "data", tmp_path / "seeds"
    (data / "osm").mkdir(parents=True)
    (data / "osm" / road_graph_path.name).symlink_to(road_graph_path)
    (data / "gtfs").symlink_to(FEED_PATH.parent)
    seeds.mkdir()
    match = seed_events["match_2027"]
    free = match.model_copy(update={"id": "match_senza_arco_mirelli", "transit_disruptions": []})
    for event in (match, free):
        (seeds / f"{event.id}.json").write_text(event.model_dump_json(), encoding="utf-8")
    measures = tmp_path / "misure.json"
    extend = req("e1", "extend_hours", "metro_line_6", payload={"until": "23:59"})
    measures.write_text(json.dumps([extend.model_dump(mode="json")]), encoding="utf-8")

    def cli(event_id: str, *extra: str) -> str:
        args = ["--data-dir", str(data), "--seeds-dir", str(seeds), "--event", event_id]
        return run_cli([*args, "--level", "mid", "--window", "arrival", *extra], capsys)

    outputs = {
        (event_id, with_extend): cli(
            event_id, *(("--measures", str(measures)) if with_extend else ())
        )
        for event_id in (match.id, free.id)
        for with_extend in (False, True)
    }
    # il blocco dei carichi (le tabelle delle metriche nominano anche max_section_load.metro_line_6)
    blocks = {
        key: out[out.index("Carichi delle tratte:") : out.index("\nNota:")]
        for key, out in outputs.items()
    }
    with capsys.disabled():
        for (event_id, with_extend), block in blocks.items():
            print(f"\n=== CLI {event_id}{' + extend_hours L6' if with_extend else ''}")
            print(block)
    assert all("metro_line_1  " in block for block in blocks.values())
    # solo con le corse della L6 compaiono le sue tratte, e solo senza la chiusura quella che arriva
    # ad Arco Mirelli
    assert "metro_line_6  " not in blocks[(match.id, False)]
    assert "metro_line_6  " in blocks[(match.id, True)]
    assert "→ ARCO MIRELLI" in blocks[(free.id, True)]
    assert "→ ARCO MIRELLI" not in blocks[(match.id, True)]


# --- determinismo ---------------------------------------------------------------------------------


def test_stessi_input_stesso_risultato_in_processi_con_hash_diversi(
    engine: TransitEngine,
    demands: dict[RunKey, Demand],
    seed_events: dict[str, Event],
) -> None:
    """Un processo nuovo con un altro `PYTHONHASHSEED` (gli insiemi di stringhe cambiano ordine)
    dà gli stessi byte di questo, su entrambi i preset e finestre, con una misura."""
    extend = req("e1", "extend_hours", "metro_line_6")
    digest = hashlib.sha256()
    for event_id in SEED_IDS:
        for window in WINDOWS:
            result = engine.run(
                seed_events[event_id],
                demands[(event_id, "mid", window)],
                [extend] if window == "arrival" else [],
                id_prefix=("fp", "it1"),
                as_of=AS_OF,
            )
            digest.update(result.model_dump_json().encode())
    code = (
        "from tests.transit_world import real_transit_fingerprint; "
        "print(real_transit_fingerprint())"
    )
    other = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "777", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert other.stdout.strip() == digest.hexdigest()
    assert other.stdout.strip() == real_transit_fingerprint()
