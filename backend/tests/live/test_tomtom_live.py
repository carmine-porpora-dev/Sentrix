import os
from datetime import datetime

import pytest

from app.clock import ROME
from app.data.tomtom import FlowReading, TomTomClient, to_segment_flow
from app.models.live_config import LiveConfig
from app.models.live_segments import LiveSegmentsConfig
from app.settings import load_env_file

pytestmark = pytest.mark.live

COMPARED = ("via_caracciolo", "viale_dohrn")


def key_or_skip() -> str:
    load_env_file()
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if not key:
        pytest.skip("TOMTOM_API_KEY non impostata (.env)")
    return key


def overlap(a: FlowReading, b: FlowReading) -> float:
    """Quota dei punti del segmento più corto che sta anche nell'altro (1 = lo stesso tratto)."""
    first = {(round(p[0], 5), round(p[1], 5)) for p in a.coordinates}
    second = {(round(p[0], 5), round(p[1], 5)) for p in b.coordinates}
    return len(first & second) / min(len(first), len(second))


async def test_viale_dohrn_e_via_caracciolo_sono_lo_stesso_tratto() -> None:
    segments = {s.id: s for s in LiveSegmentsConfig.from_yaml().segments}
    config = LiveConfig.from_yaml().tomtom
    async with TomTomClient(key_or_skip(), config) as client:
        readings = await client.fetch_many({name: segments[name] for name in COMPARED})
    for name in COMPARED:
        reading = readings[name]
        assert isinstance(reading, FlowReading), f"{name}: {reading}"
        flow = to_segment_flow(
            segments[name], reading, datetime.now(ROME), LiveConfig.from_yaml().flow.ratio_classes
        )  # prova la mappatura
        print(
            f"\n{name}: {reading.current_speed_kmh:g}/{reading.free_flow_speed_kmh:g} km/h, "
            f"confidence {reading.confidence:g}, {reading.frc}, {reading.length_m():.0f} m, "
            f"{len(reading.coordinates)} punti, da ({reading.coordinates[0][0]:.5f}, "
            f"{reading.coordinates[0][1]:.5f}) a ({reading.coordinates[-1][0]:.5f}, "
            f"{reading.coordinates[-1][1]:.5f}), rapporto {flow.ratio.value}"
        )
    caracciolo, dohrn = readings["via_caracciolo"], readings["viale_dohrn"]
    assert isinstance(caracciolo, FlowReading) and isinstance(dohrn, FlowReading)
    shared = overlap(caracciolo, dohrn)
    same = caracciolo.coordinates == dohrn.coordinates
    print(f"\nsovrapposizione dei punti: {shared:.0%}; geometria identica: {same}")
    print(f"VERDETTO: {'STESSO TRATTO' if shared >= 0.5 else 'tratti diversi'}")
