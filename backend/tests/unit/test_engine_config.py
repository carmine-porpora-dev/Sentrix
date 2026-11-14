import copy
import re
from datetime import time
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

from app.models.config import DEFAULT_ENGINE_CONFIG_PATH, EngineConfig, RailKind, VehicleKind
from app.models.demand import Zone, check_zone_set
from app.models.geo import GeoPoint
from tests.support import DELETE, mutated

YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "engine.yaml"


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    loaded = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def config() -> EngineConfig:
    return EngineConfig.from_yaml(YAML_PATH)


def error_text(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        EngineConfig.model_validate(data)
    return str(info.value)


# --- Il file reale contiene i valori approvati ---------------------------------------------------


def test_il_file_di_default_e_quello_del_repository() -> None:
    assert DEFAULT_ENGINE_CONFIG_PATH == YAML_PATH and YAML_PATH.is_file()
    assert EngineConfig.from_yaml() == EngineConfig.from_yaml(YAML_PATH)


def test_valori_generali_e_strada(config: EngineConfig) -> None:
    assert (config.version, config.seed, config.time_slice_minutes) == (1, 42, 30)
    assert (config.assignment.steps, config.assignment.step_share) == (16, 0.0625)  # 9/11/2026
    assert (config.bpr.alpha, config.bpr.beta) == (0.15, 4)
    assert config.car_occupancy_default == 2.2
    assert config.node_snap_max_distance_m == 300  # 01 6
    assert config.metrics.vc_critical_threshold == 0.9
    assert config.metrics.vc_classes == (0.6, 0.9, 1.1)
    assert config.metrics.critical_intersections_top_n == 2


def test_road_defaults_come_in_02_1(config: EngineConfig) -> None:
    expected = {  # classe: (corsie, km/h, capacità per corsia)
        "motorway": (2, 80, 1800), "motorway_link": (1, 40, 1200), "trunk": (2, 60, 1400),
        "trunk_link": (1, 40, 1200), "primary": (2, 50, 900), "primary_link": (1, 40, 800),
        "secondary": (1, 50, 800), "secondary_link": (1, 40, 700), "tertiary": (1, 40, 600),
        "tertiary_link": (1, 30, 500), "residential": (1, 30, 400), "unclassified": (1, 30, 400),
        "living_street": (1, 20, 300), "default": (1, 30, 400),
    }  # fmt: skip
    got = {k: (v.lanes, v.speed_kmh, v.capacity_per_lane) for k, v in config.road_defaults.items()}
    assert got == expected


def test_effetti_delle_misure(config: EngineConfig) -> None:
    effects = config.measure_effects
    assert (effects.traffic_post.capacity_factor, effects.traffic_post.scope) == (
        1.25,
        "incoming_edges",
    )
    assert (effects.signal_plan_change.capacity_factor, effects.signal_plan_change.scope) == (
        1.15, "incoming_edges_favored_direction",
    )  # fmt: skip
    assert (effects.detour_signage.perceived_time_factor, effects.detour_signage.scope) == (
        1.20, "saturated_path_edges",
    )  # fmt: skip
    assert (effects.close_road.capacity_factor, effects.close_road.scope) == (0.0, None)


def test_le_13_zone_come_in_01_2_1(config: EngineConfig) -> None:
    expected = [  # id, tipo, peso %, lat, lon
        ("gate_east", "road_gate", 12, 40.8736, 14.2878),  # spostate il 9/11 sulla Tangenziale
        ("gate_west", "road_gate", 8, 40.8397, 14.1665),
        ("gate_metro_north", "metro_gate", 8, 40.8935, 14.2240),
        ("central_station", "arrival_hub", 12, 40.8530, 14.2720),
        ("port", "arrival_hub", 4, 40.8380, 14.2540), ("chiaia", "near", 8, 40.8375, 14.2370),
        ("posillipo", "near", 5, 40.8180, 14.2091), ("san_ferdinando", "near", 6, 40.8400, 14.2520),
        ("vomero", "far", 10, 40.8440, 14.2300), ("arenella", "far", 6, 40.8510, 14.2290),
        ("centro_storico", "far", 8, 40.8490, 14.2500), ("fuorigrotta", "far", 8, 40.8240, 14.1950),
        ("bagnoli", "far", 5, 40.8132, 14.1669),
    ]  # fmt: skip
    got = [
        (z.id, z.type, z.weight_pct, z.centroid.lat, z.centroid.lon) for z in config.demand.zones
    ]
    assert got == expected
    assert sum(z.weight_pct for z in config.demand.zones) == 100


def test_ripartizione_modale_destinazioni_e_coppie(config: EngineConfig) -> None:
    split = {
        t: (m.car_pct, m.transit_pct, m.walk_pct)
        for t, m in config.demand.modal_split_by_type.items()
    }
    assert split == {
        "road_gate": (100, 0, 0), "metro_gate": (0, 100, 0), "arrival_hub": (0, 80, 20),
        "near": (20, 30, 50), "far": (30, 60, 10),
    }  # fmt: skip
    cars = [
        (d.point.label, d.point.lat, d.point.lon, d.share_pct)
        for d in config.demand.car_destinations
    ]
    assert cars == [  # 5 punti dal 9/11/2026 (prima 2; Piazza Vittoria spostata sull'incrocio)
        ("Piazza Vittoria", 40.8330, 14.2411, 20),
        ("Piazza Sannazaro", 40.8290, 14.2220, 20),
        ("Corso Vittorio Emanuele (Via Tasso)", 40.8367, 14.2294, 20),
        ("Corso Vittorio Emanuele (Piazzetta Cariati)", 40.8397, 14.2426, 20),
        ("Piazza Municipio", 40.8405, 14.2525, 20),
    ]

    def endpoint(e: Any) -> Any:
        return e.zone if e.zone else (e.point.lat, e.point.lon)

    pairs = [(p.id, endpoint(p.origin), endpoint(p.destination)) for p in config.demand.od_pairs]
    assert pairs == [
        ("bagnoli_centrale", "bagnoli", "central_station"),
        ("fuorigrotta_municipio", "fuorigrotta", (40.8405, 14.2525)),
        ("vomero_vittoria", (40.8440, 14.2300), (40.8330, 14.2411)),
        ("posillipo_municipio", (40.8059, 14.2007), (40.8405, 14.2525)),
        ("tangenziale_garibaldi", (40.8290, 14.1960), (40.8520, 14.2700)),
    ]


def test_trasporto_pubblico_come_in_03_1_e_report_f0(config: EngineConfig) -> None:
    t = config.transit
    assert (t.stop_radius_m, t.redistribution_radius_m, t.walk_detour_factor) == (800, 1000, 1.3)
    assert t.vehicle_capacity == {
        "bus": 90,
        "metro_line_1": 1250,
        "metro_line_6": 290,
        "funicular": 250,
    }
    assert t.vehicle_capacity_sources["metro_line_1"] == "dato ANM (ago 2024)"
    assert t.vehicle_capacity_sources["bus"] == "ipotesi"
    assert t.route_classification.metro_line_1.route_ids == [
        "4955"
    ]  # report dati F0 (Q5 confermata)
    assert t.route_classification.metro_line_6.route_ids == ["2302"]
    assert t.route_classification.funicular.route_ids == ["2305", "2315", "2300"]
    assert (t.extend_hours_default_end, t.add_runs_default) == (time(23, 59), 4)
    assert t.extend_hours_default_end.tzinfo is None


def test_gli_itinerari_come_in_03_2(config: EngineConfig) -> None:
    itineraries = config.transit.itineraries
    assert set(itineraries) == {zone.id for zone in config.demand.zones}
    # per zona: (numero di tratte, a piedi dopo l'ultima) di ogni itinerario, in ordine
    assert {
        zone: [(len(i.legs), i.egress_walk) for i in its] for zone, its in itineraries.items()
    } == {
        "gate_east": [],
        "gate_west": [],
        "gate_metro_north": [(2, False), (1, True)],
        "central_station": [(2, False), (1, True)],
        "vomero": [(1, True), (2, False)],
        "arenella": [(2, False), (1, True)],
        "centro_storico": [(2, False), (1, True)],
        "fuorigrotta": [(1, False), (1, True)],
        "posillipo": [(1, True)],
        "port": [(1, False), (0, True)],
        "chiaia": [],
        "san_ferdinando": [],
        "bagnoli": [],
    }

    def legs(zone: str, number: int) -> list[tuple[str, str, str]]:
        return [
            (leg.route_class, leg.from_stop_name, leg.to_stop_name)
            for leg in itineraries[zone][number].legs
        ]

    l6_to_area = ("metro_line_6", "Municipio", "San Pasquale")
    assert legs("gate_metro_north", 0) == [("metro_line_1", "Piscinola", "Municipio"), l6_to_area]
    assert legs("vomero", 0) == [("funicular", "Cimarosa", "Parco Margherita")]
    assert legs("vomero", 1) == [("metro_line_1", "Vanvitelli", "Municipio"), l6_to_area]
    assert legs("fuorigrotta", 0) == [("metro_line_6", "Mostra", "Arco Mirelli")]
    assert legs("fuorigrotta", 1) == [("metro_line_6", "Mostra", "Mergellina")]
    assert legs("posillipo", 0) == [("funicular", "Manzoni", "Mergellina")]
    assert legs("port", 0) == [l6_to_area]
    assert legs("port", 1) == []  # a piedi


def test_le_classi_con_itinerari_sono_i_tipi_di_veicolo_tranne_il_bus() -> None:
    assert set(get_args(RailKind)) == set(get_args(VehicleKind)) - {"bus"}


def test_la_configurazione_e_immutabile(config: EngineConfig) -> None:
    with pytest.raises(ValidationError, match="frozen"):
        config.seed = 7  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        config.bpr.alpha = 0.2  # type: ignore[misc]


# --- Validazione -------------------------------------------------------------------------------

Z = ("demand", "zones")
OD = ("demand", "od_pairs")
RC = ("transit", "route_classification")
TR = ("transit",)
VC = ("metrics", "vc_classes")
CAP = (*TR, "vehicle_capacity")
SRC = (*TR, "vehicle_capacity_sources")
END = (*TR, "extend_hours_default_end")
L1, L6, FUN = ((*RC, group, "route_ids") for group in ("metro_line_1", "metro_line_6", "funicular"))
IT = (*TR, "itineraries")


def leg(zone: str, number: int, field: str) -> tuple[str | int, ...]:
    """Il campo `field` della tratta `number` del primo itinerario di `zone`."""
    return (*IT, zone, 0, "legs", number, field)


# (nome, percorso del campo, nuovo valore, frammento dell'errore atteso)
SNAP = ("node_snap_max_distance_m",)
CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    ("pesi zone ≠ 100", (*Z, 0, "weight_pct"), 13, "I pesi delle zone deve sommare a 100"),
    ("tipo di zona sconosciuto", (*Z, 0, "type"), "boh", "type"),
    ("id zona duplicato", (*Z, 1, "id"), "gate_east", "id di zona duplicati: gate_east"),
    ("id zona non è uno slug", (*Z, 0, "id"), "Porta Est", "String should match pattern"),
    ("id O/D non è uno slug", (*OD, 0, "id"), "Bagnoli-Centrale", "String should match pattern"),
    ("lat fuori range", (*Z, 0, "centroid", "lat"), 95, "less than or equal to 90"),
    ("lat sotto -90", (*Z, 0, "centroid", "lat"), -91, "greater than or equal to -90"),
    ("lon fuori range", (*Z, 0, "centroid", "lon"), 181, "less than or equal to 180"),
    ("lon sotto -180", (*Z, 0, "centroid", "lon"), -181, "greater than or equal to -180"),
    ("ripartizione ≠ 100", ("demand", "modal_split_by_type", "far", "car_pct"), 50,
     "La ripartizione modale deve sommare a 100"),
    ("manca un tipo di zona", ("demand", "modal_split_by_type", "far"), DELETE,
     "manca la ripartizione modale per i tipi di zona: ['far']"),
    ("quote auto ≠ 100", ("demand", "car_destinations", 0, "share_pct"), 60,
     "Le quote delle destinazioni auto deve sommare a 100"),
    ("O/D con zona inesistente", (*OD, 0, "origin", "zone"), "atlantide", "'atlantide' non esiste"),
    ("O/D senza estremo", (*OD, 0, "origin"), {}, "o `zone` o `point`"),
    ("O/D con zona e punto", (*OD, 0, "origin", "point"), {"lat": 1, "lon": 1}, "o `zone` o"),
    ("id O/D duplicati", (*OD, 1, "id"), "bagnoli_centrale", "id delle coppie O/D duplicati"),
    ("passi che non coprono la matrice", ("assignment", "steps"), 3, "steps × step_share deve"),
    ("BPR alpha negativo", ("bpr", "alpha"), -0.1, "greater than 0"),
    ("manca la classe default", ("road_defaults", "default"), DELETE, "chiave 'default'"),
    ("corsie zero", ("road_defaults", "primary", "lanes"), 0, "greater than or equal to 1"),
    ("chiusura che non chiude", ("measure_effects", "close_road", "capacity_factor"), 0.1,
     "close_road deve avere capacity_factor 0"),
    ("scope sconosciuto", ("measure_effects", "traffic_post", "scope"), "ovunque", "scope"),
    ("vc_classes non crescente", VC, [0.9, 0.6, 1.1], "vc_classes deve essere crescente"),
    ("vc_classes con negativo", VC, [-0.1, 0.9, 1.1], "vc_classes deve essere crescente"),
    ("vc_classes con 2 soglie", VC, [0.6, 0.9], "vc_classes"),
    ("refuso in una chiave annidata", ("bpr", "alfa"), 0.15, "Extra inputs are not permitted"),
    ("chiave sconosciuta in radice", ("extra",), 1, "Extra inputs are not permitted"),
    ("manca un parametro", ("seed",), DELETE, "seed\n  Field required"),
    ("manca la distanza di aggancio", SNAP, DELETE, "node_snap_max_distance_m\n  Field required"),
    ("distanza di aggancio zero", SNAP, 0, "greater than 0"),
    ("distanza di aggancio negativa", SNAP, -5, "greater than 0"),
    ("versione sconosciuta", ("version",), 2, "version"),
    ("route_id numerico (YAML senza virgolette)", L1, [4955], "valid string"),
    ("route_ids vuoti", FUN, [], "at least 1 item"),
    ("route_id duplicato nello stesso gruppo", FUN, ["2305", "2305"], "senza duplicati"),
    ("route_id fatto di soli spazi", FUN, ["2305", "  "], "senza duplicati"),
    ("route_id in due gruppi", L6, ["4955"], "route_id '4955' in due gruppi"),
    ("manca un tipo di veicolo", (*CAP, "bus"), DELETE, "vehicle_capacity: attese le chiavi"),
    ("capacità non positiva", (*CAP, "bus"), 0, "capacità devono essere positive"),
    ("capacità senza fonte", (*SRC, "bus"), "  ", "ogni capacità ha una fonte"),
    ("fattore a piedi < 1", (*TR, "walk_detour_factor"), 0.9, "greater than or equal to 1"),
    ("orario YAML 23:59 senza virgolette (=1439)", END, 1439, 'serve una stringa "HH:MM"'),
    ("orario con il fuso", END, "23:59+01:00", 'serve una stringa "HH:MM"'),
    ("orario impossibile", END, "25:99", "time format"),
    ("corse aggiuntive zero", (*TR, "add_runs_default"), 0, "greater than or equal to 1"),
    ("itinerari: manca una zona", (*IT, "bagnoli"), DELETE, "mancano le zone ['bagnoli']"),
    ("itinerari: zona che non esiste", (*IT, "atlantide"), [],
     "zone che non esistono ['atlantide']"),
    ("itinerari: senza tratte e senza piedi", (*IT, "port", 1, "egress_walk"), False,
     "senza tratte deve essere a piedi"),
    ("itinerari: interscambio non dichiarato", leg("central_station", 1, "from_stop_name"),
     "Duomo", "l'interscambio non è dichiarato"),
    ("itinerari: sale e scende alla stessa fermata", leg("fuorigrotta", 0, "to_stop_name"),
     " mostra ", "sale e scende alla stessa fermata"),
    ("itinerari: classe bus in una tratta", leg("fuorigrotta", 0, "route_class"), "bus",
     "route_class"),
    ("itinerari: nome di fermata vuoto", leg("fuorigrotta", 0, "from_stop_name"), "",
     "at least 1 character"),
    ("itinerari: chiave di tratta sconosciuta", leg("fuorigrotta", 0, "line"), "L6",
     "Extra inputs are not permitted"),
    ("itinerari: manca egress_walk", (*IT, "port", 0, "egress_walk"), DELETE, "Field required"),
    ("itinerari: elenco assente", IT, DELETE, "itineraries\n  Field required"),
]  # fmt: skip


def test_zone_mancante_e_zona_inesistente_insieme(raw: dict[str, Any]) -> None:
    """Una zona rinominata: mancano 'bagnoli' ed esiste 'atlantide', anche se i numeri tornano."""
    data = mutated(raw, (*IT, "atlantide"), [])
    data = mutated(data, (*IT, "bagnoli"), DELETE)
    text = error_text(data)
    assert "mancano le zone ['bagnoli']" in text and "zone che non esistono ['atlantide']" in text


@pytest.mark.parametrize(("name", "path", "value", "fragment"), CASES, ids=[c[0] for c in CASES])
def test_valori_non_validi_sono_rifiutati(
    raw: dict[str, Any], name: str, path: tuple[str | int, ...], value: Any, fragment: str
) -> None:
    assert fragment in error_text(mutated(raw, path, value)), name


def test_la_tolleranza_sui_pesi_e_mezzo_punto(raw: dict[str, Any]) -> None:
    ok = mutated(raw, (*Z, 0, "weight_pct"), 12.4)  # somma 100,4
    assert EngineConfig.model_validate(ok).demand.zones[0].weight_pct == 12.4
    assert "I pesi delle zone" in error_text(mutated(raw, (*Z, 0, "weight_pct"), 12.6))


def test_la_tolleranza_include_esattamente_mezzo_punto(raw: dict[str, Any]) -> None:
    exactly = mutated(raw, (*Z, 0, "weight_pct"), 12.5)  # somma 100,5: al limite, accettata
    assert EngineConfig.model_validate(exactly).demand.zones[0].weight_pct == 12.5
    assert "I pesi delle zone" in error_text(mutated(raw, (*Z, 0, "weight_pct"), 12.51))
    below = mutated(raw, (*Z, 0, "weight_pct"), 11.5)  # somma 99,5: limite inferiore
    assert EngineConfig.model_validate(below).demand.zones[0].weight_pct == 11.5
    assert "I pesi delle zone" in error_text(mutated(raw, (*Z, 0, "weight_pct"), 11.49))


def test_check_zone_set_e_riusabile_per_gli_eventi() -> None:
    point = GeoPoint(lat=40.8, lon=14.2)
    zones = [Zone(id="a", name="A", type="near", weight_pct=60, centroid=point),
             Zone(id="b", name="B", type="far", weight_pct=40, centroid=point)]  # fmt: skip
    check_zone_set(zones)
    with pytest.raises(ValueError, match="sommare a 100"):
        check_zone_set(zones[:1])


# --- Caricamento da YAML -----------------------------------------------------------------------


def test_chiavi_duplicate_nel_yaml_sono_un_errore() -> None:
    text = YAML_PATH.read_text(encoding="utf-8").replace("seed: 42\n", "seed: 42\nseed: 43\n", 1)
    with pytest.raises(yaml.YAMLError, match="chiave duplicata 'seed'"):
        EngineConfig.from_yaml_text(text)


def test_chiavi_duplicate_in_una_mappa_annidata() -> None:
    text = YAML_PATH.read_text(encoding="utf-8").replace(
        "bpr: { alpha: 0.15, beta: 4 }", "bpr: { alpha: 0.15, alpha: 0.2, beta: 4 }"
    )
    with pytest.raises(yaml.YAMLError, match="chiave duplicata 'alpha'"):
        EngineConfig.from_yaml_text(text)


def test_yaml_che_non_e_una_mappa() -> None:
    with pytest.raises(ValueError, match="mappa di sezioni"):
        EngineConfig.from_yaml_text("- uno\n- due\n")


def test_yaml_non_valido_e_file_mancante(tmp_path: Path) -> None:
    with pytest.raises(yaml.YAMLError):
        EngineConfig.from_yaml_text("a: [1, 2")
    with pytest.raises(FileNotFoundError):
        EngineConfig.from_yaml(tmp_path / "manca.yaml")


def test_orario_tra_virgolette_nel_testo_yaml() -> None:
    text = YAML_PATH.read_text(encoding="utf-8")
    assert 'extend_hours_default_end: "23:59"' in text
    with pytest.raises(ValidationError, match="HH:MM"):
        EngineConfig.from_yaml_text(text.replace('"23:59"', "23:59"))  # senza virgolette: 1439


# --- Hash --------------------------------------------------------------------------------------


def test_hash_stabile_e_in_esadecimale(config: EngineConfig) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", config.content_hash())
    assert config.content_hash() == EngineConfig.from_yaml(YAML_PATH).content_hash()


def test_hash_ignora_commenti_ordine_e_formato(config: EngineConfig, raw: dict[str, Any]) -> None:
    reformatted = yaml.safe_dump(raw, sort_keys=True, default_flow_style=False, allow_unicode=True)
    assert "#" not in reformatted and reformatted != YAML_PATH.read_text(encoding="utf-8")
    assert EngineConfig.from_yaml_text(reformatted).content_hash() == config.content_hash()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("bpr", "alpha"), 0.16),
        ((*RC, "metro_line_6", "route_ids"), ["2302", "9999"]),
        ((*TR, "vehicle_capacity_sources", "bus"), "altra fonte"),
        (("seed",), 43),
    ],
    ids=["valore numerico", "route_id", "fonte di una capacità", "seed"],
)
def test_hash_cambia_se_cambia_un_valore(
    config: EngineConfig, raw: dict[str, Any], path: tuple[str | int, ...], value: Any
) -> None:
    assert (
        EngineConfig.model_validate(mutated(raw, path, value)).content_hash()
        != config.content_hash()
    )


def test_hash_cambia_se_cambia_l_ordine_di_una_lista(
    config: EngineConfig, raw: dict[str, Any]
) -> None:
    data = copy.deepcopy(raw)
    data["demand"]["zones"].reverse()  # l'ordine delle liste è semantico
    assert EngineConfig.model_validate(data).content_hash() != config.content_hash()


def test_l_hash_non_dipende_dall_ordine_delle_chiavi_annidate(config: EngineConfig) -> None:
    """`content_hash` ordina le chiavi in ogni mappa, non solo al primo livello."""
    defaults = dict(reversed(config.road_defaults.items()))
    assert list(defaults) != list(config.road_defaults)
    reordered = config.model_copy(update={"road_defaults": defaults})
    assert reordered.content_hash() == config.content_hash()
