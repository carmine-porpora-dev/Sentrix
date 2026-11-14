from datetime import datetime, time
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
SECONDS_PER_HOUR = 3600


def now_rome() -> datetime:
    return datetime.now(ROME)


def seconds_of(clock: time) -> int:
    """I secondi dalla mezzanotte di un orario (come i tempi del GTFS)."""
    return clock.hour * SECONDS_PER_HOUR + clock.minute * 60 + clock.second


def format_hhmm(seconds: float) -> str:
    """«HH:MM» di un numero di secondi dalla mezzanotte (anche oltre le 24 ore, come nel GTFS)."""
    return f"{int(seconds // SECONDS_PER_HOUR):02d}:{int(seconds % SECONDS_PER_HOUR // 60):02d}"
