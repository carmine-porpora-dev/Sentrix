import math
from typing import Any

import numpy as np

EARTH_RADIUS_M = 6_371_008.8  # raggio medio terrestre (IUGG), per la distanza haversine
METERS_PER_DEGREE = math.pi * EARTH_RADIUS_M / 180  # lunghezza di 1° di meridiano (≈ 111 195 m)
COORD_DECIMALS = 6  # decimali delle coordinate nei layer GeoJSON (≈ 0,1 m)


def haversine_m(lat: Any, lon: Any, center: tuple[float, float]) -> Any:
    """Distanza in metri (haversine) tra `center` (lat, lon) e uno o più punti.

    Accetta numeri singoli o serie/array numerici di gradi; restituisce lo stesso tipo.
    """
    lat0, lon0 = np.radians(center[0]), np.radians(center[1])
    phi, lam = np.radians(lat), np.radians(lon)
    a = np.sin((phi - lat0) / 2) ** 2 + np.cos(lat0) * np.cos(phi) * np.sin((lam - lon0) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def circle_polygon(lat: float, lon: float, radius_m: float, points: int = 48) -> list[list[float]]:
    """L'anello `[lon, lat]` (GeoJSON, chiuso: il primo punto è anche l'ultimo) di un cerchio di
    `radius_m` metri attorno al punto, con `points` vertici, arrotondato a 6 decimali (≈ 0,1 m)."""
    metres_per_lon = METERS_PER_DEGREE * math.cos(math.radians(lat))
    ring = [
        [
            round(
                lon + radius_m * math.sin(2 * math.pi * n / points) / metres_per_lon, COORD_DECIMALS
            ),
            round(
                lat + radius_m * math.cos(2 * math.pi * n / points) / METERS_PER_DEGREE,
                COORD_DECIMALS,
            ),
        ]
        for n in range(points)
    ]
    return [*ring, ring[0]]


def geojson_point(lat: float, lon: float) -> dict[str, Any]:
    """La geometria GeoJSON `Point` (coordinate `[lon, lat]`, a `COORD_DECIMALS` decimali)."""
    return {
        "type": "Point",
        "coordinates": [round(lon, COORD_DECIMALS), round(lat, COORD_DECIMALS)],
    }
