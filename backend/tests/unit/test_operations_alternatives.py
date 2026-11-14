from dataclasses import dataclass, field

import pytest

from app.models.catalog import CatalogConfig
from app.operations.alternatives import (
    Alternative,
    UnknownMeasure,
    adapt,
    list_alternatives_for_measure,
)

CATALOG = CatalogConfig.from_yaml()
NODE = "3550591146"  # l'incrocio di un presidio rifiutato (formato 04 6.1)
LABEL = "Incrocio Piazza Sannazaro"


@dataclass
class StubLookup:
    """Il motore finto: risponde con ciò che gli si dà, e ricorda cosa gli è stato chiesto."""

    edges: dict[str, list[str]] = field(default_factory=lambda: {NODE: ["11-22-0", "33-22-0"]})
    favored: dict[str, str] = field(default_factory=lambda: {NODE: "11-22-0"})
    routes: dict[str, list[str]] = field(
        default_factory=lambda: {"stop_dante": ["metro_line_1", "bus_r1"]}
    )
    asked: list[str] = field(default_factory=list)

    def upstream_edges(self, node: str) -> list[str]:
        self.asked.append(f"edges:{node}")
        return self.edges.get(node, [])

    def favored_edge_key(self, node: str) -> str | None:
        self.asked.append(f"favored:{node}")
        return self.favored.get(node)

    def routes_serving(self, stop_id: str) -> list[str]:
        self.asked.append(f"routes:{stop_id}")
        return self.routes.get(stop_id, [])


def alternatives(measure: str, target: str, lookup: StubLookup) -> list[Alternative]:
    return list_alternatives_for_measure(CATALOG, measure, target, LABEL, lookup)


# --- la scena di rifiuto: presidio → cambio di piano semaforico (04 7) --------------------------


def test_un_presidio_rifiutato_ha_per_prima_il_cambio_di_piano_allo_stesso_incrocio() -> None:
    first, second = alternatives("traffic_post", NODE, StubLookup())
    assert first == Alternative(
        "signal_plan_change",
        "traffic_control",
        NODE,
        LABEL,
        {"favored_edge_key": "11-22-0"},
    )
    assert second.type == "detour_signage" and second.department == "traffic_control"


def test_la_segnaletica_e_sugli_archi_a_monte_dell_incrocio() -> None:
    *_, detour = alternatives("traffic_post", NODE, StubLookup())
    assert detour.target == "11-22-0,33-22-0"  # chiavi separate da virgola (04 6.1)
    assert detour.target_label == f"Archi a monte di {LABEL}"
    assert detour.payload == {}


def test_l_ordine_e_quello_del_catalogo() -> None:
    types = [a.type for a in alternatives("traffic_post", NODE, StubLookup())]
    assert types == CATALOG.measure("traffic_post").alternatives  # type: ignore[union-attr]


def test_senza_archi_a_monte_la_segnaletica_non_si_propone() -> None:
    lookup = StubLookup(edges={})
    assert [a.type for a in alternatives("traffic_post", NODE, lookup)] == ["signal_plan_change"]


def test_senza_un_arco_da_favorire_il_cambio_di_piano_non_si_propone() -> None:
    lookup = StubLookup(favored={})
    assert [a.type for a in alternatives("traffic_post", NODE, lookup)] == ["detour_signage"]


def test_i_doppioni_negli_archi_si_tolgono_senza_cambiare_l_ordine() -> None:
    lookup = StubLookup(edges={NODE: ["5-6-0", "1-2-0", "5-6-0", "1-2-0"]})
    *_, detour = alternatives("traffic_post", NODE, lookup)
    assert detour.target == "5-6-0,1-2-0"


def test_un_cambio_di_piano_rifiutato_ripiega_sulla_segnaletica() -> None:
    (detour,) = alternatives("signal_plan_change", NODE, StubLookup())
    assert detour.type == "detour_signage" and detour.target == "11-22-0,33-22-0"


# --- le altre catene del catalogo -----------------------------------------------------------------


def test_un_prolungamento_d_orario_rifiutato_ripiega_su_piu_corse_della_stessa_linea() -> None:
    (runs,) = alternatives("extend_hours", "metro_line_6", StubLookup())
    assert runs == Alternative("add_runs", "transport_control", "metro_line_6", LABEL)


def test_un_presidio_di_afflusso_rifiutato_ripiega_su_corse_della_linea_che_serve_la_fermata() -> (
    None
):
    (runs,) = alternatives("crowd_control_post", "stop_dante", StubLookup())
    assert runs.type == "add_runs" and runs.department == "transport_control"
    assert runs.target == "metro_line_1"  # la più rilevante, la prima
    assert runs.target_label == f"Linea per {LABEL}"


def test_senza_linee_che_servono_la_fermata_non_c_e_un_alternativa() -> None:
    assert alternatives("crowd_control_post", "stop_isolata", StubLookup()) == []


@pytest.mark.parametrize(
    "measure", ["detour_signage", "add_runs", "stop_suspension", "citizen_notice"]
)
def test_le_misure_senza_alternative_ne_danno_nessuna(measure: str) -> None:
    lookup = StubLookup()
    assert alternatives(measure, NODE, lookup) == []
    assert lookup.asked == []  # e non chiedono niente al motore


# --- compatibilità --------------------------------------------------------------------------------


def test_tutte_le_coppie_del_catalogo_sono_gestite() -> None:
    """Se il catalogo aggiunge un'alternativa con una coppia di tipi di bersaglio che `adapt` non
    conosce, questo test lo dice: con un motore che risponde a tutto, nessuna alternativa del
    catalogo deve andare persa."""
    full = StubLookup(
        edges={"x": ["1-2-0"]}, favored={"x": "1-2-0"}, routes={"x": ["metro_line_1"]}
    )
    for measure in CATALOG.measures:
        found = [
            a.type for a in list_alternatives_for_measure(CATALOG, measure.type, "x", "L", full)
        ]
        assert found == measure.alternatives, measure.type


def test_ogni_alternativa_ha_il_dipartimento_e_il_tipo_di_bersaglio_della_sua_misura() -> None:
    full = StubLookup(
        edges={"x": ["1-2-0"]}, favored={"x": "1-2-0"}, routes={"x": ["metro_line_1"]}
    )
    for measure in CATALOG.measures:
        for found in list_alternatives_for_measure(CATALOG, measure.type, "x", "L", full):
            chosen = CATALOG.measure(found.type)
            assert chosen is not None and found.department == chosen.department


def test_una_coppia_che_non_si_conosce_non_e_compatibile() -> None:
    stop_measure = CATALOG.measure("stop_suspension")
    assert stop_measure is not None
    assert adapt("edges", stop_measure, "1-2-0", "L", StubLookup()) is None
    assert adapt("none", stop_measure, "x", "L", StubLookup()) is None
    assert adapt("stop", stop_measure, "x", "L", StubLookup()) is None  # fermata → fermata


def test_il_motore_si_interroga_solo_per_quello_che_serve() -> None:
    lookup = StubLookup()
    alternatives("traffic_post", NODE, lookup)
    assert lookup.asked == [f"favored:{NODE}", f"edges:{NODE}"]  # nell'ordine del catalogo


# --- errori ------------------------------------------------------------------------------------


@pytest.mark.parametrize("measure", ["close_road", "bus_detour", "bombardamento"])
def test_un_tipo_che_non_e_nel_catalogo_e_un_errore(measure: str) -> None:
    """Il catalogo è chiuso: `close_road` e `bus_detour` sono richieste, non misure da proporre."""
    with pytest.raises(UnknownMeasure, match=f"'{measure}' non è una misura del catalogo"):
        alternatives(measure, NODE, StubLookup())
