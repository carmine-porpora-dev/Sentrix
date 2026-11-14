import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.data.gtfs import GtfsFeed, clear_feed_cache, load_feed
from app.data.paths import REPO_ROOT
from app.engine.demand import Demand, ZoneDemand
from app.engine.transit import ResolvedItinerary, ResolvedLeg, TransitNetwork
from app.engine.transit_loads import TransitLoads
from app.engine.transit_run import TransitEngine
from app.models.base import Window
from app.models.config import EngineConfig, TransitConfig
from tests.support import make_event
from tests.transit_world import (
    BAND,
    CLASSES,
    D_DUE,
    D_UNO,
    L1_ALFA_GAMMA,
    L6_BETA_EPSILON,
    S6_DAY,
    SLICE,
    WK_DAY,
    assert_persons_conserved,
    demand_of,
    determinism_probe,
    disruption,
    itinerary,
    req,
    run_loads,
    write_world_feed,
    zone,
)

BACKEND = Path(__file__).resolve().parents[2]
NOON = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def feed(tmp_path_factory: pytest.TempPathFactory) -> GtfsFeed:
    clear_feed_cache()
    return load_feed(write_world_feed(tmp_path_factory.mktemp("gate") / "feed"))


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


# --- conservazione dei passeggeri -----------------------------------------------------------------

# cinque zone che usano tutti i modi: L1 fino a GAMMA, L6 (se c'è) e poi L1 e a piedi, solo
# autobus, solo a piedi, una funicolare. Le banchine di arrivo sono tutte vicine all'area.
ITINERARIES: dict[str, list[ResolvedItinerary]] = {
    "metro": [itinerary(L1_ALFA_GAMMA)],
    "scelta": [itinerary(L6_BETA_EPSILON), itinerary(L1_ALFA_GAMMA, walk=True)],
    "bus": [],
    "piedi": [itinerary()],
    "funi": [itinerary(ResolvedLeg("funicular", D_DUE, D_UNO))],
}
ZONES = (
    zone("metro", 700, walk=10),
    zone("scelta", 300, walk=50),
    zone("bus", 1000),
    zone("piedi", 120),
    zone("funi", 80),
)
NOT_IN_BAND = (dt.time(12, 0), dt.time(12, 30))  # nessuna corsa di autobus


def zones_of(window: Window) -> tuple[ZoneDemand, ...]:
    """Le zone del mondo di prova. Nel deflusso la funicolare si prende a d1, lontana dall'area e
    quindi fuori dall'elenco delle fermate vicine: la sua zona resta fuori, per poter contare le
    persone che arrivano alle banchine."""
    return ZONES if window == "arrival" else tuple(z for z in ZONES if z.zone_id != "funi")


def scenario(**changes: Any) -> dict[str, Any]:
    return {"day": WK_DAY, "window": "arrival", "band": BAND, **changes}


SCENARIOS = {
    "base": scenario(),
    "con la L6": scenario(day=S6_DAY),
    "deflusso": scenario(window="departure"),
    "discesa chiusa": scenario(disruptions=[disruption("GAMMA", "g1", "g2")]),
    "stazione di passaggio chiusa": scenario(disruptions=[disruption("BETA", "b1", "b2")]),
    "una fermata bus sospesa": scenario(suspended=("u1",)),
    "tutte le fermate bus sospese": scenario(suspended=("u1", "u2")),
    "fermata bus e discesa chiuse": scenario(
        suspended=("u1",), disruptions=[disruption("GAMMA", "g1", "g2")]
    ),
    "senza autobus nella fascia": scenario(band=NOT_IN_BAND),
    "deflusso con salita chiusa": scenario(
        window="departure", disruptions=[disruption("GAMMA", "g1", "g2")]
    ),
}


def loads_of(
    feed: GtfsFeed, config: TransitConfig, spec: dict[str, Any]
) -> tuple[TransitLoads, Demand]:
    demand = demand_of(*zones_of(spec["window"]), window=spec["window"], band=spec["band"])
    loads = run_loads(
        feed, config, ITINERARIES, demand, spec["day"],
        disruptions=spec.get("disruptions"), suspended=spec.get("suspended", ()),
    )  # fmt: skip
    return loads, demand


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_i_passeggeri_si_conservano(feed: GtfsFeed, config: EngineConfig, name: str) -> None:
    """Tutta la domanda TPL della fascia finisce da qualche parte, una volta sola."""
    loads, demand = loads_of(feed, config.transit, SCENARIOS[name])
    to_pax_h = 60 / SLICE
    by_mode = assert_persons_conserved(loads, demand)
    # chi viaggia con un itinerario scende (sale) a una banchina: nient'altro vi arriva
    assert sum(s.pax_h - s.bus_pax_h for s in loads.stops) == pytest.approx(
        by_mode["itinerary"] * to_pax_h
    )
    # nessuna tratta porta più passeggeri di chi usa un itinerario
    assert all(s.pax_h <= by_mode["itinerary"] * to_pax_h + 1e-9 for s in loads.sections.values())


def test_la_quota_di_una_fermata_chiusa_va_alle_aperte_vicine(
    feed: GtfsFeed, config: EngineConfig
) -> None:
    """u1 sospesa: tutta la domanda bus (1000 persone = 2000 pax/h) arriva a u2, a 167 m × 1,3."""
    loads, _ = loads_of(feed, config.transit, SCENARIOS["una fermata bus sospesa"])
    shares = {s.stop.stop_id: s.bus_pax_h for s in loads.stops}
    assert shares["u1"] == 0 and shares["u2"] == pytest.approx(2000)
    base, _ = loads_of(feed, config.transit, SCENARIOS["base"])
    split = {s.stop.stop_id: s.bus_pax_h for s in base.stops}
    assert split["u1"] == pytest.approx(2000 * 360 / 540)  # in proporzione alla capacità
    assert split["u2"] == pytest.approx(2000 * 180 / 540)


# --- un solo modello di fermata indisponibile (F3-REF) -------------------------------------------


@pytest.mark.parametrize("window", ["arrival", "departure"])
def test_un_interruzione_e_una_sospensione_sono_la_stessa_cosa(
    feed: GtfsFeed, config: EngineConfig, window: Window
) -> None:
    """La fermata chiusa da un'interruzione dell'Evento e quella sospesa da `stop_suspension`
    entrano nello stesso insieme: stessi carichi, stesse fermate chiuse, stesso itinerario
    scartato."""
    spec = scenario(window=window)
    by_event, _ = loads_of(feed, config.transit, {**spec, "disruptions": [disruption("G", "g1")]})
    by_measure, _ = loads_of(feed, config.transit, {**spec, "suspended": ("g1",)})
    assert by_event.closed_stops == by_measure.closed_stops == frozenset({"g1"})
    assert by_event == by_measure

    network = TransitNetwork(feed, CLASSES, {z: tuple(i) for z, i in ITINERARIES.items()})
    event = make_event(date=WK_DAY.isoformat(), transit_disruptions=[disruption("G", "g1")])
    plain = make_event(date=WK_DAY.isoformat())
    demand = demand_of(*zones_of(window), window=window)
    engine = TransitEngine(network, config)
    via_event = engine.run(event, demand, (), id_prefix=("g", "it0"), as_of=NOON)
    via_measure = engine.run(
        plain, demand, [req("s1", "stop_suspension", "g1", window=window)],
        id_prefix=("g", "it0"), as_of=NOON,
    )  # fmt: skip
    values = lambda r: [(m.id, m.value, m.kind) for m in r.metrics.measures]  # noqa: E731
    assert values(via_event) == values(via_measure)
    assert via_event.metrics.layers == via_measure.metrics.layers
    assert via_event.metrics.sections == via_measure.metrics.sections


# --- extend_hours riapre un itinerario ------------------------------------------------------------


def test_extend_hours_rende_di_nuovo_disponibile_un_itinerario_e_porta_capacita(
    feed: GtfsFeed, config: EngineConfig
) -> None:
    """Il 20/12 la L6 (S6a 08:20, S6b 08:40: una ogni 20 minuti) non ha corse alle 09:00–09:30:
    l'itinerario non c'è. Con extend_hours fino alle 09:30 ci sono le corse delle 09:00 e delle
    09:20, l'itinerario torna e la tratta BETA → EPSILON ha 2 corse × 290 × 2 = 1160 pax/h."""
    network = TransitNetwork(feed, CLASSES, {"z": (itinerary(L6_BETA_EPSILON),)})
    engine = TransitEngine(network, config)
    event = make_event(date=S6_DAY.isoformat())
    demand = demand_of(zone("z", 100), band=(dt.time(9, 0), dt.time(9, 30)))

    def used(result: Any) -> str:
        return next(str(m.value) for m in result.metrics.measures if "itinerary_used.z" in m.id)

    def l6_trips(result: Any) -> int:
        return next(
            int(m.value) for m in result.metrics.measures if "trips_in_window.metro_line_6" in m.id
        )

    before = engine.run(event, demand, (), id_prefix=("g", "it0"), as_of=NOON)
    # nessuna corsa L6 e nessun autobus nella fascia: la zona resta non servita
    assert used(before) == "non servita (nessun autobus nelle fermate vicine)"
    assert l6_trips(before) == 0
    assert before.metrics.sections == ()

    extend = req("e1", "extend_hours", "metro_line_6", payload={"until": "09:30"})
    after = engine.run(event, demand, (extend,), id_prefix=("g", "it1"), as_of=NOON)
    assert used(after) == "itinerario 1: BETA → EPSILON (metro_line_6)"
    assert l6_trips(after) == 2
    (row,) = after.metrics.sections
    assert (row.trips, row.capacity_pax_h, row.pax_h) == (2, 1160, 200)
    assert row.load_ratio == pytest.approx(200 / 1160)


# --- determinismo ---------------------------------------------------------------------------------


def test_stessi_input_stesso_risultato_in_processi_con_hash_diversi(tmp_path: Path) -> None:
    """Gli insiemi di stringhe cambiano ordine da un processo all'altro (`PYTHONHASHSEED`): il
    risultato, con interruzioni, sospensioni e corse aggiunte, non deve dipenderne."""
    code = (
        "import sys; from pathlib import Path; from tests.transit_world import determinism_probe; "
        "print(determinism_probe(Path(sys.argv[1])))"
    )
    fingerprints = {determinism_probe(tmp_path / "in_process")}
    for seed in ("1", "2024"):
        out = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path / f"seed{seed}")],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        fingerprints.add(out.stdout.strip())
    assert len(fingerprints) == 1, fingerprints


# --- contratto con le fixture del frontend --------------------------------------------------------

FIXTURES = REPO_ROOT / "frontend" / "src" / "api" / "fixtures"


def fixture_transit_metrics() -> dict[str, tuple[str, str]]:
    """Coda dell'id → (unità, kind) di ogni metrica TPL delle fixture del frontend."""
    found: dict[str, tuple[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            id_ = node.get("id")
            if isinstance(id_, str) and "unit" in node and id_.startswith("m."):
                key = id_.split(".", 3)[3]
                if key.startswith("transit."):  # non i delta (`delta_baseline.transit…`)
                    found[key] = (node["unit"], node["kind"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for iteration in (0, 1, 2):
        walk(json.loads((FIXTURES / "run_metrics" / f"iteration_{iteration}.json").read_text()))
    return found


def engine_result(feed: GtfsFeed, config: EngineConfig, window: Window) -> Any:
    network = TransitNetwork(feed, CLASSES, {"z": (itinerary(L1_ALFA_GAMMA),)})
    event = make_event(date=WK_DAY.isoformat())
    demand = demand_of(zone("z", 3000, walk=200), window=window)
    return TransitEngine(network, config).run(event, demand, (), id_prefix=("c", "it0"), as_of=NOON)


def test_il_motore_produce_le_metriche_tpl_delle_fixture_con_le_stesse_unita(
    feed: GtfsFeed, config: EngineConfig
) -> None:
    """Il frontend nasce sul mock (D12): le metriche TPL che mostra hanno gli id e le unità del
    motore, e il kind è uno di quelli che il motore può dare per quella metrica."""
    expected = fixture_transit_metrics()
    assert set(expected) == {
        f"transit.{window}.{name}"
        for window in ("arrival", "departure")
        for name in (
            "stops_overloaded",
            "sections_overloaded",
            "trips_in_window.metro_line_6",
            "max_section_load.metro_line_1",
            "max_section_load.metro_line_6",
            "max_section_load.funicular",
        )
    }
    produced: dict[str, tuple[str, str]] = {}
    for window in ("arrival", "departure"):
        for m in engine_result(feed, config, window).metrics.measures:
            produced[m.id.split(".", 3)[3]] = (m.unit, m.kind)
    for key, (unit, kind) in expected.items():
        assert produced[key][0] == unit, key
        allowed = {"real", "estimate", "simulated"} if "trips_in_window" in key else {"estimate"}
        assert kind in allowed, key


def layer_properties(name: str) -> set[str]:
    features = json.loads((FIXTURES / "run_layers" / f"{name}_it0.json").read_text())["features"]
    return {key for feature in features for key in feature["properties"]}


@pytest.mark.parametrize("name", ["stops", "sections", "event_area"])
def test_i_layer_hanno_le_proprieta_delle_fixture(
    feed: GtfsFeed, config: EngineConfig, name: str
) -> None:
    """Le proprietà dei layer del motore e del mock coincidono (il mock ha in più `schematic`)."""
    result = engine_result(feed, config, "arrival")
    produced = {k for f in result.metrics.layers[name].features for k in f.properties}
    assert layer_properties(name) - {"schematic"} == produced
