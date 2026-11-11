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
"""2-term radial fisheye projection, 2D front-surface filtering, and True Color RGB 3D draping."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .io_and_frames import ecef_to_enu, enu_to_camera, enu_to_ecef

# Calibrated Full-Frame wide-angle camera parameters (3648 x 5472 portrait sensor, 115 deg FoV).
IMAGE_WIDTH = 3648
IMAGE_HEIGHT = 5472
LENS_FOV_DEG = 115.0

FOCAL_LENGTH_PX = 2964.42
PRINCIPAL_X = 1836.95
PRINCIPAL_Y = 2733.06
DISTORTION_K1 = -0.023685
DISTORTION_K2 = 0.000110
PITCH_BIAS_DEG = 0.0
MIN_EGO_CLEARANCE_M = 2.6


def _pose_value(pose: Mapping[str, Any], *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in pose and pose[k] is not None:
            return float(pose[k])
    return float(default)


def project_cam_to_uv(
    x_norm: float | np.ndarray,
    z_norm: float | np.ndarray,
    fx: float = FOCAL_LENGTH_PX,
    fy: float = FOCAL_LENGTH_PX,
    cx: float = PRINCIPAL_X,
    cy: float = PRINCIPAL_Y,
    k1: float = DISTORTION_K1,
    k2: float = DISTORTION_K2,
    lens_model: str = "fisheye",
) -> tuple[np.ndarray, np.ndarray] | tuple[float, float]:
    """Project normalized camera coordinates `(X_right / Y_fwd, Z_up / Y_fwd)` to `(u, v)` pixels.

    Uses the 2-term even-power radial fisheye law by default:
      `theta = atan(r)`, `theta_d = theta * (1 + k1 * theta^2 + k2 * theta^4)`.
    """
    is_scalar = np.isscalar(x_norm) and np.isscalar(z_norm)
    xn = np.asarray(x_norm, dtype=np.float64)
    zn = np.asarray(z_norm, dtype=np.float64)
    r2 = xn * xn + zn * zn

    if lens_model.lower() == "fisheye":
        r = np.sqrt(r2)
        theta = np.arctan(r)
        t2 = theta * theta
        theta_d = theta * (1.0 + k1 * t2 + k2 * (t2 * t2))
        scale = np.where(r > 1e-8, theta_d / np.where(r > 1e-8, r, 1.0), 1.0)
    else:
        scale = 1.0 + k1 * r2 + k2 * (r2 * r2)

    u = cx + fx * (xn * scale)
    v = cy - fy * (zn * scale)
    if is_scalar:
        return float(u), float(v)
    return u, v


def project_points_to_image(
    pts_enu: np.ndarray,
    heading_deg: float,
    pitch_deg: float,
    roll_deg: float,
    image_wh: tuple[int, int] = (IMAGE_WIDTH, IMAGE_HEIGHT),
    min_ego_clearance_m: float = MIN_EGO_CLEARANCE_M,
    lens_model: str = "fisheye",
) -> dict[str, np.ndarray]:
    """Project camera-centered ENU points onto a Full-Frame image and return valid mask + UV."""
    pts = np.asarray(pts_enu, dtype=np.float64)
    n_pts = len(pts)
    w, h = int(image_wh[0]), int(image_wh[1])
    sx = w / float(IMAGE_WIDTH)
    sy = h / float(IMAGE_HEIGHT)

    if n_pts == 0:
        return {
            "u": np.empty(0, dtype=np.float32),
            "v": np.empty(0, dtype=np.float32),
            "depth_m": np.empty(0, dtype=np.float32),
            "range_m": np.empty(0, dtype=np.float32),
            "in_bounds": np.empty(0, dtype=bool),
            "pts_cam": np.empty((0, 3), dtype=np.float32),
        }

    pts_cam = enu_to_camera(
        pts,
        heading_deg=heading_deg,
        pitch_deg=pitch_deg,
        roll_deg=roll_deg,
        pitch_offset_deg=PITCH_BIAS_DEG,
    )
    x_cam = pts_cam[:, 0]
    depth = pts_cam[:, 1]
    z_cam = pts_cam[:, 2]
    range_m = np.sqrt(x_cam * x_cam + depth * depth + z_cam * z_cam)

    front_ok = (depth > 0.35) & (range_m >= float(min_ego_clearance_m))
    safe_depth = np.where(front_ok, depth, 1.0)
    xn = np.where(front_ok, x_cam / safe_depth, 0.0)
    zn = np.where(front_ok, z_cam / safe_depth, 0.0)
    cone_ok = front_ok & ((xn * xn + zn * zn) <= 16.0)

    u_full, v_full = project_cam_to_uv(xn, zn, lens_model=lens_model)
    u = u_full * sx
    v = v_full * sy
    in_bounds = cone_ok & (u >= 0.0) & (u < float(w)) & (v >= 0.0) & (v < float(h))

    return {
        "u": u.astype(np.float32),
        "v": v.astype(np.float32),
        "depth_m": depth.astype(np.float32),
        "range_m": range_m.astype(np.float32),
        "in_bounds": in_bounds,
        "pts_cam": pts_cam.astype(np.float32),
    }


def filter_front_surface_overlay(
    pts_enu: np.ndarray,
    heading_deg: float,
    pitch_deg: float,
    roll_deg: float,
    cell_px: int = 14,
    max_per_cell: int = 2,
    image_wh: tuple[int, int] = (IMAGE_WIDTH, IMAGE_HEIGHT),
    min_ego_clearance_m: float = MIN_EGO_CLEARANCE_M,
) -> dict[str, np.ndarray]:
    """Filter 3D points for clean 2D photo overlays using a 14 x 14 px front-surface grid.

    Prevents horizon clumping and stops background walls or trees from bleeding through
    foreground utility poles and road signs (`d <= d_min + max(0.8 m, 0.15 * d_min)`).
    """
    proj = project_points_to_image(
        pts_enu=pts_enu,
        heading_deg=heading_deg,
        pitch_deg=pitch_deg,
        roll_deg=roll_deg,
        image_wh=image_wh,
        min_ego_clearance_m=min_ego_clearance_m,
    )
    cand_idx = np.flatnonzero(proj["in_bounds"])
    if len(cand_idx) == 0:
        empty_f = np.empty(0, dtype=np.float32)
        return {"u": empty_f, "v": empty_f, "depth_m": empty_f, "keep_indices": np.empty(0, dtype=np.int64)}

    u_c = proj["u"][cand_idx]
    v_c = proj["v"][cand_idx]
    d_c = proj["depth_m"][cand_idx]

    w, h = int(image_wh[0]), int(image_wh[1])
    cell = max(1, int(cell_px))
    gx = np.floor(u_c / cell).astype(np.int32)
    gy = np.floor(v_c / cell).astype(np.int32)
    grid_w = (w // cell) + 2
    grid_h = (h // cell) + 2

    zbuf = np.full((grid_h, grid_w), np.inf, dtype=np.float32)
    np.minimum.at(zbuf, (gy, gx), d_c)
    d_min = zbuf[gy, gx]
    front_ok = d_c <= (d_min + np.maximum(0.8, 0.15 * d_min))

    cand_idx = cand_idx[front_ok]
    u_c = u_c[front_ok]
    v_c = v_c[front_ok]
    d_c = d_c[front_ok]
    gx = gx[front_ok]
    gy = gy[front_ok]

    # Sort by (cell_id, depth) so we keep at most `max_per_cell` closest points per cell in pure NumPy.
    cell_id = gy.astype(np.int64) * int(grid_w) + gx.astype(np.int64)
    order = np.lexsort((d_c, cell_id))
    sorted_cells = cell_id[order]

    if len(sorted_cells) > 0 and max_per_cell > 0:
        unique_cells, first_idx, counts = np.unique(
            sorted_cells, return_index=True, return_counts=True
        )
        _ = unique_cells
        rank_in_cell = np.arange(len(sorted_cells), dtype=np.int64) - np.repeat(first_idx, counts)
        sel = order[rank_in_cell < int(max_per_cell)]
    else:
        sel = np.empty(0, dtype=np.int64)

    # Return closest-first for clean painter's-order rendering.
    depth_order = sel[np.argsort(d_c[sel])]
    return {
        "u": u_c[depth_order],
        "v": v_c[depth_order],
        "depth_m": d_c[depth_order],
        "keep_indices": cand_idx[depth_order],
    }


def colorize_points_zbuffer(
    points: np.ndarray,
    img_rgb: np.ndarray,
    camera_pose: Mapping[str, Any],
    is_enu: bool = False,
    anchor_pose: Mapping[str, Any] | None = None,
    cell_px: int = 2,
    depth_tolerance_m: float = 0.35,
    min_ego_clearance_m: float = MIN_EGO_CLEARANCE_M,
    full_res_wh: tuple[int, int] | None = (IMAGE_WIDTH, IMAGE_HEIGHT),
    return_scores: bool = False,
) -> tuple[np.ndarray, np.ndarray] | tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drape True Color RGB pixels from a Street View JPEG onto a 3D `.laz` point cloud.

    LAS 1.4 Point Format 1 stores `(X, Y, Z)`, `intensity`, and `gps_time` without native RGB.
    This function projects 3D points onto a paired `img_rgb` frame using the 2-term radial
    fisheye model and culls occluded background points with a `2 x 2 px` Z-buffer plus a
    foreground `3 x 3` neighborhood splat (`d <= 18 m`) so foreground pole/tree colors never
    bleed onto walls behind them.

    Never drops input points: `colors_rgb` (`(N, 3)` `uint8`) and `visible_mask` (`(N,)` `bool`)
    always match `len(points)`. Pass `full_res_wh=(3648, 5472)` when `img_rgb` was decoded at
    1/2 or 1/4 resolution (e.g., `cv2.IMREAD_REDUCED_COLOR_4`).
    """
    n_pts = len(points)
    colors_rgb = np.zeros((n_pts, 3), dtype=np.uint8)
    visible_mask = np.zeros(n_pts, dtype=bool)
    scores_f32 = np.full(n_pts, np.inf, dtype=np.float32) if return_scores else None
    if n_pts == 0 or img_rgb is None or img_rgb.size == 0:
        return (colors_rgb, visible_mask, scores_f32) if return_scores else (colors_rgb, visible_mask)

    img_h, img_w = img_rgb.shape[:2]
    if full_res_wh is not None and int(full_res_wh[0]) > img_w and int(full_res_wh[1]) > img_h:
        proj_w, proj_h = int(full_res_wh[0]), int(full_res_wh[1])
    else:
        proj_w, proj_h = img_w, img_h
    sx_px = img_w / float(proj_w)
    sy_px = img_h / float(proj_h)

    cam_lat = _pose_value(camera_pose, "latitude", "lat")
    cam_lon = _pose_value(camera_pose, "longitude", "lng", "lon")
    cam_alt = _pose_value(camera_pose, "altitude", "altMeters", "alt")
    heading = _pose_value(camera_pose, "heading", "headingDeg")
    pitch = _pose_value(camera_pose, "pitch", "pitchDeg")
    roll = _pose_value(camera_pose, "roll", "rollDeg")

    pts = np.asarray(points[:, :3], dtype=np.float64)
    if is_enu:
        if anchor_pose is not None:
            a_lat = _pose_value(anchor_pose, "latitude", "lat", default=cam_lat)
            a_lon = _pose_value(anchor_pose, "longitude", "lng", "lon", default=cam_lon)
            a_alt = _pose_value(anchor_pose, "altitude", "altMeters", "alt", default=cam_alt)
            pts_ecef = enu_to_ecef(pts, a_lat, a_lon, a_alt)
            pts_cam_enu = ecef_to_enu(pts_ecef, cam_lat, cam_lon, cam_alt, dtype=np.float64)
        else:
            pts_cam_enu = pts
    else:
        pts_cam_enu = ecef_to_enu(pts, cam_lat, cam_lon, cam_alt, dtype=np.float64)

    pts_cam = enu_to_camera(
        pts_cam_enu,
        heading_deg=heading,
        pitch_deg=pitch,
        roll_deg=roll,
        pitch_offset_deg=PITCH_BIAS_DEG,
    )
    x_cam = pts_cam[:, 0]
    depths = pts_cam[:, 1]
    z_cam = pts_cam[:, 2]
    ranges = np.sqrt(x_cam * x_cam + depths * depths + z_cam * z_cam)

    in_front = (depths > 0.25) & (ranges >= float(min_ego_clearance_m))
    if not np.any(in_front):
        return (colors_rgb, visible_mask, scores_f32) if return_scores else (colors_rgb, visible_mask)

    front_idx = np.flatnonzero(in_front)
    x_f = x_cam[front_idx]
    d_f = depths[front_idx]
    z_f = z_cam[front_idx]
    xn = x_f / d_f
    zn = z_f / d_f

    cone_ok = (xn * xn + zn * zn) <= 16.0
    if not np.any(cone_ok):
        return (colors_rgb, visible_mask, scores_f32) if return_scores else (colors_rgb, visible_mask)

    front_idx = front_idx[cone_ok]
    x_f = x_f[cone_ok]
    d_f = d_f[cone_ok]
    z_f = z_f[cone_ok]
    xn = xn[cone_ok]
    zn = zn[cone_ok]

    u_raw, v_raw = project_cam_to_uv(
        xn,
        zn,
        fx=FOCAL_LENGTH_PX * (proj_w / float(IMAGE_WIDTH)),
        fy=FOCAL_LENGTH_PX * (proj_h / float(IMAGE_HEIGHT)),
        cx=PRINCIPAL_X * (proj_w / float(IMAGE_WIDTH)),
        cy=PRINCIPAL_Y * (proj_h / float(IMAGE_HEIGHT)),
    )
    if proj_w != img_w or proj_h != img_h:
        u_px = np.floor(u_raw * sx_px).astype(np.int32)
        v_px = np.floor(v_raw * sy_px).astype(np.int32)
    else:
        u_px = np.round(u_raw).astype(np.int32)
        v_px = np.round(v_raw).astype(np.int32)

    in_bounds = (u_px >= 0) & (u_px < img_w) & (v_px >= 0) & (v_px < img_h)
    if not np.any(in_bounds):
        return (colors_rgb, visible_mask, scores_f32) if return_scores else (colors_rgb, visible_mask)

    cand_idx = front_idx[in_bounds]
    u_c = u_px[in_bounds]
    v_c = v_px[in_bounds]
    d_c = d_f[in_bounds]
    x_c = x_f[in_bounds]
    z_c = z_f[in_bounds]

    cell = max(1, int(round(max(1, int(cell_px)) * min(sx_px, sy_px))))
    grid_h = (img_h // cell) + 4
    grid_w = (img_w // cell) + 4
    gx = (u_c // cell) + 1
    gy = (v_c // cell) + 1

    zbuf = np.full((grid_h, grid_w), np.inf, dtype=np.float64)
    np.minimum.at(zbuf, (gy, gx), d_c)

    # Splat foreground points (<= 18 m) into 3 x 3 neighbors to close inter-beam laser gaps.
    fg_mask = d_c <= 18.0
    if np.any(fg_mask):
        gy_fg = gy[fg_mask]
        gx_fg = gx[fg_mask]
        d_fg = d_c[fg_mask]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy == 0 and dx == 0:
                    continue
                np.minimum.at(zbuf, (gy_fg + dy, gx_fg + dx), d_fg)

    d_min = zbuf[gy, gx]
    tol = np.maximum(float(depth_tolerance_m), 0.045 * d_min + 0.0009 * (d_min * d_min))
    unoccluded = d_c <= (d_min + tol)

    vis_idx = cand_idx[unoccluded]
    vis_u = u_c[unoccluded]
    vis_v = v_c[unoccluded]
    colors_rgb[vis_idx] = img_rgb[vis_v, vis_u, :3]
    visible_mask[vis_idx] = True

    if return_scores and scores_f32 is not None and len(vis_idx) > 0:
        d_v = d_c[unoccluded]
        r_v = np.sqrt(x_c[unoccluded] ** 2 + d_v * d_v + z_c[unoccluded] ** 2) + 1e-9
        cos_theta = np.clip(d_v / r_v, 0.10, 1.0)
        scores_f32[vis_idx] = (d_v / cos_theta).astype(np.float32)

    return (colors_rgb, visible_mask, scores_f32) if return_scores else (colors_rgb, visible_mask)


def colorize_multiview_point_cloud(
    points: np.ndarray,
    camera_views: Sequence[Mapping[str, Any]],
    is_enu: bool = False,
    anchor_pose: Mapping[str, Any] | None = None,
    cell_px: int = 2,
    min_ego_clearance_m: float = MIN_EGO_CLEARANCE_M,
    full_res_wh: tuple[int, int] | None = (IMAGE_WIDTH, IMAGE_HEIGHT),
    uncolored_fallback_intensity: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Fuse True Color RGB across multiple sequential camera stops along a street pass.

    Each entry in `camera_views` must provide `{"img_rgb": np.ndarray, "camera_pose": dict}`.
    When multiple cameras see the same 3D surface, the view with the lowest obliquity-weighted
    depth score (`d / cos(theta)` — closest and most head-on) wins. Points outside all camera
    frustums optionally fall back to neutral laser-intensity grayscale.
    """
    n_pts = len(points)
    best_rgb = np.zeros((n_pts, 3), dtype=np.uint8)
    best_score = np.full(n_pts, np.inf, dtype=np.float32)
    best_view_idx = np.full(n_pts, -1, dtype=np.int32)

    for view_idx, view in enumerate(camera_views):
        rgb_i, vis_i, score_i = colorize_points_zbuffer(
            points=points,
            img_rgb=view["img_rgb"],
            camera_pose=view["camera_pose"],
            is_enu=is_enu,
            anchor_pose=anchor_pose,
            cell_px=cell_px,
            min_ego_clearance_m=min_ego_clearance_m,
            full_res_wh=full_res_wh,
            return_scores=True,
        )
        better = vis_i & (score_i < best_score)
        if np.any(better):
            best_rgb[better] = rgb_i[better]
            best_score[better] = score_i[better]
            best_view_idx[better] = int(view_idx)

    colored_mask = best_view_idx >= 0
    if uncolored_fallback_intensity is not None and np.any(~colored_mask):
        inten = np.asarray(uncolored_fallback_intensity, dtype=np.float32)
        gray = np.clip(45.0 + 160.0 * np.clip(inten / 100.0, 0.0, 1.0), 30.0, 220.0).astype(np.uint8)
        unseen = ~colored_mask
        best_rgb[unseen] = np.column_stack([gray[unseen], gray[unseen], gray[unseen]])

    return {
        "colors_rgb": best_rgb,
        "colored_mask": colored_mask,
        "best_view_index": best_view_idx,
        "best_score": best_score,
    }


def export_colored_ply(
    filepath: str | Path,
    pts_enu: np.ndarray,
    colors_rgb: np.ndarray,
    visible_only: bool = False,
    visible_mask: np.ndarray | None = None,
) -> Path:
    """Export an `(N, 3)` ENU point cloud with `(R, G, B)` colors to binary little-endian `.ply`."""
    pts = np.asarray(pts_enu[:, :3], dtype=np.float32)
    rgb = np.asarray(colors_rgb[:, :3], dtype=np.uint8)
    if visible_only and visible_mask is not None:
        mask = np.asarray(visible_mask, dtype=bool)
        pts = pts[mask]
        rgb = rgb[mask]

    out_path = Path(filepath)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vertex_dt = np.dtype(
        [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("red", "u1"), ("green", "u1"), ("blue", "u1")]
    )
    vertices = np.empty(len(pts), dtype=vertex_dt)
    if len(pts) > 0:
        vertices["x"] = pts[:, 0]
        vertices["y"] = pts[:, 1]
        vertices["z"] = pts[:, 2]
        vertices["red"] = rgb[:, 0]
        vertices["green"] = rgb[:, 1]
        vertices["blue"] = rgb[:, 2]

    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {len(vertices)}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    ).encode("ascii")
    with out_path.open("wb") as f:
        f.write(header)
        f.write(vertices.tobytes())
    return out_path
