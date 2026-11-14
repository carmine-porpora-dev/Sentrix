import datetime as dt
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox
import pytest

from app.data.gtfs import clear_feed_cache
from app.data.paths import FEED_NAME
from app.engine.cli import (
    format_intersections,
    format_itineraries,
    format_sections,
    format_table,
    format_timings,
    format_transit_table,
    format_value,
    load_measures,
    main,
)
from app.engine.metrics import CriticalIntersection
from app.engine.run import RoadResult, RoadTimings
from app.engine.transit_metrics import SectionRow, TransitMetrics
from app.engine.transit_run import TransitResult
from app.models.config import EngineConfig
from app.models.provenance import make_measured
from tests.support import HUB, build_star_raw_graph, engine_points, make_event, make_request
from tests.transit_world import write_feed_for_itineraries

NOON = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml()


@pytest.fixture(scope="module")
def raw_star(config: EngineConfig) -> nx.MultiDiGraph:
    return build_star_raw_graph(config)


@pytest.fixture(scope="module")
def built_feed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Il feed di `write_feed_for_itineraries`, scritto una volta e copiato da ogni test."""
    event = make_event()
    return write_feed_for_itineraries(
        tmp_path_factory.mktemp("feed") / FEED_NAME,
        EngineConfig.from_yaml().transit,
        event.date,
        event.area_center,
    )


@pytest.fixture
def world(tmp_path: Path, raw_star: nx.MultiDiGraph, built_feed: Path) -> dict[str, Path]:
    """`data/osm/graph_drive.graphml`, `data/gtfs/anm` e un preset `test_event`, ciascuno nella sua
    cartella."""
    data, seeds = tmp_path / "data", tmp_path / "seeds"
    (data / "osm").mkdir(parents=True)
    ox.save_graphml(raw_star, data / "osm" / "graph_drive.graphml")
    shutil.copytree(built_feed, data / "gtfs" / FEED_NAME)
    clear_feed_cache()
    seeds.mkdir()
    (seeds / "test_event.json").write_text(make_event().model_dump_json(), encoding="utf-8")
    return {"data": data, "seeds": seeds, "out": data / "out"}


def cli(world: dict[str, Path], *args: str) -> int:
    return main(["--data-dir", str(world["data"]), "--seeds-dir", str(world["seeds"]), *args])


def written(world: dict[str, Path], level: str = "mid") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((world["out"] / f"test_event_{level}.json").read_text())
    return data


def inbound_key_of_car_destination(config: EngineConfig) -> str:
    point = config.demand.car_destinations[0].point
    return f"{HUB}-{HUB + 1 + engine_points(config).index(point)}-0"


# --- cosa stampa ----------------------------------------------------------------------------------


def test_stampa_la_tabella_di_entrambe_le_finestre(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli(world, "--event", "test_event", "--level", "mid") == 0
    out = capsys.readouterr().out
    arrival = "== Evento di prova (test_event) · arrivo · livello mid (36000 persone) =="
    departure = "== Evento di prova (test_event) · deflusso · livello mid (36000 persone) =="
    assert out.index(arrival) < out.index(departure)
    for column in ("Metrica", "Valore", "Unità", "Kind"):
        assert column in out
    assert out.count("veh_hours") == 2 and out.count("Incroci critici") == 2
    assert out.count("Tempi: R ") == 2
    assert out.count("Misure applicate") == 0
    assert "Nota: modello macroscopico statico non calibrato, non una previsione." in out
    assert f"Risultato completo: {world['out'] / 'test_event_mid.json'}" in out


def test_il_livello_cambia_titolo_e_nome_del_file(world: dict[str, Path], capsys: Any) -> None:
    assert cli(world, "--event", "test_event", "--level", "high", "--window", "arrival") == 0
    assert "livello high (72000 persone)" in capsys.readouterr().out
    assert (world["out"] / "test_event_high.json").is_file()
    assert written(world, "high")["level"] == "high"
    assert not (world["out"] / "test_event_mid.json").exists()


def test_una_sola_finestra(world: dict[str, Path], capsys: Any) -> None:
    assert cli(world, "--event", "test_event", "--level", "mid", "--window", "departure") == 0
    out = capsys.readouterr().out
    assert "deflusso" in out and "arrivo" not in out
    assert list(written(world)["windows"]) == ["departure"]


def test_la_tabella_ha_nomi_valori_unita_e_kind(world: dict[str, Path]) -> None:
    cli(world, "--event", "test_event", "--level", "mid", "--window", "arrival")
    result = RoadResult.model_validate(written(world)["windows"]["arrival"])
    lines = format_table(result).splitlines()
    assert lines[0].split() == ["Metrica", "Valore", "Unità", "Kind"]
    assert len(lines) == len(result.metrics.measures) + 1
    by_name = {line.split()[0]: line for line in lines[1:]}
    veh_hours = next(m for m in result.metrics.measures if m.id.endswith(".veh_hours"))
    assert by_name["veh_hours"].split() == [
        "veh_hours",
        f"{veh_hours.value:.3f}",
        "veic·h",
        "simulated",
    ]
    assert by_name["unassigned_pairs"].split() == ["unassigned_pairs", "0", "n", "simulated"]
    # il nome non porta il prefisso dell'id
    assert not any(name.startswith("m.") or ".road." in name for name in by_name)
    # colonne allineate: l'unità e il kind iniziano nella stessa colonna in ogni riga, e il valore
    # (a destra) finisce nella stessa colonna
    unit_col, kind_col = lines[0].index("Unità"), lines[0].index("Kind")
    value_end = lines[0].index("Valore") + len("Valore")
    for line, measure in zip(lines[1:], result.metrics.measures, strict=True):
        assert line[unit_col:].split()[0] == measure.unit
        assert line[kind_col:] == measure.kind
        assert line[:value_end].split()[-1] == format_value(measure.value)


def test_le_colonne_non_sono_piu_strette_dell_intestazione(world: dict[str, Path]) -> None:
    cli(world, "--event", "test_event", "--level", "mid", "--window", "arrival")
    result = RoadResult.model_validate(written(world)["windows"]["arrival"])
    short = make_measured(
        id="m.cli.it0.road.arrival.x",
        value=1,
        unit="n",
        kind="simulated",
        source="test",
        method="test",
        inputs=["prova"],
    )
    tiny = result.model_copy(update={"metrics": replace(result.metrics, measures=(short,))})
    assert format_table(tiny).splitlines() == [
        "Metrica  Valore  Unità  Kind",
        "x             1  n      simulated",
    ]


def test_incroci_critici_e_tempi(world: dict[str, Path]) -> None:
    cli(world, "--event", "test_event", "--level", "mid", "--window", "arrival")
    result = RoadResult.model_validate(written(world)["windows"]["arrival"])
    assert format_intersections(result) == "Incroci critici: nessuno (nessun cammino deviato)"
    items = (
        CriticalIntersection(1, 1242073124, 3.3678, "3572177101-1242073124-0", "Via Tasso"),
        CriticalIntersection(2, 7, 1.2, "1-7-0", "Incrocio 7"),
    )
    with_items = result.model_copy(
        update={"metrics": replace(result.metrics, critical_intersections=items)}
    )
    assert format_intersections(with_items).splitlines() == [
        "Incroci critici (bersagli possibili di un presidio):",
        "  1. Via Tasso · nodo 1242073124 · v/c 3.37 · arco 3572177101-1242073124-0",
        "  2. Incrocio 7 · nodo 7 · v/c 1.20 · arco 1-7-0",
    ]


def test_formato_dei_tempi() -> None:
    assert format_timings(RoadTimings(0.071, False, 0.48, 0.213, 0.764)) == (
        "Tempi: R 0.07 s, assegnazione 0.48 s, metriche 0.21 s, totale 0.76 s"
    )


# --- cosa scrive ----------------------------------------------------------------------------------


def test_il_file_ha_le_due_finestre_e_si_rilegge(world: dict[str, Path]) -> None:
    cli(world, "--event", "test_event", "--level", "mid")
    data = written(world)
    assert (data["event_id"], data["level"]) == ("test_event", "mid")
    assert list(data["windows"]) == ["arrival", "departure"]
    instants = set()
    for window, raw in data["windows"].items():
        result = RoadResult.model_validate(raw)
        assert (result.event_id, result.level, result.window) == ("test_event", "mid", window)
        assert all(m.id.startswith(f"m.cli.it0.road.{window}.") for m in result.metrics.measures)
        instants |= {m.as_of for m in result.metrics.measures}
    assert len(instants) == 1  # un solo istante per tutto il risultato
    assert list(world["out"].glob("*.part")) == []


def test_due_lanci_con_lo_stesso_istante_danno_lo_stesso_file(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.engine.cli.now_rome", lambda: NOON)
    target = world["out"] / "test_event_mid.json"
    cli(world, "--event", "test_event", "--level", "mid")
    first = target.read_bytes()
    target.unlink()
    cli(world, "--event", "test_event", "--level", "mid")
    assert target.read_bytes() == first
    for raw in json.loads(first)["windows"].values():
        measures = RoadResult.model_validate(raw).metrics.measures
        assert {m.as_of for m in measures} == {NOON}


def test_un_nuovo_lancio_sostituisce_il_file(world: dict[str, Path]) -> None:
    cli(world, "--event", "test_event", "--level", "mid")
    cli(world, "--event", "test_event", "--level", "mid", "--window", "arrival")
    assert list(written(world)["windows"]) == ["arrival"]


def test_data_dir_di_default_e_la_variabile_d_ambiente(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(world["data"]))
    code = main(["--seeds-dir", str(world["seeds"]), "--event", "test_event", "--level", "low"])
    assert code == 0
    assert (world["out"] / "test_event_low.json").is_file()


# --- le misure ------------------------------------------------------------------------------------


def test_misure_accettate_dal_file(
    world: dict[str, Path], config: EngineConfig, tmp_path: Path, capsys: Any
) -> None:
    destinations = [
        f"{HUB}-{HUB + 1 + engine_points(config).index(d.point)}-0"
        for d in config.demand.car_destinations[:2]
    ]
    requests = [
        make_request(
            f"act_{n}", iteration=iteration, type="close_road", target=target, window="arrival",
            state="ACCEPTED",
        )
        for n, iteration, target in ((7, 1, destinations[0]), (8, 2, destinations[1]))
    ] + [
        # non stradale e di un'altra finestra: nessun effetto, ma conta per l'iterazione (la 3)
        make_request(
            "act_9", iteration=3, type="citizen_notice", target="avviso", window="departure",
            state="ACCEPTED",
        )
    ]  # fmt: skip
    measures = tmp_path / "misure.json"
    measures.write_text(json.dumps([r.model_dump(mode="json") for r in requests]), encoding="utf-8")
    assert cli(world, "--event", "test_event", "--level", "mid", "--measures", str(measures)) == 0
    out = capsys.readouterr().out
    assert out.count("Misure applicate: act_7, act_8") == 1  # solo nella finestra di arrivo
    assert out.index("Misure applicate") < out.index("deflusso")
    windows = written(world)["windows"]
    assert windows["arrival"]["applied"] == ["act_7", "act_8"]
    assert windows["departure"]["applied"] == []
    arrival = RoadResult.model_validate(windows["arrival"])
    assert all(m.id.startswith("m.cli.it3.road.arrival.") for m in arrival.metrics.measures)
    unassigned = next(m for m in arrival.metrics.measures if m.id.endswith(".unassigned_pairs"))
    assert isinstance(unassigned.value, int) and unassigned.value > 0  # destinazioni chiuse


def test_senza_file_di_misure_non_ci_sono_misure() -> None:
    assert load_measures(None) == []


# --- il trasporto pubblico ------------------------------------------------------------------------
# Feed di `write_feed_for_itineraries`: una corsa ogni 10 minuti per senso. La fascia di arrivo
# 13:30–14:00 ha 3 corse per tratta; la fascia ha 10.000 persone e la zona gate_metro_north l'8 %,
# tutte sul trasporto pubblico (engine.yaml, metro_gate): 800 persone = 1.600 pax/h (× 60/30).


def sections_of(window: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    rows = window["metrics"]["sections"]
    return {(r["route_class"], f"{r['from_name']} → {r['to_name']}"): r for r in rows}


def test_stampa_il_trasporto_pubblico_di_entrambe_le_finestre(
    world: dict[str, Path], capsys: Any
) -> None:
    assert cli(world, "--event", "test_event", "--level", "mid") == 0
    out = capsys.readouterr().out
    assert out.count("\nTrasporto pubblico\n") == 2
    assert out.count("Carichi delle tratte:") == 2 and out.count("Itinerari per zona:") == 2
    assert out.count("max_section_load.metro_line_1") == 2
    # prima la strada, poi il trasporto pubblico, della stessa finestra
    arrival_road = out.index("== Evento di prova (test_event) · arrivo")
    first_transit = out.index("Trasporto pubblico")
    departure_road = out.index("== Evento di prova (test_event) · deflusso")
    assert arrival_road < first_transit < departure_road
    assert "  gate_metro_north: itinerario 1: Piscinola → Municipio (metro_line_1)" in out


def test_i_carichi_delle_tratte_sono_quelli_calcolati_a_mano(
    world: dict[str, Path], config: EngineConfig
) -> None:
    cli(world, "--event", "test_event", "--level", "mid", "--window", "arrival")
    rows = sections_of(written(world)["transit"]["arrival"])
    row = rows[("metro_line_1", "Piscinola → Municipio")]
    capacity = 3 * config.transit.vehicle_capacity["metro_line_1"] * 2  # 3 corse, × 60/30
    assert (row["trips"], row["capacity_pax_h"], row["pax_h"]) == (3, capacity, 1600)
    assert row["load_ratio"] == pytest.approx(1600 / capacity)
    # la L6 raccoglie chi arriva dalla L1 e dal porto: più persone, meno capacità
    l6 = rows[("metro_line_6", "Municipio → San Pasquale")]
    assert (
        l6["pax_h"] > 1600
        and l6["capacity_pax_h"] == 3 * config.transit.vehicle_capacity["metro_line_6"] * 2
    )


def test_il_file_ha_anche_il_trasporto_pubblico_di_ogni_finestra(world: dict[str, Path]) -> None:
    cli(world, "--event", "test_event", "--level", "mid")
    data = written(world)
    assert list(data["transit"]) == ["arrival", "departure"]
    for window, raw in data["transit"].items():
        result = TransitResult.model_validate(raw)
        assert (result.event_id, result.level, result.window) == ("test_event", "mid", window)
        assert all(m.id.startswith(f"m.cli.it0.transit.{window}.") for m in result.metrics.measures)
        assert set(result.metrics.layers) == {"stops", "sections", "event_area"}
    # la strada resta dov'era
    assert list(data["windows"]) == ["arrival", "departure"]


def test_il_tempo_di_strada_e_trasporto_hanno_lo_stesso_istante(world: dict[str, Path]) -> None:
    cli(world, "--event", "test_event", "--level", "mid")
    data = written(world)
    instants = {
        m["as_of"]
        for part in ("windows", "transit")
        for window in data[part].values()
        for m in window["metrics"]["measures"]
    }
    assert len(instants) == 1


def test_una_misura_tpl_del_file_cambia_l_offerta(
    world: dict[str, Path], config: EngineConfig, tmp_path: Path, capsys: Any
) -> None:
    """add_runs n=2 sulla L1: 2 corse per percorso nella fascia in più (5 → 3 + 2 per tratta)."""
    request = make_request(
        "act_1", type="add_runs", target="metro_line_1", window="arrival", state="ACCEPTED",
        payload={"n": 2},
    )  # fmt: skip
    measures = tmp_path / "misure.json"
    measures.write_text(json.dumps([request.model_dump(mode="json")]), encoding="utf-8")
    assert cli(world, "--event", "test_event", "--level", "mid", "--measures", str(measures)) == 0
    out = capsys.readouterr().out
    assert out.count("Misure applicate: act_1") == 1  # il trasporto pubblico, solo in arrivo
    data = written(world)["transit"]
    assert data["arrival"]["applied"] == ["act_1"] and data["departure"]["applied"] == []
    ids = [m["id"] for m in data["arrival"]["metrics"]["measures"]]
    assert all(i.startswith("m.cli.it1.transit.arrival.") for i in ids)  # l'iterazione del file
    row = sections_of(data["arrival"])[("metro_line_1", "Piscinola → Municipio")]
    assert row["trips"] == 5
    assert row["capacity_pax_h"] == 5 * config.transit.vehicle_capacity["metro_line_1"] * 2
    trips = next(
        m
        for m in data["arrival"]["metrics"]["measures"]
        if m["id"].endswith("trips_in_window.metro_line_1")
    )
    assert trips["kind"] == "simulated"


def test_senza_feed_gtfs_e_un_errore(world: dict[str, Path], capsys: Any) -> None:
    shutil.rmtree(world["data"] / "gtfs")
    fails(world, capsys, "--event", "test_event", "--level", "mid", message="Manca il feed GTFS")


def test_un_itinerario_che_il_feed_non_risolve_e_un_errore(
    world: dict[str, Path], config: EngineConfig, capsys: Any
) -> None:
    """Un feed valido ma senza le stazioni degli itinerari (qui solo quelli di una zona)."""
    only_vomero = config.transit.model_copy(
        update={"itineraries": {"vomero": config.transit.itineraries["vomero"]}}
    )
    event = make_event()
    shutil.rmtree(world["data"] / "gtfs")
    write_feed_for_itineraries(
        world["data"] / "gtfs" / FEED_NAME, only_vomero, event.date, event.area_center
    )
    clear_feed_cache()
    fails(
        world, capsys, "--event", "test_event", "--level", "mid",
        message="non risolti sul feed GTFS",
    )  # fmt: skip


# --- formattazione del trasporto pubblico ---------------------------------------------------------


def row(**changes: Any) -> SectionRow:
    fields: dict[str, Any] = {
        "route_id": "4955", "route_class": "metro_line_1", "from_name": "Dante",
        "to_name": "Municipio", "trips": 3, "capacity_pax_h": 7500.0, "pax_h": 6000.0,
        "load_ratio": 0.8,
    }  # fmt: skip
    return SectionRow(**{**fields, **changes})


def test_i_carichi_delle_tratte_in_colonne() -> None:
    text = format_sections(
        [
            row(),
            row(route_class="metro_line_6", from_name="Mostra", to_name="Arco Mirelli",
                pax_h=1800.0, capacity_pax_h=1740.0, load_ratio=1800 / 1740),
            row(route_class="funicular", from_name="A", to_name="B", capacity_pax_h=0.0,
                load_ratio=None),
        ]
    )  # fmt: skip
    assert text.splitlines() == [
        "Carichi delle tratte:",
        "Linea         Tratta                 Corse  Pax/h  Capacità  Carico",
        "metro_line_1  Dante → Municipio          3   6000      7500    0.80",
        "metro_line_6  Mostra → Arco Mirelli      3   1800      1740  1.03 !",
        "funicular     A → B                      3   6000         0       -",
    ]


def test_senza_tratte_con_passeggeri_lo_dice() -> None:
    assert format_sections([]) == (
        "Tratte con passeggeri: nessuna (la domanda TPL non usa metro o funicolari)"
    )


def test_il_carico_di_esattamente_uno_non_e_sovraccarico() -> None:
    assert format_sections([row(pax_h=7500.0, load_ratio=1.0)]).endswith("1.00")


def test_la_tabella_tpl_ha_solo_i_numeri_e_gli_itinerari_il_testo() -> None:
    def measured(name: str, value: float | str, unit: str) -> Any:
        return make_measured(
            id=f"m.cli.it0.transit.arrival.{name}", value=value, unit=unit, kind="estimate",
            source="engine.transit v1", method="m", inputs=["i"], as_of=NOON,
        )  # fmt: skip

    metrics = TransitMetrics(
        window="arrival",
        measures=(
            measured("stops_overloaded", 2, "n"),
            measured("itinerary_used.vomero", "itinerario 1: A → B (funicular)", "testo"),
            measured("walk_people", 12.5, "pax"),
        ),
        layers={},
        sections=(),
    )
    result = TransitResult(
        event_id="test_event", level="mid", window="arrival", applied=(), metrics=metrics
    )
    table = format_transit_table(result)
    assert "stops_overloaded" in table and "walk_people" in table and "vomero" not in table
    assert format_itineraries(result) == (
        "Itinerari per zona:\n  vomero: itinerario 1: A → B (funicular)"
    )
    empty = TransitResult(
        event_id="test_event", level="mid", window="arrival", applied=(),
        metrics=TransitMetrics("arrival", (), {}, ()),
    )  # fmt: skip
    assert format_itineraries(empty) == "Itinerari per zona: nessuna"


# --- gli errori -----------------------------------------------------------------------------------


def fails(
    world: dict[str, Path], capsys: pytest.CaptureFixture[str], *args: str, message: str
) -> None:
    assert cli(world, *args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # niente tabelle a metà
    assert captured.err.startswith("Errore: ")
    assert message in captured.err, captured.err
    assert not world["out"].exists()  # niente file


def test_evento_sconosciuto(world: dict[str, Path], capsys: Any) -> None:
    other = make_event(id="altro_evento")
    (world["seeds"] / "altro_evento.json").write_text(other.model_dump_json(), encoding="utf-8")
    fails(
        world,
        capsys,
        "--event",
        "nope",
        "--level",
        "mid",
        message="Evento 'nope' non trovato in",
    )
    cli(world, "--event", "nope", "--level", "mid")
    # la riga dice anche quali ci sono, in ordine
    assert "Disponibili: altro_evento, test_event" in capsys.readouterr().err


def test_i_preset_di_default_sono_quelli_del_repository(
    world: dict[str, Path], capsys: Any
) -> None:
    code = main(["--data-dir", str(world["data"]), "--event", "nope", "--level", "mid"])
    assert code == 1
    assert "Disponibili: match_2027, regate_sep_2026" in capsys.readouterr().err


def test_cartella_dei_preset_mancante(world: dict[str, Path], capsys: Any) -> None:
    assert (
        main(["--seeds-dir", str(world["seeds"] / "nowhere"), "--event", "x", "--level", "mid"])
        == 1
    )
    assert "Cartella dei seed non trovata" in capsys.readouterr().err


def test_grafo_mancante_dice_cosa_fare(world: dict[str, Path], capsys: Any) -> None:
    (world["data"] / "osm" / "graph_drive.graphml").unlink()
    fails(world, capsys, "--event", "test_event", "--level", "mid", message="esegui `make data`")


@pytest.mark.parametrize(
    "content",
    ["non è json", '{"una": "mappa"}', '[{"action_id": "x"}]'],
    ids=["json", "forma", "campi"],
)
def test_misure_illeggibili(
    world: dict[str, Path], tmp_path: Path, capsys: Any, content: str
) -> None:
    measures = tmp_path / "misure.json"
    measures.write_text(content, encoding="utf-8")
    fails(
        world, capsys, "--event", "test_event", "--level", "mid", "--measures", str(measures),
        message=f"Misure non leggibili in {measures}",
    )  # fmt: skip


def test_file_di_misure_mancante(world: dict[str, Path], tmp_path: Path, capsys: Any) -> None:
    missing = tmp_path / "nessuno.json"
    fails(
        world, capsys, "--event", "test_event", "--level", "mid", "--measures", str(missing),
        message="Misure non leggibili in",
    )  # fmt: skip


def test_una_misura_non_accettata_e_un_errore(
    world: dict[str, Path], config: EngineConfig, tmp_path: Path, capsys: Any
) -> None:
    pending = make_request(
        "act_9", type="close_road", target=inbound_key_of_car_destination(config), window="arrival"
    )  # stato di default: RECEIVED
    measures = tmp_path / "misure.json"
    measures.write_text(json.dumps([pending.model_dump(mode="json")]), encoding="utf-8")
    fails(
        world, capsys, "--event", "test_event", "--level", "mid", "--measures", str(measures),
        message="act_9 (close_road): la richiesta è RECEIVED, non accettata",
    )  # fmt: skip


@pytest.mark.parametrize(
    "args",
    [
        ["--level", "mid"],
        ["--event", "test_event"],
        ["--event", "test_event", "--level", "enorme"],
        ["--event", "test_event", "--level", "mid", "--window", "sera"],
    ],
    ids=["senza-evento", "senza-livello", "livello-ignoto", "finestra-ignota"],
)
def test_argomenti_sbagliati(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
