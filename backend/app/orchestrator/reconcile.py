from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from app.agents.payloads import PlanCandidate
from app.engine.run import RoadResult

BUS_DETOUR = "bus_detour"
DETOURS = frozenset({"detour_signage", BUS_DETOUR})


@dataclass(frozen=True)
class Discard:
    candidate: PlanCandidate
    rule: str  # R1, R2 o R3
    reason: str


@dataclass(frozen=True)
class Reconciled:
    kept: list[PlanCandidate]
    discarded: list[Discard]


def closed_edges(results: Iterable[RoadResult]) -> frozenset[str]:
    """Le chiavi `u-v-k` degli archi chiusi dall'Evento, in qualunque finestra."""
    return frozenset(
        str(feature.properties["edge_key"])
        for result in results
        for feature in (
            result.metrics.layers["edges_vc"].features
            if "edges_vc" in result.metrics.layers
            else []
        )
        if feature.properties.get("closed")
    )


def _closed_among(target: str, closed: frozenset[str]) -> list[str]:
    return [edge for edge in target.split(",") if edge in closed]


def reconcile(candidates: Sequence[PlanCandidate], closed: frozenset[str]) -> Reconciled:
    discarded: list[Discard] = []
    survivors: list[PlanCandidate] = []
    for candidate in candidates:
        measure, target = candidate.recommendation.measure_type, candidate.recommendation.target
        hit = _closed_among(target, closed) if measure in DETOURS else []
        if hit and measure == BUS_DETOUR:
            discarded.append(
                Discard(candidate, "R1", f"deviazione dei bus su arco chiuso ({hit[0]})")
            )
        elif hit:
            discarded.append(
                Discard(candidate, "R2", f"la via {hit[0]} è proposta come deviazione ma è chiusa")
            )
        else:
            survivors.append(candidate)
    kept: list[PlanCandidate] = []
    position: dict[tuple[str, str, str], int] = {}
    for candidate in survivors:
        rec = candidate.recommendation
        key = (rec.measure_type, rec.target, rec.window)
        if key not in position:
            position[key] = len(kept)
            kept.append(candidate)
            continue
        twin = position[key]
        first = kept[twin].recommendation
        evidence = list(dict.fromkeys([*first.evidence_ids, *rec.evidence_ids]))
        kept[twin] = replace(
            kept[twin], recommendation=first.model_copy(update={"evidence_ids": evidence})
        )
        reason = f"doppia di una misura uguale ({rec.measure_type}, {rec.target})"
        discarded.append(Discard(candidate, "R3", reason))
    return Reconciled(kept, discarded)
