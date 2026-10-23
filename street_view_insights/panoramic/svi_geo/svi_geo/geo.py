"""WGS84 <-> ECEF <-> local ENU conversions and bearing helpers (float64, vectorised).

A local East-North-Up frame anchored at a reference point is used for all metric work
(triangulation, clustering, segment offsets). Never cluster on raw degrees.
"""

from __future__ import annotations

import numpy as np

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_B = WGS84_A * (1.0 - WGS84_F)
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
EARTH_R_MEAN = 6371008.8


def _f64(x):
    return np.asarray(x, dtype=np.float64)


def lla_to_ecef(lat_deg, lng_deg, alt_m=0.0) -> np.ndarray:
    """Geodetic (deg, deg, m) -> ECEF metres. Output shape (..., 3)."""
    lat = np.radians(_f64(lat_deg))
    lng = np.radians(_f64(lng_deg))
    h = _f64(alt_m)
    sl, cl = np.sin(lat), np.cos(lat)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sl * sl)
    x = (n + h) * cl * np.cos(lng)
    y = (n + h) * cl * np.sin(lng)
    z = (n * (1.0 - WGS84_E2) + h) * sl
    return np.stack(np.broadcast_arrays(x, y, z), axis=-1)


def ecef_to_lla(x, y, z):
    """ECEF metres -> geodetic (lat deg, lng deg, alt m). Bowring + 3 Newton iterations."""
    x, y, z = _f64(x), _f64(y), _f64(z)
    lng = np.arctan2(y, x)
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1.0 - WGS84_E2))
    for _ in range(5):
        sl = np.sin(lat)
        n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sl * sl)
        h = p / np.cos(lat) - n
        lat = np.arctan2(z, p * (1.0 - WGS84_E2 * n / (n + h)))
    sl = np.sin(lat)
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * sl * sl)
    h = p / np.cos(lat) - n
    return np.degrees(lat), np.degrees(lng), h


def _enu_matrix(lat0_deg, lng0_deg) -> np.ndarray:
    lat0 = np.radians(float(lat0_deg))
    lng0 = np.radians(float(lng0_deg))
    sl, cl = np.sin(lat0), np.cos(lat0)
    so, co = np.sin(lng0), np.cos(lng0)
    # rows: east, north, up expressed in ECEF
    return np.array(
        [
            [-so, co, 0.0],
            [-sl * co, -sl * so, cl],
            [cl * co, cl * so, sl],
        ]
    )


def ecef_to_enu(xyz, lat0_deg, lng0_deg, alt0_m=0.0) -> np.ndarray:
    """ECEF points (..., 3) -> ENU (..., 3) relative to the reference geodetic point."""
    ref = lla_to_ecef(lat0_deg, lng0_deg, alt0_m)
    d = _f64(xyz) - ref
    return d @ _enu_matrix(lat0_deg, lng0_deg).T


def lla_to_enu(lat_deg, lng_deg, alt_m, lat0_deg, lng0_deg, alt0_m=0.0):
    """Geodetic -> (e, n, u) arrays relative to the reference point."""
    enu = ecef_to_enu(lla_to_ecef(lat_deg, lng_deg, alt_m), lat0_deg, lng0_deg, alt0_m)
    return enu[..., 0], enu[..., 1], enu[..., 2]


def enu_to_lla(e, n, u, lat0_deg, lng0_deg, alt0_m=0.0):
    """ENU (m) relative to the reference -> geodetic (lat, lng, alt)."""
    enu = np.stack(np.broadcast_arrays(_f64(e), _f64(n), _f64(u)), axis=-1)
    xyz = enu @ _enu_matrix(lat0_deg, lng0_deg) + lla_to_ecef(lat0_deg, lng0_deg, alt0_m)
    return ecef_to_lla(xyz[..., 0], xyz[..., 1], xyz[..., 2])


def bearing_deg(lat1, lng1, lat2, lng2):
    """Initial great-circle bearing from point 1 to point 2, degrees in [0, 360)."""
    p1, p2 = np.radians(_f64(lat1)), np.radians(_f64(lat2))
    dl = np.radians(_f64(lng2) - _f64(lng1))
    x = np.sin(dl) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return np.mod(np.degrees(np.arctan2(x, y)), 360.0)


def haversine_m(lat1, lng1, lat2, lng2):
    """Great-circle distance on the mean-radius sphere, metres."""
    p1, p2 = np.radians(_f64(lat1)), np.radians(_f64(lat2))
    dp = p2 - p1
    dl = np.radians(_f64(lng2) - _f64(lng1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2.0 * EARTH_R_MEAN * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def wrap180(deg):
    """Wrap angle(s) to [-180, 180)."""
    return np.mod(_f64(deg) + 180.0, 360.0) - 180.0


def angdiff(a_deg, b_deg):
    """Signed smallest difference b - a, in [-180, 180)."""
    return wrap180(_f64(b_deg) - _f64(a_deg))


def enu_bearing_deg(de, dn):
    """Compass bearing (deg, clockwise from north) of an ENU displacement."""
    return np.mod(np.degrees(np.arctan2(_f64(de), _f64(dn))), 360.0)
