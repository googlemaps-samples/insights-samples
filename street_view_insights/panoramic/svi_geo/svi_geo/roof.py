"""Roof views and roof-edge validation (pure code; Gemini only proposes the polylines).

* `render_roof_view` renders a pinhole view with no black border (per-side FOV limits).
* `validate_roof_edges` accepts a proposed edge only where the image has an oriented
  gradient and a line segment along it, off foliage, sky and no-data pixels; accepted edges
  are snapped to the image lines. `random_acceptance` reports how often random segments of
  the same image (or of the roof band) pass, so every result carries its own false-accept
  baseline. The validator checks that a straight image edge exists where an edge was drawn,
  not that it is a roof edge; `decoy_acceptance` measures how often named non-roof lines
  (horizon, wall base, siding) pass.
"""

import dataclasses
import math
import warnings
from collections.abc import Mapping, Sequence
from typing import Any

import cv2
import numpy as np

from svi_geo import rosette

MIN_ROOF_HFOV_DEG = 8.0  # narrower views carry too little context to trace a roof


def render_roof_view(
    image: np.ndarray,
    intr: rosette.Intrinsics,
    camera_pose: Mapping[str, float],
    target_bearing_deg: float,
    cam_k: int,
    pitch_deg: float = 14.0,
    hfov_deg: float = 65.0,
    width: int = 1200,
    height: int = 900,
    max_black: float = 0.01,
) -> tuple[np.ndarray, rosette.PerspectiveView, float]:
    """Render a pinhole view towards `target_bearing_deg` from one rosette frame.

    The requested `hfov_deg` is narrowed with `rosette.max_view_fov` so that less than
    `max_black` of the view falls outside the sensor or the lens model (the limit is
    per side, not a symmetric half-FOV). Returns (image, view, black_fraction), the black
    fraction being the analytic share of view pixels without image data.

    Raises ValueError if this camera cannot show even a `MIN_ROOF_HFOV_DEG` view of the
    target; use `rosette.best_camera_for_view` to pick the camera first."""
    max_hfov, _ = rosette.max_view_fov(
        intr, camera_pose, cam_k, target_bearing_deg, pitch_deg, width / height,
        max_black=max_black, hfov_cap=max(hfov_deg, MIN_ROOF_HFOV_DEG),
    )  # fmt: skip
    if max_hfov < MIN_ROOF_HFOV_DEG:
        raise ValueError(
            f"camera {cam_k} cannot render a {MIN_ROOF_HFOV_DEG} deg view at bearing "
            f"{target_bearing_deg:.1f}, pitch {pitch_deg:.1f}; choose another camera"
        )
    view = rosette.PerspectiveView(
        width=width,
        height=height,
        hfov_deg=min(hfov_deg, max_hfov),
        yaw_deg=target_bearing_deg,
        pitch_deg=pitch_deg,
        roll_deg=0.0,
    )
    rendered = rosette.render_perspective(image, intr, camera_pose, view, cam_k=cam_k)
    black = rosette.view_black_fraction(intr, camera_pose, view, cam_k, step=4)
    return rendered, view, black


@dataclasses.dataclass(frozen=True)
class TypedEdge:
    """A roof polyline in view pixels, (x, y) per vertex, with its Gemini edge type."""

    edge_type: str | None
    points: list[tuple[float, float]]
    reason: str = ""  # why it was rejected (empty when accepted)


@dataclasses.dataclass
class RoofValidationResult:
    valid_edges: list[TypedEdge]
    rejected_edges: list[TypedEdge]
    mean_gradient_support: float  # over accepted edges only
    raw_mean_gradient_support: float  # over all edges
    median_angle_residual_deg: float  # accepted segments vs their snapped lines
    floating_sky_edges_count: int
    corner_foldover_rate: float  # from snapped vertices of accepted edges
    random_acceptance: float  # share of random segments this validator accepts on this image


# Tuned on synthetic seeds 0-7 (tests/synthetic_scenes.py); asserted on held-out seeds 8-15.
GRAD_PERCENTILE = 85.0  # a supporting pixel's gradient magnitude is >= this image percentile
NORMAL_SEARCH_PX = 2  # search +-this many pixels along the segment normal
ORIENT_TOL_DEG = 20.0  # gradient direction within this of the segment normal
MIN_SUPPORT = 0.70  # share of samples that must be supported
LSD_DIST_PX = 3.0  # an LSD segment within this distance ...
LSD_ANGLE_DEG = 5.0  # ... and angle of the segment counts towards its overlap
MIN_LSD_OVERLAP = 0.50  # share of the segment length covered by such LSD segments
MAX_FOLIAGE = 0.40
MAX_SKY = 0.40
MIN_VALID = 0.98  # share of samples inside the (eroded) valid mask
VALID_ERODE_PX = 5  # keeps segments off the no-data border
MIN_SEGMENT_PX = 8.0
PARALLEL_DEG = 10.0  # consecutive snapped lines closer than this to parallel meet at midpoint
RANDOM_LEN_PX = (100.0, 400.0)


@dataclasses.dataclass
class _Context:
    gray: np.ndarray
    mag: np.ndarray
    ang: np.ndarray  # gradient direction, degrees [0, 360)
    mag_thresh: float
    lsd: np.ndarray  # (n, 4) x1, y1, x2, y2
    foliage: np.ndarray  # bool
    sky: np.ndarray  # bool (interior of sky above the horizon)
    valid: np.ndarray  # bool (eroded valid mask)


def _foliage_mask(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([35, 40, 40]), np.array([85, 255, 255])) > 0


def _sky_mask(img: np.ndarray, horizon_row: float | None) -> np.ndarray:
    """Smooth, bright, low-saturation-or-blue pixels above the horizon, eroded so that the
    boundary between sky and a roof is not counted as sky."""
    h, w = img.shape[:2]
    row = h // 3 if horizon_row is None else int(np.clip(horizon_row, 0, h))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    bright = hsv[..., 2] >= 100
    blue_or_grey = ((hsv[..., 0] >= 90) & (hsv[..., 0] <= 130)) | (hsv[..., 1] <= 40)
    smooth = ~rosette.textured_mask(img, ksize=15, min_std=6.0)
    sky = bright & blue_or_grey & smooth
    sky[row:] = False
    sky = cv2.erode(sky.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    return sky


def horizon_row_for(view: rosette.PerspectiveView) -> float:
    """Image row of the horizon (elevation 0) in a zero-roll pinhole view."""
    return view.cy + view.f * math.tan(math.radians(view.pitch_deg))


def _context(img: np.ndarray, valid_mask: np.ndarray | None, horizon_row: float | None):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    if valid_mask is None:
        valid_mask = np.ones(gray.shape, bool)
    valid = cv2.erode(
        valid_mask.astype(np.uint8), np.ones((2 * VALID_ERODE_PX + 1,) * 2, np.uint8)
    ).astype(bool)
    thresh = float(np.percentile(mag[valid], GRAD_PERCENTILE)) if valid.any() else math.inf
    lines = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    lsd = np.zeros((0, 4)) if lines is None else lines.reshape(-1, 4).astype(np.float64)
    return _Context(gray, mag, ang, thresh, lsd, _foliage_mask(img),
                    _sky_mask(img, horizon_row), valid)  # fmt: skip


def _samples(p1, p2, h, w, step=2.0):
    n = max(2, int(np.linalg.norm(p2 - p1) / step) + 1)
    t = np.linspace(0.0, 1.0, n)
    pts = p1[None, :] * (1 - t)[:, None] + p2[None, :] * t[:, None]
    return pts, np.clip(np.rint(pts).astype(int), [0, 0], [w - 1, h - 1])


def _segment_check(ctx: _Context, p1: np.ndarray, p2: np.ndarray):
    """(accepted, reason, support, supporting pixel coords) for one straight segment."""
    h, w = ctx.gray.shape
    d = p2 - p1
    length = float(np.linalg.norm(d))
    if length < MIN_SEGMENT_PX:
        return False, "too_short", 0.0, np.zeros((0, 2))
    u = d / length
    nrm = np.array([-u[1], u[0]])
    pts, ipts = _samples(p1, p2, h, w)
    inside = (pts[:, 0] >= 0) & (pts[:, 0] <= w - 1) & (pts[:, 1] >= 0) & (pts[:, 1] <= h - 1)
    valid_frac = float(np.mean(inside & ctx.valid[ipts[:, 1], ipts[:, 0]]))

    normal_deg = math.degrees(math.atan2(nrm[1], nrm[0])) % 180.0
    supported = np.zeros(len(pts), bool)
    hits = []
    for off in range(-NORMAL_SEARCH_PX, NORMAL_SEARCH_PX + 1):
        q = np.clip(np.rint(pts + off * nrm).astype(int), [0, 0], [w - 1, h - 1])
        m = ctx.mag[q[:, 1], q[:, 0]]
        a = ctx.ang[q[:, 1], q[:, 0]] % 180.0
        da = np.abs(((a - normal_deg) + 90.0) % 180.0 - 90.0)
        ok = (m >= ctx.mag_thresh) & (da <= ORIENT_TOL_DEG) & ~supported
        supported |= ok
        hits.append(q[ok])
    support = float(np.mean(supported))
    hit_px = np.concatenate(hits) if hits else np.zeros((0, 2))

    fol = float(np.mean(ctx.foliage[ipts[:, 1], ipts[:, 0]]))
    sky = float(np.mean(ctx.sky[ipts[:, 1], ipts[:, 0]]))
    if valid_frac < MIN_VALID:
        return False, "outside_valid", support, hit_px
    if fol > MAX_FOLIAGE:
        return False, "foliage", support, hit_px
    if sky > MAX_SKY:
        return False, "sky", support, hit_px
    if support < MIN_SUPPORT:
        return False, "weak_gradient", support, hit_px
    if _lsd_overlap(ctx.lsd, p1, u, length) < MIN_LSD_OVERLAP:
        return False, "no_line_segment", support, hit_px
    return True, "", support, hit_px


def _lsd_overlap(lsd: np.ndarray, p1: np.ndarray, u: np.ndarray, length: float) -> float:
    """Share of [0, length] along the segment covered by near-collinear LSD segments."""
    if len(lsd) == 0:
        return 0.0
    a, b = lsd[:, :2], lsd[:, 2:]
    v = b - a
    vl = np.linalg.norm(v, axis=1)
    keep = vl > 1e-6
    a, b, v, vl = a[keep], b[keep], v[keep], vl[keep]
    cos = np.abs(v @ u) / vl
    nrm = np.array([-u[1], u[0]])
    da, db = np.abs((a - p1) @ nrm), np.abs((b - p1) @ nrm)
    near = (
        (cos >= math.cos(math.radians(LSD_ANGLE_DEG))) & (da <= LSD_DIST_PX) & (db <= LSD_DIST_PX)
    )
    if not near.any():
        return 0.0
    ta, tb = (a[near] - p1) @ u, (b[near] - p1) @ u
    iv = sorted(zip(np.minimum(ta, tb), np.maximum(ta, tb), strict=True))
    covered, cur_s, cur_e = 0.0, None, None
    for s, e in iv:
        s, e = max(0.0, s), min(length, e)
        if e <= s:
            continue
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                covered += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        covered += cur_e - cur_s
    return covered / length


def _fit_line(hit_px: np.ndarray, p1: np.ndarray, p2: np.ndarray):
    """(point, unit direction) of the line through the supporting pixels (or the segment)."""
    if len(hit_px) >= 5:
        vx, vy, x0, y0 = cv2.fitLine(hit_px.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01)
        return np.array([x0[0], y0[0]], float), np.array([vx[0], vy[0]], float)
    d = p2 - p1
    return p1.astype(float), d / max(np.linalg.norm(d), 1e-9)


def _project(pt, line):
    c, u = line
    return c + np.dot(pt - c, u) * u


def _intersect(l1, l2):
    (c1, u1), (c2, u2) = l1, l2
    a = np.array([u1, -u2]).T
    if abs(np.linalg.det(a)) < 1e-9:
        return None
    t = np.linalg.solve(a, c2 - c1)
    return c1 + t[0] * u1


def _snap_polyline(pts: np.ndarray, lines: list, tol: float) -> np.ndarray:
    """Vertices = intersections of consecutive snapped lines (midpoint of the projections
    when they are within PARALLEL_DEG of parallel); ends are projected onto their line.
    A vertex that would move more than `tol` keeps its original position."""
    out = []
    n = len(pts)
    for i in range(n):
        if i == 0:
            q = _project(pts[0], lines[0])
        elif i == n - 1:
            q = _project(pts[-1], lines[-1])
        else:
            l1, l2 = lines[i - 1], lines[i]
            cos = abs(float(np.dot(l1[1], l2[1])))
            q = None
            if cos < math.cos(math.radians(PARALLEL_DEG)):
                q = _intersect(l1, l2)
            if q is None:
                q = 0.5 * (_project(pts[i], l1) + _project(pts[i], l2))
        if np.linalg.norm(q - pts[i]) > tol:
            q = pts[i].astype(float)
        out.append(q)
    return np.array(out)


def _foldover_count(pts: np.ndarray) -> tuple[int, int]:
    corners = folds = 0
    for i in range(1, len(pts) - 1):
        v1, v2 = pts[i - 1] - pts[i], pts[i + 1] - pts[i]
        n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            continue
        corners += 1
        folds += int(np.dot(v1, v2) / (n1 * n2) > 0.9)  # the polyline turns back on itself
    return corners, folds


def _as_typed(edge) -> tuple[str | None, list[tuple[float, float]]]:
    if isinstance(edge, TypedEdge):
        return edge.edge_type, list(edge.points)
    if isinstance(edge, Mapping):
        return edge.get("edge_type"), list(edge["points"])
    if len(edge) == 2 and isinstance(edge[0], str | type(None)):
        return edge[0], list(edge[1])
    return None, list(edge)


def random_segments(
    h: int,
    w: int,
    n: int = 200,
    seed: int = 0,
    region: Sequence[float] | None = None,
) -> list[list[tuple]]:
    """`n` random straight segments fully inside an h x w image, or inside `region`
    (x0, y0, x1, y1), clipped to the image. Lengths are RANDOM_LEN_PX, shortened to fit a
    small region (at most its shorter side and at least MIN_SEGMENT_PX)."""
    x0, y0, x1, y1 = (0.0, 0.0, w - 1.0, h - 1.0) if region is None else region
    x0, x1 = max(0.0, float(x0)), min(w - 1.0, float(x1))
    y0, y1 = max(0.0, float(y0)), min(h - 1.0, float(y1))
    short = min(x1 - x0, y1 - y0) if region is not None else math.inf
    lo = max(MIN_SEGMENT_PX, min(RANDOM_LEN_PX[0], 0.5 * short))
    hi = max(lo, min(RANDOM_LEN_PX[1], math.hypot(x1 - x0, y1 - y0)))
    if x1 - x0 < MIN_SEGMENT_PX and y1 - y0 < MIN_SEGMENT_PX:
        raise ValueError(f"region {region} is too small for {MIN_SEGMENT_PX} px segments")
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < n:
        p = rng.uniform([x0, y0], [x1, y1])
        a = rng.uniform(0, math.pi)
        q = p + rng.uniform(lo, hi) * np.array([math.cos(a), math.sin(a)])
        if x0 <= q[0] <= x1 and y0 <= q[1] <= y1:
            out.append([tuple(p), tuple(q)])
    return out


def _geometric_gate(
    p1: np.ndarray,
    p2: np.ndarray,
    roof_box: Sequence[float] | None,
    wall_box: Sequence[float] | None,
) -> tuple[bool, str]:
    """Check whether a segment `[p1, p2]` satisfies the roof-band and wall-exclusion gates."""
    if roof_box is None and wall_box is None:
        return True, ""
    y_min = min(float(p1[1]), float(p2[1]))
    y_max = max(float(p1[1]), float(p2[1]))
    y_mid = 0.5 * (float(p1[1]) + float(p2[1]))
    if roof_box is not None:
        _, ry0, _, ry1 = (float(v) for v in roof_box)
        band_h = max(20.0, ry1 - ry0)
        # Allow slack above ridge and below eave for 1-story vs 2-story height variance
        if (
            y_max < ry0 - 0.35 * band_h
            or y_min > ry1 + 0.35 * band_h
            or y_mid > ry1 + 0.25 * band_h
        ):
            return False, "outside_roof_band"
    if wall_box is not None:
        wx0, wy0, wx1, wy1 = (float(v) for v in wall_box)
        wall_h = max(20.0, wy1 - wy0)
        # Interior of wall box below the eave band
        if y_min > wy0 + 0.20 * wall_h and y_max <= wy1 + 12.0:
            return False, "wall_decoy"
    return True, ""


def _acceptance(
    ctx: _Context,
    segs,
    roof_box: Sequence[float] | None = None,
    wall_box: Sequence[float] | None = None,
) -> float:
    acc = 0
    for p, q in segs:
        p_arr, q_arr = np.asarray(p, float), np.asarray(q, float)
        g_ok, _ = _geometric_gate(p_arr, q_arr, roof_box, wall_box)
        if not g_ok:
            continue
        acc += int(_segment_check(ctx, p_arr, q_arr)[0])
    return acc / max(1, len(segs))


def random_line_baseline(
    img: np.ndarray,
    n: int = 200,
    seed: int = 0,
    valid_mask: np.ndarray | None = None,
    horizon_row: float | None = None,
    region: Sequence[float] | None = None,
) -> float:
    """Share of `n` random segments that the validator accepts on `img` (inside `region`,
    e.g. the expected roof band, when given): the false-accept rate to compare an edge's
    acceptance against."""
    ctx = _context(img, valid_mask, horizon_row)
    return _acceptance(ctx, random_segments(*img.shape[:2], n=n, seed=seed, region=region))


def decoy_acceptance(
    img: np.ndarray,
    decoys: Mapping[str, Sequence[Sequence[Sequence[float]]]],
    valid_mask: np.ndarray | None = None,
    horizon_row: float | None = None,
    *,
    roof_box: Sequence[float] | None = None,
    wall_box: Sequence[float] | None = None,
    min_sky_contact: float = 0.0,
) -> dict[str, float]:
    """Share of each named group of straight decoy segments (horizon, wall base, siding,
    ...) that the validator accepts. The validator checks that a straight image edge exists
    along a proposed segment, not that the edge is a roof edge, so a decoy lying on a real
    straight boundary is expected to pass; these numbers say how often."""
    ctx = _context(img, valid_mask, horizon_row)
    _ = min_sky_contact
    return {
        name: _acceptance(ctx, segs, roof_box=roof_box, wall_box=wall_box)
        for name, segs in decoys.items()
        if len(segs)
    }


def straight_lines_in(
    img: np.ndarray, region: Sequence[float], min_len_px: float = 40.0
) -> list[list[tuple[float, float]]]:
    """LSD line segments of at least `min_len_px` lying fully inside `region` (x0, y0, x1,
    y1). With `views.wall_box` as the region these are real straight edges that are not roof
    edges, a stronger decoy set for `decoy_acceptance` than lines at assumed rows."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    lines = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    if lines is None:
        return []
    x0, y0, x1, y1 = region
    out = []
    for ax, ay, bx, by in lines.reshape(-1, 4).astype(float):
        inside = x0 <= min(ax, bx) and max(ax, bx) <= x1 and y0 <= min(ay, by) and max(ay, by) <= y1
        if inside and math.hypot(bx - ax, by - ay) >= min_len_px:
            out.append([(ax, ay), (bx, by)])
    return out


def validate_roof_edges(
    img: np.ndarray,
    typed_edges: Sequence[Any],
    valid_mask: np.ndarray | None = None,
    horizon_row: float | None = None,
    snap_tol_px: float = 6.0,
    n_random: int = 200,
    seed: int = 0,
    baseline_region: Sequence[float] | None = None,
    *,
    roof_box: Sequence[float] | None = None,
    wall_box: Sequence[float] | None = None,
    min_sky_contact: float = 0.0,
) -> RoofValidationResult:
    """Accept a roof polyline only if every segment is backed by image evidence.

    Per segment: >= MIN_SUPPORT of samples have, within +-NORMAL_SEARCH_PX along the normal,
    a gradient >= the GRAD_PERCENTILE of the image oriented within ORIENT_TOL_DEG of the
    normal; near-collinear LSD segments cover >= MIN_LSD_OVERLAP of it; at most MAX_FOLIAGE
    lies on foliage and MAX_SKY inside the sky; and it stays inside `valid_mask` (eroded).
    When `roof_box` / `wall_box` are supplied, segments below the eave band or inside the
    wall box are rejected (`outside_roof_band` / `wall_decoy`)."""
    ctx = _context(img, valid_mask, horizon_row)
    valid, rejected = [], []
    sup_ok, sup_all, residuals = [], [], []
    floating = corners = folds = 0
    for edge in typed_edges:
        etype, raw = _as_typed(edge)
        pts = np.asarray(raw, float).reshape(-1, 2)
        if len(pts) < 2:
            rejected.append(TypedEdge(etype, [tuple(p) for p in pts], "too_few_points"))
            continue
        if min_sky_contact > 0.0 and etype == "RIDGE":
            from svi_geo import cvchecks as cvc

            sc = cvc.sky_contact(
                img, [tuple(map(float, p)) for p in pts], horizon_row=horizon_row, valid_mask=valid_mask
            )
            if math.isfinite(sc) and sc < min_sky_contact:
                rejected.append(
                    TypedEdge(etype, [tuple(map(float, p)) for p in pts], "low_sky_contact")
                )
                continue
        geom_checks = [
            _geometric_gate(pts[i], pts[i + 1], roof_box, wall_box) for i in range(len(pts) - 1)
        ]
        geom_bad = [r for ok, r in geom_checks if not ok]
        checks = [_segment_check(ctx, pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        sups = [c[2] for c in checks]
        sup_all.extend(sups)
        bad = geom_bad + [c[1] for c in checks if not c[0]]
        if any(r == "sky" for r in bad):
            floating += 1
        if bad:
            rejected.append(TypedEdge(etype, [tuple(map(float, p)) for p in pts], bad[0]))
            continue
        lines = [_fit_line(c[3], pts[i], pts[i + 1]) for i, c in enumerate(checks)]
        for i, (_, u) in enumerate(lines):
            d = pts[i + 1] - pts[i]
            cos = abs(float(np.dot(d / np.linalg.norm(d), u)))
            residuals.append(math.degrees(math.acos(min(1.0, cos))))
        snapped = _snap_polyline(pts, lines, snap_tol_px)
        c, f = _foldover_count(snapped)
        corners, folds = corners + c, folds + f
        sup_ok.extend(sups)
        valid.append(TypedEdge(etype, [tuple(map(float, p)) for p in snapped]))
    random_acc = (
        _acceptance(
            ctx,
            random_segments(*img.shape[:2], n=n_random, seed=seed, region=baseline_region),
            roof_box=roof_box,
            wall_box=wall_box,
        )
        if n_random
        else math.nan
    )
    return RoofValidationResult(
        valid_edges=valid,
        rejected_edges=rejected,
        mean_gradient_support=float(np.mean(sup_ok)) if sup_ok else 0.0,
        raw_mean_gradient_support=float(np.mean(sup_all)) if sup_all else 0.0,
        median_angle_residual_deg=float(np.median(residuals)) if residuals else 0.0,
        floating_sky_edges_count=floating,
        corner_foldover_rate=folds / max(corners, 1),
        random_acceptance=random_acc,
    )


def validate_and_snap_roof_edges(
    image_bgr: np.ndarray,
    roof_edges: Sequence[Sequence[Sequence[float]]],
    snap_tol_px: float = 6.0,
    **_ignored: Any,
) -> RoofValidationResult:
    """Deprecated: use `validate_roof_edges` (typed edges, valid mask, random baseline)."""
    warnings.warn(
        "validate_and_snap_roof_edges is deprecated; use validate_roof_edges",
        DeprecationWarning,
        stacklevel=2,
    )
    return validate_roof_edges(image_bgr, [(None, e) for e in roof_edges], snap_tol_px=snap_tol_px)
