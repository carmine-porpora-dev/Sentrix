from app.models.base import FrozenModel, Slug, Window
from app.models.run import AttendanceLevel


class EngineResult(FrozenModel):
    """Il risultato di un'iterazione di una finestra: serializzabile e senza tempi, così due run
    con gli stessi input sono identici byte per byte."""

    event_id: Slug
    level: AttendanceLevel
    window: Window
    applied: tuple[str, ...]  # action_id delle misure applicate, nell'ordine
