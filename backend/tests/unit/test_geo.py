import pandas as pd
import pytest

from app.geo import COORD_DECIMALS, EARTH_RADIUS_M, circle_polygon, geojson_point, haversine_m


def test_haversine_scalare_e_serie() -> None:
    center = (40.8320, 14.2350)
    # Valori calcolati a parte con una formula indipendente: 112,46 m e 394,77 m.
    assert float(haversine_m(40.8330, 14.2352, center)) == pytest.approx(112.46, abs=0.05)
    assert float(haversine_m(40.8320, 14.2350, center)) == 0.0
    series = haversine_m(pd.Series([40.8330, 40.8313]), pd.Series([14.2352, 14.2304]), center)
    assert isinstance(series, pd.Series)
    assert series.tolist() == pytest.approx([112.46, 394.77], abs=0.05)
    # Simmetrica: la distanza A-B è quella B-A.
    assert float(haversine_m(40.8320, 14.2350, (40.8330, 14.2352))) == pytest.approx(
        112.46, abs=0.05
    )


def test_un_grado_di_latitudine_e_circa_111_km() -> None:
    # 2π·R/360, calcolato a mano: un grado di meridiano vale 111 195 m con questo raggio.
    assert float(haversine_m(1.0, 0.0, (0.0, 0.0))) == pytest.approx(111_195, abs=1)
    assert EARTH_RADIUS_M == 6_371_008.8


def test_accetta_array_numpy_e_liste_di_gradi() -> None:
    import numpy as np

    center = (40.8320, 14.2350)
    from_array = haversine_m(np.array([40.8330, 40.8313]), np.array([14.2352, 14.2304]), center)
    assert from_array.tolist() == pytest.approx([112.46, 394.77], abs=0.05)
    assert haversine_m([40.8330], [14.2352], center).tolist() == pytest.approx([112.46], abs=0.05)


def test_geojson_point_ha_longitudine_e_latitudine_in_questo_ordine() -> None:
    assert geojson_point(40.832012345, 14.235098765) == {
        "type": "Point",
        "coordinates": [14.235099, 40.832012],  # [lon, lat], a COORD_DECIMALS decimali
    }
    assert COORD_DECIMALS == 6


def test_il_cerchio_e_un_anello_chiuso_a_distanza_costante() -> None:
    center = (40.8320, 14.2350)
    ring = circle_polygon(center[0], center[1], 400)
    assert len(ring) == 49 and ring[0] == ring[-1]  # 48 vertici più la chiusura
    # il primo vertice è a nord del centro, alla stessa longitudine
    assert ring[0][0] == center[1] and ring[0][1] > center[0]
    for lon, lat in ring:
        assert float(haversine_m(lat, lon, center)) == pytest.approx(400, abs=0.5)
    # il quarto è a est: stessa latitudine, longitudine maggiore
    east = ring[12]
    assert east[1] == pytest.approx(center[0], abs=1e-6) and east[0] > center[1]
    assert len(circle_polygon(center[0], center[1], 400, points=8)) == 9


def test_il_cerchio_ha_coordinate_a_sei_decimali() -> None:
    ring = circle_polygon(40.8320, 14.2350, 400)
    assert all(round(x, COORD_DECIMALS) == x for point in ring for x in point)
