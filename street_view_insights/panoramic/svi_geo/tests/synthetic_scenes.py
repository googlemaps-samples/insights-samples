"""Seeded procedural street scenes for the roof-edge validator (no imagery, no mocks).

Each scene is a 1200x900 BGR image with a sky gradient, textured ground, a house with
textured walls and a gabled roof, noisy foliage blobs away from the roof line, a black
invalid wedge (like the no-data border of a rendered view) and a JPEG round trip. It comes
with the ground-truth roof polylines (typed, pixel x/y) and the valid-pixel mask.
"""

from __future__ import annotations

import dataclasses

import cv2
import numpy as np

W, H = 1200, 900


@dataclasses.dataclass
class Scene:
    image: np.ndarray  # BGR uint8
    edges: list[tuple[str, list[tuple[float, float]]]]  # (edge_type, [(x, y), ...])
    valid_mask: np.ndarray  # bool, False inside the black wedge
    horizon_row: float
    wedge: np.ndarray  # (3, 2) wedge triangle
    foliage_centres: list[tuple[int, int, int]]  # (x, y, radius)


def _texture(rng, h, w, base, amp, blur=3):
    noise = rng.normal(0.0, amp, (h, w, 1)).astype(np.float32)
    if blur > 1:
        noise = cv2.GaussianBlur(noise, (0, 0), blur)[..., None]
    return np.clip(np.asarray(base, np.float32)[None, None, :] + noise, 0, 255)


def make_scene(seed: int) -> Scene:
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)

    # sky gradient above the horizon, textured ground below
    horizon = int(rng.integers(560, 640))
    top = np.array([rng.uniform(200, 240), rng.uniform(150, 190), rng.uniform(90, 130)])
    bottom = np.array([235.0, 225.0, 215.0])
    t = np.linspace(0, 1, horizon)[:, None, None]
    img[:horizon] = top * (1 - t) + bottom * t
    img[horizon:] = _texture(rng, H - horizon, W, (95, 100, 105), 18, blur=1.5)

    # house: walls + gabled roof
    x0 = int(rng.integers(250, 400))
    x1 = int(rng.integers(800, 950))
    y_base = horizon + int(rng.integers(40, 90))
    y_eave = int(rng.integers(330, 400))
    wall_col = (rng.uniform(120, 200), rng.uniform(130, 200), rng.uniform(140, 220))
    img[y_eave:y_base, x0:x1] = _texture(rng, y_base - y_eave, x1 - x0, wall_col, 10, blur=1)
    for yy in range(y_eave + 12, y_base, 14):  # siding courses: short horizontal texture lines
        img[yy : yy + 1, x0:x1] *= 0.93

    overhang = int(rng.integers(15, 35))
    ex0, ex1 = x0 - overhang, x1 + overhang
    roof_col = (rng.uniform(40, 80), rng.uniform(40, 70), rng.uniform(50, 90))
    side_gable = bool(rng.integers(0, 2))
    if side_gable:
        inset = int(rng.integers(60, 140))
        y_ridge = y_eave - int(rng.integers(110, 170))
        poly = np.array([[ex0, y_eave], [ex1, y_eave], [ex1 - inset, y_ridge],
                         [ex0 + inset, y_ridge]], np.int32)  # fmt: skip
        edges = [
            ("EAVE", [(ex0, y_eave), (ex1, y_eave)]),
            ("RIDGE", [(ex0 + inset, y_ridge), (ex1 - inset, y_ridge)]),
            ("RAKE", [(ex0, y_eave), (ex0 + inset, y_ridge)]),
            ("RAKE", [(ex1, y_eave), (ex1 - inset, y_ridge)]),
        ]
    else:
        apex_x = (ex0 + ex1) // 2 + int(rng.integers(-40, 40))
        y_apex = y_eave - int(rng.integers(150, 230))
        poly = np.array([[ex0, y_eave], [ex1, y_eave], [apex_x, y_apex]], np.int32)
        edges = [
            ("EAVE", [(ex0, y_eave), (ex1, y_eave)]),
            ("RAKE", [(ex0, y_eave), (apex_x, y_apex), (ex1, y_eave)]),
        ]
    roof_tex = _texture(rng, H, W, roof_col, 14, blur=1)
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [poly], 1)
    img[mask > 0] = roof_tex[mask > 0]

    # noisy foliage blobs: beside and below the house, never on the roof outline
    foliage = []
    roof_box = (ex0 - 30, int(poly[:, 1].min()) - 30, ex1 + 30, y_eave + 30)
    for _ in range(int(rng.integers(5, 9))):
        for _attempt in range(50):
            r = int(rng.integers(40, 110))
            cx = int(rng.integers(r, W - r))
            cy = int(rng.integers(horizon - 150, H - r))
            bx0, by0, bx1, by1 = roof_box
            if cx + r < bx0 or cx - r > bx1 or cy - r > by1 or cy + r < by0:
                break
        yy, xx = np.ogrid[:H, :W]
        rad = r * (1 + 0.25 * np.sin(np.arctan2(yy - cy, xx - cx) * rng.integers(3, 7)))
        blob = (yy - cy) ** 2 + (xx - cx) ** 2 <= rad**2
        leaf = _texture(rng, H, W, (40, rng.uniform(110, 160), 50), 35, blur=1)
        img[blob] = leaf[blob]
        foliage.append((cx, cy, r))

    # black no-data wedge in a lower corner, like a view that runs past the sensor edge
    if rng.integers(0, 2):
        wedge = np.array([[0, H - 1], [0, H - int(rng.integers(250, 400))],
                          [int(rng.integers(150, 300)), H - 1]], np.int32)  # fmt: skip
    else:
        wedge = np.array([[W - 1, H - 1], [W - 1, H - int(rng.integers(250, 400))],
                          [W - int(rng.integers(150, 300)), H - 1]], np.int32)  # fmt: skip
    wmask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(wmask, [wedge], 1)
    img[wmask > 0] = 0

    out = np.clip(img, 0, 255).astype(np.uint8)
    ok, jpg = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 85])
    assert ok
    out = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
    edges_f = [(t_, [(float(x), float(y)) for x, y in pts]) for t_, pts in edges]
    return Scene(out, edges_f, wmask == 0, float(horizon), wedge, foliage)


def jitter(edges, rng, px=2):
    """Ground-truth edges with every vertex moved by up to `px` pixels in x and y."""
    return [
        (
            t,
            [
                (x + float(rng.integers(-px, px + 1)), y + float(rng.integers(-px, px + 1)))
                for x, y in pts
            ],
        )  # fmt: skip
        for t, pts in edges
    ]
