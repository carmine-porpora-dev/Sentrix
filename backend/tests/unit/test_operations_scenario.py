import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.data.seeds import read_seed_events
from app.db.repository import Repository
from app.engine.measures import MeasureError, check_requests
from app.models.catalog import CatalogConfig
from app.models.event import Event
from app.models.operations import OperationRequest
from app.operations.alternatives import list_alternatives_for_measure
from app.operations.center import OperationsCenter
from tests.operations_support import make_center, make_draft, make_repo, settled
from tests.support import make_run

EVENTS = {event.id: event for event in read_seed_events()}
CATALOG = CatalogConfig.from_yaml()
CRITICAL = [("3550591146", "Incrocio Piazza Vittoria"), ("3550591200", "Incrocio Piazza Sannazaro")]


@dataclass
class EngineStub:
    """Il motore finto: ciò che serve a `VERIFY` è quali misure gli arrivano. Le convalida con la
    funzione vera del motore (`check_requests`: solo misure accettate) e ne registra l'elenco."""

    calls: list[tuple[int, list[str]]] = field(default_factory=list)

    def compute(self, iteration: int, requests: list[OperationRequest]) -> None:
        check_requests(requests)
        self.calls.append((iteration, [r.action_id for r in requests]))

    # ciò che il catalogo chiede al motore per scegliere il bersaglio dell'alternativa
    def upstream_edges(self, node: str) -> list[str]:
        return [f"{node[-3:]}-1-0", f"{node[-3:]}-2-0"]

    def favored_edge_key(self, node: str) -> str | None:
        return f"{node[-3:]}-1-0"

    def routes_serving(self, stop_id: str) -> list[str]:
        return []


@dataclass
class Scene:
    center: OperationsCenter
    repo: Repository
    engine: EngineStub
    first: list[OperationRequest]  # le richieste iniziali, con l'esito
    replacements: list[OperationRequest]  # le alternative, con l'esito
    notice: OperationRequest


def free_patrols(event: Event) -> int:
    departure = next(r for r in event.resources if r.window == "departure")
    return departure.municipal_police_patrols_total - departure.municipal_police_patrols_committed


async def play(tmp_path: Path, event_id: str) -> Scene:
    repo = make_repo(tmp_path)
    repo.add_run(make_run("run_1", event_id=event_id))
    center = make_center(repo)
    engine = EngineStub()
    # 2. DISPATCH: un presidio per ogni incrocio critico, insieme
    created = [
        center.create(make_draft(target=node, target_label=label)).action_id
        for node, label in CRITICAL
    ]
    first = list(await asyncio.gather(*(center.dispatch(a) for a in created)))
    # 5. VERIFY, iterazione 1: al motore arrivano solo le misure accettate
    engine.compute(1, [r for r in first if r.state == "ACCEPTED"])
    # 4. REPLAN: per ogni rifiuto, la prima alternativa compatibile
    replacements: list[OperationRequest] = []
    for refused in (r for r in first if r.state == "REJECTED"):
        (alternative, *_) = list_alternatives_for_measure(
            CATALOG, refused.type, refused.target, refused.target_label, engine
        )
        draft = make_draft(
            iteration=2,
            type=alternative.type,
            target=alternative.target,
            target_label=alternative.target_label,
            payload=alternative.payload,
            alternative_of=refused.action_id,
        )
        replacements.append(await center.dispatch(center.create(draft).action_id))
    accepted = [r for r in (*first, *replacements) if r.state == "ACCEPTED"]
    if replacements:
        engine.compute(2, accepted)
    # alla fine, l'avviso ai cittadini con le sole misure approvate
    text = "Misure attive: " + "; ".join(r.target_label for r in accepted)
    notice_draft = make_draft(
        iteration=len(engine.calls) + 1,
        type="citizen_notice",
        target="all",
        target_label="Cittadini",
        payload={"text": text},
    )
    notice = await center.dispatch(center.create(notice_draft).action_id)
    await settled(center)
    return Scene(center, repo, engine, first, replacements, notice)


@pytest.mark.parametrize("event_id", ["match_2027", "regate_sep_2026"])
async def test_la_scena_viene_dai_dati_dell_evento(tmp_path: Path, event_id: str) -> None:
    """Stessa funzione, due eventi: quante richieste passano lo dice l'Evento (pattuglie totali −
    impegnate), non il codice."""
    event = EVENTS[event_id]
    departure = next(r for r in event.resources if r.window == "departure")
    scene = await play(tmp_path, event_id)
    accepted_first = min(len(CRITICAL), free_patrols(event))
    assert [r.state for r in scene.first] == (
        ["ACCEPTED"] * accepted_first + ["REJECTED"] * (len(CRITICAL) - accepted_first)
    )
    window = f"{event.departure.start:%H:%M}–{event.departure.end:%H:%M}"
    for refused in (r for r in scene.first if r.state == "REJECTED"):
        assert refused.reject_code == "UNAVAILABLE"
        total = departure.municipal_police_patrols_total  # al rifiuto sono tutte impegnate
        assert refused.reject_reason == (
            f"Pattuglie esaurite nella finestra {window}: {total} totali, {total} già impegnate "
            "ai varchi"
        )
    # un rifiuto, una ripianificazione: con pattuglie libere per tutti non ce n'è bisogno
    assert len(scene.replacements) == len(CRITICAL) - accepted_first
    assert all(r.state == "ACCEPTED" for r in scene.replacements)
    assert scene.notice.state == "ACCEPTED"


async def test_match_2027_una_libera_la_seconda_e_rifiutata_e_sostituita(tmp_path: Path) -> None:
    scene = await play(tmp_path, "match_2027")
    accepted, refused = scene.first
    assert (accepted.state, refused.state) == ("ACCEPTED", "REJECTED")
    assert refused.reject_code == "UNAVAILABLE"
    assert refused.reject_reason == (
        "Pattuglie esaurite nella finestra 21:00–23:00: 6 totali, 6 già impegnate ai varchi"
    )
    (replacement,) = scene.replacements
    assert replacement.type == "signal_plan_change" and replacement.department == "traffic_control"
    assert replacement.alternative_of == refused.action_id  # alternative_of valorizzato
    assert replacement.target == refused.target  # lo stesso incrocio
    assert replacement.payload == {"favored_edge_key": "200-1-0"}
    assert replacement.state == "ACCEPTED"  # 0 modifiche usate su 3


async def test_verify_riceve_le_misure_accettate_iterazione_per_iterazione(
    tmp_path: Path,
) -> None:
    scene = await play(tmp_path, "match_2027")
    accepted, refused = scene.first
    (replacement,) = scene.replacements
    assert scene.engine.calls == [
        (1, [accepted.action_id]),  # iterazione 1: un presidio
        (2, [accepted.action_id, replacement.action_id]),  # iterazione 2: presidio + semaforo
    ]
    assert refused.action_id not in [a for _, ids in scene.engine.calls for a in ids]


async def test_il_motore_rifiuterebbe_la_misura_rifiutata(tmp_path: Path) -> None:
    """Il motore vero non accetta una richiesta non in vigore: per questo VERIFY passa solo le
    accettate (02 6)."""
    scene = await play(tmp_path, "match_2027")
    _, refused = scene.first
    with pytest.raises(MeasureError):
        check_requests([refused])


async def test_il_registro_delle_decisioni_racconta_la_scena(tmp_path: Path) -> None:
    scene = await play(tmp_path, "match_2027")
    accepted, refused = scene.first
    (replacement,) = scene.replacements
    log = [(d.actor, d.decision) for d in scene.repo.list_decisions("run_1")]
    assert log == [
        ("orchestrator", f"Richiesta {accepted.action_id} inviata (simulata)"),
        ("orchestrator", f"Richiesta {refused.action_id} inviata (simulata)"),
        ("municipal_police", f"Richiesta {accepted.action_id} accettata"),
        ("municipal_police", f"Richiesta {refused.action_id} rifiutata (UNAVAILABLE)"),
        ("orchestrator", f"Richiesta {replacement.action_id} inviata (simulata)"),
        ("traffic_control", f"Richiesta {replacement.action_id} accettata"),
        ("orchestrator", f"Richiesta {scene.notice.action_id} inviata (simulata)"),
        ("public_comms", f"Richiesta {scene.notice.action_id} accettata"),
    ]


async def test_le_risorse_alla_fine_della_scena(tmp_path: Path) -> None:
    scene = await play(tmp_path, "match_2027")
    free = {(b.window, b.resource): b for b in scene.center.resources("run_1")}
    patrols = free[("departure", "patrols")]
    assert (patrols.total, patrols.used, patrols.remaining) == (6, 6, 0)
    signal = free[("departure", "signal_changes")]
    assert (signal.total, signal.used, signal.remaining) == (3, 1, 2)
    assert free[("arrival", "patrols")].remaining == 3  # l'altra finestra non si è toccata


async def test_ogni_richiesta_ha_la_sua_storia_completa(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        scene = await play(tmp_path, "match_2027")
    assert caplog.records == []  # nessun avanzamento simulato è fallito (e quindi registrato)
    accepted, refused = scene.first
    (replacement,) = scene.replacements

    def path(action: str) -> list[str]:
        return [e.to_state for e in scene.repo.list_operation_events(action)]

    full = ["CREATED", "SENT", "RECEIVED", "ACCEPTED", "IN_PROGRESS", "COMPLETED"]
    assert path(accepted.action_id) == full
    assert path(replacement.action_id) == full
    assert path(refused.action_id) == ["CREATED", "SENT", "RECEIVED", "REJECTED"]
    assert scene.notice.state == "ACCEPTED"  # cita solo le misure approvate
    assert all(r.simulation for r in scene.repo.list_operation_requests("run_1"))


async def test_un_avviso_che_cita_la_misura_rifiutata_per_id_non_passa(tmp_path: Path) -> None:
    scene = await play(tmp_path, "match_2027")
    _, refused = scene.first
    bad = scene.center.create(
        make_draft(
            iteration=4,
            type="citizen_notice",
            target="all",
            target_label="Cittadini",
            payload={"text": f"Presidio {refused.action_id} attivo"},
        )
    )
    decided = await scene.center.dispatch(bad.action_id)
    assert (decided.state, decided.reject_code) == ("REJECTED", "UNAPPROVED_MEASURE")
    await settled(scene.center)
