"""Synthetic unit tests for svi_geo.cvchecks (Gemini-independent OpenCV checks, Task T4)."""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from svi_geo import cvchecks as cvc
from svi_geo import rosette


def test_vertical_post_support_pole_gradient_and_tilted_line():
    h, w = 400, 400
    # 1. Drawn 4 px vertical pole inside box -> support >= 0.6 of box height
    img_pole = np.full((h, w, 3), 180, dtype=np.uint8)
    cv2.rectangle(img_pole, (198, 80), (202, 320), (40, 40, 40), -1)
    box = (185.0, 80.0, 215.0, 320.0)
    sup = cvc.vertical_post_support(img_pole, box)
    assert sup >= 0.6

    # 2. Smooth gradient -> 0.0
    grad = np.tile(np.linspace(50, 200, w, dtype=np.uint8)[None, :], (h, 1))
    img_grad = cv2.merge([grad, grad, grad])
    assert cvc.vertical_post_support(img_grad, box) == pytest.approx(0.0)

    # 3. Line tilted by 25 deg (> 10 deg limit) -> 0.0
    img_tilt = np.full((h, w, 3), 180, dtype=np.uint8)
    dx = int(round(240 * math.tan(math.radians(25.0))))
    cv2.line(img_tilt, (200 - dx // 2, 80), (200 + dx // 2, 320), (30, 30, 30), 4)
    assert cvc.vertical_post_support(img_tilt, box, max_tilt_deg=10.0) == pytest.approx(0.0)


def test_sky_mask_and_sky_contact():
    h, w = 600, 800
    img = np.zeros((h, w, 3), dtype=np.uint8)
    horizon = 350
    # Smooth bright blue sky in top 250 rows, textured house wall from row 250..500
    img[:250] = (235, 195, 135)
    rng = np.random.default_rng(7)
    wall = np.clip(140 + rng.normal(0, 22, (350, w, 3)), 10, 250).astype(np.uint8)
    img[250:] = wall

    gt_sky = np.zeros((h, w), dtype=bool)
    gt_sky[:250] = True
    pred_sky = cvc.sky_mask(img, horizon_row=horizon)
    inter = np.logical_and(gt_sky, pred_sky).sum()
    union = np.logical_or(gt_sky, pred_sky).sum()
    iou = float(inter / max(1, union))
    assert iou >= 0.90

    # Roofline at y=250 (directly under sky) -> sky_contact >= 0.8
    roofline = [(100.0, 250.0), (700.0, 250.0)]
    assert cvc.sky_contact(img, roofline, horizon_row=horizon) >= 0.80

    # Siding line at y=340 (under textured wall) -> sky_contact <= 0.1
    siding = [(100.0, 340.0), (700.0, 340.0)]
    assert cvc.sky_contact(img, siding, horizon_row=horizon) <= 0.10


def test_horizontal_vp_and_vp_alignment():
    h, w = 600, 800
    img = np.full((h, w, 3), 200, dtype=np.uint8)
    true_vp = (720.0, 300.0)
    # Draw 8 converging facade lines from x=80..520 aimed at true_vp
    for y_left in np.linspace(120, 480, 8):
        slope = (true_vp[1] - y_left) / (true_vp[0] - 80.0)
        y_right = y_left + slope * (520.0 - 80.0)
        cv2.line(img, (80, int(round(y_left))), (520, int(round(y_right))), (30, 30, 30), 3)

    vp = cvc.horizontal_vp(img, seed=0)
    assert vp is not None
    assert abs(vp[0] - true_vp[0]) <= 0.02 * w

    # A segment aimed at true_vp has alignment ~0 deg; a 30 deg tilted segment is ~30 deg off
    aligned_seg = [(100.0, 300.0), (400.0, 300.0)]
    assert cvc.vp_alignment(aligned_seg, true_vp) == pytest.approx(0.0, abs=0.5)
    dy = 50.0 * math.tan(math.radians(30.0))
    tilted_seg = [(200.0, 300.0 - dy), (300.0, 300.0 + dy)]
    assert cvc.vp_alignment(tilted_seg, true_vp) == pytest.approx(30.0, abs=0.5)


def test_ground_ipm_round_trip_and_kerb_evidence():
    view = rosette.PerspectiveView(
        yaw_deg=35.0, pitch_deg=-22.0, hfov_deg=70.0, width=1024, height=768
    )
    cam_h = 2.5

    # Pixel -> ground -> pixel round trip within 0.5 px
    for u_in, v_in in [(512.0, 520.0), (320.0, 460.0), (740.0, 610.0)]:
        gx, gy = cvc.pixel_to_ground(view, u_in, v_in, cam_height_m=cam_h)
        u_out, v_out, ok = cvc.ground_to_pixel(view, gx, gy, cam_height_m=cam_h)
        assert ok
        assert math.hypot(u_out - u_in, v_out - v_in) <= 0.5

    # Render a synthetic road scene with a bright kerb line at x_lat = -3.0 m (left of travel)
    rng = np.random.default_rng(11)
    img = np.clip(90 + rng.normal(0, 6, (view.height, view.width, 3)), 10, 240).astype(np.uint8)
    uniform_img = img.copy()

    pts = []
    for y_fwd in np.linspace(3.5, 18.0, 40):
        u, v, ok = cvc.ground_to_pixel(view, -3.0, float(y_fwd), cam_height_m=cam_h)
        if ok:
            pts.append([int(round(u)), int(round(v))])
    pts_arr = np.array(pts, dtype=np.int32)
    cv2.polylines(img, [pts_arr], isClosed=False, color=(235, 235, 235), thickness=5)

    ev_left = cvc.kerb_evidence(img, view, side="LEFT", cam_height_m=cam_h)
    assert ev_left["present"] is True
    assert ev_left["lateral_m"] is not None
    assert abs(abs(ev_left["lateral_m"]) - 3.0) <= 0.30

    ev_uniform = cvc.kerb_evidence(uniform_img, view, side="LEFT", cam_height_m=cam_h)
    assert ev_uniform["present"] is False
    assert ev_uniform["lateral_m"] is None


def test_road_descriptor_identical_and_asphalt_vs_brick():
    rng = np.random.default_rng(3)
    # Smooth dark grey asphalt
    asphalt = np.clip(75 + rng.normal(0, 4, (128, 128, 3)), 10, 245).astype(np.uint8)
    # Textured reddish-brown brick pattern
    brick = np.full((128, 128, 3), (60, 85, 175), dtype=np.uint8)
    for y in range(0, 128, 16):
        cv2.line(brick, (0, y), (127, y), (200, 200, 200), 2)
        offset = 16 if (y // 16) % 2 else 0
        for x in range(offset, 128, 32):
            cv2.line(brick, (x, y), (x, min(127, y + 16)), (200, 200, 200), 2)

    d_asphalt = cvc.road_descriptor(asphalt)
    assert cvc.descriptor_distance(d_asphalt, cvc.road_descriptor(asphalt.copy())) == pytest.approx(
        0.0, abs=1e-9
    )
    d_brick = cvc.road_descriptor(brick)
    assert cvc.descriptor_distance(d_asphalt, d_brick) > cvc.DESCRIPTOR_DIFF_THRESHOLD


def test_placebo_boxes_seeded_and_redaction_masking():
    b1 = cvc.placebo_boxes(10, 800, 600, seed=42)
    b2 = cvc.placebo_boxes(10, 800, 600, seed=42)
    b3 = cvc.placebo_boxes(10, 800, 600, seed=43)
    assert b1 == b2 and b1 != b3
    assert len(b1) == 10
    for x0, y0, x1, y1 in b1:
        assert 0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 600

    # Exact-zero redaction pixels and valid_mask=False pixels are ignored by checks
    h, w = 300, 300
    img = np.full((h, w, 3), 180, dtype=np.uint8)
    cv2.rectangle(img, (148, 40), (152, 260), (40, 40, 40), -1)
    box = (135.0, 40.0, 165.0, 260.0)
    assert cvc.vertical_post_support(img, box) >= 0.6

    # Masking out the box via valid_mask drops support to 0
    mask = np.ones((h, w), dtype=bool)
    mask[:, 130:170] = False
    assert cvc.vertical_post_support(img, box, valid_mask=mask) == pytest.approx(0.0)

    # Exact-zero redaction inside the box drops support to 0
    redacted = img.copy()
    redacted[:, 130:170] = 0
    assert cvc.vertical_post_support(redacted, box) == pytest.approx(0.0)


def test_street_tree_support_distinguishes_tree_from_pole_and_sky():
    h, w = 400, 400
    # 1. Synthetic tree: green textured canopy in top 60% + dark vertical trunk in bottom 45%
    img_tree = np.full((h, w, 3), (220, 195, 175), dtype=np.uint8)  # sky background
    rng = np.random.default_rng(19)
    canopy = np.zeros((160, 120, 3), dtype=np.uint8)
    canopy[..., 0] = rng.integers(25, 65, size=(160, 120))  # B
    canopy[..., 1] = rng.integers(110, 185, size=(160, 120))  # G (dominant)
    canopy[..., 2] = rng.integers(30, 80, size=(160, 120))  # R
    img_tree[60:220, 140:260] = canopy
    cv2.rectangle(img_tree, (194, 200), (206, 350), (35, 45, 55), -1)  # trunk
    box_tree = (135.0, 55.0, 265.0, 355.0)
    sup_tree = cvc.street_tree_support(img_tree, box_tree)
    assert sup_tree >= 0.45

    # 2. Bare grey pole without green canopy -> low tree support (< 0.20)
    img_pole = np.full((h, w, 3), 180, dtype=np.uint8)
    cv2.rectangle(img_pole, (198, 60), (202, 350), (40, 40, 40), -1)
    assert cvc.street_tree_support(img_pole, box_tree) < 0.20

    # 3. Uniform blue sky -> 0.0
    img_sky = np.full((h, w, 3), (235, 195, 135), dtype=np.uint8)
    assert cvc.street_tree_support(img_sky, box_tree) == pytest.approx(0.0, abs=0.05)
