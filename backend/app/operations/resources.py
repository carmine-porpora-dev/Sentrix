from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.models.api import ResourceBalance
from app.models.base import Window
from app.models.event import DepartmentResources, Event
from app.models.operations import ACTIVE_STATES, OperationRequest

# I nomi delle risorse (quelli del pannello Operations e di `ResourceBalance.resource`): una volta.
PATROLS = "patrols"
SIGNAL_CHANGES = "signal_changes"
RESERVE_BUSES = "reserve_buses"
HOUR_EXTENSIONS = "hour_extensions"


class InvalidPayload(ValueError):
    """Una richiesta che non si può valutare perché il suo `payload` non è nel formato previsto
    (04 6.2): la regola la rifiuta, non la indovina."""


@dataclass(frozen=True)
class Pool:
    """Una risorsa di un dipartimento: da dove viene il totale e quali richieste la consumano."""

    department: str
    resource: str
    consumers: frozenset[str]  # tipi di richiesta che la consumano
    total: Callable[[DepartmentResources], int]
    committed: Callable[[DepartmentResources], int] = lambda _resources: 0  # già impegnate


POOLS: tuple[Pool, ...] = (
    Pool(
        "municipal_police",
        PATROLS,
        frozenset({"traffic_post", "crowd_control_post"}),
        total=lambda r: r.municipal_police_patrols_total,
        committed=lambda r: r.municipal_police_patrols_committed,
    ),
    Pool(
        "traffic_control",
        SIGNAL_CHANGES,
        frozenset({"signal_plan_change"}),
        total=lambda r: r.traffic_control_signal_changes_max,
    ),
    Pool(
        "transport_control",
        RESERVE_BUSES,
        frozenset({"add_runs"}),
        total=lambda r: r.transport_control_reserve_buses,
    ),
    Pool(
        "transport_control",
        HOUR_EXTENSIONS,
        frozenset({"extend_hours"}),
        total=lambda r: r.transport_control_hour_extensions,
    ),
)


def pool(resource: str) -> Pool:
    return next(p for p in POOLS if p.resource == resource)


def event_resources(event: Event, window: Window) -> DepartmentResources:
    """Le risorse che l'Evento dichiara per la finestra; se non ne dichiara, zero di tutto."""
    for item in event.resources:
        if item.window == window:
            return item
    return DepartmentResources(
        window=window,
        municipal_police_patrols_total=0,
        municipal_police_patrols_committed=0,
        traffic_control_signal_changes_max=0,
        transport_control_reserve_buses=0,
        transport_control_hour_extensions=0,
    )


def units(request: OperationRequest, add_runs_default: int) -> int:
    """Quante unità della sua risorsa consuma una richiesta: una, salvo `add_runs`, che chiede `n`
    bus di riserva (`payload.n`, intero ≥ 1; se manca, il valore predefinito di `engine.yaml`)."""
    if request.type != "add_runs":
        return 1
    n = request.payload.get("n", add_runs_default)
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise InvalidPayload(f"add_runs: 'n' deve essere un intero ≥ 1 (trovato {n!r})")
    return n


def assigned(
    requests: Sequence[OperationRequest],
    resource: str,
    window: Window,
    add_runs_default: int,
    *,
    excluding: str | None = None,
) -> int:
    """Le unità di `resource` già assegnate nel run, nella finestra. `excluding` è la richiesta
    che si sta valutando: non si conta da sola."""
    consumers = pool(resource).consumers
    return sum(
        units(request, add_runs_default)
        for request in requests
        if request.type in consumers
        and request.window == window
        and request.state in ACTIVE_STATES
        and request.action_id != excluding
    )


def balance(
    event: Event,
    requests: Sequence[OperationRequest],
    resource: str,
    window: Window,
    add_runs_default: int,
    *,
    excluding: str | None = None,
) -> ResourceBalance:
    """Totale, usate e rimaste di una risorsa in una finestra."""
    chosen = pool(resource)
    resources = event_resources(event, window)
    total = chosen.total(resources)
    used = chosen.committed(resources) + assigned(
        requests, resource, window, add_runs_default, excluding=excluding
    )
    return ResourceBalance(
        department=chosen.department,
        window=window,
        resource=resource,
        total=total,
        used=used,
        remaining=max(total - used, 0),
    )


def balances(
    event: Event, requests: Sequence[OperationRequest], add_runs_default: int
) -> list[ResourceBalance]:
    """Tutte le risorse dei dipartimenti, per le finestre che l'Evento dichiara, nell'ordine dei
    dipartimenti (finestre nell'ordine dell'Evento)."""
    declared = [item.window for item in event.resources]
    return [
        balance(event, requests, chosen.resource, window, add_runs_default)
        for window in declared
        for chosen in POOLS
    ]
