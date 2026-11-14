import datetime as dt
from dataclasses import replace
from typing import Any

import networkx as nx
import pytest

from app.data.resolvers import ResolveError
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.assign import Assignment, assign
from app.engine.background import build_background
from app.engine.demand import Demand, OdFlow
from app.engine.graph import describe_sources
from app.engine.measures import RoadNetwork, apply_measures
from app.engine.metrics import (
    MetricsError,
    RoadMetrics,
    build_reference,
    od_pair_nodes,
    road_metrics,
)
from app.models.config import AssignmentConfig, EngineConfig, MetricsConfig, ODEndpoint, ODPair
from app.models.demand import Zone
from app.models.event import Event
from app.models.geo import GeoPoint
from tests.support import make_event, make_request

SOURCES = {"lanes_source": "default", "speed_source": "osm"}  # per `describe_sources`
COORDS = {
    1: (14.2300, 40.8300),
    2: (14.2400, 40.8300),
    3: (14.2350, 40.8350),
    4: (14.2350, 40.8250),
    5: (14.2500, 40.8300),  # isolato
}
AS_OF = dt.datetime(2026, 11, 9, 12, 0, tzinfo=dt.UTC)
PREFIX = ("run1", "it0")


def point(node: int) -> GeoPoint:
    lon, lat = COORDS[node]
    return GeoPoint(lat=lat, lon=lon)


def diamond() -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node, (lon, lat) in COORDS.items():
        g.add_node(node, x=lon, y=lat)
    for u, v, t0, cap, length, name in [
        (1, 2, 1.0, 1000.0, 1000.0, "Diretta"),
        (1, 3, 0.7, 10000.0, 800.0, "Nord"),
        (3, 2, 0.7, 10000.0, 900.0, "Nord"),
        (1, 4, 0.9, 10000.0, 1000.0, "Sud"),
        (4, 2, 0.9, 10000.0, 1100.0, "Sud"),
    ]:
        g.add_edge(u, v, key=0, t0_min=t0, capacity_vph=cap, length_m=length, name=name, **SOURCES)
    return g


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    base = EngineConfig.from_yaml()
    pairs = [
        ODPair(
            id="uno_due",
            label="1 → 2",
            origin=ODEndpoint(point=point(1)),
            destination=ODEndpoint(point=point(2)),
        )
    ]
    return base.model_copy(
        update={
            "assignment": AssignmentConfig(steps=4, step_share=0.25),  # valori a mano su 4 passi
            "demand": base.demand.model_copy(update={"od_pairs": pairs}),
        }
    )


def with_pairs(config: EngineConfig, pairs: list[ODPair]) -> EngineConfig:
    return config.model_copy(
        update={"demand": config.demand.model_copy(update={"od_pairs": pairs})}
    )


def flow(origin: int, dest: int, vph: float, zone: str = "z") -> OdFlow:
    return OdFlow(
        zone_id=zone, origin_node=origin, dest_node=dest, veh_per_hour=vph, destination_label=None
    )


def demand_of(flows: list[OdFlow], window: str = "departure") -> Demand:
    return Demand(
        window=window,  # type: ignore[arg-type]
        level="mid",
        attendance=0,
        band_start=dt.time(18, 30),
        band_end=dt.time(19, 0),
        band_share=0.3,
        persons=0.0,
        zones=(),
        flows=tuple(flows),
        car_occupancy=2.2,
        inputs=("event test_event rev 1", "livello di affluenza mid"),
        assumptions=(),
    )


QUIET = {"arrival_peak_share": 0.0, "departure_peak_share": 0.0}
CLOSURE = [{"label": "Diretta chiusa", "edge_keys": ["1-2-0"]}]


def world(
    config: EngineConfig,
    flows: list[OdFlow],
    *,
    event: Event | None = None,
    requests: list[Any] | None = None,
    graph: nx.MultiDiGraph | None = None,
    window: str = "departure",
    prefix: tuple[str, ...] = PREFIX,
) -> tuple[RoadMetrics, nx.MultiDiGraph, RoadNetwork, Assignment, Assignment]:
    base = graph or diamond()
    evt = event or make_event(background=QUIET)
    network = apply_measures(base, evt, window, requests or [], config)  # type: ignore[arg-type]
    background = build_background(base, evt, window, network.closed)  # type: ignore[arg-type]
    assignment = assign(network.graph, background.volumes, flows, config)
    reference = build_reference(base, evt, window, config)  # type: ignore[arg-type]
    result = road_metrics(
        base,
        network,
        assignment,
        reference,
        demand_of(flows, window),
        evt,
        config,
        background=background,
        id_prefix=prefix,
        as_of=AS_OF,
    )
    return result, base, network, assignment, reference


def by_tail(result: RoadMetrics) -> dict[str, Any]:
    return {m.id.split(".road.departure.")[1]: m for m in result.measures}


# --- riferimento R -------------------------------------------------------------------------------


def test_il_riferimento_ha_solo_il_fondo_e_nessuna_chiusura(config: EngineConfig) -> None:
    base = diamond()
    event = make_event(
        background={"arrival_peak_share": 0.35, "departure_peak_share": 0.4},
        closures=CLOSURE,
    )
    reference = build_reference(base, event, "departure", config)
    assert list(reference.edges) == ["1-2-0", "1-3-0", "1-4-0", "3-2-0", "4-2-0"]  # anche la chiusa
    assert all(load.v_event == 0 for load in reference.edges.values())
    # fondo di partenza: 0,4 × capacità; Diretta 400 su 1.000 → v/c 0,4, t = 1 + 0,15 × 0,4^4
    assert reference.edges["1-2-0"].v_total == pytest.approx(400.0)
    assert reference.edges["1-2-0"].t_min == pytest.approx(1 + 0.15 * 0.4**4, rel=1e-12)
    assert reference.demand_veh_per_hour == 0 and reference.unassigned == ()


# --- misure con la Diretta chiusa -----------------------------------------------------------------


@pytest.fixture(scope="module")
def closed_world(config: EngineConfig) -> tuple[RoadMetrics, Assignment]:
    event = make_event(background=QUIET, closures=CLOSURE)
    result, _, _, assignment, _ = world(config, [flow(1, 2, 800.0)], event=event)
    return result, assignment


def test_chiusa_la_diretta_il_traffico_va_a_nord(closed_world: Any) -> None:
    _, assignment = closed_world
    assert sorted(assignment.edges) == ["1-3-0", "1-4-0", "3-2-0", "4-2-0"]  # la Diretta è chiusa
    assert assignment.edges["1-3-0"].v_event == pytest.approx(800.0)
    assert assignment.edges["1-4-0"].v_event == 0.0


def test_ore_veicolo(closed_world: Any) -> None:
    metrics = by_tail(closed_world[0])
    # 2 archi × 800 veic/h × 0,7000043 min / 60 × (30/60)
    expected = 2 * 800 * 0.7 * (1 + 0.15 * 0.08**4) / 60 * 0.5
    assert metrics["veh_hours"].value == pytest.approx(expected, rel=1e-12)  # 9,33339
    assert metrics["veh_hours"].unit == "veic·h"


def test_tempo_origine_destinazione_e_riferimento(closed_world: Any) -> None:
    metrics = by_tail(closed_world[0])
    assert metrics["od_time.uno_due"].value == pytest.approx(2 * 0.7 * (1 + 0.15 * 0.08**4))
    assert metrics["od_time.uno_due"].value == pytest.approx(1.4000086, abs=1e-7)
    assert metrics["od_time_ref.uno_due"].value == pytest.approx(1.0)  # R: la Diretta, a vuoto
    assert metrics["od_time.mean"].value == metrics["od_time.uno_due"].value  # una sola coppia
    assert {metrics[k].unit for k in ("od_time.uno_due", "od_time_ref.uno_due")} == {"min"}


def test_archi_critici_nessuno_sotto_soglia(closed_world: Any) -> None:
    metrics = by_tail(closed_world[0])
    assert (
        metrics["critical_edges.count"].value == 0 and metrics["critical_edges.count"].unit == "n"
    )
    assert metrics["critical_edges.km"].value == 0.0 and metrics["critical_edges.km"].unit == "km"
    assert closed_world[0].critical_edges == ()


def test_deviazione_in_chilometri(closed_world: Any) -> None:
    metrics = by_tail(closed_world[0])
    # Nord 800 + 900 = 1.700 m contro la Diretta 1.000 m: +0,7 km, su 1 coppia su 1
    assert metrics["detour_extra_km"].value == pytest.approx(0.7, rel=1e-12)
    assert metrics["detour_extra_km"].unit == "km"
    assert "1 coppie su 1 cambiano percorso" in metrics["detour_extra_km"].assumptions


def test_coppie_senza_percorso(closed_world: Any) -> None:
    metrics = by_tail(closed_world[0])
    assert metrics["unassigned_pairs"].value == 0 and metrics["unassigned_pairs"].unit == "n"


def test_incroci_critici_sui_cammini_deviati(closed_world: Any) -> None:
    result = closed_world[0]
    # archi deviati con flusso: 1→3 e 3→2, entrambi v/c 0,08; a parità vince il nodo con id minore
    assert [(i.rank, i.node, i.edge_key) for i in result.critical_intersections] == [
        (1, 2, "3-2-0"),
        (2, 3, "1-3-0"),
    ]
    assert [i.vc for i in result.critical_intersections] == pytest.approx([0.08, 0.08])
    assert [i.label for i in result.critical_intersections] == ["Diretta / Nord", "Nord"]
    metrics = by_tail(result)
    assert metrics["critical_intersection.1.vc"].value == pytest.approx(0.08)
    assert metrics["critical_intersection.1.vc"].unit == "rapporto"
    assert metrics["critical_intersection.2.vc"].value == pytest.approx(0.08)
    assert "critical_intersection.3.vc" not in metrics  # top N = 2


# --- provenienza ---------------------------------------------------------------------------------


def test_gli_id_le_unita_e_la_provenienza(closed_world: Any) -> None:
    result = closed_world[0]
    ids = [m.id for m in result.measures]
    assert len(ids) == len(set(ids)) == 10
    assert ids[0] == "m.run1.it0.road.departure.veh_hours"
    assert set(by_tail(result)) == {
        "veh_hours",
        "od_time.uno_due",
        "od_time_ref.uno_due",
        "od_time.mean",
        "critical_edges.count",
        "critical_edges.km",
        "detour_extra_km",
        "unassigned_pairs",
        "critical_intersection.1.vc",
        "critical_intersection.2.vc",
    }
    for m in result.measures:
        assert m.kind == "simulated" and m.source == "engine.metrics v1"
        assert m.as_of == AS_OF
        assert "event test_event rev 1" in m.inputs
        assert any("non una previsione" in a for a in m.assumptions)  # principio 6
        assert m.method.strip()


def test_il_metodo_contiene_la_formula(closed_world: Any) -> None:
    metrics = by_tail(closed_world[0])
    assert (
        metrics["veh_hours"].method == "Σ archi (v_totale × t_min / 60) × (30/60), fascia di picco"
    )
    assert "soglia" not in metrics["critical_edges.count"].method
    assert metrics["critical_edges.count"].method == "archi aperti con v/c > 0.9"


# --- layer ---------------------------------------------------------------------------------------


def test_layer_edges_vc(closed_world: Any) -> None:
    layer = closed_world[0].layers["edges_vc"]
    assert [f.id for f in layer.features] == [
        "1-3-0",
        "3-2-0",
        "1-2-0",
    ]  # aperti per chiave, poi chiusi
    north, _, closed = layer.features
    assert north.properties == {
        "edge_key": "1-3-0",
        "name": "Nord",
        "length_m": 800.0,
        "vc": pytest.approx(0.08),
        "vc_class": 0,
        "closed": False,
        "detour": True,
        "window": "departure",
    }
    assert north.geometry == {
        "type": "LineString",
        "coordinates": [[14.23, 40.83], [14.235, 40.835]],
    }
    assert closed.properties["closed"] is True and closed.properties["vc"] == 0.0
    assert closed.properties["detour"] is False and closed.properties["name"] == "Diretta"


def test_layer_closures(closed_world: Any) -> None:
    layer = closed_world[0].layers["closures"]
    assert [f.id for f in layer.features] == ["1-2-0"]
    assert layer.features[0].properties == {
        "edge_key": "1-2-0",
        "label": "Diretta chiusa",
        "length_m": 1000.0,
        "mode": "closed",
    }
    assert layer.features[0].geometry == {
        "type": "LineString",
        "coordinates": [[14.23, 40.83], [14.24, 40.83]],
    }


def test_layer_incroci_critici(closed_world: Any) -> None:
    layer = closed_world[0].layers["critical_intersections"]
    assert [f.id for f in layer.features] == ["2", "3"]
    first = layer.features[0]
    assert first.geometry == {"type": "Point", "coordinates": [14.24, 40.83]}
    assert first.properties == {
        "node": "2",
        "label": "Diretta / Nord",
        "rank": 1,
        "vc": pytest.approx(0.08),
        "window": "departure",
        "evidence_id": "m.run1.it0.road.departure.critical_intersection.1.vc",
    }
    # l'evidenza citata è davvero una delle metriche
    assert first.properties["evidence_id"] in {m.id for m in closed_world[0].measures}


# --- archi critici (nessuna chiusura, la Diretta satura) ------------------------------------------


def test_le_coordinate_dei_layer_hanno_sei_decimali(config: EngineConfig) -> None:
    """≈ 0,1 m: abbastanza per la mappa, e il file non porta cifre inutili."""
    g = diamond()
    g.nodes[1]["x"] = 14.23004567891
    g.nodes[3]["x"] = 14.23501234567
    event = make_event(background=QUIET, closures=CLOSURE)
    result, *_ = world(config, [flow(1, 2, 800.0)], event=event, graph=g)

    def first_coordinates(layer: str, feature_id: str) -> Any:
        feature = next(f for f in result.layers[layer].features if f.id == feature_id)
        assert feature.geometry is not None
        return feature.geometry["coordinates"]

    assert first_coordinates("edges_vc", "1-2-0")[0] == [14.230046, 40.83]
    assert first_coordinates("closures", "1-2-0")[0] == [14.230046, 40.83]
    assert first_coordinates("critical_intersections", "3") == [14.235012, 40.835]


def test_archi_critici_e_classi_di_v_c(config: EngineConfig) -> None:
    """2.000 veic/h da 1 a 2 senza chiusure, a 4 passi: la Diretta ne prende 3 passi su 4
    (1.500, v/c 1,5) e il Nord il quarto (500 su 10.000, v/c 0,05)."""
    result, *_ = world(config, [flow(1, 2, 2000.0)])
    metrics = by_tail(result)
    assert metrics["critical_edges.count"].value == 1
    assert metrics["critical_edges.km"].value == pytest.approx(1.0)  # la Diretta: 1.000 m
    assert [(c.edge_key, c.name, c.length_m) for c in result.critical_edges] == [
        ("1-2-0", "Diretta", 1000.0)
    ]
    assert result.critical_edges[0].vc == pytest.approx(1.5)
    features = {f.id: f for f in result.layers["edges_vc"].features}
    assert features["1-2-0"].properties["vc_class"] == 3  # 1,5 ≥ 1,1
    assert features["1-3-0"].properties["vc_class"] == 0  # 0,05 < 0,6 ma ha flusso dell'evento
    # tempo O/D: il cammino a costo minimo ora è il Nord (1,4000013 < 1,759 della Diretta)
    assert metrics["od_time.uno_due"].value == pytest.approx(2 * 0.7 * (1 + 0.15 * 0.05**4))
    assert metrics["od_time_ref.uno_due"].value == pytest.approx(1.0)
    assert metrics["detour_extra_km"].value == pytest.approx(0.7)


def test_la_soglia_viene_dalla_configurazione(config: EngineConfig) -> None:
    low = config.model_copy(
        update={
            "metrics": MetricsConfig(
                vc_critical_threshold=0.04,
                vc_classes=(0.6, 0.9, 1.1),
                critical_intersections_top_n=2,
            )
        }
    )
    result, *_ = world(low, [flow(1, 2, 2000.0)])
    metrics = by_tail(result)
    # con soglia 0,04: la Diretta (1,5) e i due archi del Nord (0,05) superano tutti
    assert metrics["critical_edges.count"].value == 3
    assert metrics["critical_edges.count"].method == "archi aperti con v/c > 0.04"
    assert metrics["critical_edges.km"].value == pytest.approx((1000 + 800 + 900) / 1000)
    assert [c.edge_key for c in result.critical_edges] == [
        "1-2-0",
        "1-3-0",
        "3-2-0",
    ]  # dal più alto


def test_gli_incroci_sono_al_massimo_top_n(config: EngineConfig) -> None:
    one = config.model_copy(
        update={
            "metrics": MetricsConfig(
                vc_critical_threshold=0.9,
                vc_classes=(0.6, 0.9, 1.1),
                critical_intersections_top_n=1,
            )
        }
    )
    event = make_event(background=QUIET, closures=CLOSURE)
    result, *_ = world(one, [flow(1, 2, 800.0)], event=event)
    assert [i.node for i in result.critical_intersections] == [2]
    assert [f.id for f in result.layers["critical_intersections"].features] == ["2"]
    assert "critical_intersection.2.vc" not in by_tail(result)


# --- niente deviazioni, coppie senza percorso, errori ---------------------------------------------


def test_la_deviazione_conta_le_coppie_che_cambiano_su_quelle_dell_evento(
    config: EngineConfig,
) -> None:
    """Due coppie nei flussi: la Diretta chiusa fa cambiare cammino a 1→2, non a 3→2."""
    event = make_event(background=QUIET, closures=CLOSURE)
    result, *_ = world(config, [flow(1, 2, 800.0), flow(3, 2, 100.0)], event=event)
    detour = by_tail(result)["detour_extra_km"]
    assert "1 coppie su 2 cambiano percorso" in detour.assumptions
    assert detour.value == pytest.approx(0.7)  # (1.700 − 1.000) m / 1000, sulla sola coppia 1→2


def test_senza_deviazioni(config: EngineConfig) -> None:
    result, *_ = world(config, [flow(1, 2, 50.0)])
    metrics = by_tail(result)
    assert metrics["detour_extra_km"].value == 0.0
    assert (
        "nessuna coppia O/D cambia percorso: 0 per definizione"
        in metrics["detour_extra_km"].assumptions
    )
    assert result.critical_intersections == ()
    assert result.layers["critical_intersections"].features == []
    assert not any(k.startswith("critical_intersection") for k in metrics)
    assert result.layers["closures"].features == []


def test_una_coppia_senza_percorso(config: EngineConfig) -> None:
    pairs = [
        ODPair(
            id="uno_due",
            label="1 → 2",
            origin=ODEndpoint(point=point(1)),
            destination=ODEndpoint(point=point(2)),
        ),
        ODPair(
            id="uno_cinque",
            label="1 → 5",
            origin=ODEndpoint(point=point(1)),
            destination=ODEndpoint(point=point(5)),
        ),
    ]
    result, *_ = world(with_pairs(config, pairs), [flow(1, 2, 100.0), flow(1, 5, 30.0)])
    metrics = by_tail(result)
    assert "od_time.uno_cinque" not in metrics and "od_time_ref.uno_cinque" not in metrics
    assert metrics["od_time.mean"].value == metrics["od_time.uno_due"].value
    assert (
        metrics["od_time.mean"].assumptions[-1]
        == "coppie senza percorso escluse dalla media: uno_cinque"
    )
    assert metrics["unassigned_pairs"].value == 1
    assert metrics["detour_extra_km"].value == 0.0  # la coppia 1→5 non ha percorso: non conta


def test_nessuna_coppia_raggiungibile_niente_media(config: EngineConfig) -> None:
    pairs = [
        ODPair(
            id="uno_cinque",
            label="1 → 5",
            origin=ODEndpoint(point=point(1)),
            destination=ODEndpoint(point=point(5)),
        )
    ]
    result, *_ = world(with_pairs(config, pairs), [])
    assert not any(k.startswith("od_time") for k in by_tail(result))


def test_la_zona_della_coppia_viene_dalle_zone_dell_evento(config: EngineConfig) -> None:
    pair = ODPair(
        id="zone", label="A → B",
        origin=ODEndpoint(zone="zona_a"), destination=ODEndpoint(zone="zona_b"),
    )  # fmt: skip
    zones = [
        Zone(id="zona_a", name="A", type="near", weight_pct=50, centroid=point(1)),
        Zone(id="zona_b", name="B", type="near", weight_pct=50, centroid=point(2)),
    ]
    event = make_event(background=QUIET, zones_override=[z.model_dump() for z in zones])
    result, *_ = world(with_pairs(config, [pair]), [flow(1, 2, 100.0)], event=event)
    assert by_tail(result)["od_time.zone"].value == pytest.approx(1.0, rel=1e-3)


def test_i_nodi_delle_coppie_od(config: EngineConfig) -> None:
    """Un estremo `zone` è il centroide della zona dell'Evento, uno `point` vale per sé."""
    pairs = [
        ODPair(
            id="da_zona",
            label="A → 2",
            origin=ODEndpoint(zone="zona_a"),
            destination=ODEndpoint(point=point(2)),
        ),
        ODPair(
            id="da_punti",
            label="3 → 4",
            origin=ODEndpoint(point=point(3)),
            destination=ODEndpoint(point=point(4)),
        ),
    ]
    zones = [
        Zone(id="zona_a", name="A", type="near", weight_pct=100, centroid=point(1)),
    ]
    event = make_event(zones_override=[z.model_dump() for z in zones])
    assert od_pair_nodes(event, diamond(), with_pairs(config, pairs)) == {
        "da_zona": (1, 2),
        "da_punti": (3, 4),
    }


def test_una_zona_che_l_evento_non_ha_e_un_errore(config: EngineConfig) -> None:
    pair = ODPair(
        id="zone",
        label="A → B",
        origin=ODEndpoint(zone="inesistente"),
        destination=ODEndpoint(point=point(2)),
    )
    with pytest.raises(
        MetricsError, match="coppia O/D 'zone': la zona 'inesistente' non è tra le zone"
    ):
        world(with_pairs(config, [pair]), [])


def test_un_estremo_troppo_lontano_e_un_errore(config: EngineConfig) -> None:
    far = GeoPoint(lat=41.5, lon=15.0)
    pair = ODPair(
        id="lontano",
        label="x",
        origin=ODEndpoint(point=far),
        destination=ODEndpoint(point=point(2)),
    )
    with pytest.raises(ResolveError, match="dista"):
        world(with_pairs(config, [pair]), [])


# --- chiusure di tipo diverso e misure ------------------------------------------------------------


def test_riduzione_di_capacita_nel_layer_delle_chiusure(config: EngineConfig) -> None:
    event = make_event(
        background=QUIET,
        closures=[
            {
                "label": "Corsia chiusa",
                "edge_keys": ["1-2-0"],
                "mode": "capacity_reduction",
                "capacity_factor": 0.5,
            },
            {"label": "Poi chiusa", "edge_keys": ["1-2-0", "1-3-0"]},
        ],
    )
    result, *_ = world(config, [], event=event)
    features = result.layers["closures"].features
    assert [(f.id, f.properties["label"], f.properties["mode"]) for f in features] == [
        ("1-2-0", "Corsia chiusa", "capacity_reduction"),  # un arco in due chiusure: vale la prima
        ("1-3-0", "Poi chiusa", "closed"),
    ]
    assert features[0].properties["capacity_factor"] == 0.5
    assert "capacity_factor" not in features[1].properties


def test_una_misura_cambia_le_metriche_e_il_prefisso_degli_id(config: EngineConfig) -> None:
    event = make_event(background=QUIET, closures=CLOSURE)
    flows = [flow(1, 2, 800.0)]
    plain, *_ = world(config, flows, event=event, prefix=("run1", "it0"))
    signed, *_ = world(
        config,
        flows,
        event=event,
        prefix=("run1", "it1"),
        requests=[
            make_request(
                "a1",
                type="detour_signage",
                target="1-3-0,3-2-0",
                window="departure",
                state="ACCEPTED",
            )
        ],
    )
    assert by_tail(signed)["veh_hours"].id == "m.run1.it1.road.departure.veh_hours"
    # la segnaletica rende il Nord più costoso (1,4 × 1,2 = 1,68), ma il Sud costa 1,8: il traffico
    # resta a nord e il tempo O/D reale, che non contiene il fattore, non cambia
    assert by_tail(signed)["od_time.uno_due"].value == pytest.approx(
        by_tail(plain)["od_time.uno_due"].value
    )


def test_finestra_arrivo_negli_id(config: EngineConfig) -> None:
    result, *_ = world(config, [flow(1, 2, 100.0)], window="arrival")
    assert all(".road.arrival." in m.id for m in result.measures)
    assert result.window == "arrival"
    assert result.layers["edges_vc"].features[0].properties["window"] == "arrival"


def test_incroci_critici_in_arrivo_hanno_la_finestra(config: EngineConfig) -> None:
    """La finestra sta nelle feature degli incroci (come negli archi), non solo nell'evidenza che
    citano: i layer di un'iterazione mettono insieme le due finestre e la mappa le separa da lì."""
    event = make_event(background=QUIET, closures=CLOSURE)
    result, *_ = world(config, [flow(1, 2, 800.0)], event=event, window="arrival")
    incroci = result.layers["critical_intersections"].features
    assert incroci, "il mondo di prova ha almeno un incrocio critico"
    assert all(f.properties["window"] == "arrival" for f in incroci)
    assert all(".road.arrival." in str(f.properties["evidence_id"]) for f in incroci)


# --- determinismo ---------------------------------------------------------------------------------


def test_stessi_input_stesso_risultato(config: EngineConfig) -> None:
    event = make_event(background=QUIET, closures=CLOSURE)
    flows = [flow(1, 2, 800.0)]
    first = world(config, flows, event=event)[0]
    second = world(config, flows, event=event)[0]
    assert first == second
    assert first.measures == second.measures


# --- rete a imbuto: due origini, due deviazioni ---------------------------------------------------

FAN = {
    1: (14.2300, 40.8300),
    6: (14.2300, 40.8400),
    2: (14.2400, 40.8350),
    3: (14.2350, 40.8300),
    4: (14.2350, 40.8400),
}


def fan_point(node: int) -> GeoPoint:
    lon, lat = FAN[node]
    return GeoPoint(lat=lat, lon=lon)


def fan() -> nx.MultiDiGraph:
    """Da 1 e da 6 a 2 la strada diretta (chiusa nell'evento) e un giro ciascuna:
    1→3→2 (600 + 700 = 1.300 m, contro i 1.000 m della diretta: +0,3 km, senza nomi) e
    6→4→2 (800 + 900 = 1.700 m, contro 900 m: +0,8 km). I giri costano 0,6 + 0,6 = 1,2 contro 1,0
    della diretta: con 1,0 + 1,0 sarebbe un pareggio, che si risolve con la chiave minore."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node, (lon, lat) in FAN.items():
        g.add_node(node, x=lon, y=lat)
    for u, v, t0, cap, length, name in [
        (1, 2, 1.0, 1000.0, 1000.0, "Diretta Uno"),
        (6, 2, 1.0, 1000.0, 900.0, "Diretta Sei"),
        (1, 3, 0.6, 1000.0, 600.0, None),
        (3, 2, 0.6, 1000.0, 700.0, None),
        (6, 4, 0.6, 1000.0, 800.0, "Giro Sei"),
        (4, 2, 0.6, 1000.0, 900.0, "Giro Sei"),
    ]:
        attrs: dict[str, Any] = {
            "t0_min": t0,
            "capacity_vph": cap,
            "length_m": length,
            **SOURCES,
        }
        if name is not None:
            attrs["name"] = name
        g.add_edge(u, v, key=0, **attrs)
    return g


@pytest.fixture(scope="module")
def fan_config(config: EngineConfig) -> EngineConfig:
    def pair(pair_id: str, origin: int) -> ODPair:
        return ODPair(
            id=pair_id,
            label=f"{origin} → 2",
            origin=ODEndpoint(point=fan_point(origin)),
            destination=ODEndpoint(point=fan_point(2)),
        )

    pairs = [pair("uno_due", 1), pair("sei_due", 6)]
    return with_pairs(config, pairs).model_copy(
        update={
            "metrics": MetricsConfig(
                vc_critical_threshold=0.9,
                vc_classes=(0.6, 0.9, 1.1),
                critical_intersections_top_n=3,
            )
        }
    )


@pytest.fixture(scope="module")
def fan_world(fan_config: EngineConfig) -> RoadMetrics:
    event = make_event(
        background=QUIET,
        closures=[{"label": "Diretti chiuse", "edge_keys": ["1-2-0", "6-2-0"]}],
    )
    result, *_ = world(fan_config, [flow(1, 2, 300.0), flow(6, 2, 800.0)], event=event, graph=fan())
    return result


def test_imbuto_media_dei_tempi_di_due_coppie(fan_world: RoadMetrics) -> None:
    metrics = by_tail(fan_world)
    # 1→2: due archi da 300/1000 (t = 0,6 × (1 + 0,15 × 0,3^4)); 6→2: due archi da 800/1000
    one = 2 * 0.6 * (1 + 0.15 * 0.3**4)
    six = 2 * 0.6 * (1 + 0.15 * 0.8**4)
    assert metrics["od_time.uno_due"].value == pytest.approx(one, rel=1e-12)
    assert metrics["od_time.sei_due"].value == pytest.approx(six, rel=1e-12)
    assert metrics["od_time.mean"].value == pytest.approx((one + six) / 2, rel=1e-12)
    assert metrics["od_time.mean"].value < metrics["od_time.sei_due"].value  # non il massimo
    assert metrics["od_time_ref.uno_due"].value == pytest.approx(1.0)  # R: la diretta, a vuoto
    assert metrics["od_time_ref.sei_due"].value == pytest.approx(1.0)


def test_imbuto_deviazione_media_sulle_coppie_che_cambiano(fan_world: RoadMetrics) -> None:
    metrics = by_tail(fan_world)
    # +0,3 km e +0,8 km: media 0,55 km (non la somma, 1,1)
    assert metrics["detour_extra_km"].value == pytest.approx(0.55, rel=1e-12)
    assert "2 coppie su 2 cambiano percorso" in metrics["detour_extra_km"].assumptions


def test_imbuto_incroci_critici_massimo_degli_entranti_e_ordine(fan_world: RoadMetrics) -> None:
    got = [(i.rank, i.node, i.edge_key) for i in fan_world.critical_intersections]
    # nodo 2: entranti deviati 3→2 (v/c 0,3) e 4→2 (0,8) → 0,8; nodo 4: 6→4 (0,8); nodo 3: 1→3 (0,3)
    assert got == [(1, 2, "4-2-0"), (2, 4, "6-4-0"), (3, 3, "1-3-0")]
    assert [i.vc for i in fan_world.critical_intersections] == pytest.approx([0.8, 0.8, 0.3])
    metrics = by_tail(fan_world)
    assert [metrics[f"critical_intersection.{n}.vc"].value for n in (1, 2, 3)] == pytest.approx(
        [0.8, 0.8, 0.3]
    )


def test_imbuto_etichette_degli_incroci(fan_world: RoadMetrics) -> None:
    labels = {i.node: i.label for i in fan_world.critical_intersections}
    assert labels[2] == "Diretta Sei / Diretta Uno"  # i primi due nomi in ordine alfabetico
    assert labels[4] == "Giro Sei"
    assert labels[3] == "Incrocio 3"  # nessun arco con nome


# --- valori esattamente sulle soglie --------------------------------------------------------------


@pytest.mark.parametrize(
    ("vph", "vc_class", "critical"),
    [(600.0, 1, False), (900.0, 2, False), (1100.0, 3, True)],
)
def test_soglie_esatte_di_v_c(
    config: EngineConfig, vph: float, vc_class: int, critical: bool
) -> None:
    """La Diretta da sola con v/c 0,6 / 0,9 / 1,1: la classe sale alla soglia (≥) mentre l'arco
    è critico solo oltre 0,9 (>)."""
    result, *_ = world(config, [flow(1, 2, vph)])
    features = {f.id: f for f in result.layers["edges_vc"].features}
    assert features["1-2-0"].properties["vc"] == pytest.approx(vph / 1000)
    assert features["1-2-0"].properties["vc_class"] == vc_class
    assert by_tail(result)["critical_edges.count"].value == (1 if critical else 0)


@pytest.mark.parametrize(("share", "in_layer"), [(0.6, True), (0.59, False)])
def test_il_layer_include_gli_archi_dalla_prima_soglia(
    config: EngineConfig, share: float, in_layer: bool
) -> None:
    """Senza flusso dell'evento, solo il fondo: tutti gli archi hanno v/c = quota."""
    event = make_event(background={"arrival_peak_share": share, "departure_peak_share": share})
    result, *_ = world(config, [], event=event)
    assert len(result.layers["edges_vc"].features) == (5 if in_layer else 0)


# --- ore-veicolo con il fondo --------------------------------------------------------------------


def test_le_ore_veicolo_comprendono_il_fondo(config: EngineConfig) -> None:
    """Fondo 0,4 della capacità, Diretta chiusa, 800 veic/h a nord: Nord v = 4.800 su 10.000
    (t = 0,7 × (1 + 0,15 × 0,48^4)), Sud v = 4.000 (t = 0,9 × (1 + 0,15 × 0,4^4)). Il fondo
    degli archi chiusi è 0 e la Diretta non conta."""
    event = make_event(
        background={"arrival_peak_share": 0.4, "departure_peak_share": 0.4}, closures=CLOSURE
    )
    result, *_ = world(config, [flow(1, 2, 800.0)], event=event)
    north = 2 * 4800 * 0.7 * (1 + 0.15 * 0.48**4)
    south = 2 * 4000 * 0.9 * (1 + 0.15 * 0.4**4)
    assert by_tail(result)["veh_hours"].value == pytest.approx(
        (north + south) / 60 * 0.5, rel=1e-12
    )


def test_un_cammino_finale_senza_flusso_dell_evento_non_e_un_cammino_deviato(
    config: EngineConfig,
) -> None:
    """Il cammino a costo minimo di 1→2 passa dal Sud, che nessun veicolo dell'evento ha percorso
    (carichi scritti a mano: il Nord, caricato, è diventato carissimo). La deviazione in km si
    misura (+1,1 km: Sud 2.100 m contro la Diretta 1.000 m), ma gli archi del Sud non hanno flusso
    dell'evento, quindi non sono «cammini deviati» e non danno incroci critici."""
    from app.engine.assign import EdgeLoad

    event = make_event(background=QUIET, closures=CLOSURE)
    base = diamond()
    network = apply_measures(base, event, "departure", [], config)

    def load(v_event: float, t_min: float, cost_min: float) -> EdgeLoad:
        return EdgeLoad(
            v_event=v_event,
            v_background=0.0,
            capacity_vph=10000.0,
            v_total=v_event,
            vc=v_event / 10000.0,
            t_min=t_min,
            cost_min=cost_min,
        )

    edges = {
        "1-3-0": load(100.0, 0.7, 5.0),
        "1-4-0": load(0.0, 0.9, 0.9),
        "3-2-0": load(100.0, 0.7, 5.0),
        "4-2-0": load(0.0, 0.9, 0.9),
    }
    assignment = Assignment(
        steps=4,
        seed=42,
        edges=edges,
        unassigned=(),
        demand_veh_per_hour=100.0,
        assigned_veh_per_hour=100.0,
        assumptions=(),
    )
    result = road_metrics(
        base,
        network,
        assignment,
        build_reference(base, event, "departure", config),
        demand_of([flow(1, 2, 100.0)]),
        event,
        config,
        background=build_background(base, event, "departure", network.closed),
        id_prefix=PREFIX,
        as_of=AS_OF,
    )
    metrics = by_tail(result)
    assert metrics["detour_extra_km"].value == pytest.approx(1.1, rel=1e-12)
    assert metrics["od_time.uno_due"].value == pytest.approx(1.8)  # Sud: tempo reale 0,9 + 0,9
    assert result.critical_intersections == ()
    assert not any(k.startswith("critical_intersection") for k in metrics)
    # nel layer: gli archi con flusso (il Nord) e quello chiuso; nessuno è sul cammino deviato
    assert [f.id for f in result.layers["edges_vc"].features] == ["1-3-0", "3-2-0", "1-2-0"]
    assert [f.properties["detour"] for f in result.layers["edges_vc"].features] == [False] * 3


# --- assunzioni di tutti gli input ---------------------------------------------------------------


def test_ogni_numero_porta_le_assunzioni_di_tutti_gli_input(config: EngineConfig) -> None:
    """Domanda, traffico di fondo, rete (chiusure e misure) e origine degli attributi della rete
    finiscono nelle assunzioni di ogni `Measured`; la dichiarazione del modello compare una volta
    sola, in testa."""
    flows = [flow(1, 2, 800.0)]
    event = make_event(background=QUIET, closures=CLOSURE)
    base = diamond()
    network = apply_measures(base, event, "departure", [], config)
    assert any("chiusure dell'evento" in a for a in network.assumptions)  # il testo vero
    demand = replace(
        demand_of(flows), assumptions=(STATIC_MODEL_ASSUMPTION, "assunzione della domanda")
    )
    background = replace(
        build_background(base, event, "departure", network.closed),
        assumptions=(STATIC_MODEL_ASSUMPTION, "assunzione del fondo"),
    )
    assignment = assign(network.graph, background.volumes, flows, config)
    result = road_metrics(
        base,
        network,
        assignment,
        build_reference(base, event, "departure", config),
        demand,
        event,
        config,
        background=background,
        id_prefix=PREFIX,
        as_of=AS_OF,
    )
    expected = (
        STATIC_MODEL_ASSUMPTION,
        *assignment.assumptions[1:],
        *network.assumptions[1:],
        "assunzione della domanda",
        "assunzione del fondo",
        describe_sources(base),
    )
    assert len(result.measures) >= 10
    for measure in result.measures:
        common = [a for a in measure.assumptions if a in expected]
        assert common == list(expected), measure.id
        assert measure.assumptions.count(STATIC_MODEL_ASSUMPTION) == 1, measure.id
