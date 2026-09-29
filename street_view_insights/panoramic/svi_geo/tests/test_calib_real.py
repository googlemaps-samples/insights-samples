"""Zero-mock tests for the real-data calibration problem builder (synthetic geometry)."""

import dataclasses
import math

import numpy as np
import pandas as pd

from svi_geo import calib_real, calibrate, geo, rosette
from svi_geo.calib_real import FrameFeatures

INTR = rosette.Intrinsics(
    width=3648, height=5472, fx=1750.0, fy=1750.0, cx=1824.0, cy=2800.0, max_theta_deg=95.0
)
REF = (48.8, 2.37, 50.0)


def _frames(n_panos=2, r=0.08, spacing=10.0):
    rows = []
    for i in range(n_panos):
        ce, cn = 0.0, i * spacing
        for k in range(6):
            h = (60.0 * k) % 360
            e = ce + r * math.sin(math.radians(h))
            n = cn + r * math.cos(math.radians(h))
            lat, lng, alt = geo.enu_to_lla(e, n, 0.0, *REF)
            rows.append(
                {
                    "pano_id": f"P{i}",
                    "cam_k": k,
                    "heading": h,
                    "pitch": 9.0 if k % 2 == 0 else -9.0,
                    "roll": 0.0,
                    "cam_lat": float(lat),
                    "cam_lng": float(lng),
                    "cam_alt": float(alt),
                    "aoi": "a",
                }
            )
    return pd.DataFrame(rows)


def test_instances_measure_radius_and_share_pano_centre():
    inst = calib_real.instances_from_frames(_frames(r=0.08))
    assert len(inst.instances) == 12
    assert abs(inst.radius_m - 0.08) < 1e-3
    c0 = [i.center_enu for i in inst.instances if i.pano_id == "P0"]
    c1 = [i.center_enu for i in inst.instances if i.pano_id == "P1"]
    np.testing.assert_allclose(c0[0], c0[5], atol=1e-9)
    assert abs(np.linalg.norm(c1[0] - c0[0]) - 10.0) < 0.01
    assert inst.index[("P1", 3)] == 9


def _synthetic_features(inst, intr, n=400, seed=0, outliers=40):
    """Project random 3D points into every frame; shared random descriptors per point."""
    rng = np.random.default_rng(seed)
    az = rng.uniform(0, 360, n)
    el = rng.uniform(-20, 30, n)
    dist = rng.uniform(8, 40, n)
    pts = dist[:, None] * rosette.bearing_to_dir(az, el)
    desc = rng.normal(size=(n, 128)).astype(np.float32)
    out = {}
    for ci in inst.instances:
        R = rosette.cam_rotation(ci.heading, ci.pitch, ci.roll, (1, 1))
        h = math.radians(ci.heading)
        C = ci.center_enu + inst.radius_m * np.array([math.sin(h), math.cos(h), 0.0])
        d_cam = (pts - C) @ R
        uv = rosette.project(intr, d_cam)
        th = np.degrees(np.arccos(np.clip(d_cam[:, 2] / np.linalg.norm(d_cam, axis=1), -1, 1)))
        ok = (th < 90) & (uv[:, 0] > 0) & (uv[:, 0] < intr.width) & (uv[:, 1] > 0)
        ok &= uv[:, 1] < intr.height
        u, d = uv[ok], desc[ok].copy()
        # corrupt some correspondences: swap descriptors between points in this view
        j = rng.choice(len(u), min(outliers, len(u)), replace=False)
        d[j] = d[rng.permutation(j)]
        out[(ci.pano_id, ci.cam_k)] = FrameFeatures(u, d, [])
    return out


def test_intra_matches_angular_filter_keeps_true_correspondences():
    inst = calib_real.instances_from_frames(_frames(n_panos=1))
    feats = _synthetic_features(inst, INTR)
    ms = calib_real.intra_matches(
        inst, lambda p, k: feats[(p, k)], ["P0"], INTR.width, intr=INTR, thr_deg=1.0
    )
    prob = ms.problem(inst, INTR.width, INTR.height, 0, [])
    assert prob.n_intra > 50
    # every kept match is geometrically consistent under the true model
    truth = dataclasses.replace(INTR, rosette_radius_m=inst.radius_m)
    err = calibrate.heldout_match_errors(prob, truth)
    assert np.percentile(err, 95) < 0.5


def test_sequence_matches_between_consecutive_panos():
    inst = calib_real.instances_from_frames(_frames(n_panos=2))
    feats = _synthetic_features(inst, INTR, n=800, outliers=30)
    ms = calib_real.sequence_matches(
        inst, lambda p, k: feats[(p, k)], [("P0", "P1")], INTR, thr_deg=0.3, min_inliers=10
    )
    prob = ms.problem(inst, INTR.width, INTR.height, 1, [])
    assert prob.n_seq > 30
    assert set(prob.m_pair.tolist()) == {0}


def test_select_chains_tags_vertical_lines():
    inst = calib_real.instances_from_frames(_frames(n_panos=1))
    ci = inst.instances[0]  # heading 0, pitch +9
    R = rosette.cam_rotation(ci.heading, ci.pitch, ci.roll, (1, 1))
    C = ci.center_enu + inst.radius_m * np.array([0.0, 1.0, 0.0])
    vert = np.array([2.0, 12.0, 0.0]) + np.linspace(-2, 6, 60)[:, None] * [0, 0, 1.0]
    horiz = np.array([-6.0, 12.0, 3.0]) + np.linspace(0, 8, 60)[:, None] * [1.0, 0, 0]
    raw = []
    for pts in (vert, horiz):
        raw.append((0, rosette.project(INTR, (pts - C) @ R)))
    chains = calib_real.select_chains(inst, INTR, raw)
    assert len(chains) == 2
    assert sum(c.vertical for c in chains) == 1
    # a curved chain (circle arc) is rejected as not straight
    t = np.linspace(0, math.pi, 60)
    arc = np.stack([1824 + 600 * np.cos(t), 2800 + 600 * np.sin(t)], -1)
    assert calib_real.select_chains(inst, INTR, [(0, arc)]) == []
