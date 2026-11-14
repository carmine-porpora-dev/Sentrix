import pytest

from app.agents.templates import (
    fallback_analysis,
    fallback_event_demand,
    fallback_notice,
    fallback_plan,
    fallback_replan,
    format_number,
)
from app.agents.validators import (
    parse_analysis,
    parse_event_demand,
    parse_notice,
    parse_plan,
    parse_replan,
)
from tests.agents_support import (
    CATALOG,
    CONFIG,
    candidate,
    config_with,
    event_demand,
    notice,
    plan,
    replan,
    traffic,
    transit,
)

# --- numeri all'italiana ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "decimals", "text"),
    [
        (4820.0, 1, "4.820"),
        (38.4, 1, "38,4"),
        (1.2, 1, "1,2"),
        (1.078, 1, "1,1"),  # arrotondato come i validatori
        (6, 1, "6"),
        (0.0, 1, "0"),
        (11250.0, 1, "11.250"),
        (1234567.0, 0, "1.234.567"),
        (2.675, 2, "2,68"),  # mezzo verso l'alto, non verso il pari
        (-12.0, 1, "-12"),
        (0.04, 1, "0"),
    ],
)
def test_i_numeri_si_scrivono_all_italiana(value: float, decimals: int, text: str) -> None:
    assert format_number(value, decimals) == text


# --- gli stessi validatori dell'LLM -------------------------------------------------------------


def test_i_testi_di_riserva_passano_gli_stessi_validatori() -> None:
    cases = [
        (event_demand(), fallback_event_demand, parse_event_demand),
        (traffic(), fallback_analysis, parse_analysis),
        (transit(), fallback_analysis, parse_analysis),
        (plan(), fallback_plan, parse_plan),
        (replan(), fallback_replan, parse_replan),
        ({**replan(), "alternatives": []}, fallback_replan, parse_replan),
        (notice(), fallback_notice, parse_notice),
        ({**notice(), "accepted": []}, fallback_notice, parse_notice),
        ({**traffic(), "signals": []}, fallback_analysis, parse_analysis),
        ({**plan(), "candidates": []}, fallback_plan, parse_plan),
    ]
    for payload, fallback, parse in cases:
        draft = fallback(payload, CONFIG)
        parse(draft.model_dump_json(), payload, CONFIG)  # non solleva: i testi sono validi


def test_ogni_misura_del_catalogo_ha_la_sua_etichetta() -> None:
    assert set(CONFIG.labels.measures) == {m.type for m in CATALOG.measures}


def test_senza_etichetta_si_scrive_il_tipo_di_misura() -> None:
    config = config_with(labels={"measures": {"altro": "altra misura"}})
    assert "traffic_post a Piazza Vittoria" in fallback_plan(plan(), config).text


# --- Event & Demand -----------------------------------------------------------------------------


def test_la_domanda_dell_evento_con_provenienza_dei_numeri() -> None:
    draft = fallback_event_demand(event_demand(), CONFIG)
    assert draft.text == (
        "Napoli–Juventus 2027 (27/08/2027): ipotesi di scenario di 45.000 persone "
        "(stima del modello). Nella finestra di deflusso (18:00–21:00), 18.000 persone nella "
        "fascia di picco: 11.250 in auto, 4.500 sui mezzi pubblici, 2.250 a piedi "
        "(stima del modello). Chiusure: Via Caracciolo."
    )
    assert "L'affluenza è un'ipotesi di scenario indicata nell'Evento." in draft.assumptions


def test_senza_dati_di_domanda_il_testo_lo_dice() -> None:
    payload = {**event_demand(), "measures": [], "context": {}}
    assert fallback_event_demand(payload, CONFIG).text == "Nessun dato di domanda disponibile."


def test_le_interruzioni_del_trasporto_si_elencano() -> None:
    payload = event_demand()
    payload["context"]["transit_disruptions"] = ["Stazione Mergellina chiusa"]
    text = fallback_event_demand(payload, CONFIG).text
    assert text.endswith("Interruzioni del trasporto pubblico: Stazione Mergellina chiusa.")


# --- Traffic e Transit: finding e scelta deterministica delle misure ----------------------------


def test_un_finding_per_segnale_e_la_prima_misura_ammessa() -> None:
    draft = fallback_analysis(traffic(), CONFIG)
    assert [f.signal for f in draft.findings] == ["s1", "s2"]
    assert [(r.signal, r.measure_type) for r in draft.recommendations] == [
        ("s1", "traffic_post"),  # non signal_plan_change: è la prima del catalogo
        ("s2", "detour_signage"),
    ]
    assert draft.findings[0].summary == (
        "Piazza Vittoria: incrocio con rapporto v/c 1,2 (stima del modello) "
        "nella finestra di deflusso."
    )
    assert draft.findings[1].summary == (
        "Riviera di Chiaia: archi molto carichi, rapporto v/c 1,3 (stima del modello) "
        "nella finestra di deflusso."
    )
    assert draft.recommendations[0].rationale == (
        "Misura del catalogo per questa criticità: presidio stradale."
    )


def test_il_trasporto_ha_le_sue_frasi_e_le_sue_misure() -> None:
    draft = fallback_analysis(transit(), CONFIG)
    summaries = {f.signal: f.summary for f in draft.findings}
    assert summaries["s1"] == (
        "Linea 1 della metropolitana: carico massimo di tratta 2,7 (stima), oltre la capacità, "
        "nella finestra di deflusso."
    )
    assert summaries["s2"] == (
        "Linea 6 della metropolitana: nessuna corsa nella finestra di deflusso."
    )
    assert (
        summaries["s3"]
        == "Fermata Riviera di Chiaia: carico 1,6 (stima) nella finestra di deflusso."
    )
    assert [(r.signal, r.measure_type) for r in draft.recommendations] == [
        ("s1", "extend_hours"),
        ("s2", "extend_hours"),
        ("s3", "crowd_control_post"),
    ]
    assert draft.text.startswith("Criticità del trasporto pubblico individuate dagli strumenti")


def test_una_fermata_oltre_la_soglia_di_sicurezza_si_dice() -> None:
    payload = transit()
    payload["signals"][2]["trigger"] = "stop_overloaded_unsafe"
    payload["signals"][2]["allowed"] = ["stop_suspension"]
    draft = fallback_analysis(payload, CONFIG)
    assert "oltre la soglia di sicurezza" in draft.findings[2].summary
    assert draft.recommendations[2].measure_type == "stop_suspension"


def test_un_segnale_di_sola_informazione_non_ha_raccomandazione() -> None:
    payload = traffic()
    payload["signals"][0]["severity"] = "info"
    draft = fallback_analysis(payload, CONFIG)
    assert [f.signal for f in draft.findings] == ["s1", "s2"]  # il finding c'è
    assert [r.signal for r in draft.recommendations] == ["s2"]  # la misura no


def test_un_segnale_senza_misure_ammesse_non_ha_raccomandazione() -> None:
    payload = traffic()
    payload["signals"][0]["allowed"] = []
    assert [r.signal for r in fallback_analysis(payload, CONFIG).recommendations] == ["s2"]


def test_un_trigger_sconosciuto_ha_una_frase_generica() -> None:
    payload = traffic()
    payload["signals"][0]["trigger"] = "altro_trigger"
    assert fallback_analysis(payload, CONFIG).findings[0].summary == (
        "Piazza Vittoria: criticità «altro_trigger», valore 1,2 (stima del modello), "
        "nella finestra di deflusso."
    )


def test_senza_il_valore_dell_evidenza_la_frase_non_lo_inventa() -> None:
    payload = traffic()
    payload["measures"] = []
    assert fallback_analysis(payload, CONFIG).findings[0].summary == (
        "Piazza Vittoria: criticità «critical_intersection» nella finestra di deflusso."
    )


def test_senza_segnali_il_testo_lo_dice() -> None:
    draft = fallback_analysis({**traffic(), "signals": []}, CONFIG)
    assert draft.text == "Gli strumenti non hanno individuato criticità stradali."
    assert draft.findings == [] and draft.recommendations == []


def test_la_sintesi_elenca_i_bersagli_con_la_gravita() -> None:
    assert fallback_analysis(traffic(), CONFIG).text == (
        "Criticità stradali individuate dagli strumenti (stima del modello): "
        "Piazza Vittoria (critica), Riviera di Chiaia (critica)."
    )


# --- Operations ---------------------------------------------------------------------------------


def test_il_piano_ordina_per_gravita_poi_per_arrivo_e_taglia_al_tetto() -> None:
    payload = plan()
    first, second = payload["candidates"]
    first["severity"], second["severity"] = "warning", "critical"
    third = {**first, "id": "c3", "severity": "critical", "target": "Piazza Dante"}
    payload["candidates"].append(third)
    payload["max_measures"] = 2
    draft = fallback_plan(payload, CONFIG)
    assert [item.candidate for item in draft.plan] == [
        "c2",
        "c3",
    ]  # le critiche, in ordine d'arrivo
    assert (
        draft.plan[0].rationale == "Incrocio saturo."
    )  # la motivazione dell'agente che l'ha proposta
    assert draft.text == (
        "Piano in ordine di gravità: presidio stradale a Piazza Sannazaro; "
        "presidio stradale a Piazza Dante."
    )


def test_il_piano_vuoto() -> None:
    draft = fallback_plan({**plan(), "candidates": []}, CONFIG)
    assert draft.plan == [] and draft.text == "Nessuna misura da pianificare."


def test_dopo_un_rifiuto_la_prima_alternativa() -> None:
    draft = fallback_replan(replan(), CONFIG)
    assert draft.choice == "a1"
    assert draft.text == (
        "Rifiutata la richiesta di presidio stradale a Incrocio 1: Pattuglie esaurite nella "
        "finestra 21:00–23:00: 6 totali, 6 già impegnate. "
        "In alternativa si chiede cambio del piano semaforico a Piazza Vittoria."
    )
    assert draft.rationale == "È la prima alternativa del catalogo compatibile con il bersaglio."


def test_senza_alternative_serve_una_decisione_umana() -> None:
    draft = fallback_replan({**replan(), "alternatives": []}, CONFIG)
    assert draft.choice is None
    assert draft.text.endswith("Nessuna alternativa compatibile: serve una decisione umana.")


def test_un_rifiuto_senza_motivo_non_lascia_due_punti_a_vuoto() -> None:
    payload = replan()
    payload["rejected"]["reject_reason"] = None
    assert fallback_replan(payload, CONFIG).text.startswith(
        "Rifiutata la richiesta di presidio stradale a Incrocio 1. In alternativa"
    )


def test_l_avviso_elenca_le_misure_approvate_con_orario() -> None:
    assert fallback_notice(notice(), CONFIG).text == (
        "Misure in vigore per l'evento: presidio stradale a Incrocio 1 (18:00–21:00)."
    )
    assert fallback_notice({**notice(), "accepted": []}, CONFIG).text == (
        "Nessuna misura straordinaria in vigore."
    )


def test_i_testi_di_riserva_non_dicono_mai_previsto() -> None:
    forbidden = set(CONFIG.language.forbidden_when_simulated)
    for payload, fallback in [
        (event_demand(), fallback_event_demand),
        (traffic(), fallback_analysis),
        (transit(), fallback_analysis),
        (plan(), fallback_plan),
        (replan(), fallback_replan),
        (notice(), fallback_notice),
    ]:
        text = fallback(payload, CONFIG).model_dump_json().lower()
        assert not any(word in text for word in forbidden), fallback.__name__


def test_un_candidato_di_prova_ha_la_gravita() -> None:
    assert candidate("c1").severity == "critical"
