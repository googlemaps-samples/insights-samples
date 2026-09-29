"""Synthetic (zero-mock) tests for rosette self-calibration."""

import dataclasses
import math

import numpy as np
import pytest

from svi_geo import calibrate, rosette

TRUE = rosette.Intrinsics(
    width=3648,
    height=5472,
    fx=1800.0,
    fy=1800.0,
    cx=1824.0,
    cy=2900.0,
    k1=0.02,
    k2=-0.01,
    k3=0.0,
    k4=0.0,
    max_theta_deg=95.0,
    rosette_radius_m=0.12,
)
INIT = dataclasses.replace(rosette.DEFAULT_INTRINSICS, max_theta_deg=95.0)


@pytest.fixture(scope="module")
def scene():
    return calibrate.synthetic_rosette_problem(
        TRUE,
        n_panos=12,
        n_points_per_pair=60,
        n_seq_pairs=8,
        n_lines_per_cam=3,
        pixel_noise=0.5,
        outlier_frac=0.10,
        delta_sigma_deg=0.3,
        seed=3,
    )


@pytest.fixture(scope="module")
def fitted(scene):
    prob, _ = scene
    return calibrate.fit(prob, INIT, use_overlap=True, use_sequence=True, use_lines=True)


def test_synthetic_problem_is_well_formed(scene):
    prob, truth = scene
    assert prob.n_intra > 1000
    assert prob.n_seq > 100
    assert len(prob.chains) > 50
    assert set(truth["deltas"]) == set(range(6))
    # truth deltas are zero-mean (gauge)
    np.testing.assert_allclose(np.mean(list(truth["deltas"].values()), axis=0), 0, atol=1e-9)


def test_radius_is_a_gauge_of_intra_pano_matches():
    """Intra-pano residuals are invariant to the rosette radius when depth is free.

    Within one pano Ca - Cb = r * (u_a - u_b), so scaling r only rescales every triangulated
    depth; the angles are unchanged. This is why `fit` holds r at a measured value instead of
    the plan's "fit r" (deviation).
    """
    prob, truth = calibrate.synthetic_rosette_problem(
        TRUE,
        n_panos=3,
        n_points_per_pair=30,
        n_seq_pairs=0,
        n_lines_per_cam=0,
        pixel_noise=0.3,
        outlier_frac=0.0,
        seed=4,
    )
    m = calibrate._Model(prob, TRUE, (1, 1), (1, 2), True, False, False, 0.2)
    x = calibrate._x0(m, TRUE, TRUE.fx, 0.12)
    x[m.lay.i_delta : m.lay.i_delta + 18] = np.ravel([truth["deltas"][k] for k in range(6)])
    y = x.copy()
    y[m.lay.i_r] = 0.24
    rx, ry = m.match_residual_vectors(x), m.match_residual_vectors(y)
    assert np.abs(rx).max() > 0.001  # non-trivial residuals (pixel noise)
    # identical except where a triangulated depth hits the 2 m floor / far clip
    same = np.abs(rx - ry).max(axis=1) < 1e-9
    assert same.mean() > 0.9


def test_fit_recovers_intrinsics_and_deltas(fitted):
    fit = fitted.intrinsics
    assert fit.fx == pytest.approx(TRUE.fx, rel=0.01)
    assert abs(fit.cx - TRUE.cx) < 8 and abs(fit.cy - TRUE.cy) < 8
    # r is held at the nominal 0.10 m (true 0.12 m); the error is absorbed by the depths
    assert fit.rosette_radius_m == pytest.approx(0.10, abs=1e-3)
    assert tuple(fit.pose_convention) == (1, 1)
    assert fit.fitted


def test_fit_recovers_rotation_deltas(scene, fitted):
    _, truth = scene
    for k in range(6):
        np.testing.assert_allclose(
            fitted.intrinsics.cam_rot_delta_deg[k], truth["deltas"][k], atol=0.1
        )


def test_heldout_angular_residual_small(scene, fitted):
    res = fitted
    held, _ = calibrate.synthetic_rosette_problem(
        TRUE,
        n_panos=4,
        n_points_per_pair=40,
        n_seq_pairs=0,
        n_lines_per_cam=0,
        pixel_noise=0.5,
        outlier_frac=0.0,
        delta_sigma_deg=0.3,
        seed=99,
        deltas=_deltas_of(scene),
    )
    err = calibrate.heldout_match_errors(held, res.intrinsics)
    assert np.median(err) < 0.2
    err0 = calibrate.heldout_match_errors(held, INIT)
    assert np.median(err0) > 3 * np.median(err)


def _deltas_of(scene):
    return scene[1]["deltas"]


def test_ablation_lines_and_sequence_only(scene):
    prob, _ = scene
    res = calibrate.fit(prob, INIT, use_overlap=False, use_sequence=True, use_lines=True)
    assert res.intrinsics.fx == pytest.approx(TRUE.fx, rel=0.03)


def test_wrong_pitch_sign_is_detected():
    prob, _ = calibrate.synthetic_rosette_problem(
        TRUE,
        n_panos=6,
        n_points_per_pair=40,
        n_seq_pairs=0,
        n_lines_per_cam=2,
        pixel_noise=0.5,
        outlier_frac=0.0,
        delta_sigma_deg=0.2,
        seed=5,
        reported_convention=(-1, 1),
    )
    res = calibrate.fit(prob, INIT, conventions=[(1, 1), (-1, 1), (1, -1), (-1, -1)])
    assert tuple(res.intrinsics.pose_convention) == (-1, 1)


def test_great_circle_residual_zero_for_straight_line():
    # rays of a straight 3D line lie on a plane through the camera centre
    p0, d = np.array([1.0, -2.0, 6.0]), np.array([0.3, 1.0, 0.1])
    pts = p0 + np.linspace(-3, 3, 50)[:, None] * d
    rays = pts / np.linalg.norm(pts, axis=1, keepdims=True)
    r, n = calibrate.great_circle_residuals(rays)
    assert np.abs(r).max() < 1e-9
    assert abs(np.dot(n, d)) < 1e-9


def test_midpoint_triangulation_errors_zero_for_exact_rays():
    c1, c2 = np.array([0.0, 0, 0]), np.array([0.1, 0, 0])
    x = np.array([[2.0, 10.0, 1.0], [-3.0, 8.0, -0.5]])
    r1 = (x - c1) / np.linalg.norm(x - c1, axis=1, keepdims=True)
    r2 = (x - c2) / np.linalg.norm(x - c2, axis=1, keepdims=True)
    e1, e2 = calibrate.two_view_errors_deg(c1, r1, c2, r2)
    assert np.abs(e1).max() < 1e-6 and np.abs(e2).max() < 1e-6
    ang = math.degrees(0.01)
    r2b = r2 + np.array([0.0, 0.0, 0.01]) * np.linalg.norm(r2, axis=1, keepdims=True)
    e1, e2 = calibrate.two_view_errors_deg(
        c1, r1, c2, r2b / np.linalg.norm(r2b, axis=1, keepdims=True)
    )
    # divergent rays are treated as a point at infinity, so the split error is bounded by the
    # perturbation plus the parallax of the 0.1 m baseline at the true depth (~10 m)
    parallax = np.degrees(0.1 / np.linalg.norm(x, axis=1))
    assert np.all(e1 + e2 < (ang + parallax) * 1.05)
    assert np.all(np.maximum(e1, e2) > 0.25 * ang)


def test_heldout_metric_sees_bearing_error_that_small_depths_would_absorb():
    """QA F4: a +3 deg yaw error on one camera must show up in the held-out metric."""
    zero = {k: [0.0, 0.0, 0.0] for k in range(6)}
    held, _ = calibrate.synthetic_rosette_problem(
        TRUE,
        n_panos=4,
        n_points_per_pair=60,
        n_seq_pairs=0,
        n_lines_per_cam=0,
        pixel_noise=0.0,
        outlier_frac=0.0,
        seed=11,
        deltas=zero,
    )
    good = dataclasses.replace(TRUE, cam_rot_delta_deg=zero)
    bad = dataclasses.replace(TRUE, cam_rot_delta_deg={**zero, 1: [3.0, 0.0, 0.0]})
    involves_1 = np.array(
        [
            held.instances[a].cam_k == 1 or held.instances[b].cam_k == 1
            for a, b in zip(held.m_a, held.m_b, strict=True)
        ]
    )
    sub = held.subset(involves_1)
    assert np.median(calibrate.heldout_match_errors(sub, good)) < 0.05
    err = calibrate.heldout_match_errors(sub, bad)
    assert np.median(err) >= 0.5
    # a 0.5 m depth floor would hide most of it (the pre-fix behaviour)
    loose = calibrate.heldout_match_errors(sub, bad, min_depth_m=0.5)
    assert np.median(loose) < np.median(err)
    comp = calibrate.heldout_match_error_components(sub, bad)
    assert np.median(comp["along_b"]) > np.median(comp["across_b"])
