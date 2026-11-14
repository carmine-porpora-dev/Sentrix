import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.models.base import Window

MAX_CHARS = 1024  # lunghezza massima del messaggio WhatsApp (12.4)
TITLE = "*Sentrix — Avviso viabilità*"  # prima riga, in grassetto WhatsApp
FOOTER = "Messaggio automatico di Sentrix"
ROADS_HEADING = "Strade chiuse:"
TRANSIT_HEADING = "Trasporto pubblico (TPL):"
NOTICE_HEADING = "Misure per i cittadini:"
MAX_NAME_CHARS = 200
MIN_NOTICE_CHARS = 40  # sotto, l'avviso tagliato non dice più nulla: si omette
ELLIPSIS = "…"
ITALY_PREFIX = "+39"


def mask_phone(number: str) -> str:
    """`+39 *** *** **12`: solo le ultime due cifre (e il prefisso italiano, se c'è). È l'unica
    forma in cui un numero esce dal `.env` (database, API, interfaccia, log decisioni)."""
    digits = re.sub(r"\D", "", number)
    prefix = ITALY_PREFIX if f"+{digits}".startswith(ITALY_PREFIX) else "+**"
    return f"{prefix} *** *** **{digits[-2:]}"


def _cut(text: str, room: int) -> str:
    """`text` in al più `room` caratteri, tagliato su una parola e chiuso da «…»."""
    if len(text) <= room:
        return text
    cut = text[: max(room - 1, 0)].rsplit(" ", 1)[0].rstrip(" ,;:.-—")
    return cut + ELLIPSIS


def _unique(labels: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(label.strip() for label in labels if label.strip()))


SEPARATOR = "\n\n"


def _listing(heading: str, items: Sequence[str], room: int) -> str | None:
    """Il titolo e le voci che stanno in `room` caratteri; le altre diventano «• e altre N». `None`
    se non c'è posto nemmeno per il titolo e una riga."""
    lines = [heading]
    size = len(heading)
    for index, item in enumerate(items):
        line = f"• {item}"
        left = len(items) - index  # voci ancora da scrivere, questa compresa
        fits = size + 1 + len(line) <= room
        # se dopo questa ne restano altre, deve starci anche la riga «e altre N»
        tail_fits = left == 1 or size + 1 + len(line) + 1 + len(f"• e altre {left - 1}") <= room
        if fits and tail_fits:
            lines.append(line)
            size += 1 + len(line)
            continue
        tail = f"• e altre {left}"
        if size + 1 + len(tail) > room:
            return None if len(lines) == 1 else "\n".join(lines)
        lines.append(tail)
        break
    return "\n".join(lines)


def advisory_text(
    *,
    event_name: str,
    event_date: date,
    closed_roads: Sequence[str],
    transit_disruptions: Sequence[str],
    notice: str | None,
) -> str:
    """L'avviso viabilità: titolo, evento e data, strade chiuse, linee TPL interessate, avviso ai
    cittadini, chiusura. Mai oltre `MAX_CHARS`: se non c'è posto, le voci in coda diventano «e altre
    N» e l'avviso ai cittadini si accorcia; titolo, evento e chiusura restano sempre."""
    name = _cut(event_name.strip(), MAX_NAME_CHARS)
    blocks = [f"{TITLE}\nEvento: {name} ({event_date:%d/%m/%Y})"]
    # il posto che resta per i blocchi in mezzo, ognuno col suo separatore davanti
    room = MAX_CHARS - len(blocks[0]) - len(SEPARATOR) - len(FOOTER)
    for heading, labels in ((ROADS_HEADING, closed_roads), (TRANSIT_HEADING, transit_disruptions)):
        items = _unique(labels)
        block = _listing(heading, items, room - len(SEPARATOR)) if items else None
        if block:
            blocks.append(block)
            room -= len(SEPARATOR) + len(block)
    if notice and notice.strip():
        available = room - len(SEPARATOR) - len(NOTICE_HEADING) - 1
        if available >= MIN_NOTICE_CHARS:
            blocks.append(f"{NOTICE_HEADING}\n{_cut(notice.strip(), available)}")
    blocks.append(FOOTER)
    return SEPARATOR.join(blocks)


# --- il bollettino ai servizi di emergenza (spech 12.3) ----------------------------------------

BULLETIN_TITLE = "BOLLETTINO VIABILITÀ — SIMULATO"
BULLETIN_CLOSED_HEADING = "Strade chiuse:"
BULLETIN_SATURATED_HEADING = (
    "Strade sature (carico oltre il {percent}% della capacità, stima del modello):"
)
BULLETIN_CRITICAL_HEADING = "Incroci critici:"
BULLETIN_TRANSIT_HEADING = "Trasporto pubblico interrotto:"
BULLETIN_NOTHING = "Nessuna criticità rilevata dal modello nelle due finestre."
BULLETIN_FOOTER = (
    "Bollettino simulato di Sentrix: nessun invio a enti reali. "
    "I valori sono stime di un modello non calibrato."
)
WINDOW_NAMES: dict[Window, str] = {"arrival": "arrivo", "departure": "deflusso"}


@dataclass(frozen=True)
class Listed:
    """Una voce di un elenco del bollettino e le finestre in cui vale (`arrival`, `departure`)."""

    label: str
    windows: tuple[Window, ...] = ()


def _bullets(items: Sequence[Listed], spans: Mapping[Window, str], limit: int) -> list[str]:
    """Le prime `limit` voci, ognuna con le sue finestre («— arrivo 12:00–14:00»); il resto diventa
    una riga «e altre N»."""
    lines = []
    for item in items[:limit]:
        when = ", ".join(f"{WINDOW_NAMES[w]} {spans[w]}" for w in item.windows)
        lines.append(f"• {item.label}" + (f" — {when}" if when else ""))
    if len(items) > limit:
        lines.append(f"• e altre {len(items) - limit}")
    return lines


def bulletin_text(
    *,
    recipient: str,
    event_name: str,
    event_date: date,
    spans: Mapping[Window, str],
    closed_roads: Sequence[str],
    saturated: Sequence[Listed],
    critical_intersections: Sequence[Listed],
    transit_disruptions: Sequence[str],
    saturation_threshold: float,
    limit: int,
) -> str:
    """Il bollettino viabilità per un destinatario: strade chiuse, strade sature (raggruppate per
    nome, con la finestra), incroci critici, linee TPL interrotte, finestre di arrivo e deflusso.
    Deterministico; i numeri sono quelli del motore (la soglia è `engine.yaml`), mai scritti qui."""
    blocks = [
        f"{BULLETIN_TITLE}\nA: {recipient}\nEvento: {event_name.strip()} ({event_date:%d/%m/%Y})\n"
        + " · ".join(
            f"{WINDOW_NAMES[w].capitalize()}: {spans[w]}" for w in ("arrival", "departure")
        )
    ]
    sections = (
        (BULLETIN_CLOSED_HEADING, [Listed(label) for label in _unique(closed_roads)]),
        (BULLETIN_SATURATED_HEADING.format(percent=round(saturation_threshold * 100)), saturated),
        (BULLETIN_CRITICAL_HEADING, critical_intersections),
        (BULLETIN_TRANSIT_HEADING, [Listed(label) for label in _unique(transit_disruptions)]),
    )
    for heading, items in sections:
        if items:
            blocks.append("\n".join([heading, *_bullets(items, spans, limit)]))
    if len(blocks) == 1:
        blocks.append(BULLETIN_NOTHING)
    blocks.append(BULLETIN_FOOTER)
    return SEPARATOR.join(blocks)
