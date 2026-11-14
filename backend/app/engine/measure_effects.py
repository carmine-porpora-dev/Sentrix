from collections.abc import Sequence
from datetime import datetime

import networkx as nx

from app.data.resolvers import edge_key
from app.engine import STATIC_MODEL_ASSUMPTION
from app.engine.assign import Assignment
from app.engine.measures import ROAD_TYPES, target_edges
from app.models.base import Window
from app.models.operations import OperationRequest
from app.models.provenance import Measured, make_measured, measured_id

SOURCE = "engine.measure_effects v1"
# Tipi che hanno un v/c da confrontare: le chiusure portano la capacità a 0 e non ne hanno.
EFFECT_TYPES = ROAD_TYPES - {"close_road"}

_WHAT = {
    "traffic_post": "gli archi entranti nell'incrocio",
    "signal_plan_change": "l'arco entrante favorito",
    "detour_signage": "gli archi indicati",
}


def measure_effects(
    requests: Sequence[OperationRequest],
    graph: nx.MultiDiGraph,
    before: Assignment,
    after: Assignment,
    *,
    window: Window,
    id_prefix: Sequence[str],
    as_of: datetime,
) -> tuple[Measured, ...]:
    """`vc_before` e `vc_after` di ogni misura di `requests` (quelle introdotte in questa
    iterazione, della finestra e di un tipo con effetto), nell'ordine (iterazione, action_id).

    `graph` è la rete con le misure (per leggere i bersagli), `before` e `after` le due
    assegnazioni. Si confrontano solo gli archi che hanno un carico in entrambe.
    """
    out: list[Measured] = []
    for request in sorted(requests, key=lambda r: (r.iteration, r.action_id)):
        if request.type not in EFFECT_TYPES or request.window != window:
            continue
        keys = [
            key
            for u, v, k in target_edges(request, graph)
            if (key := edge_key(u, v, k)) in before.edges and key in after.edges
        ]
        if not keys:
            continue
        what = _WHAT[request.type]
        inputs = [
            f"misura {request.action_id} ({request.type}), finestra {window}",
            f"{len(keys)} archi toccati: {', '.join(keys[:4])}{'…' if len(keys) > 4 else ''}",
        ]
        assumptions = [
            STATIC_MODEL_ASSUMPTION,
            "le altre misure introdotte nella stessa iterazione contribuiscono alla differenza",
            "assegnazione incrementale, non un equilibrio: il v/c può anche salire",
        ]
        for part, loads, with_what in (
            ("vc_before", before, "senza le misure introdotte in questa iterazione"),
            ("vc_after", after, "con tutte le misure in vigore"),
        ):
            out.append(
                make_measured(
                    id=measured_id(
                        *id_prefix, "road", window, "measure_effect", request.action_id, part
                    ),
                    value=max(loads.edges[key].vc for key in keys),
                    unit="rapporto",
                    kind="simulated",
                    source=SOURCE,
                    method=f"massimo v/c su {what} toccati dalla misura, {with_what}",
                    inputs=inputs,
                    assumptions=assumptions,
                    as_of=as_of,
                )
            )
    return tuple(out)
