from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.agents.drafts import (
    AnalysisDraft,
    EventDemandDraft,
    FindingDraft,
    NoticeDraft,
    PlanChoice,
    PlanDraft,
    RecommendationDraft,
    ReplanDraft,
)
from app.models.agents_config import AgentsConfig
from app.models.base import WINDOWS

WINDOW_WORDS = {"arrival": "arrivo", "departure": "deflusso"}
KIND_WORDS = {"simulated": "stima del modello", "estimate": "stima", "real": "dato reale"}
SEVERITY_WORDS = {"critical": "critica", "warning": "da tenere sotto controllo", "info": "lieve"}
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
SUBJECTS = {"traffic": "stradali", "transit": "del trasporto pubblico"}
MODEL_NOTE = "Il modello è macroscopico, statico e non calibrato."
SCENARIO_NOTE = "L'affluenza è un'ipotesi di scenario indicata nell'Evento."


def format_number(value: float, decimals: int) -> str:
    """All'italiana (4.820; 38,4; 6): arrotondato come i validatori, senza zeri decimali inutili."""
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    integer, _, fraction = f"{rounded:,.{decimals}f}".partition(".")
    integer = integer.replace(",", ".")
    return f"{integer},{fraction}" if fraction.strip("0") else integer


class _Facts:
    """I valori dell'input, scritti come li scrive un testo: numero e provenienza."""

    def __init__(self, payload: dict[str, Any], config: AgentsConfig) -> None:
        self.measures: dict[str, dict[str, Any]] = {m["id"]: m for m in payload.get("measures", [])}
        self.decimals = config.numbers.decimals
        self.measure_labels = config.labels.measures

    def number(self, measure: dict[str, Any] | None) -> str | None:
        """«4.820» o «1,2», o `None` se il dato non c'è o non è un numero."""
        if measure is None or not isinstance(measure["value"], int | float):
            return None
        return format_number(measure["value"], self.decimals)

    def kinds(self, *measures: dict[str, Any] | None) -> str:
        """«(stima del modello)»: da dove vengono i numeri di una frase, una volta sola."""
        words = dict.fromkeys(KIND_WORDS[m["kind"]] for m in measures if m is not None)
        return f"({' / '.join(words)})" if words else ""

    def of(self, measure_id: str) -> str | None:
        """Un numero con la sua provenienza: «1,2 (stima del modello)»."""
        measure = self.measures.get(measure_id)
        number = self.number(measure)
        return None if number is None else f"{number} {self.kinds(measure)}"

    def ending(self, suffix: str) -> dict[str, Any] | None:
        return next((m for i, m in self.measures.items() if i.endswith(suffix)), None)

    def measure_label(self, measure_type: str) -> str:
        return self.measure_labels.get(measure_type, measure_type)


def _window(window: str) -> str:
    return WINDOW_WORDS.get(window, window)


# --- Event & Demand -----------------------------------------------------------------------------


def fallback_event_demand(payload: dict[str, Any], config: AgentsConfig) -> EventDemandDraft:
    facts = _Facts(payload, config)
    context = payload.get("context", {})
    parts: list[str] = []
    attendance = facts.ending(".event.attendance")
    if (number := facts.number(attendance)) is not None:
        name = str(context.get("event", "Evento"))
        title = name
        if "date" in context:
            title = f"{name} ({date.fromisoformat(context['date']).strftime('%d/%m/%Y')})"
        parts.append(f"{title}: ipotesi di scenario di {number} persone {facts.kinds(attendance)}.")
    for window in WINDOWS:
        in_band = facts.ending(f".event.{window}.persons_in_band")
        if (number := facts.number(in_band)) is None:
            continue
        shares = [
            (facts.ending(f".event.{window}.{name}"), what)
            for name, what in (
                ("car_persons", "in auto"),
                ("transit_persons", "sui mezzi pubblici"),
                ("walk_persons", "a piedi"),
            )
        ]
        known = [(m, what) for m, what in shares if facts.number(m) is not None]
        split = ", ".join(f"{facts.number(m)} {what}" for m, what in known)
        kinds = facts.kinds(in_band, *(m for m, _ in known))
        span = context.get(f"{window}_window")
        where = f"Nella finestra di {_window(window)}" + (f" ({span})" if span else "")
        sentence = f"{where}, {number} persone nella fascia di picco"
        parts.append(f"{sentence}: {split} {kinds}." if split else f"{sentence} {kinds}.")
    closures = [str(item) for item in context.get("closures", [])]
    if closures:
        parts.append("Chiusure: " + ", ".join(closures) + ".")
    disruptions = [str(item) for item in context.get("transit_disruptions", [])]
    if disruptions:
        parts.append("Interruzioni del trasporto pubblico: " + ", ".join(disruptions) + ".")
    text = " ".join(parts) or "Nessun dato di domanda disponibile."
    return EventDemandDraft(text=text, assumptions=[MODEL_NOTE, SCENARIO_NOTE])


# --- Traffic e Transit --------------------------------------------------------------------------


def _summary(signal: dict[str, Any], facts: _Facts) -> str:
    """Una frase per segnale, dal suo trigger: il valore è quello della prima evidenza."""
    value = facts.of(signal["evidence"][0])
    label = signal["target"]
    where = f"nella finestra di {_window(signal['window'])}"
    trigger = signal["trigger"]
    if trigger == "line_no_service_in_window":
        return f"{label}: nessuna corsa {where}."
    if value is None:
        return f"{label}: criticità «{trigger}» {where}."
    if trigger == "critical_intersection":
        return f"{label}: incrocio con rapporto v/c {value} {where}."
    if trigger == "saturated_path":
        return f"{label}: archi molto carichi, rapporto v/c {value} {where}."
    if trigger == "section_overloaded":
        return f"{label}: carico massimo di tratta {value}, oltre la capacità, {where}."
    if trigger == "stop_overloaded_unsafe":
        return f"Fermata {label}: carico {value}, oltre la soglia di sicurezza, {where}."
    if trigger == "stop_overloaded":
        return f"Fermata {label}: carico {value} {where}."
    return f"{label}: criticità «{trigger}», valore {value}, {where}."


def fallback_analysis(payload: dict[str, Any], config: AgentsConfig) -> AnalysisDraft:
    """Un finding per ogni segnale; una raccomandazione (la prima misura ammessa) per ogni segnale
    che non sia di sola informazione."""
    facts = _Facts(payload, config)
    signals = payload["signals"]
    findings = [FindingDraft(signal=s["id"], summary=_summary(s, facts)) for s in signals]
    recommendations = [
        RecommendationDraft(
            signal=s["id"],
            measure_type=s["allowed"][0],
            rationale="Misura del catalogo per questa criticità: "
            f"{facts.measure_label(s['allowed'][0])}.",
        )
        for s in signals
        if s["allowed"] and s["severity"] != "info"
    ]
    subject = SUBJECTS.get(payload["agent"], "")
    if signals:
        listed = ", ".join(f"{s['target']} ({SEVERITY_WORDS[s['severity']]})" for s in signals)
        text = f"Criticità {subject} individuate dagli strumenti (stima del modello): {listed}."
    else:
        text = f"Gli strumenti non hanno individuato criticità {subject}."
    return AnalysisDraft(
        text=text, findings=findings, recommendations=recommendations, assumptions=[MODEL_NOTE]
    )


# --- Operations ---------------------------------------------------------------------------------


def fallback_plan(payload: dict[str, Any], config: AgentsConfig) -> PlanDraft:
    """Per gravità (le critiche per prime), poi nell'ordine d'arrivo; al massimo `max_measures`."""
    ranked = sorted(payload["candidates"], key=lambda c: SEVERITY_ORDER[c["severity"]])
    chosen = ranked[: payload["max_measures"]]
    plan = [PlanChoice(candidate=c["id"], rationale=c["rationale"]) for c in chosen]
    if chosen:
        labels = _Facts(payload, config).measure_label
        listed = "; ".join(f"{labels(c['measure_type'])} a {c['target']}" for c in chosen)
        text = f"Piano in ordine di gravità: {listed}."
    else:
        text = "Nessuna misura da pianificare."
    return PlanDraft(text=text, plan=plan, assumptions=[MODEL_NOTE])


def fallback_replan(payload: dict[str, Any], config: AgentsConfig) -> ReplanDraft:
    """La prima alternativa dell'input (le alternative arrivano già nell'ordine del catalogo e
    senza quelle già rifiutate), o nessuna: allora serve una decisione umana."""
    labels = _Facts(payload, config).measure_label
    rejected = payload["rejected"]
    refused = f"{labels(rejected['measure_type'])} a {rejected['target']}"
    reason = (rejected.get("reject_reason") or "").strip()
    because = f": {reason}" if reason else ""
    alternatives = payload["alternatives"]
    if not alternatives:
        return ReplanDraft(
            text=f"Rifiutata la richiesta di {refused}{because}. "
            "Nessuna alternativa compatibile: serve una decisione umana.",
            choice=None,
            rationale="Nessuna alternativa compatibile con il bersaglio.",
        )
    first = alternatives[0]
    alternative = f"{labels(first['measure_type'])} a {first['target']}"
    return ReplanDraft(
        text=f"Rifiutata la richiesta di {refused}{because}. "
        f"In alternativa si chiede {alternative}.",
        choice=first["id"],
        rationale="È la prima alternativa del catalogo compatibile con il bersaglio.",
    )


def fallback_notice(payload: dict[str, Any], config: AgentsConfig) -> NoticeDraft:
    """L'elenco delle misure approvate, con bersaglio e orario, e nient'altro."""
    labels = _Facts(payload, config).measure_label
    accepted = payload["accepted"]
    if not accepted:
        return NoticeDraft(text="Nessuna misura straordinaria in vigore.")
    listed = "; ".join(
        f"{labels(item['measure_type'])} a {item['target']} ({item['hours']})" for item in accepted
    )
    return NoticeDraft(text=f"Misure in vigore per l'evento: {listed}.")
