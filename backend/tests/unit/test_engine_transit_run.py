import dataclasses
import datetime as dt
import json

import pytest

from app.clock import now_rome
from app.data.gtfs import GtfsFeed, clear_feed_cache, load_feed
from app.engine.measures import MeasureError
from app.engine.transit import TransitNetwork
from app.engine.transit_run import TransitEngine, TransitResult
from app.models.config import EngineConfig
from tests.support import make_event
from tests.transit_world import (
    CLASSES,
    L1_ALFA_GAMMA,
    SLICE,
    WK_DAY,
    demand_of,
    itinerary,
    req,
    write_world_feed,
    zone,
)

AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    config = EngineConfig.from_yaml()
    assert config.time_slice_minutes == SLICE  # il mondo di prova conta 30 minuti
    return config


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory, config: EngineConfig) -> TransitEngine:
    clear_feed_cache()
    feed: GtfsFeed = load_feed(write_world_feed(tmp_path_factory.mktemp("run") / "feed"))
    network = TransitNetwork(feed, CLASSES, {"z": (itinerary(L1_ALFA_GAMMA),)})
    return TransitEngine(network, config)


EVENT = make_event(date=WK_DAY.isoformat())
DEMAND = demand_of(zone("z", 3000))


def run(engine: TransitEngine, *measures: object) -> TransitResult:
    return engine.run(EVENT, DEMAND, measures, id_prefix=("run7", "it2"), as_of=AS_OF)  # type: ignore[arg-type]


def value(result: TransitResult, name: str) -> float | int | str:
    prefix = "m.run7.it2.transit.arrival."
    return next(m.value for m in result.metrics.measures if m.id == prefix + name)


def test_il_risultato_porta_evento_livello_finestra_e_prefisso(engine: TransitEngine) -> None:
    result = run(engine)
    assert (result.event_id, result.level, result.window) == (EVENT.id, "mid", "arrival")
    assert result.applied == ()
    assert all(m.id.startswith("m.run7.it2.transit.arrival.") for m in result.metrics.measures)
    assert all(m.as_of == AS_OF for m in result.metrics.measures)
    assert value(result, "max_section_load.metro_line_1") == pytest.approx(1.2)
    assert value(result, "sections_overloaded") == 1


def test_stessi_input_stesso_risultato_byte_per_byte(engine: TransitEngine) -> None:
    first, second = run(engine).model_dump_json(), run(engine).model_dump_json()
    assert first == second
    dumped = json.loads(first)
    assert dumped["metrics"]["window"] == "arrival"
    assert {f["id"] for f in dumped["metrics"]["layers"]["event_area"]["features"]} == {
        "event_area"
    }
    assert dumped["metrics"]["sections"][0]["from_name"] == "BETA"


def test_come_as_of_senza_indicazione_vale_adesso(engine: TransitEngine) -> None:
    before = now_rome()
    result = engine.run(EVENT, DEMAND, (), id_prefix=("run7", "it2"))
    after = now_rome()
    stamps = {m.as_of for m in result.metrics.measures}
    assert len(stamps) == 1 and before <= stamps.pop() <= after


def test_le_misure_tpl_cambiano_i_numeri_e_si_dichiarano_applicate(engine: TransitEngine) -> None:
    """add_runs n=2 sulla L1: 4 corse in più (2 percorsi × 2) → BETA → GAMMA ne ha 2 + 2 = 4."""
    result = run(engine, req("a1", "add_runs", "metro_line_1", payload={"n": 2}))
    assert result.applied == ("a1",)
    assert value(result, "trips_in_window.metro_line_1") == 9
    # 6000 pax/h su 4 corse × 1250 × 2 = 10000 pax/h
    assert value(result, "max_section_load.metro_line_1") == pytest.approx(0.6)
    assert value(result, "sections_overloaded") == 0


def test_le_misure_di_un_altra_finestra_o_stradali_non_cambiano_nulla(
    engine: TransitEngine,
) -> None:
    other = req("a2", "add_runs", "metro_line_1", window="departure")
    road = req("a3", "traffic_post", "incrocio_1", window="arrival")
    result = run(engine, other, road)
    assert result.applied == ()
    assert value(result, "trips_in_window.metro_line_1") == 5


def test_una_fermata_sospesa_toglie_l_itinerario(engine: TransitEngine) -> None:
    """g1 sospesa: l'itinerario non c'è, la domanda va sul bus (che nel mondo di prova ha corse)."""
    result = run(engine, req("s1", "stop_suspension", "g1"))
    assert result.applied == ("s1",)
    assert value(result, "itinerary_used.z") == "autobus"
    assert value(result, "sections_overloaded") == 0


def test_il_livello_della_domanda_arriva_al_risultato(engine: TransitEngine) -> None:
    high = dataclasses.replace(DEMAND, level="high")
    result = engine.run(EVENT, high, (), id_prefix=("run7", "it2"), as_of=AS_OF)
    assert result.level == "high"


def test_una_misura_non_accettata_e_un_errore(engine: TransitEngine) -> None:
    with pytest.raises(MeasureError, match="a4"):
        run(engine, req("a4", "add_runs", "metro_line_1", state="RECEIVED"))


def test_una_misura_con_bersaglio_sbagliato_e_un_errore(engine: TransitEngine) -> None:
    with pytest.raises(MeasureError, match="metro_line_9"):
        run(engine, req("a5", "extend_hours", "metro_line_9"))
