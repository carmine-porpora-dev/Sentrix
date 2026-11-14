from collections.abc import Sequence
from datetime import datetime

from app.clock import now_rome
from app.data.gtfs import service_day
from app.engine.demand import Demand
from app.engine.result import EngineResult
from app.engine.transit import TransitNetwork
from app.engine.transit_loads import assign_transit
from app.engine.transit_measures import apply_transit_measures
from app.engine.transit_metrics import TransitMetrics, transit_metrics
from app.models.config import EngineConfig
from app.models.event import Event
from app.models.operations import OperationRequest


class TransitResult(EngineResult):
    """Il risultato del trasporto pubblico: `applied` sono le misure TPL applicate."""

    metrics: TransitMetrics


class TransitEngine:
    """La rete TPL (feed e itinerari risolti) e la configurazione."""

    def __init__(self, network: TransitNetwork, config: EngineConfig) -> None:
        self._network = network
        self._config = config

    def run(
        self,
        event: Event,
        demand: Demand,
        measures: Sequence[OperationRequest] = (),
        *,
        id_prefix: Sequence[str],
        as_of: datetime | None = None,
    ) -> TransitResult:
        """Carichi e metriche TPL della fascia di picco di `demand` (finestra e livello inclusi).

        `measures` sono le richieste dell'iterazione: `apply_transit_measures` ignora quelle di
        altre finestre e i tipi stradali, e rifiuta quelle non accettate. `id_prefix` apre gli id
        dei `Measured` e `as_of` è il loro istante (omesso = adesso).
        """
        as_of = as_of if as_of is not None else now_rome()
        network, config = self._network, self._config
        service = service_day(network.feed.service_dates, event.date)
        applied = apply_transit_measures(
            network,
            config.transit,
            service,
            demand.window,
            demand.band_start,
            demand.band_end,
            measures,
        )
        loads = assign_transit(
            network,
            config.transit,
            event,
            demand,
            config.time_slice_minutes,
            applied.suspended,
            applied.extra,
        )
        metrics = transit_metrics(
            network, loads, event, demand, measures=applied, id_prefix=id_prefix, as_of=as_of
        )
        return TransitResult(
            event_id=event.id,
            level=demand.level,
            window=demand.window,
            applied=applied.applied,
            metrics=metrics,
        )
