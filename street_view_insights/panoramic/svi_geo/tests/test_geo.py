import numpy as np
import pytest

from svi_geo import geo


def test_ecef_equator_prime_meridian():
    np.testing.assert_allclose(geo.lla_to_ecef(0.0, 0.0, 0.0), [6378137.0, 0.0, 0.0], atol=1e-6)


def test_ecef_north_pole():
    x, y, z = geo.lla_to_ecef(90.0, 0.0, 0.0)
    assert abs(x) < 1e-6 and abs(y) < 1e-6
    assert z == pytest.approx(6356752.314, abs=1e-3)


def test_enu_100m_north():
    lat0, lng0 = 48.8, 2.37
    lat1 = lat0 + 100.0 / 111_200.0  # approx 100 m
    d = geo.haversine_m(lat0, lng0, lat1, lng0)
    e, n, u = geo.lla_to_enu(lat1, lng0, 0.0, lat0, lng0, 0.0)
    assert abs(e) < 1e-6
    assert n == pytest.approx(d, abs=0.5)  # haversine sphere vs ellipsoid
    # exact 100 m north round trip
    lat, lng, alt = geo.enu_to_lla(0.0, 100.0, 0.0, lat0, lng0, 0.0)
    e, n, u = geo.lla_to_enu(lat, lng, alt, lat0, lng0, 0.0)
    assert n == pytest.approx(100.0, abs=0.01)
    assert abs(e) < 0.01


def test_round_trip_vectorised():
    rng = np.random.default_rng(0)
    lat0, lng0, h0 = 37.39, -122.07, 20.0
    enu = rng.uniform(-500, 500, size=(100, 3))
    lat, lng, h = geo.enu_to_lla(enu[:, 0], enu[:, 1], enu[:, 2], lat0, lng0, h0)
    e, n, u = geo.lla_to_enu(lat, lng, h, lat0, lng0, h0)
    np.testing.assert_allclose(np.stack([e, n, u], 1), enu, atol=1e-6)
    lat2, lng2, _ = geo.enu_to_lla(e, n, u, lat0, lng0, h0)
    np.testing.assert_allclose(lat2, lat, atol=1e-9)
    np.testing.assert_allclose(lng2, lng, atol=1e-9)


def test_bearing_east():
    lat0, lng0 = 10.0, 20.0
    lat1, lng1, _ = geo.enu_to_lla(1000.0, 0.0, 0.0, lat0, lng0, 0.0)
    assert geo.bearing_deg(lat0, lng0, lat1, lng1) == pytest.approx(90.0, abs=0.01)
    assert geo.bearing_deg(lat1, lng1, lat0, lng0) == pytest.approx(270.0, abs=0.01)


def test_wrap_and_angdiff():
    assert geo.wrap180(190) == pytest.approx(-170)
    assert geo.wrap180(-190) == pytest.approx(170)
    assert geo.angdiff(359, 1) == pytest.approx(2)
    assert geo.angdiff(1, 359) == pytest.approx(-2)
    np.testing.assert_allclose(geo.wrap180(np.array([0, 180, 540])), [0, -180, -180])


def test_float32_upcast():
    out = geo.lla_to_ecef(np.float32(48.8), np.float32(2.37), np.float32(0))
    assert out.dtype == np.float64
