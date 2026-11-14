import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.clock import now_rome
from app.db.repository import Repository, StateConflict
from app.models.api import ManualResponse, ResourceBalance
from app.models.catalog import Measure
from app.models.operations import OperationRequest, OperationRequestDraft
from app.models.run import Run
from app.operations import resources
from app.operations.alternatives import Alternative, TargetLookup, list_alternatives_for_measure
from app.operations.lifecycle import RequestLifecycle, RunNotFound
from app.operations.registry import DepartmentRegistry
from app.operations.rules import Accept, Reject, RuleState, evaluate

logger = logging.getLogger(__name__)

SYSTEM = "system"  # attore di un esito che nessuno ha deciso: la risposta non è arrivata
TIMEOUT_CODE = "TIMEOUT"
USER = "user"  # attore di un esito scelto da una persona (risposta manuale)


class AcceptNotAllowed(Exception):
    """Una risposta manuale «accetta» che la regola del dipartimento non permetterebbe (04 5):
    la persona può rifiutare la richiesta, non accettarla oltre le risorse o contro un conflitto."""

    def __init__(self, action_id: str, code: str, reason: str) -> None:
        super().__init__(f"Non si può accettare: {reason}. La richiesta si può rifiutare.")
        self.action_id = action_id
        self.code = code  # il codice con cui la regola avrebbe rifiutato (es. UNAVAILABLE)
        self.reason = reason


class NotAwaitingResponse(Exception):
    """La richiesta non attende una risposta manuale: non è in `RECEIVED`, oppure non è stata
    inviata con la risposta manuale (o nessun invio la sta più aspettando)."""

    def __init__(self, action_id: str, state: str, detail: str) -> None:
        super().__init__(f"Richiesta '{action_id}' ({state}): {detail}")
        self.action_id = action_id
        self.state = state


def _deliver(future: asyncio.Future[OperationRequest], request: OperationRequest) -> None:
    if not future.done():  # scaduto il tempo, il compito che aspettava l'ha già annullato
        future.set_result(request)


class OperationsCenter:
    def __init__(
        self,
        repo: Repository,
        registry: DepartmentRegistry,
        *,
        add_runs_default: int,
        clock: Callable[[], datetime] = now_rome,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._repo = repo
        self._registry = registry
        self._add_runs_default = add_runs_default
        self._sleep = sleep  # i test lo sostituiscono: il ritardo simulato non si aspetta davvero
        self.lifecycle = RequestLifecycle(repo, registry, clock)
        # Valutare una richiesta e scriverne l'esito è una sola operazione: senza, due richieste
        # che chiedono l'ultima pattuglia la vedrebbero libera tutte e due (anche da thread).
        self._deciding = threading.Lock()
        self._background: set[asyncio.Task[None]] = set()
        # Le richieste che aspettano una persona: chi le ha inviate è un compito `asyncio`, chi
        # risponde (l'endpoint dell'API) gira su un altro thread, quindi serve un blocco.
        self._waiting: dict[
            str, tuple[asyncio.AbstractEventLoop, asyncio.Future[OperationRequest]]
        ] = {}
        self._waiting_lock = threading.Lock()

    def _run(self, run_id: str) -> Run:
        run = self._repo.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    def rule_state(self, run_id: str) -> RuleState:
        """Ciò che le regole possono guardare per un run: l'Evento nella revisione che il run ha
        usato (non quella di oggi: il run non cambia se l'Evento si modifica dopo) e le sue
        richieste."""
        run = self._run(run_id)
        event = self._repo.get_event_revision(run.event_id, run.event_revision)
        if event is None:  # il repository lo garantisce alla creazione del run
            raise RunNotFound(run_id)
        return RuleState(
            event=event,
            requests=self._repo.list_operation_requests(run_id),
            add_runs_default=self._add_runs_default,
        )

    def resources(self, run_id: str) -> list[ResourceBalance]:
        """Le risorse dei dipartimenti per un run: totale, usate e rimaste, per finestra. Ogni run
        parte dalle risorse dell'Evento: i consumi di un altro run non contano."""
        state = self.rule_state(run_id)
        return resources.balances(state.event, state.requests, state.add_runs_default)

    # --- richieste -----------------------------------------------------------------------------

    def create(self, draft: OperationRequestDraft) -> OperationRequest:
        """Una richiesta `CREATED` per il dipartimento che gestisce il tipo (lo dice il registro:
        chi la chiede conosce la misura, non l'ente)."""
        return self.lifecycle.create(draft, self._registry.for_type(draft.type).id)

    def list_catalog(self) -> list[Measure]:
        """Le misure che gli agenti possono proporre (catalogo chiuso, 04 6)."""
        return list(self._registry.catalog.measures)

    def alternatives(
        self, measure_type: str, target: str, target_label: str, lookup: TargetLookup
    ) -> list[Alternative]:
        """Le alternative a una misura rifiutata, compatibili col suo bersaglio."""
        return list_alternatives_for_measure(
            self._registry.catalog, measure_type, target, target_label, lookup
        )

    def status(self, action_id: str) -> OperationRequest:
        request = self._repo.get_operation_request(action_id)
        if request is None:
            raise LookupError(f"Richiesta '{action_id}' non trovata")
        return request

    # --- invio ---------------------------------------------------------------------------------

    async def dispatch(self, action_id: str, *, manual: bool = False) -> OperationRequest:
        """Invia la richiesta al suo dipartimento e aspetta l'esito (04 4), tutto in-process:
        `CREATED → SENT → RECEIVED`, dopo il ritardo simulato la regola decide `ACCEPTED` o
        `REJECTED`. Se il dipartimento non risponde entro `auto_timeout_s`: `REJECTED`/`TIMEOUT`.
        Con `manual` (risposta manuale, 04 5) la richiesta resta `RECEIVED` finché una persona
        non risponde (`respond_manually`), entro `manual_timeout_s`: poi `REJECTED`/`TIMEOUT`.
        Dopo un'accettazione `IN_PROGRESS` e `COMPLETED` avanzano da soli, in secondo piano (si
        vedono nell'interfaccia, non bloccano il run). Si possono inviare più richieste insieme
        (`asyncio.gather`): l'esito di ognuna lo decide la regola, una alla volta."""
        request = self.lifecycle.advance(self.status(action_id), "SENT")
        request = self.lifecycle.advance(request, "RECEIVED")
        decided = await (self._await_person(request) if manual else self._respond(request))
        if decided.state == "ACCEPTED":
            self._start_progress(decided)
        return decided

    async def _respond(self, request: OperationRequest) -> OperationRequest:
        try:
            async with asyncio.timeout(self._registry.auto_timeout_s):
                await self._sleep(self._registry.response_delay_s)
        except TimeoutError:
            return self._time_out(request, self._registry.auto_timeout_s)
        return self._decide(request)

    async def _await_person(self, request: OperationRequest) -> OperationRequest:
        """Aspetta `respond_manually`: nessuna regola e nessun ritardo, decide la persona."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[OperationRequest] = loop.create_future()
        with self._waiting_lock:
            self._waiting[request.action_id] = (loop, future)
        try:
            return await asyncio.wait_for(future, timeout=self._registry.manual_timeout_s)
        except TimeoutError:
            return self._time_out(request, self._registry.manual_timeout_s)
        finally:
            with self._waiting_lock:
                self._waiting.pop(request.action_id, None)

    def respond_manually(self, action_id: str, response: ManualResponse) -> OperationRequest:
        """La risposta di una persona a una richiesta `RECEIVED` inviata con la risposta manuale:
        rifiuta con codice e motivo (sempre), oppure accetta, ma **solo se la regola del
        dipartimento accetterebbe** (`AcceptNotAllowed` altrimenti: le risorse restano coerenti e
        la richiesta resta in attesa, si può ancora rifiutare). La decisione è registrata con
        attore `user`. Si può chiamare da qualunque thread. `NotAwaitingResponse` se la richiesta
        non attende una risposta (o se il timeout o un'altra risposta sono arrivati prima)."""
        request = self.status(action_id)
        if request.state != "RECEIVED":
            raise NotAwaitingResponse(
                action_id, request.state, "non attende una risposta: deve essere in RECEIVED"
            )
        with self._waiting_lock:
            waiting = self._waiting.get(action_id)
        if waiting is None:
            raise NotAwaitingResponse(
                action_id, request.state, "la risposta manuale non è attiva per questa richiesta"
            )
        loop, future = waiting
        accepted = response.decision == "accept"
        try:
            # valutare e scrivere l'esito è un'operazione sola, come in `_decide`
            with self._deciding:
                note = None
                if accepted:
                    verdict = evaluate(request, self.rule_state(request.run_id))
                    if isinstance(verdict, Reject):
                        raise AcceptNotAllowed(action_id, verdict.code, verdict.reason)
                    note = f"Accettata con la risposta manuale. {verdict.reason}"
                decided = self.lifecycle.advance(
                    request,
                    "ACCEPTED" if accepted else "REJECTED",
                    actor=USER,
                    note=note,
                    reject_code=None if accepted else response.reject_code,
                    reject_reason=None if accepted else response.reject_reason,
                )
        except StateConflict as exc:
            raise NotAwaitingResponse(
                action_id, exc.found, "un'altra risposta o il timeout sono arrivati prima"
            ) from exc
        try:
            loop.call_soon_threadsafe(_deliver, future, decided)
        except RuntimeError:  # il ciclo di chi aspettava è già chiuso: l'esito è comunque scritto
            logger.warning("Nessuno aspettava più la richiesta %s", action_id)
        return decided

    def _decide(self, request: OperationRequest) -> OperationRequest:
        with self._deciding:
            verdict = evaluate(request, self.rule_state(request.run_id))
            if isinstance(verdict, Accept):
                return self.lifecycle.advance(
                    request, "ACCEPTED", actor=request.department, note=verdict.reason
                )
            return self.lifecycle.advance(
                request,
                "REJECTED",
                actor=request.department,
                reject_code=verdict.code,
                reject_reason=verdict.reason,
            )

    def _time_out(self, request: OperationRequest, seconds: int) -> OperationRequest:
        """La risposta non è arrivata: `REJECTED` con codice `TIMEOUT`, deciso dal sistema. Se
        intanto qualcuno ha risposto, vale la sua risposta."""
        try:
            return self.lifecycle.advance(
                request,
                "REJECTED",
                actor=SYSTEM,
                reject_code=TIMEOUT_CODE,
                reject_reason=f"Nessuna risposta del dipartimento entro {seconds} s",
            )
        except StateConflict:
            return self.status(request.action_id)

    # --- avanzamenti simulati ------------------------------------------------------------------

    def _start_progress(self, request: OperationRequest) -> None:
        task = asyncio.create_task(self._progress(request))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _progress(self, request: OperationRequest) -> None:
        """`IN_PROGRESS` e `COMPLETED`: simulati, servono solo a farli vedere (04 3)."""
        try:
            for state in ("IN_PROGRESS", "COMPLETED"):
                await self._sleep(self._registry.response_delay_s)
                request = self.lifecycle.advance(request, state)
        except Exception:
            logger.exception(
                "Avanzamento simulato della richiesta %s interrotto", request.action_id
            )

    async def settle(self) -> None:
        """Aspetta gli avanzamenti simulati in corso (nei test, e a fine run). I compiti
        finiti si tolgono qui, senza contare sulla callback che li toglie da sola: `gather` su
        compiti già finiti non cede il passo al ciclo, e la callback non farebbe in tempo."""
        while self._background:
            done, _pending = await asyncio.wait(list(self._background))
            self._background.difference_update(done)
