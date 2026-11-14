from collections.abc import Callable
from dataclasses import dataclass

from app.engine.run import RoadResult


def _ratio(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


@dataclass(frozen=True)
class EngineTargetLookup:
    """`road`: il risultato stradale della finestra della misura rifiutata. `routes_of_stop`: le
    linee che servono una fermata (`Engines.routes_serving`)."""

    road: RoadResult | None
    routes_of_stop: Callable[[str], list[str]]

    def upstream_edges(self, node: str) -> list[str]:
        """Le chiavi `u-v-k` degli archi entranti nell'incrocio con flusso dell'Evento sui cammini
        deviati, dal v/c più alto."""
        if self.road is None:
            return []
        layer = self.road.metrics.layers.get("edges_vc")
        entering = [
            (_ratio(f.properties.get("vc")), str(f.properties["edge_key"]))
            for f in (layer.features if layer else [])
            if f.properties.get("detour") and str(f.properties["edge_key"]).split("-")[1] == node
        ]
        return [key for _, key in sorted(entering, key=lambda item: (-item[0], item[1]))]

    def favored_edge_key(self, node: str) -> str | None:
        """L'arco entrante che raggiunge l'incrocio con il v/c più alto (04 6.1)."""
        if self.road is None:
            return None
        found = [i for i in self.road.metrics.critical_intersections if str(i.node) == node]
        return found[0].edge_key if found else None

    def routes_serving(self, stop_id: str) -> list[str]:
        return self.routes_of_stop(stop_id)
