import json
import re
from datetime import date, datetime, time
from typing import Any

import pytest
from pydantic import ValidationError

from app.clock import ROME
from app.models.config import CarDestination
from app.models.event import Event
from tests.support import DELETE, make_event, mutated

CLOSURES: list[dict[str, Any]] = [
    {
        "label": "Via Francesco Caracciolo (viale Dohrn – piazza Vittoria)",
        "street_names": ["Via Francesco Caracciolo"],
        "bbox": [14.2275, 40.8295, 14.2450, 40.8365],
        "source_ref": "Ord. dirigenziale Comune di Napoli n. 1496 del 2/09/2026 (fonte stampa)",
    },
    {
        "label": "Viale Anton Dohrn",
        "street_names": ["Viale Anton Dohrn"],
        "source_ref": "Ord. dirigenziale Comune di Napoli n. 1496 del 2/09/2026 (fonte stampa)",
    },
]


def resources(window: str, committed: int = 3) -> dict[str, Any]:
    return {
        "window": window,
        "municipal_police_patrols_total": 6,
        "municipal_police_patrols_committed": committed,
        "traffic_control_signal_changes_max": 3,
        "transport_control_reserve_buses": 8,
        "transport_control_hour_extensions": 1,
    }


@pytest.fixture
def regate() -> dict[str, Any]:
    """01 5.1: Regate preliminari settembre 2026."""
    return {
        "id": "regate_sep_2026",
        "name": "Regate preliminari settembre 2026",
        "date": "2026-09-26",
        "description": "Seconda regata preliminare, 24–27/09/2026. Caso reale già avvenuto.",
        "area_center": {"lat": 40.8320, "lon": 14.2350, "label": "Rotonda Diaz"},
        "area_radius_m": 400,
        "arrival": {"start": "12:00", "end": "14:00", "peak": "13:30"},
        "departure": {"start": "16:00", "end": "18:00", "peak": "16:30"},
        "attendance": {
            "low": 20000,
            "mid": 40000,
            "high": 60000,
            "source_ref": "Attesi oltre 60.000 spettatori, picco ~40.000 (Corriere dello Sport)",
        },
        "closures": CLOSURES,
        "transit_disruptions": [],
        "background": {"arrival_peak_share": 0.35, "departure_peak_share": 0.40},
        "resources": [resources("departure"), resources("arrival")],
        "real_measures": [
            {
                "label": "Metro e funicolari prolungate fino alle 2:00",
                "measure_type": "extend_hours",
                "target": "metro+funicolari",
                "source_ref": "Piano ANM per le pre-regate (napolike.it)",
            }
        ],
        "sources": ["Ord. dirigenziale 1496/2026", "Corriere dello Sport, 24/09/2026"],
        "created_at": "2026-11-07T10:00:00+01:00",
        "updated_at": "2026-11-07T10:00:00+01:00",
    }


@pytest.fixture
def match() -> dict[str, Any]:
    """01 5.2: Match 2027 — serata di regata."""
    return {
        "id": "match_2027",
        "name": "Match 2027 — serata di regata",
        "date": "2027-07-10",
        "area_center": {"lat": 40.8320, "lon": 14.2350, "label": "Rotonda Diaz"},
        "arrival": {"start": "16:00", "end": "19:00", "peak": "18:00"},
        "departure": {"start": "21:00", "end": "23:00", "peak": "21:30"},
        "attendance": {
            "low": 50000,
            "mid": 150000,
            "high": 300000,
            "source_ref": "Ipotesi di scenario",
        },
        "closures": [
            {**c, "source_ref": "Ipotesi basata sul dispositivo di settembre 2026"}
            for c in CLOSURES
        ],
        "transit_disruptions": [
            {
                "label": "Stazione Arco Mirelli chiusa per sicurezza",
                "stop_name": "Arco Mirelli",
                "window": "arrival",
                "source_ref": "Ipotesi di scenario",
            }
        ],
        "background": {"arrival_peak_share": 0.40, "departure_peak_share": 0.25},
        "resources": [resources("departure", committed=5), resources("arrival")],
        "created_at": "2026-11-07T10:00:00+01:00",
        "updated_at": "2026-11-07T10:00:00+01:00",
    }


def error_locs(data: dict[str, Any]) -> list[tuple[Any, ...]]:
    with pytest.raises(ValidationError) as info:
        Event.model_validate(data)
    return [tuple(e["loc"]) for e in info.value.errors()]


def error_text(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        Event.model_validate(data)
    return str(info.value)


# --- I due eventi precaricati sono validi ---------------------------------------------------


def test_regate_settembre_2026(regate: dict[str, Any]) -> None:
    e = Event.model_validate(regate)
    assert (e.id, e.date, e.date.weekday()) == ("regate_sep_2026", date(2026, 9, 26), 5)  # sabato
    assert (e.area_center.lat, e.area_center.lon, e.area_radius_m) == (40.8320, 14.2350, 400)
    assert (e.arrival.start, e.arrival.end, e.arrival.peak) == (time(12), time(14), time(13, 30))
    assert (e.departure.start, e.departure.end, e.departure.peak) == (
        time(16),
        time(18),
        time(16, 30),
    )
    assert (e.attendance.low, e.attendance.mid, e.attendance.high) == (20000, 40000, 60000)
    assert [c.street_names for c in e.closures] == [
        ["Via Francesco Caracciolo"],
        ["Viale Anton Dohrn"],
    ]
    assert e.closures[0].bbox == (14.2275, 40.8295, 14.2450, 40.8365)
    assert e.closures[0].mode == "closed" and e.closures[0].capacity_factor == 0
    assert (e.background.arrival_peak_share, e.background.departure_peak_share) == (0.35, 0.40)
    assert {r.window for r in e.resources} == {"arrival", "departure"}
    assert [m.measure_type for m in e.real_measures] == ["extend_hours"]
    assert e.transit_disruptions == []


def test_match_2027(match: dict[str, Any]) -> None:
    e = Event.model_validate(match)
    assert (e.date, e.date.weekday()) == (date(2027, 7, 10), 5)
    assert (e.arrival.peak, e.departure.peak) == (time(18), time(21, 30))
    assert (e.attendance.low, e.attendance.mid, e.attendance.high) == (50000, 150000, 300000)
    (disruption,) = e.transit_disruptions
    assert (disruption.stop_name, disruption.window, disruption.stop_ids) == (
        "Arco Mirelli",
        "arrival",
        [],
    )
    departure = next(r for r in e.resources if r.window == "departure")
    assert (
        departure.municipal_police_patrols_total,
        departure.municipal_police_patrols_committed,
    ) == (6, 5)
    assert (e.background.arrival_peak_share, e.background.departure_peak_share) == (0.40, 0.25)
    assert e.real_measures == []


def test_valori_di_default(match: dict[str, Any]) -> None:
    e = Event.model_validate(match)
    assert e.description is None and e.area_radius_m == 400 and e.revision == 1
    assert e.car_destinations is None and e.zones_override is None
    assert e.modal_split_override is None and e.car_occupancy is None
    assert e.sources == [] and e.real_measures == []
    minimal = {k: v for k, v in match.items() if k not in ("closures", "transit_disruptions")}
    assert Event.model_validate(minimal).closures == []


def test_i_timestamp_sono_normalizzati_a_roma(regate: dict[str, Any]) -> None:
    e = Event.model_validate({**regate, "created_at": "2026-11-07T09:00:00+00:00",
                              "updated_at": "2026-11-07T09:30:00Z"})  # fmt: skip
    assert e.created_at == datetime(2026, 11, 7, 10, 0, tzinfo=ROME) and e.created_at.hour == 10
    assert e.updated_at.utcoffset() == e.created_at.utcoffset()


def test_json_andata_e_ritorno(regate: dict[str, Any], match: dict[str, Any]) -> None:
    for data in (regate, match):
        e = Event.model_validate(data)
        again = Event.model_validate_json(e.model_dump_json())
        assert again == e
        assert (
            json.loads(e.model_dump_json())["arrival"]["start"] == data["arrival"]["start"] + ":00"
        )


def test_l_evento_e_immutabile(regate: dict[str, Any]) -> None:
    e = Event.model_validate(regate)
    with pytest.raises(ValidationError, match="frozen"):
        e.name = "altro"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        e.arrival.peak = time(13)  # type: ignore[misc]
    renamed = Event.model_validate({**e.model_dump(mode="json"), "name": "Altro", "revision": 2})
    assert (renamed.name, renamed.revision, e.name) == (
        "Altro",
        2,
        "Regate preliminari settembre 2026",
    )


# --- Finestre ------------------------------------------------------------------------------


@pytest.mark.parametrize("peak", ["12:00", "12:01", "13:59"])
def test_il_picco_puo_coincidere_con_l_inizio_ma_non_con_la_fine(
    regate: dict[str, Any], peak: str
) -> None:
    ok = Event.model_validate(mutated(regate, ("arrival", "peak"), peak))
    assert ok.arrival.peak == time.fromisoformat(peak)


def test_finestre_non_valide_errore_sul_campo_giusto(regate: dict[str, Any]) -> None:
    assert error_locs(mutated(regate, ("arrival", "peak"), "14:00")) == [("arrival", "peak")]
    assert error_locs(mutated(regate, ("departure", "end"), "16:00")) == [("departure", "end")]


# --- Tabella dei casi non validi ----------------------------------------------------------

A, D = "arrival", "departure"
CL = ("closures", 0)
RS = ("resources", 0)
COMMITTED = (*RS, "municipal_police_patrols_committed")
BUSES = (*RS, "transport_control_reserve_buses")
CASES: list[tuple[str, tuple[str | int, ...], Any, str]] = [
    ("fine uguale all'inizio", (A, "end"), "12:00", "la fine deve essere dopo l'inizio"),
    ("fine prima dell'inizio", (A, "end"), "11:00", "la fine deve essere dopo l'inizio"),
    ("picco prima dell'inizio", (A, "peak"), "11:59", "il picco deve cadere"),
    ("picco uguale alla fine", (A, "peak"), "14:00", "il picco deve cadere"),
    ("picco dopo la fine", (D, "peak"), "19:00", "il picco deve cadere"),
    ("orario numerico (YAML/JSON)", (A, "start"), 720, 'serve una stringa "HH:MM"'),
    ("orario con fuso", (A, "start"), "12:00+01:00", 'serve una stringa "HH:MM"'),
    ("orario impossibile", (A, "start"), "25:00", "time format"),
    ("livello medio sotto il basso", ("attendance", "mid"), 10000, "livello medio non può"),
    ("livello alto sotto il medio", ("attendance", "high"), 30000, "livello alto non può"),
    ("affluenza negativa", ("attendance", "low"), -1, "greater than or equal to 0"),
    ("chiusura senza strade né archi", (*CL, "street_names"), [], "almeno un nome di strada"),
    ("nome di strada vuoto", (*CL, "street_names"), ["Via Roma", " "], "non possono essere vuoti"),
    ("bbox con ovest ≥ est", (*CL, "bbox"), [14.25, 40.83, 14.22, 40.84], "ovest < est"),
    ("bbox con sud ≥ nord", (*CL, "bbox"), [14.22, 40.84, 14.25, 40.83], "ovest < est"),
    ("bbox fuori dal globo", (*CL, "bbox"), [14.22, 40.83, 14.25, 95], "ovest < est"),
    ("bbox a 3 numeri", (*CL, "bbox"), [14.22, 40.83, 14.25], "bbox"),
    ("chiave arco malformata", (*CL, "edge_keys"), ["12-34"], "chiavi arco non valide"),
    ("closed con fattore ≠ 0", (*CL, "capacity_factor"), 0.5, "con mode 'closed'"),
    ("modo sconosciuto", (*CL, "mode"), "demolita", "mode"),
    ("sorgente della chiusura vuota", (*CL, "label"), "", "at least 1 character"),
    ("sfondo oltre 1", ("background", "arrival_peak_share"), 1.2, "less than or equal to 1"),
    ("sfondo di partenza oltre 1", ("background", "departure_peak_share"), 1.2, "equal to 1"),
    ("sfondo di arrivo negativo", ("background", "arrival_peak_share"), -0.1, "equal to 0"),
    ("sfondo negativo", ("background", "departure_peak_share"), -0.1, "greater than or equal to 0"),
    ("pattuglie impegnate > totali", COMMITTED, 9, "non possono superare"),
    ("risorse negative", BUSES, -1, "greater than or equal to 0"),
    ("finestra di risorse duplicata", ("resources", 1, "window"), "departure", "una sola voce"),
    ("finestra di risorse sconosciuta", ("resources", 1, "window"), "both", "window"),
    ("nessuna risorsa", ("resources",), [], "at least 1 item"),
    ("destinazioni auto vuote", ("car_destinations",), [], "almeno una destinazione"),
    ("occupazione auto zero", ("car_occupancy",), 0, "greater than 0"),
    ("revisione zero", ("revision",), 0, "greater than or equal to 1"),
    ("id non è uno slug", ("id",), "Regate 2026", "String should match pattern"),
    ("nome vuoto", ("name",), "", "at least 1 character"),
    ("raggio zero", ("area_radius_m",), 0, "greater than or equal to 1"),
    ("data non valida", ("date",), "2026-02-30", "date"),
    ("coordinate fuori range", ("area_center", "lat"), 91, "less than or equal to 90"),
    ("timestamp senza fuso", ("created_at",), "2026-11-07T10:00:00", "timezone"),
    ("aggiornato prima di creato", ("updated_at",), "2026-11-07T09:59:00+01:00", "non può"),
    ("chiave sconosciuta", ("colore",), "rosso", "Extra inputs are not permitted"),
    ("manca l'arrivo", ("arrival",), DELETE, "arrival\n  Field required"),
    ("manca il picco", (A, "peak"), DELETE, "arrival.peak\n  Field required"),
]  # fmt: skip


@pytest.mark.parametrize(("name", "path", "value", "fragment"), CASES, ids=[c[0] for c in CASES])
def test_valori_non_validi_sono_rifiutati(
    regate: dict[str, Any], name: str, path: tuple[str | int, ...], value: Any, fragment: str
) -> None:
    assert fragment in error_text(mutated(regate, path, value)), name


def test_errori_per_campo_con_percorso(regate: dict[str, Any]) -> None:
    data = mutated(regate, ("resources", 0, "municipal_police_patrols_committed"), 9)
    assert error_locs(data) == [("resources", 0, "municipal_police_patrols_committed")]
    data = mutated(regate, ("closures", 1, "bbox"), [1, 2, 0, 3])
    assert error_locs(data) == [("closures", 1, "bbox")]
    data = mutated(regate, ("attendance", "mid"), 10000)
    assert error_locs(data) == [("attendance", "mid")]


def test_piu_errori_vengono_tutti_riportati(regate: dict[str, Any]) -> None:
    data = mutated(mutated(regate, ("arrival", "peak"), "11:00"), ("attendance", "high"), 100)
    assert sorted(error_locs(data)) == [("arrival", "peak"), ("attendance", "high")]


# --- Chiusure: casi validi ---------------------------------------------------------------


def test_riduzione_di_capacita_e_chiusura_solo_per_chiavi_arco(regate: dict[str, Any]) -> None:
    reduction = mutated(mutated(regate, ("closures", 0, "mode"), "capacity_reduction"),
                        ("closures", 0, "capacity_factor"), 0.5)  # fmt: skip
    assert Event.model_validate(reduction).closures[0].capacity_factor == 0.5
    by_keys = mutated(mutated(regate, ("closures", 0, "street_names"), []),
                      ("closures", 0, "edge_keys"), ["1234567-7654321-0"])  # fmt: skip
    assert Event.model_validate(by_keys).closures[0].edge_keys == ["1234567-7654321-0"]


@pytest.mark.parametrize("factor", [0, 1, 1.5, -0.2])
def test_riduzione_di_capacita_richiede_un_fattore_tra_0_e_1(
    regate: dict[str, Any], factor: float
) -> None:
    data = mutated(mutated(regate, ("closures", 0, "mode"), "capacity_reduction"),
                   ("closures", 0, "capacity_factor"), factor)  # fmt: skip
    assert "tra 0 e 1" in error_text(data)


# --- Override opzionali -----------------------------------------------------------------


POINT = {"lat": 40.83, "lon": 14.24}


def zone(zone_id: str, weight: float) -> dict[str, Any]:
    return {
        "id": zone_id,
        "name": zone_id.upper(),
        "type": "near",
        "weight_pct": weight,
        "centroid": POINT,
    }


def test_override_validi(regate: dict[str, Any]) -> None:
    data = {
        **regate,
        "car_destinations": [
            {"point": {**POINT, "label": "A"}, "share_pct": 70},
            {"point": POINT, "share_pct": 30},
        ],  # fmt: skip
        "zones_override": [zone("a", 60), zone("b", 40)],
        "modal_split_override": {"far": {"car_pct": 10, "transit_pct": 80, "walk_pct": 10}},
        "car_occupancy": 3.0,
    }
    e = Event.model_validate(data)
    assert e.car_destinations is not None and isinstance(e.car_destinations[0], CarDestination)
    assert [z.id for z in e.zones_override or []] == ["a", "b"]
    assert e.modal_split_override is not None and e.modal_split_override["far"].transit_pct == 80
    assert e.car_occupancy == 3.0


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("car_destinations", [{"point": POINT, "share_pct": 60}, {"point": POINT, "share_pct": 60}],
         "Le quote delle destinazioni auto deve sommare a 100"),
        ("zones_override", [zone("a", 60), zone("b", 30)], "I pesi delle zone deve sommare a 100"),
        ("zones_override", [zone("a", 50), zone("a", 50)], "id di zona duplicati: a"),
        ("zones_override", [zone("Zona A", 100)], "String should match pattern"),
        ("modal_split_override", {"far": {"car_pct": 50, "transit_pct": 60, "walk_pct": 10}},
         "La ripartizione modale deve sommare a 100"),
        ("modal_split_override", {"mare": {"car_pct": 0, "transit_pct": 0, "walk_pct": 100}},
         "mare"),
    ],
    ids=["quote auto", "pesi zone", "zone duplicate", "id zona", "somma", "tipo sconosciuto"],
)  # fmt: skip
def test_override_non_validi(regate: dict[str, Any], field: str, value: Any, fragment: str) -> None:
    assert fragment in error_text({**regate, field: value})


def test_le_destinazioni_auto_sono_lo_stesso_modello_della_configurazione() -> None:
    # Una sola definizione di «punto + quota»: configurazione ed Evento la condividono.
    assert Event.model_fields["car_destinations"].annotation == list[CarDestination] | None


# --- Bordi ammessi ---------------------------------------------------------------------------


def test_i_livelli_di_affluenza_possono_coincidere(regate: dict[str, Any]) -> None:
    same = mutated(mutated(regate, ("attendance", "low"), 1000), ("attendance", "mid"), 1000)
    same = mutated(same, ("attendance", "high"), 1000)
    e = Event.model_validate(same)
    assert (e.attendance.low, e.attendance.mid, e.attendance.high) == (1000, 1000, 1000)
    zero = mutated(mutated(mutated(regate, ("attendance", "low"), 0), ("attendance", "mid"), 0),
                   ("attendance", "high"), 5)  # fmt: skip
    assert Event.model_validate(zero).attendance.low == 0


def test_tutte_le_pattuglie_possono_essere_impegnate(regate: dict[str, Any]) -> None:
    e = Event.model_validate(mutated(regate, COMMITTED, 6))  # totali 6, impegnate 6
    assert e.resources[0].municipal_police_patrols_committed == 6
    assert (
        Event.model_validate(mutated(regate, COMMITTED, 0))
        .resources[0]
        .municipal_police_patrols_committed
        == 0
    )


@pytest.mark.parametrize("share", [0, 0.0, 1, 1.0])
def test_lo_sfondo_ammette_gli_estremi_0_e_1(regate: dict[str, Any], share: float) -> None:
    data = mutated(mutated(regate, ("background", "arrival_peak_share"), share),
                   ("background", "departure_peak_share"), share)  # fmt: skip
    e = Event.model_validate(data)
    assert (e.background.arrival_peak_share, e.background.departure_peak_share) == (share, share)


def test_chiavi_arco_con_nodi_osm_lunghi(regate: dict[str, Any]) -> None:
    keys = ["1234567890-9876543210-0", "5-6-12"]
    e = Event.model_validate(mutated(regate, ("closures", 0, "edge_keys"), keys))
    assert e.closures[0].edge_keys == keys


def test_l_hash_dell_evento_segue_il_contenuto() -> None:
    event = make_event()
    assert re.fullmatch(r"[0-9a-f]{64}", event.content_hash())
    assert make_event().content_hash() == event.content_hash()
    assert make_event(name="Altro nome").content_hash() != event.content_hash()
    assert make_event(attendance={"low": 1, "mid": 2, "high": 3}).content_hash() != (
        event.content_hash()
    )


def test_finestra_e_quota_di_fondo_per_finestra() -> None:
    event = make_event(background={"arrival_peak_share": 0.4, "departure_peak_share": 0.25})
    assert event.time_window("arrival") is event.arrival
    assert event.time_window("departure") is event.departure
    assert event.arrival != event.departure
    assert event.background.peak_share("arrival") == 0.4
    assert event.background.peak_share("departure") == 0.25


def test_window_span_scrive_l_orario_della_finestra_in_un_solo_modo() -> None:
    event = make_event()
    assert event.window_span("arrival") == "12:00–15:00"
    assert event.window_span("departure") == "18:00–21:00"
