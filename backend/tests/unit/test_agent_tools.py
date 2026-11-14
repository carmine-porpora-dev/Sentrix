import pytest

from app.agents.tools import (
    EVENT_DEMAND_TOOLS,
    TRAFFIC_TOOLS,
    TRANSIT_TOOLS,
    ToolError,
    event_demand_tools,
    severity_of,
    traffic_tools,
    transit_tools,
)
from app.engine.run import RoadResult
from app.models.agents_config import AgentsConfig, Thresholds
from app.models.base import Window
from app.models.provenance import Measured
from tests.agents_support import AS_OF, RUN, demand, measure, road_result, transit_result
from tests.support import make_event

CONFIG = AgentsConfig.from_yaml()


def ids(items: list[Measured]) -> list[str]:
    return [m.id for m in items]


# --- gravità -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "info"),
        (0.89, "info"),
        (0.9, "warning"),
        (1.09, "warning"),
        (1.1, "critical"),
        (3.4, "critical"),
    ],
)
def test_la_gravita_viene_dalle_soglie_della_configurazione(value: float, expected: str) -> None:
    assert severity_of(value, CONFIG.severity.road) == expected


def test_le_soglie_sono_in_ordine() -> None:
    with pytest.raises(ValueError, match="warning_at deve essere minore"):
        Thresholds(warning_at=1.2, critical_at=1.0)


# --- Event & Demand ------------------------------------------------------------------------


def test_event_demand_da_l_affluenza_dell_evento_e_la_domanda_per_finestra() -> None:
    event = make_event()
    tools = event_demand_tools(
        event,
        "mid",
        {"departure": demand("departure"), "arrival": demand("arrival")},
        run_id=RUN,
        as_of=AS_OF,
    )
    assert tools.agent == "event_demand" and tools.tools_called == EVENT_DEMAND_TOOLS
    found = {m.id: m for m in tools.measures}
    attendance = found["m.run_1.it0.event.attendance"]
    assert (attendance.value, attendance.unit, attendance.kind) == (
        event.attendance.mid,
        "pax",
        "simulated",
    )
    assert attendance.source == f"Evento {event.id} (revisione {event.revision})"
    for window in ("arrival", "departure"):
        for name, value in (
            ("persons_in_band", 1000.0),
            ("car_persons", 400.0),
            ("transit_persons", 500.0),
            ("walk_persons", 100.0),
        ):
            measured = found[f"m.run_1.it0.event.{window}.{name}"]
            assert (measured.value, measured.unit, measured.kind) == (value, "pax", "simulated")
            assert "non calibrato" in " ".join(measured.assumptions)
    assert tools.signals == []  # niente criticità: il compito dell'agente è la sintesi


def test_l_affluenza_porta_la_fonte_indicata_dall_evento() -> None:
    event = make_event()
    event = event.model_copy(
        update={
            "attendance": event.attendance.model_copy(update={"source_ref": "Questura di Napoli"})
        }
    )
    (attendance, *_) = event_demand_tools(event, "high", {}, run_id=RUN, as_of=AS_OF).measures
    assert attendance.value == event.attendance.high
    assert attendance.assumptions == ["fonte indicata nell'Evento: Questura di Napoli"]


def test_il_contesto_dell_evento_ha_nomi_e_finestre_non_numeri_da_citare() -> None:
    event = make_event()
    context = event_demand_tools(event, "mid", {}, run_id=RUN, as_of=AS_OF).context
    assert context["event"] == event.name and context["attendance_level"] == "mid"
    assert context["arrival_window"] == f"{event.arrival.start:%H:%M}–{event.arrival.end:%H:%M}"
    assert context["closures"] == [c.label for c in event.closures]


def test_una_finestra_senza_domanda_non_ha_metriche() -> None:
    tools = event_demand_tools(
        make_event(), "mid", {"departure": demand()}, run_id=RUN, as_of=AS_OF
    )
    assert not any(".arrival." in m.id for m in tools.measures)


# --- Traffic ------------------------------------------------------------------------------------


def test_traffic_porta_le_metriche_del_motore_e_i_segnali_con_le_evidenze() -> None:
    tools = traffic_tools(
        {"departure": road_result("departure")}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG
    )
    assert tools.agent == "traffic" and tools.tools_called == TRAFFIC_TOOLS
    assert "m.run_1.it0.road.departure.veh_hours" in ids(tools.measures)
    intersection, edge = tools.signals
    assert (intersection.trigger, intersection.target, intersection.target_kind) == (
        "critical_intersection",
        "1001",
        "intersection",
    )
    assert intersection.target_label == "Piazza Vittoria" and intersection.window == "departure"
    assert intersection.severity == "critical"  # v/c 1,2 ≥ 1,1
    assert intersection.evidence_ids == ["m.run_1.it0.road.departure.critical_intersection.1.vc"]
    assert intersection.location is not None and abs(intersection.location.lat - 40.8) < 1e-9
    assert (edge.trigger, edge.target, edge.target_kind) == ("saturated_path", "1-2-0", "edges")
    assert edge.target_label == "Riviera di Chiaia"
    assert edge.evidence_ids == ["m.run_1.it0.road.departure.edge_vc.1-2-0"]


def test_ogni_evidenza_di_un_segnale_e_un_measured_che_si_puo_ritrovare() -> None:
    tools = traffic_tools(
        {"departure": road_result(), "arrival": road_result("arrival")},
        run_id=RUN,
        iteration=2,
        as_of=AS_OF,
        config=CONFIG,
    )
    known = {m.id for m in tools.measures}
    assert tools.signals and all(set(s.evidence_ids) <= known for s in tools.signals)
    assert len(known) == len(tools.measures)  # nessun id due volte


def test_il_measured_di_un_arco_ha_il_valore_e_la_provenienza_del_motore() -> None:
    result = road_result()
    tools = traffic_tools(
        {"departure": result}, run_id=RUN, iteration=1, as_of=AS_OF, config=CONFIG
    )
    derived = tools.measure("m.run_1.it1.road.departure.edge_vc.1-2-0")
    assert derived is not None
    assert (derived.value, derived.unit, derived.kind) == (1.3, "rapporto", "simulated")
    assert derived.source == "engine.metrics v1" and derived.as_of == AS_OF
    base = next(m for m in result.metrics.measures if m.id.endswith("veh_hours"))
    assert derived.assumptions == base.assumptions and "arco 1-2-0" in derived.inputs


def test_gli_archi_sono_al_massimo_quelli_della_configurazione() -> None:
    edges = tuple((f"{n}-{n + 1}-0", f"Via {n}", 2.0 - n / 10) for n in range(1, 9))
    tools = traffic_tools(
        {"departure": road_result(edges=edges)}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG
    )
    targets = [s.target for s in tools.signals if s.trigger == "saturated_path"]
    assert targets == [
        e[0] for e in edges[: CONFIG.tools.top_congested_edges]
    ]  # i più saturi, in ordine


def test_un_arco_senza_nome_si_chiama_con_la_sua_chiave() -> None:
    tools = traffic_tools(
        {"departure": road_result(edges=(("7-8-0", None, 1.2),))},
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=CONFIG,
    )
    assert tools.signals[1].target_label == "7-8-0"


def test_senza_incroci_critici_ci_sono_solo_gli_archi() -> None:
    tools = traffic_tools(
        {"departure": road_result(intersections=())},
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=CONFIG,
    )
    assert [s.trigger for s in tools.signals] == ["saturated_path"]


def test_i_segnali_seguono_l_ordine_delle_finestre_e_dei_rank() -> None:
    both: dict[Window, RoadResult] = {
        "departure": road_result("departure", intersections=((5, "Cinque", 1.5), (6, "Sei", 1.4))),
        "arrival": road_result("arrival", intersections=((7, "Sette", 1.3),)),
    }
    tools = traffic_tools(both, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG)
    assert [
        (s.window, s.target) for s in tools.signals if s.trigger == "critical_intersection"
    ] == [
        ("arrival", "7"),
        ("departure", "5"),
        ("departure", "6"),
    ]
    # ogni incrocio cita il v/c del suo rank, nella sua finestra
    evidence = {
        (s.window, s.target): s.evidence_ids
        for s in tools.signals
        if s.trigger == "critical_intersection"
    }
    assert evidence[("departure", "5")] == ["m.run_1.it0.road.departure.critical_intersection.1.vc"]
    assert evidence[("departure", "6")] == ["m.run_1.it0.road.departure.critical_intersection.2.vc"]
    assert evidence[("arrival", "7")] == ["m.run_1.it0.road.arrival.critical_intersection.1.vc"]


def test_una_metrica_che_il_motore_non_ha_prodotto_e_un_errore() -> None:
    result = road_result()
    broken = result.model_copy(
        update={
            "metrics": result.metrics.__class__(
                window="departure",
                measures=tuple(
                    m for m in result.metrics.measures if "critical_intersection" not in m.id
                ),
                layers=result.metrics.layers,
                critical_edges=result.metrics.critical_edges,
                critical_intersections=result.metrics.critical_intersections,
            )
        }
    )
    with pytest.raises(ToolError, match="critical_intersection.1.vc"):
        traffic_tools({"departure": broken}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG)


def test_gli_strumenti_sono_deterministici() -> None:
    results: dict[Window, RoadResult] = {"departure": road_result()}
    first = traffic_tools(results, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG)
    second = traffic_tools(results, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG)
    assert first.model_dump() == second.model_dump()


# --- Transit ------------------------------------------------------------------------------------


def test_transit_trova_la_linea_senza_corse_e_quella_satura() -> None:
    tools = transit_tools(
        {"departure": transit_result()}, run_id=RUN, iteration=0, as_of=AS_OF, config=CONFIG
    )
    assert tools.agent == "transit" and tools.tools_called == TRANSIT_TOOLS
    by_trigger = {(s.trigger, s.target): s for s in tools.signals}
    no_service = by_trigger[("line_no_service_in_window", "metro_line_6")]
    assert no_service.target_kind == "route" and no_service.severity == "warning"
    assert no_service.target_label == "Linea 6 della metropolitana"
    assert no_service.evidence_ids == ["m.run_1.it0.transit.departure.trips_in_window.metro_line_6"]
    overloaded = by_trigger[("section_overloaded", "metro_line_1")]
    assert overloaded.severity == "critical"  # carico 2,7 ≥ 1,5
    assert overloaded.evidence_ids == [
        "m.run_1.it0.transit.departure.max_section_load.metro_line_1"
    ]
    assert ("section_overloaded", "funicular") not in by_trigger  # 0,5 ≤ 1


def test_una_linea_con_corse_e_senza_sovraccarico_non_ha_segnali() -> None:
    tools = transit_tools(
        {
            "departure": transit_result(
                trips={"metro_line_1": 6}, loads={"metro_line_1": 0.8}, stops=()
            )
        },
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=CONFIG,
    )
    assert tools.signals == []


def test_le_fermate_piu_cariche_diventano_bersagli_con_un_measured() -> None:
    stops = (
        ("1", "Dante", 1.2, True, False),
        ("2", "Municipio", 2.0, True, False),
        ("3", "Garibaldi", 1.9, True, False),
        ("4", "Chiusa", 4.0, True, True),  # chiusa: non si presidia
        ("5", "Libera", 0.4, False, False),  # non sovraccarica
        ("6", "Non segnalata", 3.5, False, False),  # il motore non la dà sovraccarica
    )
    tools = transit_tools(
        {"departure": transit_result(stops=stops)},
        run_id=RUN,
        iteration=1,
        as_of=AS_OF,
        config=CONFIG,
    )
    picked = [s for s in tools.signals if s.target_kind == "stop"]
    assert [s.target for s in picked] == ["2", "3"]  # le due più cariche, aperte e sovraccariche
    assert picked[0].target_label == "Municipio" and picked[0].trigger == "stop_overloaded"
    assert picked[0].severity == "critical"  # carico 2,0 ≥ 1,5
    derived = tools.measure("m.run_1.it1.transit.departure.stop_load.2")
    assert derived is not None and (derived.value, derived.unit, derived.kind) == (
        2.0,
        "rapporto",
        "estimate",
    )
    assert derived.source == "engine.transit v1"


def test_una_fermata_poco_oltre_la_capacita_e_solo_un_attenzione() -> None:
    stops = (("1", "Dante", 1.2, True, False),)
    tools = transit_tools(
        {"departure": transit_result(stops=stops)},
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=CONFIG,
    )
    (signal,) = [s for s in tools.signals if s.target_kind == "stop"]
    assert (signal.trigger, signal.severity) == ("stop_overloaded", "warning")  # 1,0 ≤ 1,2 < 1,5


def test_una_fermata_oltre_la_soglia_di_sicurezza_e_da_sospendere() -> None:
    stops = (("9", "Affollatissima", 3.4, True, False),)
    tools = transit_tools(
        {"departure": transit_result(stops=stops)},
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=CONFIG,
    )
    (signal,) = [s for s in tools.signals if s.target_kind == "stop"]
    assert (signal.trigger, signal.severity) == ("stop_overloaded_unsafe", "critical")


def test_gli_itinerari_sono_contesto_non_evidenze() -> None:
    tools = transit_tools(
        {
            "departure": transit_result(
                itineraries={"vomero": "funicolare, poi a piedi", "port": "a piedi"}
            )
        },
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=CONFIG,
    )
    assert tools.context == {
        "itineraries": {"departure:vomero": "funicolare, poi a piedi", "departure:port": "a piedi"}
    }


def test_i_segnali_del_trasporto_hanno_evidenze_note() -> None:
    tools = transit_tools(
        {"departure": transit_result(), "arrival": transit_result("arrival")},
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=CONFIG,
    )
    known = {m.id for m in tools.measures}
    assert tools.signals and all(set(s.evidence_ids) <= known for s in tools.signals)
    assert len(known) == len(tools.measures)


def test_la_configurazione_dei_nomi_delle_linee_vale_per_i_segnali() -> None:
    config = CONFIG.model_copy(
        update={
            "labels": CONFIG.labels.model_copy(
                update={"route_classes": {"funicular": "Le funicolari"}}
            )
        }
    )
    tools = transit_tools(
        {"departure": transit_result(trips={"funicular": 0, "metro_line_6": 0}, loads={})},
        run_id=RUN,
        iteration=0,
        as_of=AS_OF,
        config=config,
    )
    assert [
        (s.target, s.target_label)
        for s in tools.signals
        if s.trigger == "line_no_service_in_window"
    ] == [
        ("funicular", "Le funicolari")
    ]  # una classe che la configurazione non nomina non è un bersaglio


# --- il test non e' vuoto -----------------------------------------------------------------------


def test_i_measured_di_prova_sono_quelli_che_il_motore_scrive() -> None:
    sample = measure(("road", "departure", "veh_hours"), 1.0, "veic·h")
    assert sample.id == "m.run_1.it0.road.departure.veh_hours"
