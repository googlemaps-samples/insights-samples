"""Unit tests for label-free geometry helpers and repeat-pass pairing (Task T5)."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from svi_geo import geo, rosette, sequence
from svi_geo import labelfree as lf
from svi_geo import simulate as sim
from svi_geo import triangulate as tri


def test_heldout_reprojection_noise_free_and_injected_bias():
    fr = sim.synthetic_frames(8, 10.0, 48.85, 2.35, travel_deg=0.0)
    scene = sim.make_scene(fr, n_poles=6, n_signs=0, n_houses=0, seed=10)
    res = sim.simulate_observations(scene, fr, rosette.DEFAULT_INTRINSICS, sim.NOISE_FREE)
    obs = sim.to_observations(res.detections, fr, rosette.DEFAULT_INTRINSICS, scene.ref_lla)

    by_obj: dict[str, list] = {}
    truth_map = sim.truth_labels(res.detections)
    for o in obs:
        obj_id = truth_map[o.obs_id]
        if obj_id is not None:
            by_obj.setdefault(obj_id, []).append(o)

    clean = lf.heldout_reprojection(by_obj, tol_deg=2.0)
    assert clean["hit_rate"] == pytest.approx(1.0)
    assert clean["median_error_deg"] == pytest.approx(0.0, abs=1e-3)

    # Inject a 5 deg azimuth bias into every 3rd observation of each object:
    # when that biased observation is the held-out target, its bearing is ~5 deg off (> 2.0 deg tol),
    # while when it is in the k-1 training views it perturbs the intersection slightly.
    # Specifically, if we bias the held-out observation by +5 deg on exactly half of evaluations,
    # the hit rate drops by the predicted amount (0.5).
    biased = lf.heldout_reprojection(by_obj, tol_deg=2.0, test_bias_deg=5.0, bias_fraction=0.5)
    assert biased["hit_rate"] == pytest.approx(0.5, abs=0.05)
    assert biased["median_error_deg"] > 1.5


def test_split_half_location_noise_free_and_sigma_1deg_at_20m():
    # Place 6 cameras along y = -25..+25 m (x=0) observing targets at x = 20 m
    origins = [np.array([0.0, -25.0 + 10.0 * k, 0.0]) for k in range(6)]
    target = np.array([20.0, 0.0, 0.0])

    clean_rays = []
    for orig in origins:
        d = target - orig
        az = float(geo.enu_bearing_deg(d[0], d[1]))
        clean_rays.append(tri.Ray(orig, az, 0.0))

    res_clean = lf.split_half_location([clean_rays])
    assert res_clean["n_valid"] == 1
    assert res_clean["p50_m"] == pytest.approx(0.0, abs=1e-6)

    # Analytic covariance for sigma = 1 deg at ~20 m across even (0,2,4) vs odd (1,3,5) cameras
    sigma_rad = math.radians(1.0)

    def half_cov(sub_origins: list[np.ndarray]) -> np.ndarray:
        rows = []
        weights = []
        for orig in sub_origins:
            d = target[:2] - orig[:2]
            r = float(np.linalg.norm(d))
            u = d / r
            n_vec = np.array([-u[1], u[0]])
            rows.append(n_vec)
            weights.append(1.0 / ((r * sigma_rad) ** 2))
        a_mat = np.asarray(rows)
        # intersect_rays weights each ray equally (unit normal distance); cov = (A^T A)^{-1} A^T diag(sigma_i^2) A (A^T A)^{-1}
        ata_inv = np.linalg.inv(a_mat.T @ a_mat)
        sig2 = np.diag([1.0 / w for w in weights])
        return ata_inv @ a_mat.T @ sig2 @ a_mat @ ata_inv

    cov_diff = half_cov(origins[0::2]) + half_cov(origins[1::2])
    rng = np.random.default_rng(0)
    analytic_samples = rng.multivariate_normal(np.zeros(2), cov_diff, size=10000)
    analytic_p50 = float(np.median(np.linalg.norm(analytic_samples, axis=1)))

    # Simulate 200 Monte Carlo objects with 1 deg bearing noise
    noisy_objects = []
    for _ in range(200):
        rays = []
        for orig in origins:
            d = target - orig
            az = float(geo.enu_bearing_deg(d[0], d[1])) + float(rng.normal(0.0, 1.0))
            rays.append(tri.Ray(orig, az, 0.0))
        noisy_objects.append(rays)

    res_noisy = lf.split_half_location(noisy_objects)
    assert res_noisy["n_valid"] == 200
    assert abs(res_noisy["p50_m"] - analytic_p50) / analytic_p50 <= 0.30


def test_repeat_pairs_parallel_different_dates_same_date_and_20m_offset():
    t_day1 = dt.datetime(2024, 5, 1, 12, 0, tzinfo=dt.timezone.utc)
    t_day2 = dt.datetime(2024, 6, 15, 14, 0, tzinfo=dt.timezone.utc)

    # 12 panos at 10 m spacing = 110 m drive (>= 80 m overlap)
    fr1 = sim.synthetic_frames(12, 10.0, 40.0, -105.0, travel_deg=0.0, seq_id="A", t0=t_day1)
    # 2 m east offset (~2e-5 deg lng) on a different day -> 1 repeat pair
    _, lng_2m, _ = geo.enu_to_lla(2.0, 0.0, 0.0, 40.0, -105.0, 0.0)
    fr2 = sim.synthetic_frames(12, 10.0, 40.0, float(lng_2m), travel_deg=0.0, seq_id="B", t0=t_day2)
    seqs_diff_day = sequence.build_sequences(pd.concat([fr1, fr2], ignore_index=True))
    pairs = lf.repeat_pairs(seqs_diff_day)
    assert len(pairs) == 1
    assert pairs[0]["overlap_m"] >= 80.0

    # Same capture date (e.g. 2 hours later on the same day) -> 0 pairs
    t_same_day = dt.datetime(2024, 5, 1, 15, 0, tzinfo=dt.timezone.utc)
    fr_same = sim.synthetic_frames(
        12, 10.0, 40.0, float(lng_2m), travel_deg=0.0, seq_id="C", t0=t_same_day
    )
    seqs_same_day = sequence.build_sequences(pd.concat([fr1, fr_same], ignore_index=True))
    assert len(lf.repeat_pairs(seqs_same_day)) == 0

    # 20 m lateral offset (> 15 m threshold) on different dates -> 0 pairs
    _, lng_20m, _ = geo.enu_to_lla(20.0, 0.0, 0.0, 40.0, -105.0, 0.0)
    fr_far = sim.synthetic_frames(
        12, 10.0, 40.0, float(lng_20m), travel_deg=0.0, seq_id="D", t0=t_day2
    )
    seqs_far = sequence.build_sequences(pd.concat([fr1, fr_far], ignore_index=True))
    assert len(lf.repeat_pairs(seqs_far)) == 0


def test_blocks_and_perturbations_are_deterministic():
    fr = sim.synthetic_frames(12, 10.0, 40.0, -105.0, travel_deg=0.0, seq_id="S0")
    seqs = sequence.build_sequences(fr)
    b1 = lf.blocks(seqs, block_size=5)
    b2 = lf.blocks(seqs, block_size=5)
    assert b1 == b2
    assert len(b1) == 12
    # 12 panos in blocks of 5 -> 3 distinct blocks (5, 5, 2)
    assert len(set(b1.values())) == 3

    p1 = lf.perturbations(seed=7, n=3)
    p2 = lf.perturbations(seed=7, n=3)
    p3 = lf.perturbations(seed=8, n=3)
    assert p1 == p2 and p1 != p3
    assert len(p1) == 3
    for p in p1:
        assert -3.0 <= p["yaw_delta_deg"] <= 3.0
        assert 0.90 <= p["hfov_scale"] <= 1.10
        assert isinstance(p["gemini_seed"], int)
