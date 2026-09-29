"""Zero-mock tests for multi-view ray triangulation."""

import math

import numpy as np
import pytest

from svi_geo import triangulate as tri


def _ray_to(origin, target, sigma_deg=0.0, rng=None):
    d = np.asarray(target, float) - np.asarray(origin, float)
    az = math.degrees(math.atan2(d[0], d[1]))
    el = math.degrees(math.atan2(d[2], math.hypot(d[0], d[1])))
    if sigma_deg and rng is not None:
        az += rng.normal(0, sigma_deg)
    return tri.Ray(np.asarray(origin, float), az, el)


def test_three_rays_intersect_exactly():
    target = np.array([5.0, 20.0, 1.0])
    rays = [_ray_to((x, 0.0, 2.5), target) for x in (-10.0, 0.0, 10.0)]
    res = tri.intersect_rays(rays)
    assert res.ok, res.reason
    np.testing.assert_allclose(res.point[:2], target[:2], atol=1e-6)
    assert abs(res.point[2] - target[2]) < 1e-6
    assert res.rms_m < 1e-6


def test_bearing_noise_half_degree_gives_sub_half_metre_error():
    rng = np.random.default_rng(0)
    target = np.array([4.0, 15.0, 0.0])
    errs = []
    for _ in range(200):
        rays = [
            _ray_to((y * 0.0 + x, 0.0, 2.5), target, 0.5, rng)
            for x, y in ((-10, 0), (0, 0), (10, 0))
        ]
        res = tri.intersect_rays(rays)
        assert res.ok
        errs.append(np.linalg.norm(res.point[:2] - target[:2]))
    assert np.median(errs) < 0.5


def test_parallel_rays_are_ill_conditioned():
    rays = [tri.Ray(np.array([x, 0.0, 2.5]), 0.0, 0.0) for x in (0.0, 0.3)]
    res = tri.intersect_rays(rays)
    assert not res.ok and res.reason == "ill_conditioned"


def test_intersection_behind_camera_is_rejected():
    # both rays point away from where their lines cross
    rays = [
        tri.Ray(np.array([0.0, 0.0, 2.5]), 45.0, 0.0),
        tri.Ray(np.array([10.0, 0.0, 2.5]), -45.0, 0.0),
    ]
    rays = [tri.Ray(r.origin, (r.az_deg + 180.0) % 360.0, 0.0) for r in rays]
    res = tri.intersect_rays(rays)
    assert not res.ok and res.reason == "behind"


def test_out_of_range_and_high_rms():
    far = np.array([0.0, 200.0, 0.0])
    rays = [_ray_to((x, 0.0, 2.5), far) for x in (-30.0, 30.0)]
    assert tri.intersect_rays(rays).reason == "out_of_range"
    rays = [
        _ray_to((-10, 0, 2.5), (0, 20, 0)),
        _ray_to((10, 0, 2.5), (0, 20, 0)),
        _ray_to((0, 0, 2.5), (8, 20, 0)),
    ]
    assert tri.intersect_rays(rays).reason == "high_rms"


def test_single_view_pole_range_from_ground_contact():
    el_bottom = -math.degrees(math.atan2(2.5, 12.0))
    assert tri.single_view_range(el_bottom, cam_height_m=2.5) == pytest.approx(12.0, abs=0.01)
    assert tri.single_view_range(1.0, cam_height_m=2.5) is None


def test_sign_range_from_plate_height():
    r, h, z0 = 15.0, 0.75, 1.5  # plate spans z0..z0+h relative to the camera
    el_t = math.degrees(math.atan2(z0 + h, r))
    el_b = math.degrees(math.atan2(z0, r))
    assert tri.plate_range(el_t, el_b, plate_height_m=h) == pytest.approx(r, rel=1e-6)


def test_point_from_range():
    ray = tri.Ray(np.array([1.0, 2.0, 2.5]), 90.0, 0.0)
    np.testing.assert_allclose(tri.point_from_range(ray, 10.0), [11.0, 2.0, 2.5], atol=1e-9)
