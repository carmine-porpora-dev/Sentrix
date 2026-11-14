import csv
import io
from datetime import datetime

from app.api.exports import CriticalEdge, critical_edges_csv, metrics_csv
from app.clock import ROME
from app.models.provenance import Measured, make_measured


def measured(value: float | int | str = 4820.5) -> Measured:
    return make_measured(
        id="m.run1.it0.road.departure.veh_hours",
        value=value,
        unit="veic·h",
        kind="simulated",
        source="engine.metrics v1",
        method="somma sugli archi, con virgola",
        inputs=["osm"],
        as_of=datetime(2026, 11, 9, 10, 0, 21, tzinfo=ROME),
    )


def test_intestazioni_della_spec() -> None:
    assert metrics_csv([]) == "iteration,metric_id,value,unit,kind,source,method,as_of\n"
    assert critical_edges_csv([]) == "iteration,edge_key,name,vc,length_m\n"


def test_una_riga_per_metrica_con_virgolette_dove_servono() -> None:
    text = metrics_csv([(1, measured())])
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[1] == [
        "1",
        "m.run1.it0.road.departure.veh_hours",
        "4820.5",
        "veic·h",
        "simulated",
        "engine.metrics v1",
        "somma sugli archi, con virgola",
        "2026-11-09T10:00:21+01:00",
    ]
    assert text.endswith("\n") and "\r" not in text


def test_archi_critici() -> None:
    text = critical_edges_csv(
        [CriticalEdge(1, "3465091789-3468033710-0", "Riviera di Chiaia", 1.05, 440.0)]
    )
    assert text.splitlines() == [
        "iteration,edge_key,name,vc,length_m",
        "1,3465091789-3468033710-0,Riviera di Chiaia,1.05,440.0",
    ]


def test_un_testo_non_diventa_una_formula() -> None:
    for start in ("=CMD()", "+1", "-1", "@SUM(A1)"):
        text = critical_edges_csv([CriticalEdge(0, "1-2-0", start, 0.9, 10.0)])
        cell = next(csv.reader(io.StringIO(text.split("\n")[1])))[2]
        assert cell == "'" + start
    qualitative = metrics_csv([(0, measured("=oops"))])
    assert "'=oops" in qualitative
    assert "'=oops" not in metrics_csv([(0, measured(7))])


def test_i_numeri_negativi_restano_numeri() -> None:
    text = metrics_csv([(1, measured(-3.5))])
    assert ",-3.5," in text and "'-3.5" not in text
