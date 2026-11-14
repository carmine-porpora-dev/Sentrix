import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from app.agents.tools import attendance_measured
from app.api.exports import CriticalEdge
from app.clock import ROME
from app.data.live_flow import summarize
from app.data.seeds import read_seed_events
from app.data.tomtom import congestion_class
from app.geo import circle_polygon
from app.models.agents import Finding, Recommendation
from app.models.api import (
    AgentSummary,
    Feature,
    FeatureCollection,
    IterationMetrics,
    LayerName,
    LiveFlowResponse,
    LiveMode,
    LiveSegmentFlow,
    MetricDelta,
    MetricsResponse,
    OperationEvent,
    RequestView,
    ResourceBalance,
    RunExport,
    RunView,
    StateTransition,
    VdeptRegistry,
)
from app.models.base import WINDOWS
from app.models.catalog import CatalogConfig
from app.models.config import EngineConfig
from app.models.departments import DepartmentsConfig
from app.models.emergency_services import EmergencyServicesConfig
from app.models.event import Event
from app.models.geo import GeoPoint
from app.models.live_config import LiveConfig
from app.models.live_segments import LiveSegmentsConfig
from app.models.notifications import Notification
from app.models.operations import Decision, OperationRequest
from app.models.provenance import Kind, Measured, make_measured, measured_id
from app.models.run import AttendanceLevel, PlanItem, Run
from app.notifications.bulletins import critical_intersections, saturated_streets
from app.notifications.templates import advisory_text, bulletin_text, mask_phone
from app.orchestrator.layers import requests_layer

LEVEL: AttendanceLevel = "mid"


def free_patrols(event: Event, window: str) -> int:
    resources = next(r for r in event.resources if r.window == window)
    return resources.municipal_police_patrols_total - resources.municipal_police_patrols_committed


def scene_event() -> Event:
    """L'evento della scena di rifiuto (04 7): quello in cui il deflusso lascia UNA sola pattuglia
    libera, così il primo presidio è accettato e il secondo no. Si sceglie dai dati, non dal nome:
    nessun codice conosce i preset (principio 4)."""
    candidates = [e for e in read_seed_events() if free_patrols(e, "departure") == 1]
    assert len(candidates) == 1, [e.id for e in candidates]
    return candidates[0]


T0 = datetime(2026, 11, 9, 10, 0, 0, tzinfo=ROME)  # il mock parte sempre da qui
SOURCE = "mock.fixture"
MOCK_NOTE = "Valore di esempio per il mock del frontend (F1-09): non è un risultato del motore"

# Secondi dall'inizio del run in cui nasce ogni cosa (stesso orologio per tutto il mock).
STATE_TIMELINE: tuple[tuple[float, str], ...] = (
    (0, "INTAKE"), (3, "ANALYZE"), (22, "RECONCILE"), (24, "PLAN"), (30, "DISPATCH"),
    (33, "AWAIT"), (40, "VERIFY"), (52, "REPLAN"), (56, "DISPATCH"), (58, "AWAIT"),
    (63, "VERIFY"), (76, "DONE"),
)  # fmt: skip
ITERATION_AT = {1: 40.0, 2: 63.0}  # a questi istanti `iteration` sale (VERIFY)
REPLAN_AT = 52.0
METRICS_AT = {0: 21.0, 1: 50.0, 2: 70.0}  # quando sono pronte le metriche di ogni iterazione
END = 76.0
# I fotogrammi del polling: uno per stato, più quelli in cui cambia qualcosa d'importante.
FRAME_TIMES: tuple[float, ...] = (
    1, 5, 15, 23, 27, 31, 34, 38, 45, 55.5, 57.2, 61, 68, 77,
)  # fmt: skip

CLOSED_STREET_NAME = "Viale Anton Dohrn; Via Francesco Caracciolo"  # il nome OSM degli archi chiusi

CRITICAL_INTERSECTIONS = {  # nodi OSM risolti sui dati acquisiti (resolve_seeds)
    "9137361046": ("Piazza Vittoria", 40.8353, 14.2449),
    "1798206520": ("Piazza Sannazaro", 40.8289, 14.2223),
}
LUNGOMARE = ((40.8320, 14.2268), (40.8317, 14.2406))  # innesto di viale Dohrn → Piazza Vittoria

# --- metriche di esempio (indice = iterazione 0, 1, 2) --------------------------------------------
VEH_HOURS = {"arrival": (3210, 3210, 3210), "departure": (4820, 4760, 4690)}
OD_TIME = {  # min, per coppia O/D; l'arrivo non cambia perché nessuna misura lo riguarda
    "departure": {
        "bagnoli_centrale": (41.2, 40.1, 38.8),
        "fuorigrotta_municipio": (35.6, 34.9, 33.4),
        "vomero_vittoria": (29.8, 29.1, 28.2),
        "posillipo_municipio": (48.3, 46.7, 44.9),
        "tangenziale_garibaldi": (37.1, 36.5, 35.9),
    },
    "arrival": {
        "bagnoli_centrale": (24.1,) * 3,
        "fuorigrotta_municipio": (21.8,) * 3,
        "vomero_vittoria": (18.9,) * 3,
        "posillipo_municipio": (33.5,) * 3,
        "tangenziale_garibaldi": (26.0,) * 3,
    },
}
DETOUR_KM = {"arrival": (2.1, 2.1, 2.1), "departure": (2.9, 2.9, 2.8)}
INTERSECTION_VC = {  # v/c dei due incroci critici, in ordine di rango
    "arrival": ((0.88, 0.81),) * 3,
    "departure": ((1.08, 0.97), (1.01, 0.97), (1.01, 0.91)),
}
# L'effetto locale delle misure stradali (02 7, `measure_effect`): il v/c massimo sull'incrocio che
# la misura tocca, prima → dopo l'iterazione in cui entra in vigore. Sono quelli dell'incrocio
# critico di INTERSECTION_VC (act_001: rango 1, Piazza Vittoria; act_004: rango 2, Piazza Sannazaro)
# tra l'iterazione precedente e quella in cui la misura entra: azione → (iterazione, indice).
MEASURE_EFFECT_AT = {"act_001": (1, 0), "act_004": (2, 1)}
ARRIVAL_CRITICAL_EDGES = (4, 2.1)  # (n, km): in arrivo non c'è un layer di archi
TRANSIT_L6_RUNS = {"arrival": (12, 12, 12), "departure": (0, 8, 8)}
TRANSIT_OVERLOADED_STOPS = {"arrival": (1, 1, 1), "departure": (3, 2, 2)}
TRANSIT_OVERLOADED_SECTIONS = {"arrival": (1, 1, 1), "departure": (2, 1, 1)}
# carico massimo (passeggeri/capacità) per classe di linea: la L1 è sempre la più carica (1,12, come nel
# layer `sections`); la L6 nel deflusso senza corse (0) finché la misura non ne aggiunge
TRANSIT_MAX_LOAD = {
    "metro_line_1": {"arrival": (1.12, 1.12, 1.12), "departure": (1.12, 1.12, 1.12)},
    "metro_line_6": {"arrival": (0.9, 0.8, 0.8), "departure": (0.0, 0.8, 0.8)},
    "funicular": {"arrival": (0.45, 0.45, 0.45), "departure": (0.5, 0.5, 0.5)},
}
STOP_CAPACITY_PAX_H = 5000.0  # capacità di esempio di una fermata e di una tratta (mock)
SECTION_TRIPS = 4
SECTION_CAPACITY_PAX_H = 5000.0

# Archi del layer `edges_vc` (solo finestra di deflusso): (id tratto LIVE, chiave arco, nome OSM,
# lunghezza m, v/c per iterazione). Chiavi, nomi e lunghezze dai commenti di live_segments.yaml;
# le geometrie sono SCHEMATICHE (segmenti est-ovest centrati sul punto del tratto).
EDGES: tuple[tuple[str, str, str, int, tuple[float, float, float]], ...] = (
    ("riviera_chiaia_2", "3465091789-3468033710-0", "Riviera di Chiaia", 440, (1.12, 1.05, 0.93)),
    ("riviera_chiaia_1", "8399521503-9137948052-0", "Riviera di Chiaia", 821, (0.98, 0.94, 0.88)),
    ("via_partenope", "3420000620-194087475-0", "Via Partenope; Via Nazario Sauro", 107, (0.74, 0.74, 0.72)),
    ("galleria_vittoria", "1242030781-3420057522-0", "Via Ferdinando Acton; Galleria della Vittoria", 671, (1.03, 0.99, 0.91)),
    ("via_acton", "3455594756-9055605241-0", "Via Ferdinando Acton", 584, (0.95, 0.93, 0.89)),
    ("corso_vittorio_emanuele_1", "11413409184-13414395318-0", "Corso Vittorio Emanuele", 818, (0.91, 0.88, 0.84)),
    ("corso_vittorio_emanuele_2", "1943835478-1289339058-0", "Corso Vittorio Emanuele", 637, (0.86, 0.86, 0.85)),
    ("galleria_laziale", "197555700-3550590945-0", "Galleria di Posillipo (Laziale); Via Fuorigrotta", 1132, (0.97, 0.96, 0.95)),
)  # fmt: skip
# Geometrie schematiche degli archi che i preset chiudono (chiavi = `edge_keys` dei seed): lunghezza
# e punti dai nodi risolti sui dati OSM acquisiti, a 4 decimali. Un arco chiuso senza geometria qui
# ferma la generazione: meglio un errore che una mappa che mente.
EDGE_GEOMETRY: dict[str, tuple[int, tuple[tuple[float, float], tuple[float, float]]]] = {
    "18122092-8475097329-0": (1180, LUNGOMARE),
    "8475097329-18122092-0": (1180, LUNGOMARE),
    "8399521491-8475097329-0": (33, ((40.8318, 14.2265), (40.8320, 14.2268))),
    "8475097329-8399521499-0": (32, ((40.8320, 14.2268), (40.8319, 14.2264))),
}

LIVE_FREE_FLOW = (27, 28, 29, 31, 45, 35, 32, 40, 38, 36, 80, 80, 80, 45)  # km/h
LIVE_RATIO = (0.55, 0.95, 0.90, 0.97, 1.0, 0.92, 0.88, 0.70, 0.96, 0.98, 1.0, 0.99, 1.0, 0.85)


def it_int(value: int) -> str:
    """Intero all'italiana per i testi: punto come separatore delle migliaia."""
    return f"{value:,}".replace(",", ".")


def it_number(value: float, digits: int = 1) -> str:
    """Numero all'italiana per i testi: virgola decimale."""
    return f"{value:.{digits}f}".replace(".", ",")


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _geometry_line(coords: Iterable[tuple[float, float]]) -> dict[str, Any]:
    """LineString GeoJSON da punti (lat, lon): GeoJSON vuole (lon, lat)."""
    return {
        "type": "LineString",
        "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in coords],
    }


def _geometry_point(lat: float, lon: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}


def _east_west(lat: float, lon: float, length_m: float) -> list[tuple[float, float]]:
    """Un segmento est-ovest lungo `length_m` centrato sul punto (geometria schematica)."""
    half = (length_m / 2) / (111_195 * math.cos(math.radians(lat)))
    return [(lat, lon - half), (lat, lon + half)]


@dataclass(frozen=True)
class PlanStep:
    """Un elemento del piano com'è a partire da `t` (uno stato dopo l'altro)."""

    t: float
    status: str
    action_id: str | None = None
    replaced_by: int | None = None
    note: str | None = None


class World:
    """Tutto ciò che il mock sa del run, costruito una volta e interrogato per istante."""

    def __init__(self) -> None:
        self.event: Event = scene_event()
        self.run_id = f"run_mock_{self.event.id}"
        self.engine = EngineConfig.from_yaml()
        self.catalog = CatalogConfig.from_yaml()
        self.departments = DepartmentsConfig.from_yaml()
        self.live = LiveSegmentsConfig.from_yaml()
        self.live_config = LiveConfig.from_yaml()
        self._check_sources()
        e = self.event
        self.departure_window = f"{e.departure.start:%H:%M}–{e.departure.end:%H:%M}"
        self.peak = f"{e.departure.peak:%H:%M}"
        self.closed_edges = [(k, *EDGE_GEOMETRY[k]) for k in sorted(self._closed_keys())]
        police = next(r for r in e.resources if r.window == "departure")
        self.police_total = police.municipal_police_patrols_total
        self.police_busy = police.municipal_police_patrols_committed + 1  # + il primo presidio
        self.recommendations = self._recommendations()
        self.plan_steps = self._plan_steps()
        self.requests = self._requests()
        self.request_events = self._request_events()
        self.findings = self._findings()
        self.decision_specs = self._decision_specs()
        self._all_metrics = {it: self._build_metrics(it) for it in (0, 1, 2)}

    # --- controlli sui dati veri ----------------------------------------------------------------

    def _closed_keys(self) -> set[str]:
        return {key for closure in self.event.closures for key in closure.edge_keys}

    def _check_sources(self) -> None:
        pairs = {pair.id for pair in self.engine.demand.od_pairs}
        assert pairs == set(OD_TIME["departure"]) == set(OD_TIME["arrival"]), pairs
        missing = self._closed_keys() - set(EDGE_GEOMETRY)
        assert not missing, f"manca la geometria schematica degli archi chiusi: {sorted(missing)}"
        live_ids = {s.id for s in self.live.segments}
        assert len(LIVE_FREE_FLOW) == len(LIVE_RATIO) == len(live_ids), (
            "un valore per ogni tratto LIVE"
        )
        assert {edge[0] for edge in EDGES} <= live_ids, "tratti LIVE cambiati"

    # --- metriche -------------------------------------------------------------------------------

    def _measured(
        self,
        it: int,
        parts: tuple[str, ...],
        value: float | int,
        unit: str,
        kind: Kind,
        method: str,
    ) -> Measured:
        source = SOURCE if kind != "real" else f"{SOURCE} (gtfs.anm)"
        return make_measured(
            id=measured_id(self.run_id, f"it{it}", *parts),
            value=value,
            unit=unit,
            kind=kind,
            source=source,
            method=f"{method} (valore di esempio)",
            inputs=[f"event {self.event.id} rev {self.event.revision}", "fixture F1-09"],
            assumptions=[MOCK_NOTE],
            as_of=at(METRICS_AT[it]),
        )

    def mid(self, it: int, *parts: str) -> str:
        """L'id di una metrica dell'iterazione `it` (come lo citano le evidenze)."""
        return measured_id(self.run_id, f"it{it}", *parts)

    def critical_edges(self, it: int) -> list[tuple[str, str, int, float]]:
        """Gli archi del layer con v/c oltre la soglia critica: (chiave, nome, lunghezza, v/c)."""
        threshold = self.engine.metrics.vc_critical_threshold
        return [(k, n, length, vc[it]) for _, k, n, length, vc in EDGES if vc[it] > threshold]

    def _build_metrics(self, it: int) -> list[Measured]:
        # come il backend vero: l'affluenza dell'Evento è tra le metriche dell'iterazione 0
        out: list[Measured] = (
            [attendance_measured(self.event, LEVEL, self.run_id)] if it == 0 else []
        )
        for window in WINDOWS:
            base = ("road", window)
            out.append(self._measured(it, (*base, "veh_hours"), VEH_HOURS[window][it], "veic·h",
                                      "simulated", "somma sugli archi di v × t"))  # fmt: skip
            times = []
            for pair, series in OD_TIME[window].items():
                times.append(series[it])
                out.append(self._measured(it, (*base, "od_time", pair), series[it], "min",
                                          "simulated", "cammino minimo sui costi finali"))  # fmt: skip
            out.append(self._measured(it, (*base, "od_time", "mean"), round(mean(times), 1), "min",
                                      "simulated", "media semplice delle 5 coppie O/D"))  # fmt: skip
            if window == "departure":
                critical = self.critical_edges(it)
                count, km = len(critical), round(sum(c[2] for c in critical) / 1000, 1)
            else:
                count, km = ARRIVAL_CRITICAL_EDGES
            out.append(self._measured(it, (*base, "critical_edges", "count"), count, "n",
                                      "simulated", "archi con v/c oltre la soglia critica"))  # fmt: skip
            out.append(self._measured(it, (*base, "critical_edges", "km"), km, "km",
                                      "simulated", "lunghezza degli archi critici"))  # fmt: skip
            out.append(self._measured(it, (*base, "detour_extra_km"), DETOUR_KM[window][it], "km",
                                      "simulated", "lunghezza media delle deviazioni"))  # fmt: skip
            out.append(self._measured(it, (*base, "unassigned_pairs"), 0, "n",
                                      "simulated", "coppie O/D senza percorso"))  # fmt: skip
            for rank, vc in enumerate(INTERSECTION_VC[window][it], start=1):
                out.append(self._measured(it, (*base, "critical_intersection", str(rank), "vc"), vc,
                                          "rapporto", "simulated", "massimo v/c degli archi entranti"))  # fmt: skip
            tpl = ("transit", window)
            runs_kind: Kind = "real" if (window == "arrival" or it == 0) else "simulated"
            out.append(self._measured(it, (*tpl, "trips_in_window", "metro_line_6"), TRANSIT_L6_RUNS[window][it],
                                      "n", runs_kind, "corse della Linea 6 nella fascia di picco"))  # fmt: skip
            out.append(self._measured(it, (*tpl, "stops_overloaded"),
                                      TRANSIT_OVERLOADED_STOPS[window][it], "n", "estimate",
                                      "fermate vicine all'area con passeggeri/capacità > 1"))  # fmt: skip
            out.append(self._measured(it, (*tpl, "sections_overloaded"),
                                      TRANSIT_OVERLOADED_SECTIONS[window][it], "n", "estimate",
                                      "tratte di metro e funicolare con passeggeri/capacità > 1"))  # fmt: skip
            for kind, by_window in TRANSIT_MAX_LOAD.items():
                out.append(self._measured(it, (*tpl, "max_section_load", kind), by_window[window][it],
                                          "rapporto", "estimate",
                                          f"massimo di passeggeri/capacità tra le tratte di {kind}"))  # fmt: skip
        for action_id, (when, rank_index) in MEASURE_EFFECT_AT.items():
            if when != it:
                continue
            request = self.requests[action_id]
            vcs = INTERSECTION_VC[request.window]
            for part, value in (
                ("vc_before", vcs[it - 1][rank_index]),
                ("vc_after", vcs[it][rank_index]),
            ):
                out.append(
                    self._measured(it, ("road", request.window, "measure_effect", action_id, part),
                                   value, "rapporto", "simulated",
                                   "massimo v/c sugli archi toccati dalla misura"))  # fmt: skip
        return out

    def metrics(self, it: int) -> list[Measured]:
        return list(self._all_metrics[it])

    def metrics_response(self, it: int) -> MetricsResponse:
        deltas: list[MetricDelta] = []
        if it > 0:
            previous = {m.id.split(f"it{it - 1}.", 1)[1]: m for m in self._all_metrics[it - 1]}
            baseline = {m.id.split("it0.", 1)[1]: m for m in self._all_metrics[0]}
            for metric in self._all_metrics[it]:
                tail = metric.id.split(f"it{it}.", 1)[1]
                then, base = previous.get(tail), baseline.get(tail)
                if then is None and base is None:
                    continue  # una metrica nuova (l'effetto di una misura): niente da confrontare
                deltas.append(
                    MetricDelta(
                        metric_id=metric.id,
                        vs_previous=self._delta(it, "previous", tail, metric, then)
                        if then
                        else None,
                        vs_baseline=self._delta(it, "baseline", tail, metric, base)
                        if base
                        else None,
                    )
                )
        return MetricsResponse(
            run_id=self.run_id, iteration=it, metrics=self.metrics(it), deltas=deltas
        )

    def _delta(self, it: int, kind: str, tail: str, now: Measured, then: Measured) -> Measured:
        assert isinstance(now.value, int | float) and isinstance(then.value, int | float)
        merged: Kind = now.kind if now.kind == then.kind else "estimate"
        return make_measured(
            id=measured_id(self.run_id, f"it{it}", f"delta_{kind}", *tail.split(".")),
            value=round(now.value - then.value, 2),
            unit=now.unit,
            kind=merged,
            source=SOURCE,
            method=f"differenza con l'iterazione {it - 1 if kind == 'previous' else 0} (valore di esempio)",
            inputs=[now.id, then.id],
            assumptions=[MOCK_NOTE],
            as_of=now.as_of,
        )

    # --- piano, richieste, finding --------------------------------------------------------------

    def _recommendations(self) -> dict[int, Recommendation]:
        def crit(it: int, rank: int) -> str:
            return self.mid(it, "road", "departure", "critical_intersection", str(rank), "vc")

        def rec(
            measure: str, target: str, why: str, evidence: list[str], **params: Any
        ) -> Recommendation:
            department = self.catalog.measure(measure)
            assert department is not None, measure
            return Recommendation(
                measure_type=measure, target=target, department=department.department,
                window="departure", params=params, rationale=why, evidence_ids=evidence,
            )  # fmt: skip

        v1 = it_number(INTERSECTION_VC["departure"][0][0], 2)
        v2 = it_number(INTERSECTION_VC["departure"][0][1], 2)
        return {
            1: rec("traffic_post", "9137361046", f"Presidio a Piazza Vittoria: v/c {v1} sulla deviazione in deflusso.", [crit(0, 1)]),
            2: rec("traffic_post", "1798206520", f"Presidio a Piazza Sannazaro: v/c {v2} sulla deviazione in deflusso.", [crit(0, 2)]),
            3: rec("extend_hours", "2302", "La Linea 6 non ha corse nella finestra di deflusso: servizio da prolungare.",
                   [self.mid(0, "transit", "departure", "trips_in_window", "metro_line_6")], until="01:30"),
            4: rec("signal_plan_change", "1798206520", "Alternativa al presidio rifiutato: variazione del piano semaforico allo stesso incrocio.", [crit(1, 2)]),
            5: rec("citizen_notice", "cittadinanza", "Avviso sulle chiusure e sui servizi prolungati, dopo le misure accettate.",
                   [self.mid(2, "road", "departure", "veh_hours")]),
            6: rec("detour_signage", "18122092-8475097329-0", "Deviazione indicata su un arco che il dispositivo chiude.",
                   [self.mid(0, "road", "departure", "critical_edges", "count")]),
        }  # fmt: skip

    def _plan_steps(self) -> dict[int, tuple[PlanStep, ...]]:
        discarded = (
            "R2: la stessa via risulta chiusa dal dispositivo e proposta come deviazione: "
            "scartata la deviazione"
        )
        return {
            1: (PlanStep(29, "proposed"), PlanStep(36, "accepted", "act_001")),
            2: (PlanStep(29, "proposed"), PlanStep(36, "rejected", "act_002"),
                PlanStep(55, "replaced", "act_002", replaced_by=4)),
            3: (PlanStep(29, "proposed"), PlanStep(37, "accepted", "act_003")),
            4: (PlanStep(55, "proposed"), PlanStep(60, "accepted", "act_004")),
            5: (PlanStep(29, "proposed"), PlanStep(74, "accepted", "act_005")),
            6: (PlanStep(29, "discarded", note=discarded),),
        }  # fmt: skip

    def _requests(self) -> dict[str, OperationRequest]:
        reasons = {
            "act_002": ("UNAVAILABLE",
                        f"Pattuglie esaurite nella finestra {self.departure_window}: {self.police_total} totali, {self.police_busy} già impegnate ai varchi"),
        }  # fmt: skip

        def request(
            action: str,
            seq: int,
            iteration: int,
            state: str,
            label: str,
            geo: tuple[float, float] | None,
            priority: str = "high",
            **extra: Any,
        ) -> OperationRequest:
            rec = self.recommendations[seq]
            code, reason = reasons.get(action, (None, None))
            return OperationRequest.model_validate({
                "action_id": action, "run_id": self.run_id, "iteration": iteration,
                "department": rec.department, "type": rec.measure_type, "target": rec.target,
                "target_label": label,
                "target_geo": {"lat": geo[0], "lon": geo[1], "label": label} if geo else None,
                "window": rec.window, "priority": priority,
                "payload": rec.params, "state": state,
                "reject_code": code, "reject_reason": reason, "simulation": True, **extra,
            })  # fmt: skip

        closures = "; ".join(c.label for c in self.event.closures)
        notice = {
            "text": f"Chiusure dalle {self.event.arrival.start:%H:%M}: {closures}. "
            "Linea 6 prolungata fino all'1:30."
        }
        return {
            "act_001": request("act_001", 1, 1, "IN_PROGRESS", "Incrocio Piazza Vittoria", (40.8353, 14.2449)),
            "act_002": request("act_002", 2, 1, "REJECTED", "Incrocio Piazza Sannazaro", (40.8289, 14.2223)),
            "act_003": request("act_003", 3, 1, "ACCEPTED", "Linea 6", None, "normal"),
            "act_004": request("act_004", 4, 2, "ACCEPTED", "Incrocio Piazza Sannazaro", (40.8289, 14.2223),
                               alternative_of="act_002"),
            "act_005": request("act_005", 5, 2, "COMPLETED", "Avviso ai cittadini", None, "low")
                       .model_copy(update={"payload": notice}),
        }  # fmt: skip

    def _request_events(self) -> dict[str, tuple[tuple[float, str | None, str, str | None], ...]]:
        """Per richiesta: (istante, da, a, motivo). Il motivo del rifiuto è quello della richiesta."""
        sent = "inviata al dipartimento (simulazione)"

        def life(
            t0: float, final: tuple[tuple[float, str, str, str | None], ...]
        ) -> tuple[Any, ...]:
            return (
                (t0, None, "CREATED", None),
                (t0 + 1, "CREATED", "SENT", sent),
                (t0 + 2, "SENT", "RECEIVED", None),
                *((t, a, b, why) for t, a, b, why in final),
            )

        return {
            "act_001": life(30, ((36, "RECEIVED", "ACCEPTED", "Pattuglia disponibile"),
                                 (37, "ACCEPTED", "IN_PROGRESS", None))),
            "act_002": life(30, ((36, "RECEIVED", "REJECTED", self.requests["act_002"].reject_reason),)),
            "act_003": life(30, ((37, "RECEIVED", "ACCEPTED", "Prolungamento orario disponibile"),)),
            "act_004": life(56, ((60, "RECEIVED", "ACCEPTED", "Variazione semaforica consentita"),)),
            "act_005": life(71, ((74, "RECEIVED", "ACCEPTED", "Testo coerente con le misure accettate"),
                                 (75, "ACCEPTED", "COMPLETED", None))),
        }  # fmt: skip

    def _findings(self) -> dict[str, list[Finding]]:
        def crit(rank: int) -> str:
            return self.mid(0, "road", "departure", "critical_intersection", str(rank), "vc")

        vc1, vc2 = INTERSECTION_VC["departure"][0]
        n_edges = len(self.critical_edges(0))
        km = round(sum(e[2] for e in self.critical_edges(0)) / 1000, 1)
        return {
            "traffic": [
                Finding(summary=f"Piazza Vittoria: l'incrocio più carico sulla deviazione in deflusso (v/c {it_number(vc1, 2)}).",
                        severity="critical", window="departure", trigger="critical_intersection",
                        target="9137361046", evidence_ids=[crit(1)], location=GeoPoint(lat=40.8353, lon=14.2449)),
                Finding(summary=f"Piazza Sannazaro: secondo incrocio critico (v/c {it_number(vc2, 2)}).",
                        severity="warning", window="departure", trigger="critical_intersection",
                        target="1798206520", evidence_ids=[crit(2)], location=GeoPoint(lat=40.8289, lon=14.2223)),
                Finding(summary=f"Riviera di Chiaia: {n_edges} archi con v/c oltre 0,9 ({it_number(km)} km) sul percorso alternativo.",
                        severity="warning", window="departure", trigger="saturated_path",
                        target="3465091789-3468033710-0",
                        evidence_ids=[self.mid(0, "road", "departure", "critical_edges", "count"),
                                      self.mid(0, "road", "departure", "critical_edges", "km")]),
            ],
            "transit": [
                Finding(summary="La Linea 6 non ha corse nella finestra di deflusso: nessun servizio.",
                        severity="warning", window="departure", trigger="line_no_service_in_window",
                        target="2302", evidence_ids=[self.mid(0, "transit", "departure", "trips_in_window", "metro_line_6")]),
                Finding(summary="Due tratte della rete risultano sovraccariche nel deflusso (stima).",
                        severity="info", window="departure", trigger="section_overloaded",
                        target="4955", evidence_ids=[self.mid(0, "transit", "departure", "sections_overloaded")]),
            ],
        }  # fmt: skip

    # --- decisioni ------------------------------------------------------------------------------

    def _decision_specs(self) -> list[tuple[float, str, str, str, list[str]]]:
        e = self.event
        stops = ", ".join(s for d in e.transit_disruptions for s in d.stop_ids) or "nessuna"
        crit1 = self.mid(0, "road", "departure", "critical_intersection", "1", "vc")
        crit2 = self.mid(0, "road", "departure", "critical_intersection", "2", "vc")
        l6 = self.mid(0, "transit", "departure", "trips_in_window", "metro_line_6")
        veh = lambda it: self.mid(it, "road", "departure", "veh_hours")  # noqa: E731
        return [
            (0.0, "system", "Analisi avviata", f"Evento {e.id}, revisione {e.revision}, livello di affluenza {LEVEL}, risposta manuale disattivata", []),
            (0.5, "orchestrator", "INTAKE → ANALYZE", f"Evento valido; {len(e.closures)} chiusure risolte ({len(self.closed_edges)} archi) e {len(e.transit_disruptions)} interruzioni del trasporto pubblico (fermate {stops})", []),
            (8.0, "event_demand", "Domanda stimata", f"{it_int(e.attendance.mid)} presenti nel livello {LEVEL}; picco di deflusso alle {self.peak}", []),
            (17.0, "transit", "Criticità del trasporto pubblico", f"Linea 6 senza corse nella finestra {self.departure_window}; 2 tratte sovraccariche (stima)", [l6]),
            (20.0, "traffic", "Criticità stradali individuate", "2 incroci critici sulla deviazione in deflusso", [crit1, crit2]),
            (22.0, "orchestrator", "ANALYZE → RECONCILE", "Agenti completati; Transit con testo di riserva", []),
            (22.5, "orchestrator", "RECONCILE: deviazione scartata", "R2: la deviazione su un arco chiuso dal dispositivo non ha senso", ["18122092-8475097329-0"]),
            (24.0, "orchestrator", "RECONCILE → PLAN", "Nessun altro conflitto tra le raccomandazioni", []),
            (29.0, "operations", "Piano proposto", "5 misure dal catalogo, una scartata in RECONCILE", [crit1, crit2, l6]),
            (30.0, "orchestrator", "PLAN → DISPATCH", "Piano pronto", []),
            (31.0, "orchestrator", "Richieste inviate (simulate)", "3 richieste: presidio ×2 e prolungamento della Linea 6", ["act_001", "act_002", "act_003"]),
            (33.0, "orchestrator", "DISPATCH → AWAIT", "In attesa degli esiti (tempo massimo 10 s)", []),
            (36.0, "municipal_police", "Richiesta act_001 accettata", "Pattuglia disponibile", ["act_001"]),
            (36.0, "municipal_police", "Richiesta act_002 rifiutata (UNAVAILABLE)", f"Pattuglie esaurite nella finestra {self.departure_window}", ["act_002"]),
            (37.0, "transport_control", "Richiesta act_003 accettata", "Prolungamento orario disponibile", ["act_003"]),
            (40.0, "orchestrator", "AWAIT → VERIFY", "Esiti ricevuti: 2 accettate, 1 rifiutata", []),
            (50.0, "orchestrator", "Iterazione 1 calcolata", "Metriche e livelli salvati per le finestre toccate dalle misure", [veh(1)]),
            (52.0, "orchestrator", "VERIFY → REPLAN", "1 rifiuto nell'ultimo round; ripianificazione 1 di 3", []),
            (55.0, "operations", "Alternativa scelta per act_002", "signal_plan_change allo stesso incrocio (prima alternativa del catalogo)", ["act_002"]),
            (56.0, "orchestrator", "REPLAN → DISPATCH", "Una richiesta alternativa", []),
            (57.0, "orchestrator", "Richiesta act_004 inviata (simulata)", "Alternativa di act_002", ["act_004"]),
            (58.0, "orchestrator", "DISPATCH → AWAIT", "In attesa dell'esito", []),
            (60.0, "traffic_control", "Richiesta act_004 accettata", "Variazione semaforica consentita (0 su 3 usate)", ["act_004"]),
            (63.0, "orchestrator", "AWAIT → VERIFY", "Nessun rifiuto nel round", []),
            (70.0, "orchestrator", "Iterazione 2 calcolata", "Confronto con l'iterazione 1 e con quella senza misure", [veh(2), veh(1), veh(0)]),
            (71.0, "orchestrator", "Avviso ai cittadini inviato", "Testo che cita solo misure accettate", ["act_005"]),
            (74.0, "public_comms", "Richiesta act_005 accettata", "Testo coerente con le misure accettate", ["act_005"]),
            (76.0, "orchestrator", "DONE", "Piano finale: 4 accettate, 1 sostituita, 1 scartata", []),
        ]  # fmt: skip

    def decisions(self, t: float) -> list[Decision]:
        visible = [s for s in self.decision_specs if s[0] <= t]
        return [
            Decision(run_id=self.run_id, seq=index, at=at(when), actor=actor, decision=what,
                     rationale=why, refs=refs)
            for index, (when, actor, what, why, refs) in enumerate(visible, start=1)
        ]  # fmt: skip

    def notifications(self) -> list[Notification]:
        """Le comunicazioni a fine run, come le mostra il mock: il WhatsApp inviato (spech 12.4,
        numero di esempio mascherato) e un bollettino ai servizi di emergenza (12.3) per
        destinatario, consegnato. I testi sono quelli veri dei template; strade sature e incroci
        sono quelli dei layer di esempio dell'ultima iterazione."""
        notice = self.requests["act_005"].payload.get("text")
        closing = [c.label for c in self.event.closures if c.mode == "closed"]
        transit = [d.label for d in self.event.transit_disruptions]
        rows = [
            Notification(
                id=1, run_id=self.run_id, iteration=2, channel="whatsapp",
                recipient_id="whatsapp_to", recipient_label=mask_phone("+390000000012"),
                kind="traffic_advisory",
                text=advisory_text(
                    event_name=self.event.name, event_date=self.event.date, closed_roads=closing,
                    transit_disruptions=transit,
                    notice=notice if isinstance(notice, str) else None,
                ),
                evidence_ids=["act_005"], state="SENT", provider_message_id=None,
                error_code=None, simulation=False, created_at=at(END + 2),
            )
        ]  # fmt: skip
        config = EmergencyServicesConfig.from_yaml()
        saturated = saturated_streets(
            self.layer("edges_vc", 2), self.engine.metrics.vc_critical_threshold
        )
        critical = critical_intersections(self.layer("critical_intersections", 2))
        spans = {w: self.event.window_span(w) for w in WINDOWS}
        evidence = list(dict.fromkeys(e for _, ids in (*saturated, *critical) for e in ids))
        for index, service in enumerate(config.services, start=2):
            rows.append(
                Notification(
                    id=index,
                    run_id=self.run_id,
                    iteration=2,
                    channel="emergency_bulletin",
                    recipient_id=service.id,
                    recipient_label=service.name,
                    kind="traffic_bulletin",
                    text=bulletin_text(
                        recipient=service.name,
                        event_name=self.event.name,
                        event_date=self.event.date,
                        spans=spans,
                        closed_roads=closing,
                        saturated=[item for item, _ in saturated],
                        critical_intersections=[item for item, _ in critical],
                        transit_disruptions=transit,
                        saturation_threshold=self.engine.metrics.vc_critical_threshold,
                        limit=config.max_listed,
                    ),
                    evidence_ids=evidence,
                    state="DELIVERED",
                    provider_message_id=None,
                    error_code=None,
                    simulation=True,
                    created_at=at(END + 1),
                )
            )
        return rows

    # --- il run in un istante -------------------------------------------------------------------

    def _state(self, t: float) -> str:
        return [state for start, state in STATE_TIMELINE if start <= t][-1]

    def run(self, t: float = END + 1) -> Run:
        state = self._state(t)
        iteration = sum(1 for when in ITERATION_AT.values() if when <= t)
        done = state == "DONE"
        return Run(
            id=self.run_id, event_id=self.event.id, event_revision=self.event.revision,
            attendance_level=LEVEL, state=state, iteration=iteration,
            replans=1 if t >= REPLAN_AT else 0, started_at=at(0), ended_at=at(END) if done else None,
            params_hash=hashlib.sha256(b"fixture F1-09: parametri di esempio").hexdigest(),
            seed=self.engine.seed, llm_mode="cache_only", error=None,
        )  # fmt: skip

    def _agent(self, name: str, t: float) -> AgentSummary:
        intervals = {"event_demand": [(3, 8)], "traffic": [(8, 20)], "transit": [(8, 17)],
                     "operations": [(24, 29), (52, 55)]}[name]  # fmt: skip
        tools = {
            "event_demand": ["create_event_context", "build_demand"],
            "traffic": ["apply_closures", "assign_traffic", "find_congested_edges",
                        "find_critical_intersections", "od_times"],
            "transit": ["get_stops_near", "get_trips_in_window", "estimate_loads",
                        "find_alternative_connections"],
            "operations": ["list_catalog", "list_alternatives_for_measure", "get_request_status",
                           "get_department_resources"],
        }[name]  # fmt: skip
        started = [a for a, _ in intervals if a <= t]
        if not started:
            return AgentSummary(agent=name, state="waiting")
        running = any(a <= t < b for a, b in intervals)
        if running:
            return AgentSummary(
                agent=name, state="running", tools_called=tools[: max(1, len(tools) // 2)]
            )
        text, origin = self._agent_text(name, t)
        fallback = name == "transit"
        return AgentSummary(
            agent=name, state="done_fallback" if fallback else "done",
            tools_called=tools, text=text, text_origin=origin,
            findings=self.findings.get(name, []),
        )  # fmt: skip

    def _agent_text(self, name: str, t: float) -> tuple[str, str]:
        vc1, vc2 = INTERSECTION_VC["departure"][0]
        critical = self.critical_edges(0)
        km = it_number(sum(e[2] for e in critical) / 1000)
        if name == "event_demand":
            return (f"{self.event.name}: {it_int(self.event.attendance.mid)} presenti (livello {LEVEL}) e picco di deflusso alle {self.peak}. "
                    f"Le {len(self.event.closures)} chiusure spostano il traffico sul percorso alternativo.", "llm_cache")  # fmt: skip
        if name == "traffic":
            return (f"Con le chiusure il deflusso carica la Riviera di Chiaia: {len(critical)} archi con v/c oltre 0,9 ({km} km). "
                    f"Incroci critici: Piazza Vittoria (v/c {it_number(vc1, 2)}) e Piazza Sannazaro ({it_number(vc2, 2)}).", "llm_cache")  # fmt: skip
        if name == "transit":
            return ("Linea 6: nessuna corsa nella finestra di deflusso (dato GTFS). Due tratte e tre fermate risultano sovraccariche nel deflusso (stime).", "template")  # fmt: skip
        if t >= 55:
            return ("Piano rivisto: il secondo presidio è stato rifiutato (pattuglie esaurite), quindi si propone la variazione "
                    "del piano semaforico a Piazza Sannazaro.", "llm_cache")  # fmt: skip
        return ("Piano: due presidi della polizia municipale, il prolungamento orario della Linea 6 e un avviso ai cittadini; "
                "scartata una deviazione su un arco chiuso.", "llm_cache")  # fmt: skip

    def plan(self, t: float) -> list[PlanItem]:
        items = []
        for seq, steps in self.plan_steps.items():
            current = [s for s in steps if s.t <= t]
            if not current:
                continue
            step = current[-1]
            items.append(PlanItem(seq=seq, recommendation=self.recommendations[seq],
                                  status=step.status,
                                  action_id=step.action_id, replaced_by=step.replaced_by,
                                  note=step.note))  # fmt: skip
        return items

    def request_view(self, action_id: str, t: float = END + 1) -> RequestView | None:
        events = [e for e in self.request_events[action_id] if e[0] <= t]
        if not events:
            return None
        state = events[-1][2]
        base = self.requests[action_id]
        # il motivo del rifiuto esiste solo da quando la richiesta è stata rifiutata
        rejected = {} if state == "REJECTED" else {"reject_code": None, "reject_reason": None}
        request = base.model_copy(update={"state": state, **rejected})
        # gli id delle transizioni crescono nell'ordine in cui accadono, su tutte le richieste
        order = sorted(
            (e[0], a, i) for a, evs in self.request_events.items() for i, e in enumerate(evs)
        )
        ids = {(a, i): n for n, (_, a, i) in enumerate(order, start=1)}
        return RequestView(
            request=request,
            events=[OperationEvent(id=ids[(action_id, i)], action_id=action_id, from_state=src,
                                   to_state=dst, reason=why, at=at(when))
                    for i, (when, src, dst, why) in enumerate(self.request_events[action_id])
                    if when <= t],
        )  # fmt: skip

    def run_view(self, t: float) -> RunView:
        run = self.run(t)
        reached = [(start, state) for start, state in STATE_TIMELINE if start <= t]
        views = [v for a in self.requests if (v := self.request_view(a, t)) is not None]
        return RunView(
            run=run,
            timeline=[StateTransition(state=s, at=at(w)) for w, s in reached],
            agents=[self._agent(a, t) for a in ("event_demand", "traffic", "transit", "operations")],
            plan=self.plan(t), requests=views, degraded=[],
        )  # fmt: skip

    # --- layer ----------------------------------------------------------------------------------

    def _vc_class(self, vc: float) -> int:
        return sum(1 for limit in self.engine.metrics.vc_classes if vc >= limit)

    def layer(self, name: LayerName, it: int) -> FeatureCollection:
        features: list[Feature] = []
        live = {s.id: s for s in self.live.segments}
        if name == "edges_vc":
            for segment, key, street, length, series in EDGES:
                point = live[segment]
                features.append(Feature(id=key, geometry=_geometry_line(_east_west(point.lat, point.lon, length)),
                    properties={"edge_key": key, "name": street, "length_m": length, "vc": series[it],
                                "vc_class": self._vc_class(series[it]), "closed": False,
                                "detour": True, "window": "departure", "schematic": True}))  # fmt: skip
            for key, length, coords in self.closed_edges:
                features.append(Feature(id=key, geometry=_geometry_line(coords),
                    properties={"edge_key": key, "name": CLOSED_STREET_NAME,
                                "length_m": length, "vc": 0.0, "vc_class": 0, "closed": True,
                                "detour": False, "window": "departure", "schematic": True}))  # fmt: skip
        elif name == "closures":
            labels = {k: c.label for c in self.event.closures for k in c.edge_keys}
            for key, length, coords in self.closed_edges:
                features.append(Feature(id=key, geometry=_geometry_line(coords),
                    properties={"edge_key": key, "label": labels[key], "length_m": length, "mode": "closed"}))  # fmt: skip
        elif name == "critical_intersections":
            for rank, (node, (label, lat, lon)) in enumerate(
                CRITICAL_INTERSECTIONS.items(), start=1
            ):
                vc = INTERSECTION_VC["departure"][it][rank - 1]
                features.append(Feature(id=node, geometry=_geometry_point(lat, lon),
                    properties={"node": node, "label": label, "rank": rank, "vc": vc, "window": "departure",
                                "evidence_id": self.mid(it, "road", "departure", "critical_intersection", str(rank), "vc")}))  # fmt: skip
        elif name == "stops":
            for number, (lat, lon, load) in enumerate(
                (
                    (40.8340, 14.2330, 1.15),
                    (40.8310, 14.2300, 0.80),
                    (40.8360, 14.2380, 1.05),
                    (40.8290, 14.2260, 0.55),
                ),
                start=1,
            ):
                load_now = round(load - (0.1 if it >= 1 and number == 1 else 0), 2)
                features.append(Feature(id=f"mock_stop_{number}", geometry=_geometry_point(lat, lon),
                    properties={"stop_id": f"mock_stop_{number}", "name": f"Fermata di esempio {number}",
                                "load_ratio": load_now, "overloaded": load_now > 1.0, "closed": False,
                                "pax_h": round(load_now * STOP_CAPACITY_PAX_H, 1),
                                "capacity_pax_h": STOP_CAPACITY_PAX_H, "schematic": True}))  # fmt: skip
        elif name == "sections":
            for route, route_class, label, coords, load in (
                (
                    "4955",
                    "metro_line_1",
                    "Linea 1 (tratta di esempio)",
                    ((40.8340, 14.2400), (40.8405, 14.2525)),
                    1.12,
                ),
                (
                    "2302",
                    "metro_line_6",
                    "Linea 6 (tratta di esempio)",
                    ((40.8290, 14.2180), (40.8340, 14.2330)),
                    0.9,
                ),
            ):
                shown = round(load - (0.1 if it >= 1 and route == "2302" else 0), 2)
                features.append(Feature(id=route, geometry=_geometry_line(coords),
                    properties={"route_id": route, "route_class": route_class, "label": label,
                                "trips": SECTION_TRIPS, "capacity_pax_h": SECTION_CAPACITY_PAX_H,
                                "pax_h": round(shown * SECTION_CAPACITY_PAX_H, 1),
                                "load_ratio": shown, "overloaded": shown > 1.0,
                                "schematic": True}))  # fmt: skip
        elif name == "event_area":
            c = self.event.area_center
            features.append(Feature(id="event_area", geometry={"type": "Polygon", "coordinates": [circle_polygon(c.lat, c.lon, self.event.area_radius_m)]},
                properties={"label": c.label, "radius_m": self.event.area_radius_m}))  # fmt: skip
        else:  # requests: la funzione del backend (`requests_layer`), non una copia delle sue proprietà
            sent_by = {0: -1, 1: 1, 2: 2}[it]
            sent: list[OperationRequest] = []
            for action_id, request in self.requests.items():
                if request.target_geo is None or request.iteration > sent_by:
                    continue
                state = self.request_view(action_id, METRICS_AT[it] if it else -1)
                if state is not None:
                    sent.append(state.request)
            return requests_layer(sent)
        return FeatureCollection(features=features)

    # --- altre risposte -------------------------------------------------------------------------

    def run_export(self) -> RunExport:
        views = [v for a in self.requests if (v := self.request_view(a)) is not None]
        return RunExport(
            event=self.event, run=self.run(), plan=self.plan(END + 1), requests=views,
            decisions=self.decisions(END + 1),
            metrics=[IterationMetrics(iteration=it, metrics=self.metrics(it)) for it in (0, 1, 2)],
        )  # fmt: skip

    def critical_edge_rows(self) -> list[CriticalEdge]:
        return [
            CriticalEdge(it, key, name, vc, float(length))
            for it in (0, 1, 2)
            for key, name, length, vc in self.critical_edges(it)
        ]

    def registry(self) -> VdeptRegistry:
        """Le risorse a fine run: libere = totale − impegnate dall'evento − assegnate nel run."""
        used_by_run = {("departure", "patrols"): 1, ("departure", "signal_changes"): 1,
                       ("departure", "hour_extensions"): 1}  # fmt: skip
        rows = []
        for res in self.event.resources:
            committed = res.municipal_police_patrols_committed
            for department, resource, total, base in (
                ("municipal_police", "patrols", res.municipal_police_patrols_total, committed),
                ("traffic_control", "signal_changes", res.traffic_control_signal_changes_max, 0),
                ("transport_control", "reserve_buses", res.transport_control_reserve_buses, 0),
                ("transport_control", "hour_extensions", res.transport_control_hour_extensions, 0),
            ):
                used = base + used_by_run.get((res.window, resource), 0)
                rows.append(ResourceBalance(department=department, window=res.window, resource=resource,
                                            total=total, used=used, remaining=total - used))  # fmt: skip
        return VdeptRegistry(departments=self.departments.departments, resources=rows)

    def live_flow(self, mode: LiveMode) -> LiveFlowResponse:
        if mode == "unavailable":
            return LiveFlowResponse(segments=[], mode=mode, degraded_reason="tomtom_key_missing")
        fetched = T0 - timedelta(seconds={"fresh": 0, "cached": 120, "snapshot": 1500}[mode])
        classes = self.live_config.flow.ratio_classes
        segments = []
        for index, segment in enumerate(self.live.segments):
            free = LIVE_FREE_FLOW[index]
            current = round(free * LIVE_RATIO[index])
            ratio = self._live_value(segment.id, "ratio", round(current / free, 3), "rapporto",
                                     "estimate", "attuale ÷ flusso libero", fetched)  # fmt: skip
            segments.append(
                LiveSegmentFlow(
                    id=segment.id,
                    label=segment.label or segment.id,
                    geometry=_geometry_line(_east_west(segment.lat, segment.lon, 220)),
                    current_speed=self._live_value(segment.id, "current_speed", current, "km/h",
                                                   "real", "velocità attuale del tratto", fetched),
                    free_flow_speed=self._live_value(segment.id, "free_flow_speed", free, "km/h",
                                                     "real", "velocità a flusso libero", fetched),
                    ratio=ratio,
                    congestion_class=congestion_class(float(ratio.value), classes),
                    fetched_at=fetched,
                )
            )  # fmt: skip
        # il riepilogo lo calcola la funzione vera del backend, sui valori di esempio dei tratti
        summary = [
            m.model_copy(update={
                "source": f"{SOURCE} ({m.source})",
                "method": f"{m.method} (valore di esempio)",
                "assumptions": [*m.assumptions, MOCK_NOTE],
            })
            for m in summarize(segments, total=len(self.live.segments))
        ]  # fmt: skip
        reason = "tomtom_unreachable" if mode == "snapshot" else None
        return LiveFlowResponse(
            segments=segments, mode=mode, degraded_reason=reason, summary=summary
        )

    def _live_value(
        self,
        segment_id: str,
        part: str,
        value: float,
        unit: str,
        kind: Kind,
        method: str,
        fetched: datetime,
    ) -> Measured:
        return make_measured(
            id=measured_id("live", segment_id, part), value=value, unit=unit, kind=kind,
            source=f"{SOURCE} (tomtom.flow)", method=f"{method} (valore di esempio)",
            inputs=["fixture F1-09"], assumptions=[MOCK_NOTE], as_of=fetched,
        )  # fmt: skip

    def network_edges(self) -> FeatureCollection:
        """Le strade da scegliere con un clic (06 4): una feature per strada, `reverse_key` è l'altro
        senso di marcia se l'esempio lo ha. Gli archi sono quelli schematici del layer `edges_vc`."""
        layer = self.layer("edges_vc", 0)
        known = {str(f.id) for f in layer.features}
        features: list[Feature] = []
        seen: set[str] = set()
        for feature in layer.features:
            key = str(feature.id)
            if key in seen:
                continue
            start, end, number = key.split("-")
            back = f"{end}-{start}-{number}"
            reverse = back if back in known else None
            seen |= {key, back} if reverse else {key}
            props = feature.properties
            features.append(Feature(id=key, geometry=feature.geometry,
                properties={"edge_key": key, "reverse_key": reverse, "name": props["name"],
                            "length_m": props["length_m"]}))  # fmt: skip
        return FeatureCollection(features=features)

    def resolve_preview(self) -> FeatureCollection:
        """Anteprima dell'evento della scena sui dati veri: archi chiusi e punti agganciati ai nodi."""
        labels = {k: c.label for c in self.event.closures for k in c.edge_keys}
        features = [
            Feature(id=key, geometry=_geometry_line(coords),
                    properties={"kind": "closure", "edge_key": key, "label": labels[key],
                                "name": CLOSED_STREET_NAME, "length_m": length})
            for key, length, coords in self.closed_edges
        ]  # fmt: skip
        center = self.event.area_center
        features.append(Feature(id="area_center", geometry=_geometry_point(center.lat, center.lon),
            properties={"kind": "area_center", "label": center.label, "node": 9137948052, "distance_m": 170}))  # fmt: skip
        for node, (label, lat, lon) in CRITICAL_INTERSECTIONS.items():
            features.append(Feature(id=node, geometry=_geometry_point(lat, lon),
                properties={"kind": "car_destination", "label": label, "node": int(node)}))  # fmt: skip
        return FeatureCollection(features=features)
