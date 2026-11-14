import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime

from app.agents.payloads import PlanCandidate
from app.agents.runner import AgentRunner, Analysis
from app.agents.tools import AgentTools
from app.clock import now_rome
from app.data.resolvers import ResolveError
from app.db.repository import Repository
from app.models.agents import AgentResult, Severity
from app.models.agents_config import AgentsConfig
from app.models.base import WINDOWS
from app.models.operations import (
    ACTIVE_STATES,
    OperationRequest,
    OperationRequestDraft,
    Priority,
)
from app.models.provenance import Measured
from app.models.run import MAX_REPLANS, Run
from app.operations.center import OperationsCenter
from app.orchestrator.engines import Engines
from app.orchestrator.journal import ENTER, Journal
from app.orchestrator.lookup import EngineTargetLookup
from app.orchestrator.plan_book import PlanBook
from app.orchestrator.reconcile import Discard, reconcile
from app.orchestrator.simulation import Simulation

logger = logging.getLogger(__name__)

PRIORITY_OF: dict[Severity, Priority] = {"critical": "high", "warning": "normal", "info": "low"}
NOTICE_TARGET = "all"
NOTICE_LABEL = "Cittadini"


@dataclass
class _State:
    """Tutto ciò che il run costruisce strada facendo (vive quanto `execute`)."""

    run: Run
    manual: bool
    sim: Simulation
    book: PlanBook
    measures: list[Measured] = field(default_factory=list)  # quelli che gli agenti possono citare
    candidates: list[PlanCandidate] = field(default_factory=list)  # dopo RECONCILE
    discards: list[Discard] = field(default_factory=list)
    tasks: dict[int, asyncio.Task[OperationRequest]] = field(default_factory=dict)
    rejected: list[int] = field(default_factory=list)  # gli elementi rifiutati nell'ultimo giro
    accepted_now: list[OperationRequest] = field(default_factory=list)  # accettate nell'ultimo giro


class Orchestrator:
    def __init__(
        self,
        *,
        repo: Repository,
        center: OperationsCenter,
        runner: AgentRunner,
        engines: Engines,
        config: AgentsConfig,
        clock: Callable[[], datetime] = now_rome,
    ) -> None:
        self._repo = repo
        self._center = center
        self._runner = runner
        self._engines = engines
        self._config = config
        self._clock = clock
        self._journal = Journal(repo)

    # --- entrata e uscita -----------------------------------------------------------------------

    async def execute(self, run_id: str, *, manual: bool = False) -> Run:
        """Porta il run da `INTAKE` a `DONE`, o a `ERROR` con il motivo. `manual`: i dipartimenti
        aspettano la risposta di una persona (04 5)."""
        run = self._repo.get_run(run_id)
        if run is None:
            raise LookupError(f"Run '{run_id}' non trovato")
        try:
            async with asyncio.timeout(self._config.run.timeout_s):
                state = self._intake(run, manual)
                await self._drive(state)
                return state.run
        except TimeoutError:
            limit = self._config.run.timeout_s
            return self._journal.fail(
                run_id, f"Tempo massimo del run superato ({limit} s)", self._clock()
            )
        except ResolveError as exc:
            # un nome o un punto dell'Evento che non si trova nei dati: il messaggio è già per chi
            # compila l'Evento («Chiusura «X»: nessun arco chiamato…»), senza il nome della classe
            logger.warning("Run %s: %s", run_id, exc)
            return self._journal.fail(run_id, str(exc), self._clock())
        except Exception as exc:
            logger.exception("Run %s fallito", run_id)
            return self._journal.fail(run_id, f"{type(exc).__name__}: {exc}", self._clock())

    def _enter(self, state: _State, name: str, why: str) -> None:
        state.run = self._journal.enter(state.run.id, name, why)

    def _log(
        self, state: _State, actor: str, decision: str, why: str, refs: Sequence[str] = ()
    ) -> None:
        self._journal.log(state.run.id, actor, decision, why, refs)

    async def _drive(self, state: _State) -> None:
        await self._analyze(state)
        self._reconcile(state)
        await self._plan(state)
        while state.book.pending:
            self._dispatch(state)
            await self._await(state)
            await self._verify(state)
            if not state.rejected:
                break
            if state.run.replans >= MAX_REPLANS:
                self._give_up(state)
                break
            await self._replan(state)
        await self._finish(state)

    # --- INTAKE ---------------------------------------------------------------------------------

    def _intake(self, run: Run, manual: bool) -> _State:
        event = self._repo.get_event_revision(run.event_id, run.event_revision)
        if event is None:
            raise LookupError(f"Evento '{run.event_id}' revisione {run.event_revision} non trovato")
        sim = Simulation(
            engines=self._engines,
            repo=self._repo,
            config=self._config,
            event=event,
            level=run.attendance_level,
            run_id=run.id,
            as_of=self._clock(),
        )
        state = _State(run=run, manual=manual, sim=sim, book=PlanBook(self._repo, run.id))
        self._enter(
            state,
            "INTAKE",
            f"Evento {event.id} (revisione {run.event_revision}), affluenza {run.attendance_level}",
        )
        return state

    # --- ANALYZE --------------------------------------------------------------------------------

    async def _analyze(self, state: _State) -> None:
        self._enter(state, "ANALYZE", "Domanda, poi Traffic e Transit in parallelo")
        run, sim = state.run, state.sim
        demand = await sim.load_demands()
        self._save(await self._runner.event_demand(demand, run_id=run.id, iteration=0))

        async def traffic() -> tuple[AgentTools, Analysis]:
            tools = await sim.baseline_road()
            return tools, await self._runner.analyse(tools, run_id=run.id, iteration=0)

        async def transit() -> tuple[AgentTools, Analysis]:
            tools = await sim.baseline_transit()
            return tools, await self._runner.analyse(tools, run_id=run.id, iteration=0)

        # Le liste si costruiscono qui, in ordine fisso (Traffic, poi Transit), non dentro i due
        # compiti: l'ordine d'arrivo dipende da quale motore finisce prima, e l'input degli
        # agenti successivi (quindi la chiave della cache LLM) non può dipendere dai tempi.
        for tools, analysis in await asyncio.gather(traffic(), transit()):
            state.measures += tools.measures
            self._save(analysis.result)
            state.candidates += analysis.candidates
        sim.store(0, demand.measures)

    def _save(self, result: AgentResult) -> None:
        self._repo.add_agent_result(result)
        evidence = list(dict.fromkeys(e for f in result.findings for e in f.evidence_ids))
        origin = "dal testo di riserva" if result.text_origin == "template" else "dall'LLM"
        self._journal.log(
            result.run_id,
            result.agent,
            f"Risultato di {result.agent} ({origin})",
            result.text,
            evidence,
        )

    # --- RECONCILE ------------------------------------------------------------------------------

    def _reconcile(self, state: _State) -> None:
        self._enter(
            state, "RECONCILE", f"{len(state.candidates)} misure proposte da Traffic e Transit"
        )
        outcome = reconcile(state.candidates, state.sim.closed_edges())
        state.candidates, state.discards = outcome.kept, outcome.discarded
        for discard in outcome.discarded:
            rec = discard.candidate.recommendation
            self._log(
                state,
                "orchestrator",
                f"Misura scartata ({discard.rule})",
                f"{rec.measure_type} su {discard.candidate.target_label}: {discard.reason}",
                rec.evidence_ids,
            )

    # --- PLAN -----------------------------------------------------------------------------------

    async def _plan(self, state: _State) -> None:
        self._enter(state, "PLAN", f"{len(state.candidates)} misure da ordinare")
        chosen: list[PlanCandidate] = []
        if state.candidates:
            outcome = await self._runner.plan(
                state.candidates,
                self._center.resources(state.run.id),
                state.measures,
                run_id=state.run.id,
                iteration=0,
            )
            self._save(outcome.result)
            chosen = outcome.chosen
        for candidate in chosen:
            state.book.propose(candidate)
        in_plan = {c.id for c in chosen}  # `plan()` numera i candidati c1… nell'ordine d'ingresso
        for number, candidate in enumerate(state.candidates, start=1):
            if f"c{number}" not in in_plan:
                note = "Fuori dal piano: oltre il limite di misure"
                state.book.add(candidate, status="discarded", note=note)
        for discard in state.discards:
            state.book.add(
                discard.candidate, status="discarded", note=f"{discard.rule}: {discard.reason}"
            )

    # --- DISPATCH e AWAIT -----------------------------------------------------------------------

    def _dispatch(self, state: _State) -> None:
        book, rounds = state.book, state.run.iteration + 1
        self._enter(
            state, "DISPATCH", f"Giro {rounds}: {len(book.pending)} richieste ai dipartimenti"
        )
        for seq in book.pending:
            rec, meta = book.items[seq].recommendation, book.meta[seq]
            request = self._center.create(
                OperationRequestDraft(
                    run_id=state.run.id,
                    iteration=rounds,
                    type=rec.measure_type,
                    target=rec.target,
                    target_label=meta.target_label,
                    target_geo=meta.location,
                    window=rec.window,
                    priority=PRIORITY_OF[meta.severity],
                    payload=rec.params,
                    alternative_of=book.replaces.get(seq),
                    simulation=True,
                )
            )
            book.actions[seq] = request.action_id
            state.tasks[seq] = asyncio.create_task(
                self._center.dispatch(request.action_id, manual=state.manual)
            )

    async def _await(self, state: _State) -> None:
        self._enter(state, "AWAIT", "Attendo gli esiti dei dipartimenti")
        book = state.book
        decided = {seq: await state.tasks[seq] for seq in book.pending}
        state.rejected, state.accepted_now = [], []
        for seq, request in decided.items():
            accepted = request.state == "ACCEPTED"
            book.update(
                seq, status="accepted" if accepted else "rejected", action_id=request.action_id
            )
            if accepted:
                state.accepted_now.append(request)
            else:
                state.rejected.append(seq)
                book.refused.add((request.type, request.target))
        state.tasks.clear()
        book.pending = []
        self._log(
            state,
            "orchestrator",
            f"Esiti ricevuti: {len(decided) - len(state.rejected)} accettate, "
            f"{len(state.rejected)} rifiutate",
            "Le risposte dei dipartimenti sono nel registro",
            [request.action_id for request in decided.values()],
        )

    # --- VERIFY ---------------------------------------------------------------------------------

    def _in_force(self, run_id: str) -> list[OperationRequest]:
        """Le misure in vigore (l'avviso ai cittadini non cambia nessun numero)."""
        return [
            r
            for r in self._repo.list_operation_requests(run_id)
            if r.state in ACTIVE_STATES and r.type != "citizen_notice"
        ]

    async def _verify(self, state: _State) -> None:
        """Ricalcola strada e TPL con tutte le misure in vigore, solo per le finestre in cui è
        caduta una misura accettata in questo giro: le altre copiano l'iterazione precedente."""
        iteration = state.run.iteration + 1
        in_force = self._in_force(state.run.id)
        touched = {request.window for request in state.accepted_now}
        self._enter(
            state,
            "VERIFY",
            f"Iterazione {iteration}: {len(in_force)} misure in vigore, "
            f"finestre ricalcolate: {', '.join(w for w in WINDOWS if w in touched) or 'nessuna'}",
        )
        await state.sim.verify(iteration, in_force, touched)
        state.run = self._repo.update_run(state.run.id, iteration=iteration)
        state.sim.store(iteration)
        self._log(
            state,
            "orchestrator",
            f"Iterazione {iteration} calcolata",
            "Metriche e layer salvati con le misure accettate",
            [r.action_id for r in in_force],
        )

    # --- REPLAN ---------------------------------------------------------------------------------

    async def _replan(self, state: _State) -> None:
        state.run = self._repo.update_run(state.run.id, replans=state.run.replans + 1)
        run, book = state.run, state.book
        self._enter(state, "REPLAN", f"Ripianificazione {run.replans} di {MAX_REPLANS}")
        for seq in state.rejected:
            request = self._center.status(book.actions[seq])
            lookup = EngineTargetLookup(
                state.sim.road_in(run.iteration, request.window), self._engines.routes_serving
            )
            options = [
                alt
                for alt in self._center.alternatives(
                    request.type, request.target, request.target_label, lookup
                )
                if (alt.type, alt.target) not in book.refused
            ]
            outcome = await self._runner.replan(
                request,
                book.items[seq].recommendation,
                options,
                state.measures,
                run_id=run.id,
                iteration=run.iteration,
            )
            self._save(outcome.result)
            if outcome.alternative is None or outcome.recommendation is None:
                self._need_human(state, seq, "Nessuna alternativa compatibile non ancora rifiutata")
                continue
            candidate = replace(
                book.meta[seq],
                recommendation=outcome.recommendation,
                target_label=outcome.alternative.target_label,
            )
            new_seq = book.propose(candidate, replaces=book.actions[seq])
            book.update(seq, status="replaced", replaced_by=new_seq)
            self._log(
                state,
                "operations",
                f"Alternativa per {request.action_id}",
                f"{outcome.alternative.type} su {outcome.alternative.target_label}",
                [request.action_id],
            )

    def _need_human(self, state: _State, seq: int, note: str) -> None:
        state.book.update(seq, status="human_decision_required", note=note)
        request = self._center.status(state.book.actions[seq])
        self._log(
            state,
            "orchestrator",
            "Decisione umana richiesta",
            f"{request.type} su {request.target_label}: {note}",
            [request.action_id],
        )

    def _give_up(self, state: _State) -> None:
        for seq in state.rejected:
            self._need_human(state, seq, f"Rifiutata anche dopo {MAX_REPLANS} ripianificazioni")

    # --- DONE -----------------------------------------------------------------------------------

    async def _finish(self, state: _State) -> None:
        """L'avviso ai cittadini con le sole misure approvate, poi `DONE`."""
        run = state.run
        accepted = self._in_force(run.id)
        if accepted:
            hours = state.sim.window_spans()
            notice = await self._runner.notice(accepted, state.measures, hours)
            request = self._center.create(
                OperationRequestDraft(
                    run_id=run.id,
                    iteration=run.iteration,
                    type="citizen_notice",
                    target=NOTICE_TARGET,
                    target_label=NOTICE_LABEL,
                    window=accepted[0].window,
                    priority="normal",
                    payload={"text": notice.text},
                    simulation=True,
                )
            )
            decided = await self._center.dispatch(request.action_id, manual=state.manual)
            result = (
                "accettato" if decided.state == "ACCEPTED" else f"rifiutato ({decided.reject_code})"
            )
            self._log(
                state,
                "operations",
                f"Avviso ai cittadini {result}",
                notice.text,
                [request.action_id],
            )
        else:
            self._log(
                state,
                "operations",
                "Nessun avviso ai cittadini",
                "Nessuna misura è stata approvata",
            )
        state.run = self._repo.update_run(run.id, state="DONE", ended_at=self._clock())
        self._log(state, "orchestrator", f"{ENTER}DONE", "Piano finale scritto", ["DONE"])
