import ast
import json
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pytest

from app.clock import ROME
from app.data.seeds import (
    DEFAULT_SEEDS_DIR,
    SeedError,
    SeedLoadResult,
    load_seed_events,
    read_seed_events,
)
from app.db.repository import Repository
from app.models.event import Event
from tests.support import DELETE, mutated

BACKEND = Path(__file__).resolve().parents[2]
CLOSURE_LABEL = "Via Francesco Caracciolo (viale Dohrn – piazza Vittoria)"
BBOX = (14.2275, 40.8295, 14.2450, 40.8365)


@pytest.fixture
def events() -> dict[str, Event]:
    return {e.id: e for e in read_seed_events()}


@pytest.fixture
def repo(tmp_path: Path) -> Repository:
    return Repository(tmp_path / "napoli.db")


def real_seed(name: str) -> dict[str, Any]:
    return json.loads((DEFAULT_SEEDS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def write_seed(directory: Path, name: str, data: Any) -> Path:
    path = directory / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def resources(event: Event, window: str) -> tuple[int, int, int, int, int]:
    (r,) = [r for r in event.resources if r.window == window]
    return (
        r.municipal_police_patrols_total,
        r.municipal_police_patrols_committed,
        r.traffic_control_signal_changes_max,
        r.transport_control_reserve_buses,
        r.transport_control_hour_extensions,
    )


# --- i due file reali, contro 01 5 --------------------------------------------------------


def test_la_cartella_dei_seed_contiene_i_due_preset() -> None:
    assert DEFAULT_SEEDS_DIR.is_dir()
    assert sorted(p.name for p in DEFAULT_SEEDS_DIR.glob("*.json")) == [
        "match_2027.json",
        "regate_sep_2026.json",
    ]


def test_i_preset_si_leggono_in_ordine_di_nome(events: dict[str, Event]) -> None:
    assert [e.id for e in read_seed_events()] == ["match_2027", "regate_sep_2026"]
    assert set(events) == {"match_2027", "regate_sep_2026"}


def test_regate_come_in_01_5_1(events: dict[str, Event]) -> None:
    e = events["regate_sep_2026"]
    assert e.name == "Regate preliminari settembre 2026"
    assert e.date == date(2026, 9, 26) and e.date.weekday() == 5  # sabato
    assert e.description == "Seconda regata preliminare, 24–27/09/2026. Caso reale già avvenuto."
    assert (e.area_center.lat, e.area_center.lon, e.area_center.label) == (
        40.8320,
        14.2350,
        "Rotonda Diaz",
    )
    assert e.area_radius_m == 400
    assert (e.arrival.start, e.arrival.end, e.arrival.peak) == (
        time(12, 0),
        time(14, 0),
        time(13, 30),
    )
    assert (e.departure.start, e.departure.end, e.departure.peak) == (
        time(16, 0),
        time(18, 0),
        time(16, 30),
    )
    assert (e.attendance.low, e.attendance.mid, e.attendance.high) == (20000, 40000, 60000)
    assert e.attendance.source_ref == (
        "Attesi oltre 60.000 spettatori, picco ~40.000 sabato-domenica "
        "(Corriere dello Sport, 24/09/2026); 20.000 ipotesi bassa"
    )
    ordinance = (
        "Dispositivo di circolazione temporaneo per la «Regata preliminare Louis Vuitton Cup "
        "2026 – Villaggio» (fase 3, 21–27/09/2026), dal sito del Comune di Napoli, consultato "
        "il 9/11/2026; la stampa lo attribuisce all'ord. dirigenziale n. 1496 del 2/09/2026"
    )
    caracciolo, dohrn = e.closures
    assert (caracciolo.label, caracciolo.street_names, caracciolo.bbox) == (
        CLOSURE_LABEL,
        ["Via Francesco Caracciolo"],
        BBOX,
    )
    assert (dohrn.label, dohrn.street_names, dohrn.bbox) == (
        "Viale Anton Dohrn",
        ["Viale Anton Dohrn"],
        None,
    )
    assert caracciolo.source_ref == dohrn.source_ref == ordinance
    assert all(c.mode == "closed" and c.capacity_factor == 0 for c in e.closures)
    assert e.transit_disruptions == []
    assert (e.background.arrival_peak_share, e.background.departure_peak_share) == (0.35, 0.40)
    assert resources(e, "departure") == (6, 3, 3, 8, 1)
    assert resources(e, "arrival") == (6, 3, 3, 8, 1)
    hours, lane = e.real_measures
    assert (hours.label, hours.measure_type, hours.target, hours.source_ref) == (
        "Metro e funicolari prolungate fino alle 2:00",
        "extend_hours",
        "metro+funicolari",
        "Piano ANM per le pre-regate (napolike.it)",
    )
    assert (lane.label, lane.measure_type, lane.target, lane.source_ref) == (
        "Senso unico per tutti i veicoli nella corsia preferenziale di Riviera di Chiaia "
        "(da piazza della Repubblica a piazza Vittoria)",
        "bus_lane_opening",
        "Riviera di Chiaia (piazza della Repubblica – piazza Vittoria)",
        ordinance,
    )
    assert e.sources == [ordinance, "Corriere dello Sport, 24/09/2026", hours.source_ref]
    assert (e.revision, e.car_destinations, e.zones_override) == (1, None, None)


def test_match_come_in_01_5_2(events: dict[str, Event]) -> None:
    e = events["match_2027"]
    assert e.name == "Match 2027 — serata di regata"
    assert e.date == date(2027, 7, 10)
    assert (e.area_center.lat, e.area_center.lon, e.area_center.label) == (
        40.8320,
        14.2350,
        "Rotonda Diaz",
    )
    assert e.area_radius_m == 400
    assert (e.arrival.start, e.arrival.end, e.arrival.peak) == (
        time(16, 0),
        time(19, 0),
        time(18, 0),
    )
    assert (e.departure.start, e.departure.end, e.departure.peak) == (
        time(21, 0),
        time(23, 0),
        time(21, 30),
    )
    assert (e.attendance.low, e.attendance.mid, e.attendance.high) == (50000, 150000, 300000)
    assert e.attendance.source_ref == "Ipotesi di scenario (documento di progetto 5.2)"
    caracciolo, dohrn = e.closures  # «stesse due del 5.1»
    assert (caracciolo.label, caracciolo.street_names, caracciolo.bbox) == (
        CLOSURE_LABEL,
        ["Via Francesco Caracciolo"],
        BBOX,
    )
    assert (dohrn.label, dohrn.street_names) == ("Viale Anton Dohrn", ["Viale Anton Dohrn"])
    assert (
        caracciolo.source_ref
        == dohrn.source_ref
        == "Ipotesi basata sul dispositivo di settembre 2026"
    )
    (mirelli,) = e.transit_disruptions
    assert (mirelli.label, mirelli.stop_name, mirelli.window, mirelli.source_ref) == (
        "Stazione Arco Mirelli chiusa per sicurezza",
        "Arco Mirelli",
        "arrival",
        "Ipotesi di scenario",
    )
    assert (e.background.arrival_peak_share, e.background.departure_peak_share) == (0.40, 0.25)
    assert resources(e, "departure") == (6, 5, 3, 8, 1)  # 5 pattuglie ai varchi
    assert resources(e, "arrival") == (6, 3, 3, 8, 1)
    assert e.real_measures == []
    assert e.revision == 1


def test_i_preset_hanno_un_istante_fisso_nei_file(events: dict[str, Event]) -> None:
    # Il file non cambia da un caricamento all'altro: nessun «adesso» nascosto.
    stamp = datetime(2026, 11, 8, 0, 0, tzinfo=ROME)
    assert all(e.created_at == e.updated_at == stamp for e in events.values())


# --- caricamento nel database --------------------------------------------------------------


def test_il_primo_caricamento_scrive_i_preset(repo: Repository, events: dict[str, Event]) -> None:
    result = load_seed_events(repo)
    assert result == SeedLoadResult(added=("match_2027", "regate_sep_2026"), skipped=())
    rows = repo.list_events()
    assert [(r.id, r.is_seed, r.revision) for r in rows] == [
        ("match_2027", True, 1),  # dal più recente: il Match è il primo, quello che si apre
        ("regate_sep_2026", True, 1),
    ]
    assert all(repo.get_event(i) == e for i, e in events.items())


def test_il_caricamento_e_idempotente(repo: Repository) -> None:
    load_seed_events(repo)
    before = [repo.get_event(i) for i in ("match_2027", "regate_sep_2026")]
    for _ in range(3):
        again = load_seed_events(repo)
        assert again == SeedLoadResult(added=(), skipped=("match_2027", "regate_sep_2026"))
    assert [repo.get_event(i) for i in ("match_2027", "regate_sep_2026")] == before
    assert len(repo.list_events()) == 2


def test_una_modifica_dellutente_sopravvive_al_riavvio(repo: Repository) -> None:
    load_seed_events(repo)
    edited = repo.update_event(
        read_seed_events()[1].model_copy(update={"name": "Regate (la mia versione)"})
    )
    assert edited.revision == 2
    result = load_seed_events(repo)
    assert "regate_sep_2026" in result.skipped
    kept = repo.get_event("regate_sep_2026")
    assert kept == edited
    assert kept is not None and kept.name == "Regate (la mia versione)"
    assert (
        repo.get_event_revision("regate_sep_2026", 1) == read_seed_events()[1]
    )  # l'originale resta


def test_un_evento_dellutente_con_lid_di_un_preset_non_viene_toccato(
    repo: Repository, events: dict[str, Event]
) -> None:
    mine = events["match_2027"].model_copy(update={"name": "Il mio match"})
    repo.add_event(mine, is_seed=False)
    result = load_seed_events(repo)
    assert result.added == ("regate_sep_2026",) and result.skipped == ("match_2027",)
    assert repo.get_event("match_2027") == mine
    rows = {r.id: r for r in repo.list_events()}
    assert rows["match_2027"].is_seed is False and rows["regate_sep_2026"].is_seed is True


def test_si_aggiunge_solo_cio_che_manca(repo: Repository, events: dict[str, Event]) -> None:
    repo.add_event(events["regate_sep_2026"], is_seed=True)
    assert load_seed_events(repo) == SeedLoadResult(
        added=("match_2027",), skipped=("regate_sep_2026",)
    )


def test_un_nuovo_file_diventa_un_nuovo_preset(repo: Repository, tmp_path: Path) -> None:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    write_seed(seeds, "regate_sep_2026", real_seed("regate_sep_2026"))
    assert load_seed_events(repo, seeds).added == ("regate_sep_2026",)
    write_seed(seeds, "match_2027", real_seed("match_2027"))
    second = load_seed_events(repo, seeds)
    assert (second.added, second.skipped) == (("match_2027",), ("regate_sep_2026",))


def test_cartella_vuota_o_con_altri_file_non_fa_niente(repo: Repository, tmp_path: Path) -> None:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    for name in (".gitkeep", "appunti.txt", "regate_sep_2026.json.bak", "regate_sep_2026.json~"):
        (seeds / name).write_text("{ non è un evento", encoding="utf-8")
    assert load_seed_events(repo, seeds) == SeedLoadResult(added=(), skipped=())
    assert repo.list_events() == []


def test_cartella_mancante_e_un_errore(repo: Repository, tmp_path: Path) -> None:
    with pytest.raises(SeedError, match="Cartella dei seed non trovata"):
        load_seed_events(repo, tmp_path / "non_esiste")


# --- file non validi: errore chiaro, nessuna scrittura -------------------------------------

REGATE = real_seed("regate_sep_2026")

BROKEN: list[tuple[str, Any, str]] = [
    ("campo mancante", mutated(REGATE, ("arrival",), DELETE), "arrival: Field required"),
    (
        "chiave sconosciuta",
        mutated(REGATE, ("colore",), "rosso"),
        "colore: Extra inputs are not permitted",
    ),
    ("picco fuori finestra", mutated(REGATE, ("arrival", "peak"), "15:00"), "arrival.peak"),
    ("orario come numero", mutated(REGATE, ("arrival", "start"), 1200), "arrival.start"),
    (
        "pattuglie impegnate oltre il totale",
        mutated(REGATE, ("resources", 0, "municipal_police_patrols_committed"), 9),
        "resources.0.municipal_police_patrols_committed",
    ),
    (
        "id non è uno slug",
        mutated(REGATE, ("id",), "Regate 2026"),
        "id: String should match pattern",
    ),
    ("radice non è un oggetto", [], "(radice)"),
    ("senza fuso orario", mutated(REGATE, ("created_at",), "2026-11-08T00:00:00"), "created_at"),
]


@pytest.mark.parametrize(("name", "data", "fragment"), BROKEN, ids=[b[0] for b in BROKEN])
def test_file_non_valido(
    repo: Repository, tmp_path: Path, name: str, data: Any, fragment: str
) -> None:
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    write_seed(seeds, "match_2027", real_seed("match_2027"))  # questo è valido
    write_seed(seeds, "regate_sep_2026", data)
    with pytest.raises(SeedError) as info:
        load_seed_events(repo, seeds)
    message = str(info.value)
    assert message.startswith("regate_sep_2026.json: "), name
    assert fragment in message, name
    assert repo.list_events() == [], "nessun preset a metà: il file valido non deve essere scritto"


def test_tutti_gli_errori_di_un_file_sono_riportati(repo: Repository, tmp_path: Path) -> None:
    data = mutated(REGATE, ("arrival", "peak"), "15:00")
    data = mutated(data, ("attendance", "mid"), 5)  # sotto il livello basso
    write_seed(tmp_path, "regate_sep_2026", data)
    with pytest.raises(SeedError) as info:
        load_seed_events(repo, tmp_path)
    assert "arrival.peak" in str(info.value) and "attendance.mid" in str(info.value)


def test_json_non_valido(repo: Repository, tmp_path: Path) -> None:
    (tmp_path / "regate_sep_2026.json").write_text('{ "id": "regate_sep_2026", ', encoding="utf-8")
    with pytest.raises(SeedError, match=r"regate_sep_2026\.json: "):
        load_seed_events(repo, tmp_path)


def test_file_vuoto(repo: Repository, tmp_path: Path) -> None:
    (tmp_path / "regate_sep_2026.json").write_text("", encoding="utf-8")
    with pytest.raises(SeedError, match=r"regate_sep_2026\.json: "):
        load_seed_events(repo, tmp_path)


def test_file_che_non_e_utf8(repo: Repository, tmp_path: Path) -> None:
    (tmp_path / "regate_sep_2026.json").write_bytes(b'{"name": "Citt\xe0"}')  # latin-1
    with pytest.raises(SeedError, match=r"regate_sep_2026\.json: "):
        load_seed_events(repo, tmp_path)


def test_chiave_duplicata_non_passa_in_silenzio(repo: Repository, tmp_path: Path) -> None:
    text = (DEFAULT_SEEDS_DIR / "regate_sep_2026.json").read_text(encoding="utf-8")
    doubled = text.replace(
        '"area_radius_m": 400,', '"area_radius_m": 400,\n  "area_radius_m": 900,'
    )
    assert doubled != text
    (tmp_path / "regate_sep_2026.json").write_text(doubled, encoding="utf-8")
    with pytest.raises(SeedError, match="chiavi duplicate: area_radius_m"):
        load_seed_events(repo, tmp_path)


def test_il_nome_del_file_deve_essere_lid(repo: Repository, tmp_path: Path) -> None:
    write_seed(tmp_path, "altro_nome", real_seed("regate_sep_2026"))
    with pytest.raises(
        SeedError, match=r"altro_nome\.json: il file deve chiamarsi 'regate_sep_2026\.json'"
    ):
        load_seed_events(repo, tmp_path)
    assert repo.list_events() == []


def test_read_seed_events_non_scrive_niente(tmp_path: Path) -> None:
    write_seed(tmp_path, "match_2027", real_seed("match_2027"))
    assert [e.id for e in read_seed_events(tmp_path)] == ["match_2027"]
    assert list(tmp_path.iterdir()) == [tmp_path / "match_2027.json"]


# --- «Evento = dato» (principio 4): nessun codice conosce i preset -------------------------


def strings_in(source: str) -> list[str]:
    return [
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_il_controllo_sulle_stringhe_funziona() -> None:
    assert "match_2027" in strings_in("if event.id == 'match_2027':\n    pass")
    assert strings_in("x = 1  # match_2027 nel commento") == []
    assert strings_in("x = f'{a}'") == []


def test_nessun_modulo_conosce_i_nomi_dei_preset() -> None:
    names = [p.stem for p in DEFAULT_SEEDS_DIR.glob("*.json")]
    titles = [real_seed(n)["name"] for n in names]
    assert len(names) == 2 and len(titles) == 2
    offenders = []
    for folder in ("app", "scripts"):
        for path in (BACKEND / folder).rglob("*.py"):
            for text in strings_in(path.read_text(encoding="utf-8")):
                if any(name in text for name in names + titles):
                    offenders.append(f"{path.relative_to(BACKEND).as_posix()}: {text[:50]!r}")
    assert offenders == [], f"codice legato a un evento: {offenders}"
