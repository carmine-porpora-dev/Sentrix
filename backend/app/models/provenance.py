import math
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from app.clock import now_rome
from app.models.base import ID_PART, FrozenModel, RomeDatetime

# real: da fonte reale · estimate: da modello o ipotesi · simulated: prodotto dal motore o dai
# dipartimenti virtuali (spech 6.2).
Kind = Literal["real", "estimate", "simulated"]

_ID_PART = re.compile(ID_PART)
# Id di un Measured: m.<parte>.<parte>... Le evidenze di agenti e raccomandazioni lo citano.
MeasuredId = Annotated[str, StringConstraints(pattern=rf"^m(\.{ID_PART})+$")]


def measured_id(*parts: str) -> str:
    """Id deterministico: stessa sequenza di parti, stesso id (così gli agenti possono citarlo).

    >>> measured_id("run42", "it1", "od", "bagnoli_centrale", "time")
    'm.run42.it1.od.bagnoli_centrale.time'
    """
    if not parts:
        raise ValueError("measured_id: serve almeno una parte")
    for part in parts:
        if not _ID_PART.fullmatch(part):
            raise ValueError(
                f"measured_id: parte non valida '{part}' (lettere, cifre, '_' e '-'; niente punti)"
            )
    return "m." + ".".join(parts)


class Measured(FrozenModel):
    id: MeasuredId  # stabile e univoco nel run: vedi `measured_id`
    value: float | int | str  # str solo per indicatori qualitativi
    # Unità: "veic/h", "min", "km", "veic·h", "pax", "rapporto", "km/h", "%"
    unit: str = Field(min_length=1)
    kind: Kind
    # Fonte: es. "engine.assign v1", "gtfs.anm AAAA-MM-GG", "tomtom.flow"
    source: str = Field(min_length=1)
    method: str = Field(min_length=1)  # es. "assegnazione incrementale BPR, 4 passi"
    # Input: es. ["osm AAAA-MM-GG", "event evt_match_2027 rev 3", "engine.yaml sha:ab12"]
    inputs: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    as_of: RomeDatetime  # sempre con fuso, normalizzato a Europe/Rome

    @field_validator("value", mode="before")
    @classmethod
    def _real_number(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("un booleano non è un valore misurato")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("il valore deve essere un numero finito")
        return value

    @field_validator("inputs", "assumptions")
    @classmethod
    def _non_blank(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("le voci non possono essere vuote")
        return value


def make_measured(
    *,
    id: str,
    value: float | int | str,
    unit: str,
    kind: Kind,
    source: str,
    method: str,
    inputs: Sequence[str],
    assumptions: Sequence[str] = (),
    as_of: datetime | None = None,
) -> Measured:
    """L'unico punto di costruzione di un `Measured`. `as_of` omesso = adesso (Europe/Rome)."""
    return Measured(
        id=id,
        value=value,
        unit=unit,
        kind=kind,
        source=source,
        method=method,
        inputs=list(inputs),
        assumptions=list(assumptions),
        as_of=as_of if as_of is not None else now_rome(),
    )
