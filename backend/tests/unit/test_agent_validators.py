import json
from pathlib import Path
from typing import Any

import pytest

from app.agents.drafts import AnalysisDraft, json_schema
from app.agents.payloads import (
    quotable,
)
from app.agents.validators import (
    MAX_REPORTED_PROBLEMS,
    parse_analysis,
    parse_event_demand,
    parse_notice,
    parse_plan,
    parse_replan,
)
from app.llm.client import InvalidResponse, LlmRequest
from tests.agents_support import (
    CONFIG,
    EVIDENCE,
    config_with,
    event_demand,
    notice,
    plan,
    replan,
    traffic,
    transit,
)
from tests.llm_support import FakeBackend, make_client, make_llm_repo


def answer(**fields: Any) -> str:
    return json.dumps({"text": "Sintesi.", **fields})


def analysis_ok(payload: dict[str, Any], **fields: Any) -> None:
    parse_analysis(answer(**fields), payload, CONFIG)


def analysis_bad(payload: dict[str, Any], match: str, **fields: Any) -> None:
    with pytest.raises(InvalidResponse, match=match):
        parse_analysis(answer(**fields), payload, CONFIG)


# --- schema -------------------------------------------------------------------------------------


def test_una_risposta_valida_e_restituita_come_bozza() -> None:
    draft = parse_analysis(
        answer(
            findings=[{"signal": "s1", "summary": "Incrocio saturo a Piazza Vittoria."}],
            recommendations=[
                {"signal": "s1", "measure_type": "traffic_post", "rationale": "Serve un presidio."}
            ],
            assumptions=["Il modello è statico e non calibrato."],
        ),
        traffic(),
        CONFIG,
    )
    assert (
        draft.findings[0].signal == "s1" and draft.recommendations[0].measure_type == "traffic_post"
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("non è json", "non è JSON valido"),
        ("", "non è JSON valido"),
        ("[]", "non rispetta lo schema: risposta"),
        ('"testo"', "non rispetta lo schema: risposta"),
        ("{}", "text: Field required"),
        ('{"text": "ok", "extra": 1}', "extra: Extra inputs are not permitted"),
        ('{"text": 5}', "text: Input should be a valid string"),
        ('{"text": "ok", "findings": [{"signal": "s1"}]}', "findings.0.summary: Field required"),
    ],
)
def test_una_risposta_che_non_e_la_bozza_non_e_valida(raw: str, message: str) -> None:
    with pytest.raises(InvalidResponse, match=message):
        parse_analysis(raw, traffic(), CONFIG)


def test_lo_schema_sbagliato_non_riporta_il_valore_ricevuto() -> None:
    """Il messaggio finisce in un prompt: dice dove e perché, non rimanda indietro l'input."""
    with pytest.raises(InvalidResponse) as caught:
        parse_analysis('{"text": 12345678}', traffic(), CONFIG)
    assert "12345678" not in str(caught.value)


def test_un_testo_vuoto_non_e_valido() -> None:
    with pytest.raises(InvalidResponse, match="text: String should have at least 1 character"):
        parse_analysis(json.dumps({"text": ""}), traffic(), CONFIG)


@pytest.mark.parametrize("blank", ["   ", "\n\t"])
def test_un_testo_di_soli_spazi_non_e_valido(blank: str) -> None:
    analysis_bad(traffic(), "«text» è vuoto", text=blank)


def test_un_finding_o_una_motivazione_di_soli_spazi_non_e_valido() -> None:
    analysis_bad(
        traffic(), r"«findings\[0\]\.summary» è vuoto", findings=[{"signal": "s1", "summary": " "}]
    )
    analysis_bad(
        traffic(),
        r"«recommendations\[0\]\.rationale» è vuoto",
        recommendations=[{"signal": "s1", "measure_type": "traffic_post", "rationale": " "}],
    )
    analysis_bad(traffic(), r"«assumptions\[1\]» è vuoto", assumptions=["Modello statico.", " "])


# --- scelte e catalogo --------------------------------------------------------------------------


def test_un_segnale_che_non_c_e_non_e_valido() -> None:
    analysis_bad(
        traffic(),
        r"«findings\[0\]\.signal» è «s9», che non è un segnale dell'input \(ammessi: s1, s2\)",
        findings=[{"signal": "s9", "summary": "Inventato."}],
    )
    analysis_bad(
        traffic(),
        r"«recommendations\[0\]\.signal» è «s0»",
        recommendations=[{"signal": "s0", "measure_type": "traffic_post", "rationale": "x"}],
    )


def test_senza_segnali_nessun_finding_e_ammesso() -> None:
    payload = {**traffic(), "signals": []}
    analysis_bad(payload, r"ammessi: nessuno", findings=[{"signal": "s1", "summary": "x"}])
    analysis_ok(payload)


def test_un_solo_finding_per_segnale() -> None:
    analysis_bad(
        traffic(),
        r"«findings\[1\]\.signal» s1: un solo finding per segnale",
        findings=[{"signal": "s1", "summary": "Uno."}, {"signal": "s1", "summary": "Due."}],
    )
    analysis_ok(
        traffic(),
        findings=[{"signal": "s1", "summary": "Uno."}, {"signal": "s2", "summary": "Due."}],
    )


@pytest.mark.parametrize(
    ("signal", "measure"),
    [("s1", "traffic_post"), ("s1", "signal_plan_change"), ("s2", "detour_signage")],
)
def test_le_misure_ammesse_per_il_segnale_passano(signal: str, measure: str) -> None:
    analysis_ok(
        traffic(),
        recommendations=[{"signal": signal, "measure_type": measure, "rationale": "Serve."}],
    )


@pytest.mark.parametrize(
    ("signal", "measure"),
    [
        ("s1", "detour_signage"),  # nel catalogo, ma per un altro trigger
        ("s2", "traffic_post"),
        ("s1", "stop_suspension"),  # nel catalogo, ma per un altro tipo di bersaglio
        ("s1", "close_road"),  # non è una misura del catalogo
        ("s1", "bombardamento"),
    ],
)
def test_una_misura_non_ammessa_per_quel_segnale_non_e_valida(signal: str, measure: str) -> None:
    analysis_bad(
        traffic(),
        rf"«recommendations\[0\]\.measure_type» è «{measure}», che non è una misura ammessa per il "
        rf"segnale {signal} \(ammessi: ",
        recommendations=[{"signal": signal, "measure_type": measure, "rationale": "x"}],
    )


def test_una_stessa_misura_per_lo_stesso_segnale_non_si_ripete() -> None:
    rec = {"signal": "s1", "measure_type": "traffic_post", "rationale": "Serve."}
    analysis_bad(
        traffic(), r"«recommendations\[1\]» ripete traffic_post per s1", recommendations=[rec, rec]
    )
    other = {**rec, "measure_type": "signal_plan_change"}
    analysis_ok(traffic(), recommendations=[rec, other])


def test_il_trasporto_ha_le_sue_misure() -> None:
    analysis_ok(
        transit(),
        recommendations=[
            {"signal": "s1", "measure_type": "add_runs", "rationale": "Più corse."},
            {"signal": "s3", "measure_type": "crowd_control_post", "rationale": "Presidio."},
        ],
    )
    analysis_bad(
        transit(),
        r"«recommendations\[0\]\.measure_type» è «traffic_post»",
        recommendations=[{"signal": "s1", "measure_type": "traffic_post", "rationale": "x"}],
    )


def test_una_raccomandazione_senza_un_finding_e_ammessa() -> None:
    analysis_ok(
        traffic(),
        recommendations=[{"signal": "s2", "measure_type": "detour_signage", "rationale": "Serve."}],
    )


# --- numeri -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Il tempo medio è 38,4 minuti.",
        "Il tempo medio è 38.4 minuti.",  # decimale col punto
        "Sono 4.820 veicoli·ora.",
        "Sono 4820 veicoli·ora.",
        "Sono 4\u00a0820 veicoli·ora.",  # spazio non separabile
        "Sono 4\u202f820 veicoli·ora.",  # spazio sottile
        "Sono 4.820,0 veicoli·ora.",
        "Il rapporto v/c è 1,2.",
        "Il rapporto v/c è 1,20.",  # più cifre di quelle richieste: si arrotonda
        "Il rapporto v/c è 1,18.",  # 1,18 → 1,2
        "Il rapporto v/c è 1.200.",  # 1.200 letto come decimale all'inglese
        "Il carico è al 120%.",  # un rapporto si scrive anche in percentuale
        "Il carico è al 120 %.",
        "Il carico è al 130% sull'altro arco.",
        "Un calo di -38,4 minuti.",  # il segno non conta
        "Tra 1,2 e 1,3.",
        "Come nel segnale s1 e nel segnale s2.",  # un identificativo non è un numero
        "Vedi m.run_1.it0.road.departure.veh_hours.",
        "Servono tre presidi.",  # i numeri scritti a parole non si leggono
        "Nessun numero.",
    ],
)
def test_i_numeri_che_vengono_dall_input_passano(text: str) -> None:
    analysis_ok(traffic(), text=text)


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("Il tempo medio è 38,9 minuti.", "38,9"),
        ("Il tempo medio è 38 minuti.", "38"),  # senza la cifra decimale non è lo stesso valore
        ("Sono 4.900 veicoli·ora.", "4.900"),
        ("Sono 4.820,5 veicoli·ora.", "4.820,5"),  # migliaia e decimale, non solo le migliaia
        ("Sono 4.8 mila veicoli.", "4.8"),
        ("Il rapporto v/c è 1,1.", "1,1"),
        ("Il rapporto v/c è 1,5.", "1,5"),
        ("Il carico è al 110%.", "110%"),
        ("Il carico è al 1,2%.", "1,2%"),  # 1,2 non è una percentuale: v/c × 100 sì
        ("Il tempo medio è del 38,4%.", "38,4%"),  # i minuti non sono un rapporto
        ("Ci sono 7 incroci critici.", "7"),
        ("Dalle 21:00 alle 23:00.", "21:00"),  # un orario che l'input non ha
        ("Il 27 agosto 2027.", "27"),  # una data che l'input non ha
        ("La Linea 2 è piena.", "2"),  # le cifre di un nome contano solo se il nome c'è
        ("Il 12/05/2027 sarà piena.", "12/05/2027"),
        ("Il 12/05/27 sarà piena.", "12/05/27"),  # anno a due cifre
        ("Il 2027-08-27 sarà piena.", "2027-08-27"),
        ("Sono 4 820 veicoli.", "4"),  # lo spazio normale non separa le migliaia
    ],
)
def test_un_numero_che_non_viene_dall_input_non_e_valido(text: str, number: str) -> None:
    analysis_bad(
        traffic(), rf"«text» cita il numero «{number}», che non è nei dati forniti", text=text
    )


def test_i_numeri_si_controllano_in_ogni_testo_della_risposta() -> None:
    analysis_bad(
        traffic(), r"«assumptions\[0\]» cita il numero «999»", assumptions=["Circa 999 persone."]
    )
    analysis_bad(
        traffic(),
        r"«findings\[0\]\.summary» cita il numero «999»",
        findings=[{"signal": "s1", "summary": "999 veicoli."}],
    )
    analysis_bad(
        traffic(),
        r"«recommendations\[0\]\.rationale» cita il numero «999»",
        recommendations=[
            {"signal": "s1", "measure_type": "traffic_post", "rationale": "999 veicoli."}
        ],
    )


def test_le_cifre_di_un_nome_dell_input_si_possono_riportare() -> None:
    text = "La Linea 1 è al limite e la Linea 6 non ha corse."
    parse_analysis(answer(text=text), transit(), CONFIG)
    analysis_bad(transit(), r"cita il numero «2»", text="La Linea 2 è piena.")


def test_gli_id_dei_misurati_non_regalano_cifre() -> None:
    """`it0`, `run_1`, `…1.vc` sono negli id, non nei nomi: scrivere «0» non è citare un dato."""
    analysis_bad(traffic(), r"cita il numero «0»", text="Nessun incrocio a 0.")
    analysis_bad(traffic(), r"cita il numero «3»", text="Tre? No, 3 incroci.")


def test_gli_orari_e_le_date_dell_evento_si_riportano_come_sono() -> None:
    ok = (
        "Napoli–Juventus 2027, il 27/08/2027 (2027-08-27): arrivi dalle 12:00 alle 15:00 e "
        "deflusso dalle 18:00. Si attendono 45.000 persone, 11.250 in auto."
    )
    parse_event_demand(answer(text=ok), event_demand(), CONFIG)
    for text, number in [
        ("Arrivi dalle 13:00.", "13:00"),
        ("Il 28/08/2027.", "28/08/2027"),
        ("Il 2027-08-28.", "2027-08-28"),
        ("Si attendono 46.000 persone.", "46.000"),
        ("Dalle 12 alle 15.", "12"),  # gli orari si riportano come «12:00», non a metà
    ]:
        with pytest.raises(InvalidResponse, match=rf"cita il numero «{number}»"):
            parse_event_demand(answer(text=text), event_demand(), CONFIG)


@pytest.mark.parametrize(
    "text",
    [
        "Il 27 agosto si gioca.",  # le cifre di una data dell'input si riportano a parole
        "Il 27/8/27 si gioca.",  # anno a due cifre
        "Si gioca il 27/08/2027.",
        "Nel 2027 si gioca.",
    ],
)
def test_le_date_dell_evento_si_scrivono_in_piu_modi(text: str) -> None:
    parse_event_demand(answer(text=text), event_demand(), CONFIG)


def test_un_valore_negativo_si_cita_senza_il_segno() -> None:
    payload = traffic()
    payload["measures"].append({"id": "m.x", "value": -12.0, "unit": "min", "kind": "simulated"})
    analysis_ok(payload, text="Il tempo scende di 12 minuti.")
    analysis_ok(payload, text="Il tempo cambia di -12 minuti.")


def test_un_orario_si_legge_anche_senza_lo_zero_iniziale() -> None:
    parse_event_demand(
        answer(text="Arrivi dalle 9:00."),
        {**event_demand(), "context": {"w": "09:00–10:00"}},
        CONFIG,
    )


def test_una_data_impossibile_non_e_nell_input() -> None:
    with pytest.raises(InvalidResponse, match=r"cita il numero «31/02/2027»"):
        parse_event_demand(answer(text="Il 31/02/2027."), event_demand(), CONFIG)


def test_le_cifre_di_un_nome_non_valgono_per_una_percentuale() -> None:
    """«Linea 1» ha un 1, ma «1%» non è il nome della linea: è una percentuale e non c'è."""
    analysis_bad(transit(), r"cita il numero «1%»", text="Il 1% della Linea 1.")


def test_i_decimali_di_confronto_vengono_dalla_configurazione() -> None:
    strict = config_with(numbers={"decimals": 2})
    parse_analysis(answer(text="Il rapporto è 1,20."), traffic(), strict)
    with pytest.raises(InvalidResponse, match="«1,21»"):
        parse_analysis(answer(text="Il rapporto è 1,21."), traffic(), strict)
    loose = config_with(numbers={"decimals": 0})
    parse_analysis(answer(text="Il tempo medio è 38 minuti e il rapporto 1."), traffic(), loose)
    with pytest.raises(InvalidResponse, match="«39»"):
        parse_analysis(answer(text="Il tempo medio è 39 minuti."), traffic(), loose)


def test_le_unita_in_percentuale_vengono_dalla_configurazione() -> None:
    minutes = config_with(numbers={"percent_units": ["min"]})
    parse_analysis(answer(text="Il tempo è 3.840%."), traffic(), minutes)
    with pytest.raises(InvalidResponse, match="«120%»"):
        parse_analysis(answer(text="Il carico è 120%."), traffic(), minutes)


# --- linguaggio ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "word", ["previsto", "Prevista", "PREVISIONE", "rilevato", "misurate", "prevede"]
)
def test_le_parole_vietate_con_dati_simulati_non_passano(word: str) -> None:
    analysis_bad(
        traffic(),
        rf"«text» usa la parola «{word.lower()}», che non si dice di un dato simulato",
        text=f"Un picco {word} a Piazza Vittoria.",
    )


def test_le_parole_vietate_si_controllano_in_ogni_testo_con_evidenza_simulata() -> None:
    analysis_bad(
        traffic(),
        r"«findings\[0\]\.summary» usa la parola «rilevato»",
        findings=[{"signal": "s1", "summary": "Picco rilevato."}],
    )
    analysis_bad(
        traffic(),
        r"«recommendations\[0\]\.rationale» usa la parola «previsto»",
        recommendations=[
            {"signal": "s1", "measure_type": "traffic_post", "rationale": "È previsto un picco."}
        ],
    )
    analysis_bad(
        traffic(), r"«assumptions\[0\]» usa la parola «misurato»", assumptions=["Non è misurato."]
    )


def test_una_parola_dentro_un_altra_non_e_la_parola_vietata() -> None:
    analysis_ok(traffic(), text="Un imprevisto non è un dato prevedibile; la previsionale non c'è.")


def test_le_parole_vietate_valgono_solo_se_l_evidenza_e_simulata() -> None:
    """Il trasporto è una stima (`estimate`), non un dato simulato: la regola non scatta."""
    parse_analysis(
        answer(
            text="Carico misurato sulle linee.",
            findings=[{"signal": "s1", "summary": "Carico rilevato."}],
        ),
        transit(),
        CONFIG,
    )


def test_un_finding_guarda_le_evidenze_del_suo_segnale_non_quelle_degli_altri() -> None:
    payload = traffic()
    s2_evidence = payload["signals"][1]["evidence"][0]
    next(m for m in payload["measures"] if m["id"] == s2_evidence)["kind"] = "real"
    analysis_ok(payload, findings=[{"signal": "s2", "summary": "Picco rilevato."}])
    analysis_bad(
        payload,
        r"«findings\[0\]\.summary» usa la parola «rilevato»",
        findings=[{"signal": "s1", "summary": "Picco rilevato."}],
    )


def test_basta_un_evidenza_simulata_tra_quelle_del_segnale() -> None:
    payload = traffic()
    payload["measures"].append({"id": "m.reale", "value": 3, "unit": "n", "kind": "real"})
    payload["signals"][0]["evidence"] = ["m.reale", EVIDENCE]  # una reale e una simulata
    analysis_bad(
        payload,
        r"«findings\[0\]\.summary» usa la parola «rilevato»",
        findings=[{"signal": "s1", "summary": "Picco rilevato."}],
    )


def test_le_parole_vietate_vengono_dalla_configurazione() -> None:
    config = config_with(language={"forbidden_when_simulated": ["ottimo"]})
    parse_analysis(answer(text="Un picco previsto."), traffic(), config)
    with pytest.raises(InvalidResponse, match="«ottimo»"):
        parse_analysis(answer(text="Un ottimo risultato."), traffic(), config)


# --- più problemi insieme -----------------------------------------------------------------------


def test_tutti_i_problemi_sono_riportati_insieme() -> None:
    with pytest.raises(InvalidResponse) as caught:
        parse_analysis(
            answer(
                text="Picco previsto di 999 veicoli.",
                findings=[{"signal": "s7", "summary": "x"}],
                recommendations=[{"signal": "s1", "measure_type": "close_road", "rationale": "y"}],
            ),
            traffic(),
            CONFIG,
        )
    message = str(caught.value)
    for part in ("«previsto»", "«999»", "«s7»", "«close_road»"):
        assert part in message


def test_anche_gli_errori_di_schema_riportati_sono_in_numero_limitato() -> None:
    extra = {name: 1 for name in "abcdefgh"}
    with pytest.raises(InvalidResponse) as caught:
        parse_analysis(json.dumps({"text": "ok", **extra}), traffic(), CONFIG)
    assert str(caught.value).count("Extra inputs are not permitted") == MAX_REPORTED_PROBLEMS


def test_i_problemi_riportati_sono_in_numero_limitato() -> None:
    many = [
        "Circa 901.",
        "Circa 902.",
        "Circa 903.",
        "Circa 904.",
        "Circa 905.",
        "Circa 906.",
        "Circa 907.",
        "Circa 908.",
    ]
    with pytest.raises(InvalidResponse) as caught:
        parse_analysis(answer(assumptions=many), traffic(), CONFIG)
    message = str(caught.value)
    assert message.count("cita il numero") == MAX_REPORTED_PROBLEMS
    assert message.endswith(f"; e altri {len(many) - MAX_REPORTED_PROBLEMS} problemi")


# --- Event & Demand -----------------------------------------------------------------------------


def test_event_demand_sintesi_e_assunzioni() -> None:
    draft = parse_event_demand(
        answer(
            text="Si attendono 45.000 persone, ipotesi di scenario.",
            assumptions=["Affluenza ipotizzata."],
        ),
        event_demand(),
        CONFIG,
    )
    assert draft.assumptions == ["Affluenza ipotizzata."]
    with pytest.raises(InvalidResponse, match=r"«assumptions\[0\]» cita il numero «7»"):
        parse_event_demand(answer(assumptions=["Circa 7 varchi."]), event_demand(), CONFIG)
    with pytest.raises(InvalidResponse, match="«previsti»"):
        parse_event_demand(answer(text="Sono previsti arrivi."), event_demand(), CONFIG)


# --- Operations: piano --------------------------------------------------------------------------


def plan_item(candidate_id: str, rationale: str = "È la più importante.") -> dict[str, str]:
    return {"candidate": candidate_id, "rationale": rationale}


def test_il_piano_sceglie_tra_i_candidati_e_li_ordina() -> None:
    draft = parse_plan(answer(plan=[plan_item("c2"), plan_item("c1")]), plan(), CONFIG)
    assert [item.candidate for item in draft.plan] == ["c2", "c1"]


def test_un_candidato_che_non_c_e_non_e_valido() -> None:
    with pytest.raises(
        InvalidResponse,
        match=r"«plan\[0\]\.candidate» è «c9», che non è un candidato dell'input "
        r"\(ammessi: c1, c2\)",
    ):
        parse_plan(answer(plan=[plan_item("c9")]), plan(), CONFIG)


def test_ogni_candidato_al_massimo_una_volta() -> None:
    with pytest.raises(
        InvalidResponse, match=r"«plan\[1\]\.candidate» c1: ogni candidato una volta"
    ):
        parse_plan(answer(plan=[plan_item("c1"), plan_item("c1")]), plan(), CONFIG)


def test_il_piano_non_supera_il_tetto_di_misure() -> None:
    payload = {**plan(), "max_measures": 1}
    with pytest.raises(InvalidResponse, match=r"«plan» ha 2 misure, al massimo 1"):
        parse_plan(answer(plan=[plan_item("c1"), plan_item("c2")]), payload, CONFIG)
    parse_plan(answer(plan=[plan_item("c1")]), payload, CONFIG)


def test_un_piano_vuoto_con_dei_candidati_non_e_valido() -> None:
    with pytest.raises(InvalidResponse, match=r"«plan» è vuoto ma i candidati sono 2"):
        parse_plan(answer(), plan(), CONFIG)
    parse_plan(answer(), {**plan(), "candidates": []}, CONFIG)  # niente da scegliere: piano vuoto


def test_il_piano_cita_le_risorse_dei_dipartimenti() -> None:
    parse_plan(
        answer(
            text="Alla Polizia Municipale resta 1 pattuglia su 6.",
            plan=[plan_item("c1", "Con 5 già impegnate.")],
        ),
        plan(),
        CONFIG,
    )
    with pytest.raises(InvalidResponse, match="«4»"):
        parse_plan(answer(text="Restano 4 pattuglie.", plan=[plan_item("c1")]), plan(), CONFIG)
    with pytest.raises(InvalidResponse, match=r"«plan\[0\]\.rationale» cita il numero «3»"):
        parse_plan(answer(plan=[plan_item("c1", "Ne servono 3.")]), plan(), CONFIG)


def test_il_tetto_di_misure_si_puo_citare() -> None:
    parse_plan(answer(text="Al massimo 2 misure.", plan=[plan_item("c1")]), plan(), CONFIG)


def test_un_evidenza_di_kind_sconosciuto_vale_come_simulata() -> None:
    """Il candidato cita `EVIDENCE`, che qui non è tra le misure dell'input: si controlla."""
    assert EVIDENCE not in quotable(plan()).kinds
    with pytest.raises(InvalidResponse, match="«previsto»"):
        parse_plan(answer(plan=[plan_item("c1", "Un picco previsto.")]), plan(), CONFIG)


def test_un_evidenza_nota_e_non_simulata_non_vieta_le_parole() -> None:
    payload = plan()
    payload["measures"].append({"id": EVIDENCE, "value": 1.2, "unit": "rapporto", "kind": "real"})
    parse_plan(answer(plan=[plan_item("c1", "Un picco rilevato.")]), payload, CONFIG)


def test_il_piano_controlla_il_linguaggio_con_le_evidenze_del_candidato() -> None:
    with pytest.raises(InvalidResponse, match=r"«plan\[0\]\.rationale» usa la parola «previsto»"):
        parse_plan(answer(plan=[plan_item("c1", "Un picco previsto.")]), plan(), CONFIG)


# --- Operations: ripianificazione ---------------------------------------------------------------


def reply(**fields: Any) -> str:
    return json.dumps(
        {"text": "Si chiede un'alternativa.", "rationale": "È la preferita.", **fields}
    )


def test_la_ripianificazione_sceglie_un_alternativa_o_nessuna() -> None:
    assert parse_replan(reply(choice="a2"), replan(), CONFIG).choice == "a2"
    assert parse_replan(reply(choice=None), replan(), CONFIG).choice is None
    assert parse_replan(reply(), replan(), CONFIG).choice is None


def test_un_alternativa_che_non_c_e_non_e_valida() -> None:
    with pytest.raises(
        InvalidResponse,
        match=r"«choice» è «a9», che non è un'alternativa dell'input \(ammessi: a1, a2\)",
    ):
        parse_replan(reply(choice="a9"), replan(), CONFIG)
    with pytest.raises(InvalidResponse, match=r"ammessi: nessuno"):
        parse_replan(reply(choice="a1"), {**replan(), "alternatives": []}, CONFIG)


def test_il_motivo_del_rifiuto_si_puo_citare_con_i_suoi_numeri_e_orari() -> None:
    parse_replan(
        reply(text="Nella finestra 21:00–23:00 le 6 pattuglie sono impegnate.", choice="a1"),
        replan(),
        CONFIG,
    )
    with pytest.raises(InvalidResponse, match="«22:00»"):
        parse_replan(reply(text="Dalle 22:00 non ci sono pattuglie."), replan(), CONFIG)
    with pytest.raises(InvalidResponse, match="«8»"):
        parse_replan(reply(rationale="Ne servono 8."), replan(), CONFIG)


def test_la_ripianificazione_vieta_le_parole_anche_senza_dati_simulati() -> None:
    payload = {**replan(), "measures": []}
    with pytest.raises(InvalidResponse, match=r"«rationale» usa la parola «previsto»"):
        parse_replan(reply(rationale="Era previsto."), payload, CONFIG)


# --- Operations: avviso -------------------------------------------------------------------------


def test_l_avviso_riporta_gli_orari_delle_misure_approvate() -> None:
    parse_notice(answer(text="Presidio a Incrocio 1 dalle 18:00 alle 21:00."), notice(), CONFIG)
    with pytest.raises(InvalidResponse, match="«17:00»"):
        parse_notice(answer(text="Presidio a Incrocio 1 dalle 17:00."), notice(), CONFIG)
    with pytest.raises(InvalidResponse, match="«12:00»"):
        parse_notice(
            answer(text="Presidio dalle 12:00."), notice(), CONFIG
        )  # l'altra finestra: non accettata


def test_l_avviso_non_scrive_altri_numeri_e_non_usa_le_parole_vietate() -> None:
    with pytest.raises(InvalidResponse, match="«3»"):
        parse_notice(answer(text="Sono attive 3 misure."), notice(), CONFIG)
    with pytest.raises(InvalidResponse, match="«previsto»"):
        parse_notice(answer(text="Il traffico è previsto in calo."), notice(), CONFIG)
    with pytest.raises(InvalidResponse, match="«text» è vuoto"):
        parse_notice(answer(text="  "), notice(), CONFIG)


def test_l_avviso_si_riporta_il_bersaglio_con_le_sue_cifre() -> None:
    parse_notice(answer(text="Presidio a Incrocio 1."), notice(), CONFIG)


# --- ciò che un testo può citare ----------------------------------------------------------------


def test_il_citabile_di_un_analisi_sono_le_misure_e_i_nomi_dei_bersagli() -> None:
    source = quotable(traffic())
    assert [(v.value, v.unit) for v in source.values] == [
        (4820.0, "veic·h"),
        (38.4, "min"),
        (1.0, "n"),  # critical_edges.count
        (1.2, "rapporto"),
        (1.3, "rapporto"),
    ]
    assert set(source.names) == {"Piazza Vittoria", "Riviera di Chiaia"}
    assert set(source.kinds.values()) == {"simulated"} and source.any_simulated


def test_il_citabile_del_trasporto_non_e_simulato_e_non_ha_i_testi_come_numeri() -> None:
    source = quotable(transit())
    assert not source.any_simulated
    assert all(isinstance(v.value, float) for v in source.values)  # l'itinerario (un testo) no
    assert "funicolare, poi a piedi" in source.names  # ma è un nome citabile
    assert "Linea 1 della metropolitana" in source.names


def test_il_citabile_del_piano_ha_le_risorse_e_il_tetto() -> None:
    source = quotable(plan())
    assert [(v.value, v.unit) for v in source.values] == [
        (4820.0, "veic·h"),
        (6.0, None),
        (5.0, None),
        (1.0, None),
        (2.0, None),
    ]
    assert {"Piazza Vittoria", "Piazza Sannazaro"} <= set(source.names)


def test_il_citabile_della_ripianificazione_e_dell_avviso_ha_motivo_e_orari() -> None:
    assert (
        "Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, 6 già impegnate"
        in quotable(replan()).names
    )
    assert set(quotable(notice()).names) == {"Incrocio 1", "18:00–21:00"}


def test_gli_id_e_i_tipi_non_sono_nomi_citabili() -> None:
    names = " ".join(quotable(traffic()).names + quotable(plan()).names + quotable(replan()).names)
    for forbidden in (
        "m.run_1",
        "critical_intersection",
        "traffic_post",
        "municipal_police",
        "UNAVAILABLE",
        "s1",
    ):
        assert forbidden not in names


# --- con il client ------------------------------------------------------------------------------


def analysis_request(payload: dict[str, Any]) -> LlmRequest[AnalysisDraft]:
    return LlmRequest(
        agent="traffic",
        prompt_version="traffic@1",
        system="Sei il Traffic Agent.",
        payload=payload,
        schema=json_schema(AnalysisDraft),
        parse=lambda raw: parse_analysis(raw, payload, CONFIG),
    )


async def test_con_il_client_un_numero_inventato_fa_ripetere_con_il_motivo(tmp_path: Path) -> None:
    payload = traffic()
    good = answer(text="Il rapporto v/c è 1,2.")
    backend = FakeBackend(answer(text="Il rapporto v/c è 9,9."), good)
    client = make_client(make_llm_repo(tmp_path), backend)
    outcome = await client.complete(analysis_request(payload))
    assert (outcome.origin, outcome.validation, outcome.calls) == ("llm", "retried", 2)
    assert outcome.value is not None and outcome.value.text == "Il rapporto v/c è 1,2."
    assert "cita il numero «9,9»" in backend.calls[1]["contents"]


async def test_con_il_client_due_risposte_inventate_ripiegano_sul_testo_di_riserva(
    tmp_path: Path,
) -> None:
    payload = traffic()
    bad = answer(text="Un picco previsto di 999 veicoli.")
    client = make_client(make_llm_repo(tmp_path), FakeBackend(bad, bad))
    outcome = await client.complete(analysis_request(payload))
    assert (outcome.value, outcome.origin, outcome.validation, outcome.degraded) == (
        None,
        "template",
        "fallback",
        "invalid_response",
    )
