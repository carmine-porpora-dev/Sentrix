import ast
import inspect
from pathlib import Path
from typing import Any

import pytest

from app.data.seeds import read_seed_events
from app.models.event import Event
from app.models.operations import ACTIVE_STATES, OperationRequest
from app.operations import resources
from app.operations.resources import InvalidPayload, balances, event_resources
from app.operations.rules import (
    RULES,
    Accept,
    Reject,
    RuleState,
    closed_edges,
    evaluate,
    municipal_police,
    public_comms,
    traffic_control,
    transport_control,
)
from tests.support import make_request

EVENTS = {event.id: event for event in read_seed_events()}
MATCH = EVENTS[
    "match_2027"
]  # partenza: 6 pattuglie, 5 impegnate; 3 modifiche; 8 bus; 1 prolungamento
REGATE = EVENTS["regate_sep_2026"]  # 6 pattuglie, 3 impegnate
ADD_RUNS_DEFAULT = 4
CLOSED = MATCH.closures[0].edge_keys[0]  # un arco chiuso dall'Evento


def req(action: str, department: str, kind: str, state: str = "ACCEPTED", **changes: Any) -> Any:
    return make_request(action, department=department, type=kind, state=state, **changes)


def post(action: str, state: str = "ACCEPTED", **changes: Any) -> Any:
    return req(action, "municipal_police", "traffic_post", state, **changes)


def state_of(event: Event, *requests: OperationRequest) -> RuleState:
    return RuleState(event=event, requests=list(requests), add_runs_default=ADD_RUNS_DEFAULT)


# --- risorse ----------------------------------------------------------------------------------


def test_le_risorse_arrivano_dall_evento_per_finestra() -> None:
    by_key = {(b.window, b.resource): b for b in balances(MATCH, [], ADD_RUNS_DEFAULT)}
    patrols = by_key[("departure", "patrols")]
    assert (patrols.department, patrols.total, patrols.used, patrols.remaining) == (
        "municipal_police",
        6,
        5,
        1,
    )
    assert by_key[("arrival", "patrols")].remaining == 3  # in arrivo ne sono impegnate meno
    assert by_key[("departure", "signal_changes")].total == 3
    assert by_key[("departure", "reserve_buses")].total == 8
    assert by_key[("departure", "hour_extensions")].total == 1
    assert len(by_key) == 8  # quattro risorse × due finestre


def test_la_stessa_regola_con_dati_diversi_da_un_esito_diverso() -> None:
    """Con il seed di settembre le pattuglie libere in deflusso sono 3: l'evento è un dato."""

    def free(event: Event) -> int:
        by_key = {(b.window, b.resource): b for b in balances(event, [], ADD_RUNS_DEFAULT)}
        return by_key[("departure", "patrols")].remaining

    assert (free(MATCH), free(REGATE)) == (1, 3)


@pytest.mark.parametrize(
    ("state", "counts"),
    [(s, s in ACTIVE_STATES) for s in ("CREATED", "SENT", "RECEIVED", "REJECTED")]
    + [(s, True) for s in ("ACCEPTED", "IN_PROGRESS", "COMPLETED")],
)
def test_si_consumano_solo_le_richieste_in_vigore(state: str, counts: bool) -> None:
    balance = resources.balance(
        MATCH, [post("a", state=state, **_rejection(state))], "patrols", "departure", 4
    )
    assert balance.used == (6 if counts else 5)


def _rejection(state: str) -> dict[str, str]:
    return {"reject_code": "X", "reject_reason": "no"} if state == "REJECTED" else {}


def test_il_consumo_e_della_sua_finestra_e_della_sua_risorsa() -> None:
    requests = [
        post("a", window="arrival"),
        req("b", "traffic_control", "signal_plan_change"),
        req("c", "transport_control", "extend_hours"),
    ]
    by_key = {(b.window, b.resource): b for b in balances(MATCH, requests, ADD_RUNS_DEFAULT)}
    assert by_key[("arrival", "patrols")].used == 4  # 3 impegnate + 1
    assert by_key[("departure", "patrols")].used == 5  # quella in arrivo non conta qui
    assert by_key[("departure", "signal_changes")].used == 1
    assert by_key[("arrival", "signal_changes")].used == 0
    assert by_key[("departure", "hour_extensions")].remaining == 0


def test_la_richiesta_che_si_valuta_non_si_conta_da_sola() -> None:
    mine = post("a")
    assert resources.assigned([mine], "patrols", "departure", 4, excluding="a") == 0
    assert resources.assigned([mine], "patrols", "departure", 4) == 1


def test_i_bus_di_riserva_si_consumano_a_n_alla_volta() -> None:
    runs = req("a", "transport_control", "add_runs", payload={"n": 3})
    default = req("b", "transport_control", "add_runs")
    assert resources.units(runs, 4) == 3 and resources.units(default, 4) == 4
    assert resources.assigned([runs, default], "reserve_buses", "departure", 4) == 7


@pytest.mark.parametrize("n", [0, -1, "4", True, 2.5, None, [1]])
def test_un_n_che_non_e_un_intero_positivo_e_un_errore(n: Any) -> None:
    with pytest.raises(InvalidPayload, match="'n' deve essere un intero"):
        resources.units(req("a", "transport_control", "add_runs", payload={"n": n}), 4)


def test_un_evento_senza_una_finestra_non_ha_risorse_in_quella_finestra() -> None:
    only_departure = MATCH.model_copy(
        update={"resources": [r for r in MATCH.resources if r.window == "departure"]}
    )
    assert event_resources(only_departure, "arrival").municipal_police_patrols_total == 0
    assert [b.window for b in balances(only_departure, [], 4)] == ["departure"] * 4


def test_le_risorse_rimaste_non_vanno_sotto_zero() -> None:
    many = [post(f"p{i}") for i in range(4)]
    balance = resources.balance(MATCH, many, "patrols", "departure", 4)
    assert (balance.used, balance.remaining) == (9, 0)


# --- Polizia Municipale -------------------------------------------------------------------------


def test_la_scena_di_rifiuto_di_match_2027_viene_dai_dati() -> None:
    """6 totali − 5 impegnate = 1 libera: il primo presidio passa, il secondo no (04 7)."""
    first, second = post("a", "RECEIVED"), post("b", "RECEIVED")
    verdict = municipal_police(first, state_of(MATCH, first, second))
    assert isinstance(verdict, Accept)
    assert verdict.reason == "Pattuglia disponibile: 1 libere su 6 nella finestra 21:00–23:00"
    accepted = post("a")  # ora è accettato e consuma l'ultima pattuglia
    refused = municipal_police(second, state_of(MATCH, accepted, second))
    assert refused == Reject(
        "UNAVAILABLE",
        "Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, 6 già impegnate ai varchi",
    )


def test_il_motivo_del_rifiuto_distingue_le_totali_dalle_impegnate() -> None:
    """Se le assegnate superano il totale (una pattuglia già accettata oltre quelle dell'Evento) i
    due numeri del motivo sono diversi: ognuno al suo posto."""
    small = MATCH.model_copy(
        update={
            "resources": [
                item.model_copy(
                    update={
                        "municipal_police_patrols_total": 2,
                        "municipal_police_patrols_committed": 2,
                    }
                )
                for item in MATCH.resources
            ]
        }
    )
    extra, asking = post("a"), post("b", "RECEIVED")
    verdict = municipal_police(asking, state_of(small, extra, asking))
    assert verdict == Reject(
        "UNAVAILABLE",
        "Pattuglie esaurite nella finestra 21:00–23:00: 2 totali, 3 già impegnate ai varchi",
    )


def test_con_il_seed_di_settembre_entrambe_le_richieste_passano() -> None:
    first = post("a", "RECEIVED")
    second = post("b", "RECEIVED")
    assert isinstance(municipal_police(first, state_of(REGATE, first, second)), Accept)
    accepted = post("a")
    assert isinstance(municipal_police(second, state_of(REGATE, accepted, second)), Accept)


def test_anche_un_presidio_di_afflusso_consuma_una_pattuglia() -> None:
    crowd = req("c", "municipal_police", "crowd_control_post", target="s1", target_label="Stop")
    other = post("b", "RECEIVED")
    assert isinstance(municipal_police(other, state_of(MATCH, crowd, other)), Reject)


def test_le_pattuglie_sono_della_finestra() -> None:
    """In arrivo ce ne sono di più: quella stessa richiesta lì passa, in deflusso no."""
    taken = post("a")
    arrival = post("b", "RECEIVED", window="arrival")
    departure = post("c", "RECEIVED")
    state = state_of(MATCH, taken, arrival, departure)
    assert isinstance(municipal_police(arrival, state), Accept)
    verdict = municipal_police(departure, state)
    assert isinstance(verdict, Reject) and "16:00" not in verdict.reason


# --- Controllo Traffico -------------------------------------------------------------------------


def signal(action: str, state: str = "ACCEPTED", **changes: Any) -> Any:
    return req(action, "traffic_control", "signal_plan_change", state, **changes)


def test_le_modifiche_semaforiche_hanno_un_massimo() -> None:
    accepted = [signal(f"s{i}") for i in range(3)]
    fourth = signal("s4", "RECEIVED")
    assert isinstance(traffic_control(fourth, state_of(MATCH, *accepted[:2], fourth)), Accept)
    verdict = traffic_control(fourth, state_of(MATCH, *accepted, fourth))
    assert verdict == Reject(
        "LIMIT_REACHED",
        "Limite di modifiche semaforiche raggiunto nella finestra 21:00–23:00: 3 su 3",
    )


def test_le_modifiche_in_attesa_o_rifiutate_non_contano() -> None:
    rejected = signal("r", "REJECTED", reject_code="X", reject_reason="no")
    pending = [signal("p", "RECEIVED"), signal("q", "SENT"), rejected]
    new = signal("n", "RECEIVED")
    assert isinstance(traffic_control(new, state_of(MATCH, *pending, new)), Accept)


def edges(action: str, kind: str, keys: str, state: str = "ACCEPTED") -> Any:
    return req(action, "traffic_control", kind, state, target=keys, target_label="Archi")


def test_un_arco_chiuso_dall_evento_non_si_devia_ne_si_richiude() -> None:
    for kind in ("detour_signage", "close_road"):
        request = edges("a", kind, CLOSED, "RECEIVED")
        verdict = traffic_control(request, state_of(MATCH, request))
        assert verdict == Reject(
            "CONFLICT_ACTIVE_DETOUR", f"L'arco {CLOSED} è già chiuso dal dispositivo"
        )


def test_un_arco_libero_passa() -> None:
    request = edges("a", "detour_signage", "1-2-0,3-4-0", "RECEIVED")
    assert traffic_control(request, state_of(MATCH, request)) == Accept(
        "Nessun conflitto sugli archi: 1-2-0, 3-4-0"
    )


def test_un_arco_gia_in_deviazione_attiva_si_rifiuta() -> None:
    active = edges("a", "detour_signage", "1-2-0,3-4-0")
    for kind in ("detour_signage", "close_road"):
        request = edges("b", kind, "3-4-0", "RECEIVED")
        verdict = traffic_control(request, state_of(MATCH, active, request))
        assert verdict == Reject(
            "CONFLICT_ACTIVE_DETOUR", "L'arco 3-4-0 è già una deviazione attiva"
        )


def test_una_close_road_in_vigore_chiude_l_arco_nella_sua_finestra() -> None:
    closing = edges("a", "close_road", "5-6-0")
    request = edges("b", "detour_signage", "5-6-0", "RECEIVED")
    assert isinstance(traffic_control(request, state_of(MATCH, closing, request)), Reject)
    other_window = edges("c", "detour_signage", "5-6-0", "RECEIVED").model_copy(
        update={"window": "arrival"}
    )
    assert isinstance(traffic_control(other_window, state_of(MATCH, closing, other_window)), Accept)


def test_una_deviazione_non_ancora_accettata_non_blocca() -> None:
    pending = edges("a", "detour_signage", "7-8-0", "RECEIVED")
    request = edges("b", "detour_signage", "7-8-0", "RECEIVED")
    assert isinstance(traffic_control(request, state_of(MATCH, pending, request)), Accept)


def test_una_riduzione_di_capacita_non_e_una_chiusura() -> None:
    reduced = MATCH.closures[0].model_copy(
        update={"mode": "capacity_reduction", "capacity_factor": 0.5}
    )
    event = MATCH.model_copy(update={"closures": [reduced]})
    request = edges("a", "detour_signage", reduced.edge_keys[0], "RECEIVED")
    assert isinstance(traffic_control(request, state_of(event, request)), Accept)
    assert reduced.edge_keys[0] not in closed_edges(request, state_of(event, request))


@pytest.mark.parametrize("target", [" ", " , ,"])
def test_senza_archi_non_c_e_niente_da_valutare(target: str) -> None:
    request = edges("a", "close_road", target, "RECEIVED").model_copy(update={"target": target})
    assert traffic_control(request, state_of(MATCH, request)) == Reject(
        "INVALID_REQUEST", "close_road: nessun arco indicato nel bersaglio"
    )


# --- Controllo Trasporti ------------------------------------------------------------------------


def runs(action: str, state: str = "ACCEPTED", **payload: Any) -> Any:
    return req(
        action, "transport_control", "add_runs", state, target="metro_line_1", payload=payload
    )


def test_i_bus_di_riserva_finiscono() -> None:
    """Otto bus, quattro a richiesta: due richieste passano, la terza no (NO_RESERVE)."""
    first, second, third = runs("a", "RECEIVED"), runs("b", "RECEIVED"), runs("c", "RECEIVED")
    assert isinstance(transport_control(first, state_of(MATCH, first)), Accept)
    accepted = runs("a")
    assert isinstance(transport_control(second, state_of(MATCH, accepted, second)), Accept)
    both = [runs("a"), runs("b")]
    assert transport_control(third, state_of(MATCH, *both, third)) == Reject(
        "NO_RESERVE",
        "Bus di riserva insufficienti nella finestra 21:00–23:00: servono 4, ne restano 0 su 8",
    )


def test_n_si_confronta_con_i_bus_rimasti() -> None:
    taken = runs("a", n=6)
    wants_three = runs("b", "RECEIVED", n=3)
    verdict = transport_control(wants_three, state_of(MATCH, taken, wants_three))
    assert isinstance(verdict, Reject) and verdict.code == "NO_RESERVE"
    assert "servono 3, ne restano 2 su 8" in verdict.reason
    wants_two = runs("c", "RECEIVED", n=2)
    assert isinstance(transport_control(wants_two, state_of(MATCH, taken, wants_two)), Accept)


def test_un_n_non_valido_si_rifiuta_con_il_motivo() -> None:
    bad = runs("a", "RECEIVED", n=0)
    assert evaluate(bad, state_of(MATCH, bad)) == Reject(
        "INVALID_REQUEST", "add_runs: 'n' deve essere un intero ≥ 1 (trovato 0)"
    )


def test_un_solo_prolungamento_d_orario() -> None:
    new = req("b", "transport_control", "extend_hours", "RECEIVED", target="metro_line_6")
    assert isinstance(transport_control(new, state_of(MATCH, new)), Accept)
    used = req("a", "transport_control", "extend_hours", target="metro_line_1")
    assert transport_control(new, state_of(MATCH, used, new)) == Reject(
        "NO_EXTENSION_LEFT",
        "Prolungamenti d'orario esauriti nella finestra 21:00–23:00: 1 totali",
    )


def test_una_deviazione_bus_non_cita_archi_chiusi() -> None:
    ok = req(
        "a",
        "transport_control",
        "bus_detour",
        "RECEIVED",
        target="R1",
        payload={"avoid_edge_keys": ["1-2-0"]},
    )
    assert isinstance(transport_control(ok, state_of(MATCH, ok)), Accept)
    bad = ok.model_copy(update={"payload": {"avoid_edge_keys": ["1-2-0", CLOSED]}})
    assert transport_control(bad, state_of(MATCH, bad)) == Reject(
        "CONFLICT_CLOSED_EDGE", f"L'arco {CLOSED} è chiuso: la deviazione lo cita"
    )


@pytest.mark.parametrize("payload", [{}, {"avoid_edge_keys": []}, {"avoid_edge_keys": "1-2-0"}])
def test_una_deviazione_bus_senza_archi_e_malformata(payload: dict[str, Any]) -> None:
    request = req("a", "transport_control", "bus_detour", "RECEIVED", target="R1", payload=payload)
    verdict = transport_control(request, state_of(MATCH, request))
    assert isinstance(verdict, Reject) and verdict.code == "INVALID_REQUEST"


def test_la_sospensione_di_una_fermata_si_accetta() -> None:
    request = req(
        "a",
        "transport_control",
        "stop_suspension",
        "RECEIVED",
        target="stop_1",
        target_label="Dante",
    )
    assert isinstance(transport_control(request, state_of(MATCH, request)), Accept)


# --- Comunicazione Pubblica ---------------------------------------------------------------------


def notice(text: Any, state: str = "RECEIVED") -> Any:
    payload = {} if text is None else {"text": text}
    return req(
        "n",
        "public_comms",
        "citizen_notice",
        state,
        target="all",
        target_label="Cittadini",
        payload=payload,
    )


def rejected_post() -> Any:
    return post(
        "r1",
        "REJECTED",
        target_label="Incrocio Piazza Sannazaro",
        reject_code="UNAVAILABLE",
        reject_reason="esaurite",
    )


def test_un_avviso_che_cita_solo_misure_approvate_passa() -> None:
    approved = post("a", target_label="Incrocio Piazza Vittoria")
    request = notice("Presidio all'Incrocio Piazza Vittoria dalle 21:00")
    assert isinstance(public_comms(request, state_of(MATCH, approved, request)), Accept)


def test_un_avviso_che_cita_una_misura_rifiutata_per_id_si_rifiuta() -> None:
    request = notice("Come da richiesta r1 attiva")
    verdict = public_comms(request, state_of(MATCH, rejected_post(), request))
    assert isinstance(verdict, Reject) and verdict.code == "UNAPPROVED_MEASURE"
    assert "r1" in verdict.reason and "REJECTED" in verdict.reason


def test_un_avviso_che_cita_per_etichetta_una_misura_non_approvata_si_rifiuta() -> None:
    request = notice("Presidio a incrocio piazza sannazaro")  # senza distinzione di maiuscole
    verdict = public_comms(request, state_of(MATCH, rejected_post(), request))
    assert isinstance(verdict, Reject) and verdict.code == "UNAPPROVED_MEASURE"


def test_un_avviso_puo_citare_il_bersaglio_dove_una_misura_ha_preso_il_posto_di_un_altra() -> None:
    """Il presidio rifiutato è stato sostituito da una modifica semaforica allo stesso incrocio."""
    replacement = signal("s", target_label="Incrocio Piazza Sannazaro")
    request = notice("Modifica semaforica all'Incrocio Piazza Sannazaro")
    state = state_of(MATCH, rejected_post(), replacement, request)
    assert isinstance(public_comms(request, state), Accept)
    # ma citare per identificativo la misura rifiutata resta un errore
    by_id = notice("Presidio r1 all'Incrocio Piazza Sannazaro")
    assert isinstance(
        public_comms(by_id, state_of(MATCH, rejected_post(), replacement, by_id)), Reject
    )


def test_un_etichetta_approvata_che_ne_contiene_una_rifiutata_non_e_una_citazione() -> None:
    """Il presidio a «Incrocio Piazza Sannazaro» è stato rifiutato e al suo posto c'è una
    segnaletica con etichetta «Archi a monte di Incrocio Piazza Sannazaro»: citare la seconda non
    è citare la prima."""
    replacement = signal("s", target_label="Archi a monte di Incrocio Piazza Sannazaro")
    state_text = "Segnaletica agli Archi a monte di Incrocio Piazza Sannazaro"
    request = notice(state_text)
    assert isinstance(
        public_comms(request, state_of(MATCH, rejected_post(), replacement, request)), Accept
    )
    # ma citare anche la misura rifiutata, fuori dall'etichetta approvata, resta un errore
    both = notice(state_text + "; presidio a Incrocio Piazza Sannazaro")
    verdict = public_comms(both, state_of(MATCH, rejected_post(), replacement, both))
    assert isinstance(verdict, Reject) and verdict.code == "UNAPPROVED_MEASURE"


@pytest.mark.parametrize("state", ["CREATED", "SENT", "RECEIVED"])
def test_una_misura_ancora_in_attesa_non_si_puo_citare(state: str) -> None:
    pending = post("p", state, target_label="Incrocio Dante")
    request = notice("Presidio all'Incrocio Dante")
    assert isinstance(public_comms(request, state_of(MATCH, pending, request)), Reject)


@pytest.mark.parametrize("text", [None, "", "   ", 5, ["x"]])
def test_un_avviso_senza_testo_e_malformato(text: Any) -> None:
    request = notice(text)
    assert public_comms(request, state_of(MATCH, request)) == Reject(
        "INVALID_REQUEST", "citizen_notice: manca il testo dell'avviso (payload.text)"
    )


def test_un_altro_avviso_non_e_una_misura_citabile() -> None:
    other = req(
        "o",
        "public_comms",
        "citizen_notice",
        "REJECTED",
        target_label="Cittadini",
        reject_code="X",
        reject_reason="no",
        payload={"text": "x"},
    )
    request = notice("Avviso ai Cittadini")
    assert isinstance(public_comms(request, state_of(MATCH, other, request)), Accept)


# --- tutte le regole ---------------------------------------------------------------------------


def test_le_regole_hanno_la_stessa_firma() -> None:
    assert set(RULES) == {
        "municipal_police",
        "traffic_control",
        "transport_control",
        "public_comms",
    }
    signatures = {inspect.signature(rule) for rule in RULES.values()}
    assert len(signatures) == 1
    assert list(next(iter(signatures)).parameters) == ["request", "state"]


def test_una_regola_non_cambia_niente_ed_e_deterministica() -> None:
    requests = [post("a"), post("b", "RECEIVED")]
    state = state_of(MATCH, *requests)
    before = [r.model_dump() for r in requests]
    verdicts = [evaluate(requests[1], state) for _ in range(3)]
    assert len({repr(v) for v in verdicts}) == 1
    assert [r.model_dump() for r in requests] == before


def test_evaluate_sceglie_la_regola_dal_dipartimento() -> None:
    request = post("a", "RECEIVED")
    assert evaluate(request, state_of(MATCH, request)) == municipal_police(
        request, state_of(MATCH, request)
    )
    foreign = request.model_copy(update={"department": "ente_reale"})
    assert evaluate(foreign, state_of(MATCH, foreign)) == Reject(
        "INVALID_REQUEST", "Dipartimento 'ente_reale' senza regole"
    )


def test_le_regole_non_conoscono_i_nomi_degli_eventi() -> None:
    """Principio 4: nessun `if event.name == ...`. Gli id dei preset non compaiono nel pacchetto."""
    package = Path(__file__).resolve().parents[2] / "app" / "operations"
    text = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    for event_id in EVENTS:
        assert event_id not in text
    assert "event.name" not in text and "event.id" not in text


# --- purezza (F5-REF) ---------------------------------------------------------------------------

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "operations"
# Ciò che una funzione pura non tocca: database, orologio, casualità, thread, file, rete, log.
IMPURE = (
    "app.db",
    "app.clock",
    "sqlite3",
    "time",
    "datetime",
    "random",
    "secrets",
    "asyncio",
    "threading",
    "logging",
    "os",
    "pathlib",
    "subprocess",
    "socket",
)


@pytest.mark.parametrize("module", ["rules.py", "resources.py"])
def test_le_regole_e_le_risorse_non_importano_nulla_di_impuro(module: str) -> None:
    """Regole e risorse sono funzioni pure: leggono solo ciò che ricevono (nessun database,
    orologio, thread o file): la stessa richiesta nello stesso stato dà la stessa risposta."""
    tree = ast.parse((PACKAGE / module).read_text(encoding="utf-8"))
    imported = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    bad = [name for name in imported if any(name == m or name.startswith(f"{m}.") for m in IMPURE)]
    assert bad == []


def test_le_regole_non_hanno_stato_globale_modificabile() -> None:
    """Nessuna lista, dizionario o insieme di modulo che una regola possa riempire tra una chiamata
    e l'altra: i soli valori di modulo sono costanti immutabili (tuple, mappe in sola lettura)."""
    tree = ast.parse((PACKAGE / "rules.py").read_text(encoding="utf-8"))
    mutable: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if isinstance(node.value, ast.List | ast.Dict | ast.Set):
            mutable += names
    assert mutable == []
    with pytest.raises(TypeError):
        RULES["municipal_police"] = municipal_police  # type: ignore[index]
