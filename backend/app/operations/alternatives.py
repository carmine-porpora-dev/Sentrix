from dataclasses import dataclass, field
from typing import Protocol

from pydantic import JsonValue

from app.models.catalog import CatalogConfig, Measure, TargetKind


class UnknownMeasure(LookupError):
    """Il tipo non è una misura del catalogo (che è chiuso: `close_road`, per esempio, non lo è)."""

    def __init__(self, measure_type: str) -> None:
        super().__init__(f"'{measure_type}' non è una misura del catalogo")
        self.measure_type = measure_type


class TargetLookup(Protocol):
    """Ciò che il catalogo non sa e chiede al motore. Ogni metodo risponde dai dati dell'iterazione
    in corso; vuoto o `None` vuol dire «non c'è»."""

    def upstream_edges(self, node: str) -> list[str]:
        """Le chiavi `u-v-k` degli archi entranti nell'incrocio `node` con flusso dell'Evento."""
        ...

    def favored_edge_key(self, node: str) -> str | None:
        """L'arco entrante favorito da un cambio di piano semaforico (v/c più alto), 04 6.1."""
        ...

    def routes_serving(self, stop_id: str) -> list[str]:
        """Le linee (classe o `route_id`) che servono la fermata, la più rilevante per prima."""
        ...


@dataclass(frozen=True)
class Alternative:
    """Una misura che si può chiedere al posto di quella rifiutata, già con il suo bersaglio."""

    type: str
    department: str
    target: str
    target_label: str
    payload: dict[str, JsonValue] = field(default_factory=dict)


def _same_target(alternative: Measure, target: str, label: str) -> Alternative:
    return Alternative(alternative.type, alternative.department, target, label)


def _signal_plan(
    alternative: Measure, node: str, label: str, lookup: TargetLookup
) -> Alternative | None:
    favored = lookup.favored_edge_key(node)
    if favored is None:
        return None  # senza arco da favorire un cambio di piano non ha senso
    return Alternative(
        alternative.type, alternative.department, node, label, {"favored_edge_key": favored}
    )


def _upstream_edges(
    alternative: Measure, node: str, label: str, lookup: TargetLookup
) -> Alternative | None:
    edges = list(dict.fromkeys(lookup.upstream_edges(node)))  # senza doppioni, nell'ordine dato
    if not edges:
        return None
    return Alternative(
        alternative.type, alternative.department, ",".join(edges), f"Archi a monte di {label}"
    )


def _routes_of_stop(
    alternative: Measure, stop_id: str, label: str, lookup: TargetLookup
) -> Alternative | None:
    routes = lookup.routes_serving(stop_id)
    if not routes:
        return None
    return Alternative(alternative.type, alternative.department, routes[0], f"Linea per {label}")


def adapt(
    original: TargetKind,
    alternative: Measure,
    target: str,
    label: str,
    lookup: TargetLookup,
) -> Alternative | None:
    """L'alternativa con il bersaglio adatto, o `None` se non è compatibile con quello di partenza.

    - incrocio → incrocio: lo stesso incrocio (il cambio di piano sceglie l'arco favorito);
    - incrocio → archi: gli archi a monte dell'incrocio con flusso dell'Evento;
    - linea → linea: la stessa linea (più corse al posto del prolungamento d'orario);
    - fermata → linea: la linea che serve la fermata.
    Qualunque altra coppia di tipi di bersaglio non è compatibile."""
    pair = (original, alternative.target_kind)
    if pair == ("intersection", "intersection"):
        if alternative.type == "signal_plan_change":
            return _signal_plan(alternative, target, label, lookup)
        return _same_target(alternative, target, label)
    if pair == ("intersection", "edges"):
        return _upstream_edges(alternative, target, label, lookup)
    if pair == ("route", "route"):
        return _same_target(alternative, target, label)
    if pair == ("stop", "route"):
        return _routes_of_stop(alternative, target, label, lookup)
    return None


def list_alternatives_for_measure(
    catalog: CatalogConfig,
    measure_type: str,
    target: str,
    target_label: str,
    lookup: TargetLookup,
) -> list[Alternative]:
    """Le alternative di `measure_type` **compatibili col suo bersaglio**, nell'ordine del catalogo.
    Dopo un rifiuto si prende la prima (e se anche quella è rifiutata, le alternative di quella)."""
    measure = catalog.measure(measure_type)
    if measure is None:
        raise UnknownMeasure(measure_type)
    found: list[Alternative] = []
    for alternative_type in measure.alternatives:
        alternative = catalog.measure(alternative_type)
        if (
            alternative is None
        ):  # il catalogo lo esclude (CatalogConfig), ma qui non si dà per scontato
            raise UnknownMeasure(alternative_type)
        candidate = adapt(measure.target_kind, alternative, target, target_label, lookup)
        if candidate is not None:
            found.append(candidate)
    return found
