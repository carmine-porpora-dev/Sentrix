import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from pydantic import ValidationError

from app.agents.drafts import AnalysisDraft, EventDemandDraft, NoticeDraft, PlanDraft, ReplanDraft
from app.agents.payloads import Quotable, QuotedValue, quotable
from app.llm.client import InvalidResponse
from app.models.agents_config import AgentsConfig
from app.models.base import FrozenModel

MAX_REPORTED_PROBLEMS = 6  # il messaggio finisce in un prompt: breve

_THOUSANDS = r"\d{1,3}(?:[.\u00a0\u202f]\d{3})+(?:,\d+)?"
_TOKEN = re.compile(
    r"(?P<iso>(?<!\d)\d{4}-\d{2}-\d{2}(?!\d))"
    r"|(?P<time>(?<!\d)\d{1,2}:\d{2}(?!\d))"
    r"|(?P<date>(?<![\w/])\d{1,2}/\d{1,2}/\d{2,4}(?![\w/]))"
    rf"|(?<![\w.,])(?P<number>{_THOUSANDS}|\d+(?:[.,]\d+)?)(?P<percent>\s?%)?"
)
_GROUPED = re.compile(_THOUSANDS)
_ENGLISH_DECIMAL = re.compile(r"\d{1,3}\.\d{3}")  # «1.078»: migliaia all'italiana o 3 decimali
_GROUP_SEPARATORS = re.compile(r"[.\u00a0\u202f]")


# --- numeri -------------------------------------------------------------------------------------


def _readings(raw: str) -> list[Decimal]:
    """Ogni lettura possibile di un numero scritto in italiano: «1.078» sono mille e settantotto o,
    scritto all'inglese, un decimale; «1,078» e «1078» una sola."""
    if _GROUPED.fullmatch(raw):
        integer, _, fraction = raw.partition(",")
        digits = _GROUP_SEPARATORS.sub("", integer)
        readings = [Decimal(f"{digits}.{fraction}" if fraction else digits)]
        if _ENGLISH_DECIMAL.fullmatch(raw):
            readings.append(Decimal(raw))
        return readings
    return [Decimal(raw.replace(",", "."))]


def _round(value: Decimal, places: int) -> Decimal:
    return abs(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _clock(raw: str) -> str:
    hours, minutes = raw.split(":")
    return f"{int(hours):02d}:{minutes}"


def _iso(raw: str) -> str | None:
    """«2027-08-27» da «27/08/2027» (o «27/8/27»); `None` se non è una data."""
    day, month, year = (int(part) for part in raw.split("/"))
    try:
        return date(year + 2000 if year < 100 else year, month, day).isoformat()
    except ValueError:
        return None


@dataclass(frozen=True)
class _Names:
    """Le cifre che un testo può riportare dai nomi dell'input: tali e quali, senza arrotondare."""

    numbers: frozenset[Decimal]
    times: frozenset[str]
    dates: frozenset[str]

    @classmethod
    def of(cls, names: Iterable[str]) -> "_Names":
        numbers: set[Decimal] = set()
        times: set[str] = set()
        dates: set[str] = set()
        for name in names:
            for found in _TOKEN.finditer(name):
                if found["iso"]:
                    dates.add(found["iso"])
                    numbers.update(Decimal(int(part)) for part in found["iso"].split("-"))
                elif found["time"]:
                    times.add(_clock(found["time"]))
                elif found["number"]:
                    numbers.update(_readings(found["number"]))
        return cls(frozenset(numbers), frozenset(times), frozenset(dates))


@dataclass(frozen=True)
class _Context:
    """Ciò che serve a controllare un testo, ricavato una volta da input e configurazione."""

    source: Quotable
    names: _Names
    decimals: int
    percent_units: frozenset[str]
    forbidden: re.Pattern[str]

    @classmethod
    def of(cls, payload: dict[str, Any], config: AgentsConfig) -> "_Context":
        source = quotable(payload)
        words = "|".join(re.escape(word) for word in config.language.forbidden_when_simulated)
        return cls(
            source=source,
            names=_Names.of(source.names),
            decimals=config.numbers.decimals,
            percent_units=frozenset(config.numbers.percent_units),
            forbidden=re.compile(rf"\b(?:{words})\b", re.IGNORECASE),
        )

    def matches_value(self, readings: list[Decimal], percent: bool) -> bool:
        targets = (self._target(quoted, percent) for quoted in self.source.values)
        wanted = {_round(target, self.decimals) for target in targets if target is not None}
        return any(_round(value, self.decimals) in wanted for value in readings)

    def _target(self, quoted: QuotedValue, percent: bool) -> Decimal | None:
        number = Decimal(str(quoted.value))
        if not percent:
            return number
        return number * 100 if quoted.unit in self.percent_units else None

    def unknown_numbers(self, text: str) -> list[str]:
        """I numeri di `text` che non vengono dall'input, come sono scritti."""
        unknown: list[str] = []
        for found in _TOKEN.finditer(text):
            if found["iso"]:
                ok = found["iso"] in self.names.dates
            elif found["date"]:
                ok = _iso(found["date"]) in self.names.dates
            elif found["time"]:
                ok = _clock(found["time"]) in self.names.times
            else:
                readings = _readings(found["number"])
                percent = found["percent"] is not None
                ok = self.matches_value(readings, percent) or (
                    not percent and any(value in self.names.numbers for value in readings)
                )
            if not ok:
                unknown.append(found.group(0).strip())
        return unknown


# --- controlli di un testo ----------------------------------------------------------------------


class _Problems:
    def __init__(self, context: _Context, *, always_plain: bool = False) -> None:
        self.context = context
        self.always_plain = always_plain  # le parole vietate valgono anche senza dati simulati
        self.found: list[str] = []

    def add(self, problem: str) -> None:
        self.found.append(problem)

    def text(self, label: str, value: str, *, simulated: bool) -> None:
        """Non vuoto, senza parole vietate (se poggia su un dato simulato), con soli numeri noti."""
        if not value.strip():
            self.add(f"«{label}» è vuoto")
            return
        if simulated and (word := self.context.forbidden.search(value)):
            self.add(
                f"«{label}» usa la parola «{word.group(0).lower()}», che non si dice di un dato "
                "simulato: scrivi «stima del modello»"
            )
        for number in self.context.unknown_numbers(value):
            self.add(
                f"«{label}» cita il numero «{number}», che non è nei dati forniti: usa solo "
                "numeri dell'input, con lo stesso valore"
            )

    def free_texts(self, **texts: str | list[str]) -> None:
        """I testi che non poggiano su un segnale: la sintesi, la motivazione, le assunzioni."""
        simulated = self.always_plain or self.context.source.any_simulated
        for label, value in texts.items():
            if isinstance(value, str):
                self.text(label, value, simulated=simulated)
                continue
            for index, item in enumerate(value):
                self.text(f"{label}[{index}]", item, simulated=simulated)

    def choice(self, label: str, chosen: str, known: Iterable[str], what: str) -> bool:
        ids = list(known)
        if chosen in ids:
            return True
        options = ", ".join(ids) if ids else "nessuno"
        self.add(f"«{label}» è «{chosen}», che non è {what} (ammessi: {options})")
        return False

    def raise_if_any(self) -> None:
        if not self.found:
            return
        shown = self.found[:MAX_REPORTED_PROBLEMS]
        more = len(self.found) - len(shown)
        suffix = f"; e altri {more} problemi" if more else ""
        raise InvalidResponse("; ".join(shown) + suffix)


def _load[D: FrozenModel](model: type[D], text: str) -> D:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise InvalidResponse("la risposta non è JSON valido") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'risposta'}: {error['msg']}"
            for error in exc.errors()[:MAX_REPORTED_PROBLEMS]
        )
        raise InvalidResponse(f"la risposta non rispetta lo schema: {details}") from exc


def _simulated(context: _Context, evidence: Iterable[str]) -> bool:
    """Un'evidenza di cui non si conosce il `kind` (non è tra le misure dell'input) vale come
    simulata: il motore produce quasi solo dati simulati, e un controllo in più costa meno di uno
    saltato."""
    return any(context.source.kinds.get(item, "simulated") == "simulated" for item in evidence)


# --- una funzione per bozza ---------------------------------------------------------------------


def parse_event_demand(
    text: str, payload: dict[str, Any], config: AgentsConfig
) -> EventDemandDraft:
    draft = _load(EventDemandDraft, text)
    problems = _Problems(_Context.of(payload, config))
    problems.free_texts(text=draft.text, assumptions=draft.assumptions)
    problems.raise_if_any()
    return draft


def parse_analysis(text: str, payload: dict[str, Any], config: AgentsConfig) -> AnalysisDraft:
    """Traffic e Transit: i segnali scelti esistono, uno per finding, e le misure sono ammesse."""
    draft = _load(AnalysisDraft, text)
    context = _Context.of(payload, config)
    problems = _Problems(context)
    signals = {signal["id"]: signal for signal in payload["signals"]}
    problems.free_texts(text=draft.text, assumptions=draft.assumptions)
    found: set[str] = set()
    for index, finding in enumerate(draft.findings):
        label = f"findings[{index}]"
        if not problems.choice(f"{label}.signal", finding.signal, signals, "un segnale dell'input"):
            continue
        if finding.signal in found:
            problems.add(f"«{label}.signal» {finding.signal}: un solo finding per segnale")
        found.add(finding.signal)
        problems.text(
            f"{label}.summary",
            finding.summary,
            simulated=_simulated(context, signals[finding.signal]["evidence"]),
        )
    proposed: set[tuple[str, str]] = set()
    for index, recommendation in enumerate(draft.recommendations):
        label = f"recommendations[{index}]"
        if not problems.choice(
            f"{label}.signal", recommendation.signal, signals, "un segnale dell'input"
        ):
            continue
        signal = signals[recommendation.signal]
        problems.choice(
            f"{label}.measure_type",
            recommendation.measure_type,
            signal["allowed"],
            f"una misura ammessa per il segnale {recommendation.signal}",
        )
        key = (recommendation.signal, recommendation.measure_type)
        if key in proposed:
            problems.add(
                f"«{label}» ripete {recommendation.measure_type} per {recommendation.signal}"
            )
        proposed.add(key)
        problems.text(
            f"{label}.rationale",
            recommendation.rationale,
            simulated=_simulated(context, signal["evidence"]),
        )
    problems.raise_if_any()
    return draft


def parse_plan(text: str, payload: dict[str, Any], config: AgentsConfig) -> PlanDraft:
    """Operations, PLAN: candidati dell'input, ognuno una volta, al massimo `max_measures`."""
    draft = _load(PlanDraft, text)
    context = _Context.of(payload, config)
    problems = _Problems(context)
    candidates = {item["id"]: item for item in payload["candidates"]}
    problems.free_texts(text=draft.text, assumptions=draft.assumptions)
    if candidates and not draft.plan:
        problems.add(f"«plan» è vuoto ma i candidati sono {len(candidates)}")
    if len(draft.plan) > payload["max_measures"]:
        problems.add(f"«plan» ha {len(draft.plan)} misure, al massimo {payload['max_measures']}")
    chosen: set[str] = set()
    for index, item in enumerate(draft.plan):
        label = f"plan[{index}]"
        if not problems.choice(
            f"{label}.candidate", item.candidate, candidates, "un candidato dell'input"
        ):
            continue
        if item.candidate in chosen:
            problems.add(f"«{label}.candidate» {item.candidate}: ogni candidato una volta")
        chosen.add(item.candidate)
        problems.text(
            f"{label}.rationale",
            item.rationale,
            simulated=_simulated(context, candidates[item.candidate]["evidence"]),
        )
    problems.raise_if_any()
    return draft


def parse_replan(text: str, payload: dict[str, Any], config: AgentsConfig) -> ReplanDraft:
    """Operations, REPLAN: l'alternativa scelta è una di quelle dell'input, o nessuna (`null`)."""
    draft = _load(ReplanDraft, text)
    problems = _Problems(_Context.of(payload, config), always_plain=True)
    problems.free_texts(text=draft.text, rationale=draft.rationale)
    if draft.choice is not None:
        alternatives = [item["id"] for item in payload["alternatives"]]
        problems.choice("choice", draft.choice, alternatives, "un'alternativa dell'input")
    problems.raise_if_any()
    return draft


def parse_notice(text: str, payload: dict[str, Any], config: AgentsConfig) -> NoticeDraft:
    """Operations, fine run: l'avviso, con i soli numeri e orari delle misure approvate."""
    draft = _load(NoticeDraft, text)
    problems = _Problems(_Context.of(payload, config), always_plain=True)
    problems.free_texts(text=draft.text)
    problems.raise_if_any()
    return draft
