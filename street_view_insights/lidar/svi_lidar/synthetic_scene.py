# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Synthetic 3D street corridor + Full-Frame RGB generator for offline sample runs & tests."""

from __future__ import annotations

from typing import Any

import numpy as np

from .io_and_frames import enu_to_ecef
from .projection_and_rgb import IMAGE_HEIGHT, IMAGE_WIDTH, project_points_to_image


def make_synthetic_street_scene(
    origin_lat: float = 40.7608,
    origin_lon: float = -111.8910,
    origin_alt: float = 1300.0,
    image_scale: int = 4,
    seed: int = 7,
) -> dict[str, Any]:
    """Create a synthetic street scene with road, curbs, sidewalk, pole, sign, tree, wall, and driveway.

    Camera sits at `(0, 0, 0)` ENU (`2.50 m` above the local road surface `z = -2.50 m`)
    looking due North (`heading = 0.0 deg`, `pitch = 4.0 deg`, `roll = 0.0 deg`).
    """
    rng = np.random.default_rng(seed)
    z_road = -2.50

    pts_list: list[np.ndarray] = []
    int_list: list[np.ndarray] = []
    label_ranges: dict[str, tuple[int, int]] = {}
    cursor = 0

    def _add(block_pts: np.ndarray, block_int: np.ndarray, name: str | None = None) -> None:
        nonlocal cursor
        n_b = len(block_pts)
        pts_list.append(block_pts.astype(np.float32))
        int_list.append(block_int.astype(np.uint16))
        if name:
            label_ranges[name] = (cursor, cursor + n_b)
        cursor += n_b

    # 1. Crowned asphalt roadway (`x in [-4.0, +4.0]`, `y in [3.5, 32.0]`), intensity ~25.
    rx = rng.uniform(-4.0, 4.0, 2600)
    ry = rng.uniform(3.5, 32.0, 2600)
    rz = z_road - 0.018 * np.abs(rx) + rng.normal(0.0, 0.005, 2600)
    _add(np.column_stack([rx, ry, rz]), rng.integers(18, 34, size=2600), "road")
    z_gutter = z_road - 0.018 * 4.0  # Roadway gutter elevation at |x| = 4.0 m

    # 2. Right curb (`x = +4.0..+4.18`, `15 cm` reveal above gutter except flush driveway `y in [13.0, 17.5]`).
    cy = rng.uniform(4.0, 30.0, 500)
    in_driveway = (cy >= 13.0) & (cy <= 17.5)
    curb_top = np.where(in_driveway, z_gutter + 0.015, z_gutter + 0.15)
    cx = rng.uniform(4.0, 4.18, 500)
    cz = curb_top + rng.normal(0.0, 0.004, 500)
    _add(np.column_stack([cx, cy, cz]), rng.integers(32, 55, size=500), "right_curb")

    # Left curb (`x = -4.18..-4.0`, continuous `15 cm` reveal above gutter) + left sidewalk (`1.8 m` wide).
    lcy = rng.uniform(4.0, 30.0, 450)
    lcx = rng.uniform(-4.18, -4.0, 450)
    lcz = z_gutter + 0.15 + rng.normal(0.0, 0.004, 450)
    _add(np.column_stack([lcx, lcy, lcz]), rng.integers(32, 55, size=450), "left_curb")

    lsx = rng.uniform(-5.95, -4.20, 1100)
    lsy = rng.uniform(4.0, 30.0, 1100)
    lsz = z_gutter + 0.15 + 0.015 * (-4.20 - lsx) + rng.normal(0.0, 0.004, 1100)
    _add(np.column_stack([lsx, lsy, lsz]), rng.integers(40, 68, size=1100), "left_sidewalk")

    # 3. Right concrete sidewalk (`x in [4.20, 6.00]` -> `1.8 m` wide, smooth) + grass verge (`6.05..7.50`).
    sx = rng.uniform(4.20, 6.00, 1200)
    sy = rng.uniform(4.0, 30.0, 1200)
    in_dw_sw = (sy >= 13.0) & (sy <= 17.5)
    sz_base = np.where(
        in_dw_sw,
        z_gutter + 0.015 + 0.045 * (sx - 4.0),
        z_gutter + 0.15 + 0.016 * (sx - 4.20),
    )
    sz = sz_base + rng.normal(0.0, 0.004, 1200)
    _add(np.column_stack([sx, sy, sz]), rng.integers(42, 70, size=1200), "right_sidewalk")

    gx = rng.uniform(6.05, 7.50, 650)
    gy = rng.uniform(4.0, 30.0, 650)
    gz = z_road + 0.17 + rng.normal(0.0, 0.055, 650)
    _add(np.column_stack([gx, gy, gz]), rng.integers(6, 15, size=650), "grass_verge")

    # 4. Leaning wood utility pole at `(x=-4.5, y=12.0)`, `10.5 m` tall, `3.5 deg` East lean + overhead wire at `12.3 m`.
    pole_h = rng.uniform(0.1, 10.5, 420)
    lean_rad = np.radians(3.5)
    px = -4.50 + pole_h * np.sin(lean_rad) + rng.normal(0.0, 0.04, 420)
    py = 12.00 + rng.normal(0.0, 0.04, 420)
    pz = z_road + pole_h * np.cos(lean_rad)
    _add(np.column_stack([px, py, pz]), rng.integers(22, 48, size=420), "pole")

    # Overhead wire 1.8 m above pole top (`> 1.2 m` air gap -> must be excluded by `measure_pole_3d`).
    wx = np.linspace(-5.2, -3.8, 45)
    wy = np.full(45, 12.0)
    wz = np.full(45, z_road + 12.4)
    _add(np.column_stack([wx, wy, wz]), np.full(45, 20, dtype=np.uint16), "wire")

    # 5. Retroreflective road sign at `(x=4.35, y=9.5)`: `0.75 m` wide x `0.90 m` tall, `2.15 m` bottom clearance.
    post_z = rng.uniform(0.1, 2.15, 60)
    _add(
        np.column_stack([np.full(60, 4.35) + rng.normal(0, 0.015, 60), np.full(60, 9.5), z_road + post_z]),
        np.full(60, 35, dtype=np.uint16),
        "sign_post",
    )
    su = rng.uniform(-0.375, 0.375, 260)
    sv = rng.uniform(2.15, 3.05, 260)
    _add(
        np.column_stack([4.35 + su, np.full(260, 9.5) + rng.normal(0, 0.006, 260), z_road + sv]),
        rng.integers(900, 4200, size=260),
        "sign_face",
    )

    # 6. Street tree at `(x=-5.4, y=18.5)`: `9.2 m` tall, `5.4 m` crown width, `3.6 m` canopy clearance.
    tz_trunk = rng.uniform(0.2, 3.5, 90)
    _add(
        np.column_stack([np.full(90, -5.4) + rng.normal(0, 0.12, 90), np.full(90, 18.5) + rng.normal(0, 0.12, 90), z_road + tz_trunk]),
        rng.integers(20, 40, size=90),
        "tree_trunk",
    )
    angles_az = rng.uniform(0, 2 * np.pi, 550)
    radii = rng.uniform(0.2, 2.75, 550)
    cz_canopy = rng.uniform(3.6, 9.25, 550)
    _add(
        np.column_stack([-5.4 + radii * np.cos(angles_az), 18.5 + radii * np.sin(angles_az), z_road + cz_canopy]),
        rng.integers(18, 45, size=550),
        "tree_canopy",
    )

    # 7. Commercial building facade on right side (`x = +8.2`, `y in [10.0, 22.0]`, `7.8 m` tall, `12.0 m` wide)
    #    with raised `14 cm` entry apron outside the flush `4.5 m` driveway (`y in [13.0, 17.5]`).
    fy = rng.uniform(10.0, 22.0, 950)
    fz = z_road + rng.uniform(0.2, 7.8, 950)
    fx = np.full(950, 8.20) + rng.normal(0.0, 0.015, 950)
    _add(np.column_stack([fx, fy, fz]), rng.integers(38, 72, size=950), "building_facade")

    ay = rng.uniform(18.0, 21.8, 180)
    ax = rng.uniform(6.2, 8.0, 180)
    az = np.full(180, z_road + 0.14) + rng.normal(0.0, 0.005, 180)
    _add(np.column_stack([ax, ay, az]), rng.integers(40, 65, size=180), "entry_apron")

    pts_enu = np.vstack(pts_list)
    intensity = np.concatenate(int_list)
    pts_ecef = enu_to_ecef(pts_enu, origin_lat, origin_lon, origin_alt)

    camera_pose = {
        "latitude": origin_lat,
        "longitude": origin_lon,
        "altitude": origin_alt,
        "heading": 0.0,
        "pitch": 4.0,
        "roll": 0.0,
    }

    # Synthesize a crisp RGB image painted by semantic region so True Color draping is visually verifiable.
    img_w = IMAGE_WIDTH // max(1, int(image_scale))
    img_h = IMAGE_HEIGHT // max(1, int(image_scale))
    img_rgb = np.full((img_h, img_w, 3), (185, 212, 242), dtype=np.uint8)  # Sky blue top
    img_rgb[img_h // 2 :, :, :] = (92, 96, 102)  # Asphalt lower half

    proj = project_points_to_image(
        pts_enu,
        heading_deg=camera_pose["heading"],
        pitch_deg=camera_pose["pitch"],
        roll_deg=camera_pose["roll"],
        image_wh=(img_w, img_h),
    )
    palette = {
        "road": (78, 82, 88),
        "right_curb": (195, 195, 190),
        "left_curb": (195, 195, 190),
        "right_sidewalk": (214, 212, 206),
        "left_sidewalk": (214, 212, 206),
        "grass_verge": (74, 138, 68),
        "building_facade": (204, 168, 136),
        "tree_trunk": (108, 78, 52),
        "tree_canopy": (46, 146, 64),
        "pole": (146, 108, 72),
        "sign_face": (228, 48, 42),
    }
    # Paint back-to-front so foreground assets overwrite background wall pixels cleanly.
    for name, color in palette.items():
        lo, hi = label_ranges[name]
        sub_valid = np.flatnonzero(proj["in_bounds"][lo:hi]) + lo
        for idx in sub_valid:
            u_i = int(round(float(proj["u"][idx])))
            v_i = int(round(float(proj["v"][idx])))
            u0, u1 = max(0, u_i - 3), min(img_w, u_i + 4)
            v0, v1 = max(0, v_i - 3), min(img_h, v_i + 4)
            img_rgb[v0:v1, u0:u1] = color

    return {
        "pts_enu": pts_enu,
        "pts_ecef": pts_ecef,
        "intensity": intensity,
        "camera_pose": camera_pose,
        "img_rgb": img_rgb,
        "full_res_wh": (IMAGE_WIDTH, IMAGE_HEIGHT),
        "label_ranges": label_ranges,
        "z_road_m": z_road,
    }
