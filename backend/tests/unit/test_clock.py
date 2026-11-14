import datetime as dt

import pytest

from app.clock import ROME, SECONDS_PER_HOUR, format_hhmm, now_rome, seconds_of


def test_secondi_dalla_mezzanotte() -> None:
    assert seconds_of(dt.time(0, 0)) == 0
    assert seconds_of(dt.time(8, 15)) == 8 * 3600 + 15 * 60
    assert seconds_of(dt.time(23, 59, 59)) == 86_399
    assert SECONDS_PER_HOUR == 3600


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "00:00"),
        (59, "00:00"),
        (60, "00:01"),
        (8 * 3600 + 15 * 60, "08:15"),
        (86_340.0, "23:59"),
    ],
)
def test_testo_hhmm(seconds: float, text: str) -> None:
    assert format_hhmm(seconds) == text


def test_hhmm_oltre_le_24_ore_come_nel_gtfs() -> None:
    assert format_hhmm(25 * 3600 + 30 * 60) == "25:30"


def test_andata_e_ritorno() -> None:
    for clock in (dt.time(6, 5), dt.time(13, 30), dt.time(23, 59)):
        assert format_hhmm(seconds_of(clock)) == f"{clock:%H:%M}"


def test_adesso_e_a_roma() -> None:
    assert now_rome().tzinfo is ROME
