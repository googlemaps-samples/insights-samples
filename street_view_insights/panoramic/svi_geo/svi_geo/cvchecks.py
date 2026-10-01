"""Gemini-independent OpenCV checks for street-view views (pure cv2/numpy, no network).

All checks mask exact-zero redaction pixels (`(img == 0).all(axis=-1)`) and pixels outside
`valid_mask` (eroded to avoid spurious sensor-edge gradients).

* `vertical_post_support` / `sign_post_support`: vertical LSD line coverage inside a pole box
  or in the vertical strip below a road-sign plate.
* `sky_mask` / `sky_contact`: smooth bright low-saturation/blue sky mask and fraction of a
  roofline or box top edge backed by sky immediately above it.
* `horizontal_vp` / `vp_alignment`: RANSAC vanishing point of near-horizontal facade LSD
  segments and angular residual (degrees) of a segment from the ray to that vanishing point.
* `pixel_to_ground` / `ground_to_pixel` / `ground_ipm` / `kerb_evidence`: exact ground-plane
  inverse perspective mapping using `rosette.PerspectiveView` and kerb line detection at
  1.5-6.0 m lateral offset.
* `road_descriptor` / `descriptor_distance`: CIE Lab statistics + 8-neighbour LBP histogram
  on valid road patches.
* `placebo_boxes`: seeded random boxes for placebo baseline comparisons.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np

from svi_geo import rosette

DESCRIPTOR_DIFF_THRESHOLD = 0.25


def _usable_mask(
    img: np.ndarray, valid_mask: np.ndarray | None = None, erode_px: int = 3
) -> np.ndarray:
    """Boolean mask of non-redacted (not exact-zero) pixels inside `valid_mask`."""
    non_zero = np.any(img != 0, axis=-1) if img.ndim == 3 else (img != 0)
    mask = non_zero if valid_mask is None else (non_zero & np.asarray(valid_mask, dtype=bool))
    if erode_px > 0:
        k = 2 * int(erode_px) + 1
        mask = cv2.erode(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    return mask


def _detect_lsd(gray: np.ndarray) -> np.ndarray:
    """(N, 4) float64 array of (x1, y1, x2, y2) LSD segments."""
    det = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    lines = det.detect(gray)[0]
    if lines is None:
        return np.zeros((0, 4), dtype=np.float64)
    return lines.reshape(-1, 4).astype(np.float64)


def _interval_union_length(intervals: list[tuple[float, float]], lo: float, hi: float) -> float:
    if not intervals or hi <= lo:
        return 0.0
    clipped = []
    for a, b in intervals:
        s, e = max(lo, min(a, b)), min(hi, max(a, b))
        if e > s:
            clipped.append((s, e))
    if not clipped:
        return 0.0
    clipped.sort()
    total = 0.0
    cur_s, cur_e = clipped[0]
    for s, e in clipped[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
    total += cur_e - cur_s
    return total


def vertical_post_support(
    img: np.ndarray,
    box: Sequence[float],
    max_tilt_deg: float = 10.0,
    valid_mask: np.ndarray | None = None,
    pad_px: int = 6,
) -> float:
    """Fraction of the box height `[y0, y1]` supported by near-vertical LSD segments (`<= max_tilt_deg`)."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (float(v) for v in box)
    x0, x1 = max(0.0, min(x0, x1)), min(float(w), max(x0, x1))
    y0, y1 = max(0.0, min(y0, y1)), min(float(h), max(y0, y1))
    box_h = y1 - y0
    if box_h < 4.0 or x1 - x0 < 2.0:
        return 0.0

    usable = _usable_mask(img, valid_mask, erode_px=2)
    ix0 = max(0, int(math.floor(x0)) - pad_px)
    ix1 = min(w, int(math.ceil(x1)) + pad_px)
    iy0 = max(0, int(math.floor(y0)))
    iy1 = min(h, int(math.ceil(y1)))
    if iy1 - iy0 < 4 or ix1 - ix0 < 2:
        return 0.0

    crop = img[iy0:iy1, ix0:ix1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    segs = _detect_lsd(gray)
    if len(segs) == 0:
        return 0.0

    tan_max = math.tan(math.radians(float(max_tilt_deg)))
    intervals: list[tuple[float, float]] = []
    for ax, ay, bx, by in segs:
        gx1, gy1 = ax + ix0, ay + iy0
        gx2, gy2 = bx + ix0, by + iy0
        mx, my = 0.5 * (gx1 + gx2), 0.5 * (gy1 + gy2)
        if not (x0 - pad_px <= mx <= x1 + pad_px and y0 <= my <= y1):
            continue
        imy = int(np.clip(round(my), 0, h - 1))
        imx = int(np.clip(round(mx), 0, w - 1))
        if not usable[imy, imx]:
            continue
        dx = abs(gx2 - gx1)
        dy = abs(gy2 - gy1)
        if dy < 4.0 or dx > dy * tan_max:
            continue
        intervals.append((min(gy1, gy2), max(gy1, gy2)))

    covered = _interval_union_length(intervals, y0, y1)
    return float(np.clip(covered / box_h, 0.0, 1.0))


def sign_post_support(
    img: np.ndarray,
    box: Sequence[float],
    max_tilt_deg: float = 10.0,
    valid_mask: np.ndarray | None = None,
) -> float:
    """Vertical post support inside or directly beneath a sign plate box."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (float(v) for v in box)
    in_box = vertical_post_support(
        img, (x0, y0, x1, y1), max_tilt_deg=max_tilt_deg, valid_mask=valid_mask
    )
    bw = max(8.0, x1 - x0)
    bh = max(12.0, y1 - y0)
    xc = 0.5 * (x0 + x1)
    strip = (
        max(0.0, xc - 0.5 * bw),
        min(float(h - 1), y1),
        min(float(w), xc + 0.5 * bw),
        min(float(h), y1 + 2.0 * bh),
    )
    below = vertical_post_support(img, strip, max_tilt_deg=max_tilt_deg, valid_mask=valid_mask)
    return max(in_box, below)


def street_tree_support(
    img: np.ndarray,
    box: Sequence[float],
    valid_mask: np.ndarray | None = None,
) -> float:
    """OpenCV foliage + trunk support in `[0, 1]` for a `STREET_TREE` box `(x0, y0, x1, y1)`.

    Combines:
    1. Canopy foliage fraction in the upper 65 % of the box (Excess Green `2G - R - B >= 18` or
       HSV green/olive hue `25 <= H <= 95` with saturation `S >= 30` and texture std `>= 6`).
    2. Vertical trunk / branch edge support in the lower 55 % of the box (vertical Sobel `|Gx|`
       dominance or vertical LSD segments).
    """
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (float(v) for v in box)
    ix0 = max(0, int(math.floor(min(x0, x1))))
    ix1 = min(w, int(math.ceil(max(x0, x1))))
    iy0 = max(0, int(math.floor(min(y0, y1))))
    iy1 = min(h, int(math.ceil(max(y0, y1))))
    if iy1 - iy0 < 12 or ix1 - ix0 < 8:
        return 0.0

    usable = _usable_mask(img, valid_mask, erode_px=1)[iy0:iy1, ix0:ix1]
    if not np.any(usable):
        return 0.0

    crop = img[iy0:iy1, ix0:ix1]
    ch, cw = crop.shape[:2]
    top_end = max(4, int(round(0.65 * ch)))
    bot_start = min(ch - 4, int(round(0.45 * ch)))

    # 1. Canopy foliage score in upper 65%
    canopy = crop[:top_end]
    canopy_usable = usable[:top_end]
    b = canopy[..., 0].astype(np.float32)
    g = canopy[..., 1].astype(np.float32)
    r = canopy[..., 2].astype(np.float32)
    exg = 2.0 * g - r - b
    hsv = cv2.cvtColor(canopy, cv2.COLOR_BGR2HSV)
    green_hsv = (
        (hsv[..., 0] >= 22) & (hsv[..., 0] <= 98) & (hsv[..., 1] >= 28) & (hsv[..., 2] >= 25)
    )
    tex = rosette.textured_mask(canopy, ksize=7, min_std=5.5)
    foliage_mask = ((exg >= 14.0) | green_hsv) & tex & canopy_usable
    denom = max(1, int(canopy_usable.sum()))
    foliage_frac = float(foliage_mask.sum() / denom)
    canopy_score = float(np.clip(foliage_frac / 0.30, 0.0, 1.0))

    # 2. Vertical trunk / stem edge energy in lower 55%
    lower = crop[bot_start:]
    lower_usable = usable[bot_start:]
    gray_low = cv2.cvtColor(lower, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = np.abs(cv2.Sobel(gray_low, cv2.CV_32F, 1, 0, ksize=3))
    gy = np.abs(cv2.Sobel(gray_low, cv2.CV_32F, 0, 1, ksize=3))
    vert_edge = (gx > 18.0) & (gx > 1.15 * gy) & lower_usable
    vert_frac = float(vert_edge.sum() / max(1, int(lower_usable.sum())))
    trunk_sobel = float(np.clip(vert_frac / 0.08, 0.0, 1.0))
    trunk_lsd = vertical_post_support(
        img,
        (x0, y0 + 0.35 * (y1 - y0), x1, y1),
        max_tilt_deg=18.0,
        valid_mask=valid_mask,
    )
    trunk_score = max(trunk_sobel, trunk_lsd)
    trunk_gate = min(1.0, canopy_score / 0.25)

    return float(np.clip(0.65 * canopy_score + 0.35 * trunk_score * trunk_gate, 0.0, 1.0))


def sky_mask(
    img: np.ndarray,
    horizon_row: float | None = None,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Boolean mask of smooth, bright, low-saturation or blue sky pixels above `horizon_row`."""
    h, w = img.shape[:2]
    row = int(round(0.65 * h)) if horizon_row is None else int(np.clip(round(horizon_row), 0, h))
    usable = _usable_mask(img, valid_mask, erode_px=0)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    bright = hsv[..., 2] >= 100
    blue_or_grey = ((hsv[..., 0] >= 85) & (hsv[..., 0] <= 135)) | (hsv[..., 1] <= 45)
    smooth = ~rosette.textured_mask(img, ksize=11, min_std=7.5)
    sky = bright & blue_or_grey & smooth & usable
    sky[row:] = False
    return sky


def sky_contact(
    img: np.ndarray,
    polyline_or_box: Sequence[Any],
    horizon_row: float | None = None,
    valid_mask: np.ndarray | None = None,
    band_px: int = 14,
) -> float:
    """Share of samples along a polyline `[(x, y), ...]` or box top `(x0, y0, x1, y1)` whose
    vertical strip `[y - band_px, y - 2]` above the edge contains sky pixels."""
    h, w = img.shape[:2]
    sky = sky_mask(img, horizon_row=horizon_row, valid_mask=valid_mask)
    usable = _usable_mask(img, valid_mask, erode_px=1)

    if len(polyline_or_box) == 4 and isinstance(polyline_or_box[0], (int, float, np.floating)):
        x0, y0, x1, _y1 = (float(v) for v in polyline_or_box)
        pts = np.array([[x0, y0], [x1, y0]], dtype=float)
    else:
        pts = np.asarray(polyline_or_box, dtype=float).reshape(-1, 2)
    if len(pts) < 2:
        return 0.0

    hits = 0
    total = 0
    for a, b in zip(pts[:-1], pts[1:], strict=True):
        seg_len = float(np.linalg.norm(b - a))
        n = max(2, int(seg_len / 3.0) + 1)
        ts = np.linspace(0.0, 1.0, n)
        samples = a[None, :] * (1.0 - ts)[:, None] + b[None, :] * ts[:, None]
        for sx, sy in samples:
            ix = int(np.clip(round(sx), 0, w - 1))
            iy = int(np.clip(round(sy), 0, h - 1))
            if not usable[iy, ix]:
                continue
            y_hi = max(0, iy - 2)
            y_lo = max(0, iy - int(band_px))
            if y_hi <= y_lo:
                continue
            total += 1
            if np.any(sky[y_lo:y_hi, ix]):
                hits += 1
    return float(hits / total) if total > 0 else 0.0


def vp_alignment(segment: Sequence[Sequence[float]], vp: tuple[float, float]) -> float:
    """Angle in degrees `[0, 90]` between `segment` `[(x1, y1), (x2, y2)]` and the ray from its
    midpoint to `vp`."""
    pts = np.asarray(segment, dtype=float).reshape(-1, 2)
    p1, p2 = pts[0], pts[-1]
    d = p2 - p1
    norm_d = float(np.linalg.norm(d))
    if norm_d < 1e-9:
        return 90.0
    mid = 0.5 * (p1 + p2)
    to_vp = np.asarray(vp, dtype=float) - mid
    norm_v = float(np.linalg.norm(to_vp))
    if norm_v < 1e-9:
        return 0.0
    cos = abs(float(np.dot(d, to_vp)) / (norm_d * norm_v))
    return float(math.degrees(math.acos(np.clip(cos, 0.0, 1.0))))


def horizontal_vp(
    img: np.ndarray,
    region: Sequence[float] | None = None,
    max_tilt_deg: float = 35.0,
    min_len_px: float = 25.0,
    valid_mask: np.ndarray | None = None,
    seed: int = 0,
    inlier_tol_deg: float = 2.0,
) -> tuple[float, float] | None:
    """RANSAC horizontal vanishing point `(vx, vy)` from LSD line segments in `img` (or `region`)."""
    h, w = img.shape[:2]
    usable = _usable_mask(img, valid_mask, erode_px=2)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    raw = _detect_lsd(gray)
    if len(raw) == 0:
        return None

    x0, y0, x1, y1 = (
        (0.0, 0.0, float(w), float(h)) if region is None else (float(v) for v in region)
    )
    segs = []
    lengths = []
    for ax, ay, bx, by in raw:
        mx, my = 0.5 * (ax + bx), 0.5 * (ay + by)
        if not (x0 <= mx <= x1 and y0 <= my <= y1):
            continue
        imy = int(np.clip(round(my), 0, h - 1))
        imx = int(np.clip(round(mx), 0, w - 1))
        if not usable[imy, imx]:
            continue
        length = math.hypot(bx - ax, by - ay)
        if length < min_len_px:
            continue
        ang = abs(math.degrees(math.atan2(by - ay, bx - ax)))
        tilt = min(ang, abs(180.0 - ang))
        if tilt <= max_tilt_deg:
            segs.append(((ax, ay), (bx, by)))
            lengths.append(length)

    if len(segs) < 2:
        return None

    # Homogeneous lines l = p1 x p2
    hom = []
    for (ax, ay), (bx, by) in segs:
        line = np.cross([ax, ay, 1.0], [bx, by, 1.0])
        hom.append(line / max(math.hypot(line[0], line[1]), 1e-12))
    hom_arr = np.asarray(hom, dtype=float)
    weights = np.asarray(lengths, dtype=float)

    n = len(segs)
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    rng = np.random.default_rng(seed)
    if len(pairs) > 250:
        chosen = rng.choice(len(pairs), size=250, replace=False)
        pairs = [pairs[k] for k in chosen]

    best_vp: tuple[float, float] | None = None
    best_score = -1.0
    for i, j in pairs:
        pt = np.cross(hom_arr[i], hom_arr[j])
        if abs(pt[2]) < 1e-7:
            # Nearly parallel horizontal lines -> far horizontal VP
            cand = (1e6, 0.5 * (segs[i][0][1] + segs[j][0][1]))
        else:
            cand = (float(pt[0] / pt[2]), float(pt[1] / pt[2]))
        score = 0.0
        for s_idx, seg in enumerate(segs):
            err = vp_alignment(seg, cand)
            if err <= inlier_tol_deg:
                score += weights[s_idx] * (1.0 - 0.2 * (err / inlier_tol_deg))
        if score > best_score:
            best_score = score
            best_vp = cand

    return best_vp


def pixel_to_ground(
    view: rosette.PerspectiveView,
    u: float | np.ndarray,
    v: float | np.ndarray,
    cam_height_m: float = 2.5,
) -> tuple[Any, Any]:
    """Map view pixel(s) `(u, v)` to ground-plane coordinates `(x_right_m, y_fwd_m)` relative to
    `view.yaw_deg` on the horizontal plane `z = -cam_height_m`."""
    d_world = view.pixel_dirs(u, v)
    de, dn, du = d_world[..., 0], d_world[..., 1], d_world[..., 2]
    valid = du < -1e-6
    safe_du = np.where(valid, du, -1.0)
    t = np.where(valid, -float(cam_height_m) / safe_du, np.nan)
    e = t * de
    n = t * dn
    yaw_rad = math.radians(view.yaw_deg)
    sin_y, cos_y = math.sin(yaw_rad), math.cos(yaw_rad)
    x_right = e * cos_y - n * sin_y
    y_fwd = e * sin_y + n * cos_y
    if np.ndim(u) == 0 and np.ndim(v) == 0:
        return float(x_right), float(y_fwd)
    return x_right, y_fwd


def ground_to_pixel(
    view: rosette.PerspectiveView,
    x_right_m: float | np.ndarray,
    y_fwd_m: float | np.ndarray,
    cam_height_m: float = 2.5,
) -> tuple[Any, Any, Any]:
    """Project ground-plane point(s) `(x_right_m, y_fwd_m)` at `z = -cam_height_m` into `view`."""
    xr = np.asarray(x_right_m, dtype=np.float64)
    yf = np.asarray(y_fwd_m, dtype=np.float64)
    yaw_rad = math.radians(view.yaw_deg)
    sin_y, cos_y = math.sin(yaw_rad), math.cos(yaw_rad)
    e = xr * cos_y + yf * sin_y
    n = -xr * sin_y + yf * cos_y
    u_up = np.full_like(e, -float(cam_height_m))
    d_world = np.stack([e, n, u_up], axis=-1)
    az, el = rosette.dir_to_bearing(d_world)
    u, v, ok = view.bearing_to_pixel(az, el)
    if np.ndim(x_right_m) == 0 and np.ndim(y_fwd_m) == 0:
        return float(u), float(v), bool(ok)
    return u, v, ok


def ground_ipm(
    img: np.ndarray,
    view: rosette.PerspectiveView,
    cam_height_m: float = 2.5,
    x_range: tuple[float, float] = (-6.0, 6.0),
    y_range: tuple[float, float] = (3.5, 18.0),
    ppm: int = 20,
    valid_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Inverse perspective map (bird's-eye ground image and boolean valid mask) on `x_range` x `y_range`
    at `ppm` pixels per metre. Row 0 is `y_range[1]` (far), row H-1 is `y_range[0]` (near);
    col 0 is `x_range[0]` (left), col W-1 is `x_range[1]` (right)."""
    h_img, w_img = img.shape[:2]
    usable = _usable_mask(img, valid_mask, erode_px=1)
    out_w = max(8, int(round((x_range[1] - x_range[0]) * ppm)))
    out_h = max(8, int(round((y_range[1] - y_range[0]) * ppm)))
    xs = np.linspace(x_range[0], x_range[1], out_w, dtype=np.float64)
    ys = np.linspace(y_range[1], y_range[0], out_h, dtype=np.float64)
    gx, gy = np.meshgrid(xs, ys)
    u, v, ok = ground_to_pixel(view, gx, gy, cam_height_m=cam_height_m)
    in_bounds = ok & (u >= 0) & (u <= w_img - 1) & (v >= 0) & (v <= h_img - 1)
    map_x = np.where(in_bounds, u, -1.0).astype(np.float32)
    map_y = np.where(in_bounds, v, -1.0).astype(np.float32)
    warped = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    warped_mask = (
        cv2.remap(
            usable.astype(np.uint8),
            map_x,
            map_y,
            cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
        )
        > 0
    )
    warped[~warped_mask] = 0
    return warped, warped_mask


def kerb_evidence(
    img: np.ndarray,
    view: rosette.PerspectiveView,
    side: str = "LEFT",
    cam_height_m: float = 2.5,
    lat_band_m: tuple[float, float] = (1.5, 6.0),
    y_range_m: tuple[float, float] = (3.5, 18.0),
    ppm: int = 20,
    max_angle_deg: float = 12.0,
    min_support_m: float = 2.5,
    valid_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """Detect a kerb/walkway boundary line nearly parallel to travel in the ground-plane IPM."""
    side_u = side.upper()
    if side_u == "LEFT":
        x_range = (-float(lat_band_m[1]), -float(lat_band_m[0]))
    elif side_u == "RIGHT":
        x_range = (float(lat_band_m[0]), float(lat_band_m[1]))
    else:
        raise ValueError(f"side must be 'LEFT' or 'RIGHT', got {side!r}")

    ipm, mask = ground_ipm(
        img,
        view,
        cam_height_m=cam_height_m,
        x_range=x_range,
        y_range=y_range_m,
        ppm=ppm,
        valid_mask=valid_mask,
    )
    eroded = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    gray = cv2.cvtColor(ipm, cv2.COLOR_BGR2GRAY) if ipm.ndim == 3 else ipm
    segs = _detect_lsd(gray)
    if len(segs) == 0:
        return {"present": False, "lateral_m": None, "support_m": 0.0, "score": 0.0}

    tan_max = math.tan(math.radians(float(max_angle_deg)))
    h_ipm, w_ipm = gray.shape[:2]
    # Cluster vertical (travel-aligned) segments into lateral bins of width 0.25 m
    candidates: list[tuple[float, float, float]] = []  # (x_m, y_lo_m, y_hi_m)
    for ax, ay, bx, by in segs:
        mx, my = 0.5 * (ax + bx), 0.5 * (ay + by)
        imy = int(np.clip(round(my), 0, h_ipm - 1))
        imx = int(np.clip(round(mx), 0, w_ipm - 1))
        if not eroded[imy, imx]:
            continue
        dx = abs(bx - ax)
        dy = abs(by - ay)
        if dy < 0.8 * ppm or dx > dy * tan_max:
            continue
        x_m = x_range[0] + (mx / max(1, w_ipm - 1)) * (x_range[1] - x_range[0])
        y1_m = y_range_m[1] - (ay / max(1, h_ipm - 1)) * (y_range_m[1] - y_range_m[0])
        y2_m = y_range_m[1] - (by / max(1, h_ipm - 1)) * (y_range_m[1] - y_range_m[0])
        candidates.append((float(x_m), min(y1_m, y2_m), max(y1_m, y2_m)))

    if not candidates:
        return {"present": False, "lateral_m": None, "support_m": 0.0, "score": 0.0}

    best_support = 0.0
    best_lat = None
    for x_ref, _, _ in candidates:
        near = [(ylo, yhi) for xm, ylo, yhi in candidates if abs(xm - x_ref) <= 0.25]
        sup = _interval_union_length(near, y_range_m[0], y_range_m[1])
        if sup > best_support:
            best_support = sup
            near_x = [xm for xm, _, _ in candidates if abs(xm - x_ref) <= 0.25]
            best_lat = float(np.median(near_x))

    span = max(1e-6, y_range_m[1] - y_range_m[0])
    score = float(np.clip(best_support / span, 0.0, 1.0))
    present = bool(best_support >= min_support_m)
    return {
        "present": present,
        "lateral_m": best_lat if present else None,
        "support_m": float(best_support),
        "score": score,
    }


def _lbp_histogram(gray: np.ndarray, valid: np.ndarray, n_bins: int = 16) -> np.ndarray:
    """Normalized 8-neighbour Local Binary Pattern histogram on interior valid pixels."""
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return np.zeros(n_bins, dtype=np.float64)
    c = gray[1:-1, 1:-1]
    v = valid[1:-1, 1:-1]
    if not np.any(v):
        return np.zeros(n_bins, dtype=np.float64)
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]
    code = np.zeros_like(c, dtype=np.uint8)
    for bit, (dy, dx) in enumerate(offsets):
        nbr = gray[1 + dy : gray.shape[0] - 1 + dy, 1 + dx : gray.shape[1] - 1 + dx]
        code |= ((nbr >= c).astype(np.uint8)) << bit
    hist, _ = np.histogram(code[v], bins=n_bins, range=(0, 256))
    tot = float(hist.sum())
    return hist.astype(np.float64) / tot if tot > 0 else np.zeros(n_bins, dtype=np.float64)


def road_descriptor(patch: np.ndarray, valid_mask: np.ndarray | None = None) -> np.ndarray:
    """Normalized CIE Lab mean/std (6 dims) + 16-bin LBP histogram (22 dims total)."""
    usable = _usable_mask(patch, valid_mask, erode_px=0)
    if not np.any(usable):
        return np.zeros(22, dtype=np.float64)
    bgr = patch if patch.ndim == 3 else cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float64) / 255.0
    pix = lab[usable]
    means = np.mean(pix, axis=0)
    stds = np.std(pix, axis=0) * 2.5
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lbp = _lbp_histogram(gray, usable, n_bins=16)
    return np.concatenate([means, stds, lbp])


def descriptor_distance(d1: np.ndarray, d2: np.ndarray) -> float:
    """Euclidean distance between two `road_descriptor` vectors."""
    return float(
        np.linalg.norm(np.asarray(d1, dtype=np.float64) - np.asarray(d2, dtype=np.float64))
    )


def placebo_boxes(
    n: int,
    width: int,
    height: int,
    seed: int = 0,
    size_range: tuple[int, int] = (40, 160),
) -> list[tuple[float, float, float, float]]:
    """`n` deterministic random pixel boxes `(x0, y0, x1, y1)` inside `width x height`."""
    rng = np.random.default_rng(seed)
    lo_s = min(size_range[0], width // 2, height // 2)
    hi_w = max(lo_s + 1, min(size_range[1], width - 1))
    hi_h = max(lo_s + 1, min(size_range[1], height - 1))
    out: list[tuple[float, float, float, float]] = []
    for _ in range(int(n)):
        bw = float(rng.integers(lo_s, hi_w + 1))
        bh = float(rng.integers(lo_s, hi_h + 1))
        x0 = float(rng.uniform(0.0, max(1.0, width - bw)))
        y0 = float(rng.uniform(0.0, max(1.0, height - bh)))
        out.append((x0, y0, x0 + bw, y0 + bh))
    return out
