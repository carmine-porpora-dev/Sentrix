import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.models.provenance import Measured

METRICS_COLUMNS = ("iteration", "metric_id", "value", "unit", "kind", "source", "method", "as_of")
CRITICAL_EDGES_COLUMNS = ("iteration", "edge_key", "name", "vc", "length_m")

# Un foglio di calcolo esegue come formula una cella di testo che inizia con questi caratteri.
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class CriticalEdge:
    iteration: int
    edge_key: str
    name: str
    vc: float
    length_m: float


def _text(value: str) -> str:
    """Un testo che non può diventare una formula (i nomi vengono da OpenStreetMap)."""
    return "'" + value if value.startswith(_FORMULA_STARTS) else value


def _csv(columns: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()


def metrics_csv(rows: Iterable[tuple[int, Measured]]) -> str:
    """`iteration,metric_id,value,unit,kind,source,method,as_of`, una riga per metrica."""
    return _csv(
        METRICS_COLUMNS,
        (
            (
                iteration,
                m.id,
                _text(m.value) if isinstance(m.value, str) else m.value,
                _text(m.unit),
                m.kind,
                _text(m.source),
                _text(m.method),
                m.as_of.isoformat(),
            )
            for iteration, m in rows
        ),
    )


def critical_edges_csv(edges: Iterable[CriticalEdge]) -> str:
    """`iteration,edge_key,name,vc,length_m`, una riga per arco critico."""
    return _csv(
        CRITICAL_EDGES_COLUMNS,
        ((e.iteration, e.edge_key, _text(e.name), e.vc, e.length_m) for e in edges),
    )
