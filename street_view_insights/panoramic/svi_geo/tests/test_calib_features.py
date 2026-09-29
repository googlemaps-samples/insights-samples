"""Zero-mock tests for calibration image features (synthetic images)."""

import cv2
import numpy as np

from svi_geo import calib_features as cf


def _textured(h=400, w=300, seed=0):
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(rng.integers(0, 255, (h, w), dtype=np.uint8), (0, 0), 2)
    return cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)


def test_detect_maps_reduced_coords_to_full_resolution():
    full = _textured(800, 600)
    half = cv2.resize(full, (300, 400), interpolation=cv2.INTER_AREA)
    ff = cf.detect(full, 1.0, n=500)
    fh = cf.detect(half, 0.5, n=500)
    assert len(ff.uv) > 50 and len(fh.uv) > 20
    # every half-res keypoint lands near some full-res keypoint
    d = np.linalg.norm(fh.uv[:, None, :] - ff.uv[None, :, :], axis=-1).min(1)
    assert np.median(d) < 3.0
    assert fh.uv[:, 0].max() > 300  # really in full-res units


def test_ratio_match_finds_identity_on_shifted_image():
    img = _textured()
    shifted = np.roll(img, (7, -5), axis=(0, 1))
    f1, f2 = cf.detect(img, 1.0, n=800), cf.detect(shifted, 1.0, n=800)
    i1, i2 = cf.ratio_match(f1.desc, f2.desc)
    assert len(i1) > 50
    disp = f2.uv[i2] - f1.uv[i1]
    good = np.linalg.norm(disp - [-5, 7], axis=1) < 1.5
    assert good.mean() > 0.9


def test_angular_inliers_and_angle():
    a = np.array([[0, 0, 1.0], [0, 0, 1.0]])
    b = np.array([[0, np.sin(np.radians(1)), np.cos(np.radians(1))], [0, 1.0, 1.0]])
    np.testing.assert_allclose(cf.angle_between_deg(a, b), [1.0, 45.0], atol=1e-9)
    assert list(cf.angular_inliers(a, b, 2.5)) == [True, False]


def test_essential_inliers_reject_outliers():
    rng = np.random.default_rng(1)
    X = np.c_[rng.uniform(-8, 8, 200), rng.uniform(-3, 3, 200), rng.uniform(10, 50, 200)]
    t = np.array([0.3, 0.0, 10.0])
    ra = X / np.linalg.norm(X, axis=1, keepdims=True)
    xb = X - t
    xb = xb[:, [0, 1, 2]]
    rb = xb / np.linalg.norm(xb, axis=1, keepdims=True)
    keep = rb[:, 2] > 0.3
    ra, rb = ra[keep], rb[keep]
    n_out = 30
    rb[:n_out] = rb[rng.permutation(len(rb))[:n_out]]
    inl = cf.essential_inliers(ra, rb, thr_deg=0.2)
    assert inl[n_out:].mean() > 0.95
    assert inl[:n_out].mean() < 0.3


def test_edge_chains_keep_long_lines_and_drop_short_ones():
    img = np.full((400, 300), 30, np.uint8)
    cv2.rectangle(img, (100, -10), (310, 410), 220, -1)  # long vertical edge at x=100
    cv2.rectangle(img, (10, 10), (30, 30), 220, -1)  # small blob: short edges
    chains = cf.edge_chains(img, 0.5, min_len_px=250)
    assert len(chains) >= 1
    longest = max(chains, key=len)
    xs = longest[:, 0]
    # full-res x of the edge ~ (100 + 0.5) / 0.5 - 0.5 ~= 200 (+- a Canny pixel)
    assert np.all(np.abs(xs - 200) < 4)
    assert np.ptp(longest[:, 1]) > 600
