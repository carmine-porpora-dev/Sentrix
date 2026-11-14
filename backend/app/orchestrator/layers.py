from collections.abc import Iterable, Mapping

from app.geo import geojson_point
from app.models.api import Feature, FeatureCollection
from app.models.base import WINDOWS, Window
from app.models.operations import OperationRequest
from app.models.provenance import Measured


def merge_windows(layers: Mapping[Window, FeatureCollection]) -> FeatureCollection:
    """Le feature delle finestre in un layer solo, nell'ordine arrivo → deflusso."""
    features: list[Feature] = []
    for window in WINDOWS:
        for feature in layers[window].features if window in layers else []:
            features.append(
                feature.model_copy(
                    update={
                        "id": None if feature.id is None else f"{window}:{feature.id}",
                        "properties": {**feature.properties, "window": window},
                    }
                )
            )
    return FeatureCollection(features=features)


def merge_by_name(
    per_window: Mapping[Window, Mapping[str, FeatureCollection]],
) -> dict[str, FeatureCollection]:
    """Per ogni nome di layer, l'unione delle finestre che lo hanno."""
    names = sorted({name for layers in per_window.values() for name in layers})
    return {
        name: merge_windows(
            {window: layers[name] for window, layers in per_window.items() if name in layers}
        )
        for name in names
    }


def requests_layer(requests: Iterable[OperationRequest]) -> FeatureCollection:
    """Le richieste che hanno una posizione (un avviso ai cittadini non ce l'ha)."""
    return FeatureCollection(
        features=[
            Feature(
                id=request.action_id,
                geometry=geojson_point(request.target_geo.lat, request.target_geo.lon),
                properties={
                    "action_id": request.action_id,
                    "type": request.type,
                    "department": request.department,
                    "state": request.state,
                    "window": request.window,
                    "target_label": request.target_label,
                    "iteration": request.iteration,
                },
            )
            for request in requests
            if request.target_geo is not None
        ]
    )


# --- provenienza dei numeri dei popup -----------------------------------------------------------

# Il popup di un arco, di una fermata o di una tratta mostra un numero (v/c, carico): ogni feature
# dichiara da quale `Measured` viene, in `evidence_id`. Quello del singolo elemento se gli strumenti
# degli agenti lo hanno derivato (gli archi più saturi, le fermate più cariche; per le tratte è il
# carico massimo della linea); altrimenti il `Measured` della finestra che documenta il modello da
# cui vengono tutti gli altri valori dello stesso layer (stesso metodo, stessi input e ipotesi).
EDGE_VC = "edge_vc"
STOP_LOAD = "stop_load"


def _ending(measures: Iterable[Measured], suffix: str) -> str | None:
    return next((m.id for m in measures if m.id.endswith(suffix)), None)


def annotate_evidence(
    window: Window, layers: Mapping[str, FeatureCollection], measures: Iterable[Measured]
) -> dict[str, FeatureCollection]:
    """I layer di una finestra con `evidence_id` in ogni feature di `edges_vc`, `stops` e
    `sections`. `measures` sono quelli della finestra e dell'iterazione, e devono includere i
    `Measured` di riferimento (`critical_edges.count`, `stops_overloaded`): senza, `KeyError`."""
    found = list(measures)
    road, transit = f".road.{window}.", f".transit.{window}."

    def derived(marker: str) -> dict[str, str]:
        """chiave dell'elemento → id del `Measured` derivato (`…<marker>.<chiave>`)."""
        return {m.id.split(marker, 1)[1]: m.id for m in found if marker in m.id}

    by_edge, by_stop = derived(f"{road}{EDGE_VC}."), derived(f"{transit}{STOP_LOAD}.")
    edge_default = _ending(found, f"{road}critical_edges.count")
    stop_default = _ending(found, f"{transit}stops_overloaded")
    if edge_default is None or stop_default is None:
        raise KeyError(f"mancano i Measured di riferimento della finestra {window}")

    def evidence(layer: str, feature: Feature) -> str:
        props = feature.properties
        if layer == "edges_vc":
            return by_edge.get(str(props.get("edge_key")), edge_default)
        if layer == "stops":
            return by_stop.get(str(props.get("stop_id")), stop_default)
        load = _ending(found, f"{transit}max_section_load.{props.get('route_class')}")
        return load or stop_default

    annotated = dict(layers)
    for name in ("edges_vc", "stops", "sections"):
        if name in layers:
            annotated[name] = FeatureCollection(
                features=[
                    f.model_copy(
                        update={"properties": {**f.properties, "evidence_id": evidence(name, f)}}
                    )
                    for f in layers[name].features
                ]
            )
    return annotated
