from pydantic import Field

from app.models.base import FrozenModel


class GeoPoint(FrozenModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = None
