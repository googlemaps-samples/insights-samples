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
"""Pure-3D LiDAR spatial building blocks for assets, facades, roads, and sidewalks."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def estimate_local_ground_z(
    pts_enu: np.ndarray,
    center_xy: tuple[float, float] | None = None,
    inner_r_m: float = 0.0,
    outer_r_m: float = 6.0,
    percentile: float = 10.0,
    subterranean_cutoff_m: float = -15.0,
) -> tuple[float, np.ndarray]:
    """Estimate local street level `Z_ground` and strip subterranean multipath glare.

    Wet asphalt and vehicle hoods can reflect ghost laser returns underground. Taking a low
    percentile (`5th–12th`) of nearby ground points after dropping deep multipath outliers
    anchors heights to the physical street surface so cross-epoch GPS altitude shifts cancel out.
    """
    pts = np.asarray(pts_enu, dtype=np.float64)
    if len(pts) == 0:
        return 0.0, np.empty(0, dtype=bool)

    valid_z = pts[:, 2] > float(subterranean_cutoff_m)
    if center_xy is None:
        cx, cy = float(np.median(pts[valid_z, 0])) if np.any(valid_z) else 0.0, (
            float(np.median(pts[valid_z, 1])) if np.any(valid_z) else 0.0
        )
    else:
        cx, cy = float(center_xy[0]), float(center_xy[1])

    radial = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    ring = valid_z & (radial >= float(inner_r_m)) & (radial <= float(outer_r_m))
    z_pool = pts[ring, 2] if np.count_nonzero(ring) >= 10 else pts[valid_z, 2]
    if len(z_pool) == 0:
        return 0.0, np.zeros(len(pts), dtype=bool)

    # Guard against isolated underground reflections by clipping >4 m below median before percentile.
    z_med = float(np.median(z_pool))
    plausible = z_pool[z_pool >= (z_med - 4.0)]
    z_ground = float(np.percentile(plausible if len(plausible) > 0 else z_pool, percentile))
    above_ground_mask = pts[:, 2] >= (z_ground - 0.15)
    return z_ground, above_ground_mask


def measure_point_to_point_3d(
    pt_a_enu: np.ndarray | tuple[float, float, float],
    pt_b_enu: np.ndarray | tuple[float, float, float],
) -> dict[str, float]:
    """Compute exact 3D Euclidean distance, horizontal span, and vertical delta in meters."""
    a = np.asarray(pt_a_enu, dtype=np.float64)[:3]
    b = np.asarray(pt_b_enu, dtype=np.float64)[:3]
    delta = b - a
    horiz_m = float(np.hypot(delta[0], delta[1]))
    dist_3d_m = float(np.linalg.norm(delta))
    return {
        "distance_3d_m": round(dist_3d_m, 3),
        "horizontal_distance_m": round(horiz_m, 3),
        "vertical_delta_m": round(float(delta[2]), 3),
    }


def measure_pole_3d(
    pts_enu: np.ndarray,
    z_ground_m: float | None = None,
    trunk_radius_m: float = 0.32,
    air_gap_stop_m: float = 1.2,
) -> dict[str, Any]:
    """Measure utility pole height above ground and 3D lean angle while excluding overhead wires.

    Fits a 3D line to the lower pole shaft (`0.5–4.5 m` AGL) via SVD so leaning poles are
    tracked accurately, keeps points within `trunk_radius_m` (`32 cm`) of that tilted axis,
    and stops at the first `>= 1.2 m` vertical air gap so overhead wires are not counted.
    """
    pts = np.asarray(pts_enu, dtype=np.float64)
    if len(pts) < 12:
        return {"valid": False, "reason": "insufficient_points", "point_count": len(pts)}

    if z_ground_m is None:
        z_ground_m, _ = estimate_local_ground_z(pts, outer_r_m=4.5)
    agl = pts[:, 2] - float(z_ground_m)

    lower_mask = (agl >= 0.5) & (agl <= 4.5)
    if np.count_nonzero(lower_mask) < 8:
        lower_mask = agl >= 0.25
    if np.count_nonzero(lower_mask) < 8:
        return {"valid": False, "reason": "insufficient_shaft_points", "point_count": len(pts)}

    lower_pts = pts[lower_mask]
    # Anchor horizontal medoid on the lower shaft to resist adjacent foliage outliers.
    xy_med = np.median(lower_pts[:, :2], axis=0)
    core_mask = np.hypot(lower_pts[:, 0] - xy_med[0], lower_pts[:, 1] - xy_med[1]) <= 0.65
    seed_pts = lower_pts[core_mask] if np.count_nonzero(core_mask) >= 6 else lower_pts

    centroid = seed_pts.mean(axis=0)
    _, _, vh = np.linalg.svd(seed_pts - centroid, full_matrices=False)
    axis = vh[0]
    if axis[2] < 0.0:
        axis = -axis
    # Guard against horizontal wire/fence seeds: pole axis must be predominantly vertical.
    if abs(axis[2]) < 0.70:
        axis = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    rel = pts - centroid
    proj_len = rel @ axis
    perp_vec = rel - np.outer(proj_len, axis)
    perp_dist = np.linalg.norm(perp_vec, axis=1)

    on_column = (agl >= 0.05) & (perp_dist <= float(trunk_radius_m))
    col_idx = np.flatnonzero(on_column)
    if len(col_idx) < 8:
        return {"valid": False, "reason": "thin_column", "point_count": int(len(col_idx))}

    col_agl = agl[col_idx]
    order = np.argsort(col_agl)
    sorted_agl = col_agl[order]
    gaps = np.diff(sorted_agl)
    big_gaps = np.flatnonzero((gaps >= float(air_gap_stop_m)) & (sorted_agl[:-1] >= 3.0))
    if len(big_gaps) > 0:
        cutoff_pos = int(big_gaps[0]) + 1
        keep_order = order[:cutoff_pos]
    else:
        keep_order = order

    inlier_idx = col_idx[keep_order]
    inlier_pts = pts[inlier_idx]
    # Re-fit final 3D shaft axis on all retained pole points for sub-degree lean precision.
    c_final = inlier_pts.mean(axis=0)
    _, _, vh_final = np.linalg.svd(inlier_pts - c_final, full_matrices=False)
    axis_final = vh_final[0]
    if axis_final[2] < 0.0:
        axis_final = -axis_final

    lean_deg = float(math.degrees(math.acos(np.clip(axis_final[2], -1.0, 1.0))))
    lean_az_deg = float((math.degrees(math.atan2(axis_final[0], axis_final[1])) + 360.0) % 360.0)
    height_m = float(np.percentile(agl[inlier_idx], 99.0))

    return {
        "valid": True,
        "height_m": round(height_m, 3),
        "lean_deg": round(lean_deg, 2),
        "lean_azimuth_deg": round(lean_az_deg, 1),
        "z_ground_m": round(float(z_ground_m), 3),
        "point_count": int(len(inlier_idx)),
        "inlier_indices": inlier_idx,
    }


def measure_sign_3d(
    pts_enu: np.ndarray,
    intensity: np.ndarray,
    z_ground_m: float | None = None,
    retro_threshold: int = 115,
    plane_tol_m: float = 0.08,
) -> dict[str, Any]:
    """Measure road sign face width, height, clearance, and retroreflectivity in 3D.

    Uses bright retroreflective returns (`intensity >= 115`, vs `0..100` diffuse background)
    to seed the flat 3D sign plane, then includes all coplanar points (both bright sheeting
    and dark borders/letters) while trimming the narrow supporting post below the sign face.
    """
    pts = np.asarray(pts_enu, dtype=np.float64)
    inten = np.asarray(intensity, dtype=np.float64)
    if len(pts) < 10:
        return {"valid": False, "reason": "insufficient_points", "point_count": len(pts)}

    if z_ground_m is None:
        z_ground_m, _ = estimate_local_ground_z(pts, outer_r_m=4.5)
    agl = pts[:, 2] - float(z_ground_m)

    above = agl >= 0.8
    retro_seed = above & (inten >= float(retro_threshold))
    seed_pts = pts[retro_seed] if np.count_nonzero(retro_seed) >= 6 else pts[above & (agl >= 1.4)]
    if len(seed_pts) < 6:
        return {"valid": False, "reason": "no_sign_seed", "point_count": int(len(seed_pts))}

    center = np.median(seed_pts, axis=0)
    near_seed = seed_pts[np.linalg.norm(seed_pts - center, axis=1) <= 1.5]
    if len(near_seed) < 6:
        near_seed = seed_pts

    mean_pt = near_seed.mean(axis=0)
    _, _, vh = np.linalg.svd(near_seed - mean_pt, full_matrices=False)
    normal = vh[2]
    horiz_u = np.array([-normal[1], normal[0], 0.0], dtype=np.float64)
    h_norm = float(np.linalg.norm(horiz_u))
    horiz_u = horiz_u / h_norm if h_norm > 1e-6 else np.array([1.0, 0.0, 0.0], dtype=np.float64)

    rel = pts - mean_pt
    plane_dist = np.abs(rel @ normal)
    u_coord = rel @ horiz_u
    coplanar = above & (plane_dist <= float(plane_tol_m)) & (np.abs(u_coord) <= 2.2)
    cand_idx = np.flatnonzero(coplanar)
    if len(cand_idx) < 8:
        return {"valid": False, "reason": "sparse_sign_plane", "point_count": int(len(cand_idx))}

    # Trim narrow vertical post (< 15 cm horizontal span) beneath the wider sign panel.
    z_vals = agl[cand_idx]
    u_vals = u_coord[cand_idx]
    z_min, z_max = float(z_vals.min()), float(z_vals.max())
    bins = np.linspace(z_min, z_max + 1e-3, max(4, int(round((z_max - z_min) / 0.08)) + 1))
    panel_z_lo = z_min
    for b_idx in range(len(bins) - 1):
        in_slice = (z_vals >= bins[b_idx]) & (z_vals < bins[b_idx + 1])
        if np.count_nonzero(in_slice) >= 3:
            slice_w = float(np.percentile(u_vals[in_slice], 95) - np.percentile(u_vals[in_slice], 5))
            if slice_w >= 0.16:
                panel_z_lo = float(bins[b_idx])
                break

    panel_mask = z_vals >= panel_z_lo
    panel_idx = cand_idx[panel_mask] if np.count_nonzero(panel_mask) >= 6 else cand_idx
    p_u = u_coord[panel_idx]
    p_agl = agl[panel_idx]
    p_int = inten[panel_idx]

    width_m = float(np.percentile(p_u, 98) - np.percentile(p_u, 2))
    bottom_m = float(np.percentile(p_agl, 2))
    top_m = float(np.percentile(p_agl, 98))
    diffuse_pool = inten[inten <= 100.0]
    diffuse_med = float(np.median(diffuse_pool)) if len(diffuse_pool) > 0 else 25.0
    retro_p90 = float(np.percentile(p_int, 90))

    return {
        "valid": True,
        "width_m": round(max(0.05, width_m), 3),
        "height_m": round(max(0.05, top_m - bottom_m), 3),
        "bottom_clearance_m": round(bottom_m, 3),
        "top_height_m": round(top_m, 3),
        "retro_p90_intensity": round(retro_p90, 1),
        "retro_ratio_vs_diffuse": round(retro_p90 / max(1.0, diffuse_med), 2),
        "point_count": int(len(panel_idx)),
        "inlier_indices": panel_idx,
    }


def measure_tree_3d(
    pts_enu: np.ndarray,
    z_ground_m: float | None = None,
) -> dict[str, Any]:
    """Measure street tree 98th-percentile height, crown width, and lowest canopy clearance."""
    pts = np.asarray(pts_enu, dtype=np.float64)
    if len(pts) < 15:
        return {"valid": False, "reason": "insufficient_points", "point_count": len(pts)}

    if z_ground_m is None:
        z_ground_m, _ = estimate_local_ground_z(pts, outer_r_m=6.0)
    agl = pts[:, 2] - float(z_ground_m)

    tree_mask = agl >= 0.4
    if np.count_nonzero(tree_mask) < 12:
        return {"valid": False, "reason": "no_elevated_points", "point_count": int(np.count_nonzero(tree_mask))}

    canopy_mask = agl >= 2.2
    canopy_pts = pts[canopy_mask] if np.count_nonzero(canopy_mask) >= 8 else pts[tree_mask]
    trunk_mask = (agl >= 0.5) & (agl < 2.2)
    trunk_xy = (
        np.median(pts[trunk_mask, :2], axis=0)
        if np.count_nonzero(trunk_mask) >= 4
        else np.median(canopy_pts[:, :2], axis=0)
    )

    # Crown spread from radial horizontal extent around trunk + principal spans.
    dx = canopy_pts[:, 0] - trunk_xy[0]
    dy = canopy_pts[:, 1] - trunk_xy[1]
    radial = np.hypot(dx, dy)
    span_x = float(np.percentile(dx, 98) - np.percentile(dx, 2))
    span_y = float(np.percentile(dy, 98) - np.percentile(dy, 2))
    crown_width_m = float(max(span_x, span_y, 2.0 * float(np.percentile(radial, 95))))

    outer_foliage = canopy_pts[radial > 0.65]
    canopy_clearance_m = (
        float(np.percentile(outer_foliage[:, 2] - float(z_ground_m), 5))
        if len(outer_foliage) >= 5
        else float(np.percentile(canopy_pts[:, 2] - float(z_ground_m), 10))
    )

    return {
        "valid": True,
        "height_m": round(float(np.percentile(agl[tree_mask], 98)), 3),
        "crown_width_m": round(crown_width_m, 3),
        "canopy_clearance_m": round(canopy_clearance_m, 3),
        "z_ground_m": round(float(z_ground_m), 3),
        "point_count": int(np.count_nonzero(tree_mask)),
    }


def measure_facade_3d(
    pts_enu: np.ndarray,
    z_ground_m: float | None = None,
    camera_xy: tuple[float, float] = (0.0, 0.0),
    plane_tol_m: float = 0.10,
) -> dict[str, Any]:
    """Fit the dominant front building wall (`>= 1.2 m` AGL) and reject interior glass returns."""
    pts = np.asarray(pts_enu, dtype=np.float64)
    if len(pts) < 20:
        return {"valid": False, "reason": "insufficient_points", "point_count": len(pts)}

    if z_ground_m is None:
        z_ground_m, _ = estimate_local_ground_z(pts, outer_r_m=8.0)
    agl = pts[:, 2] - float(z_ground_m)

    # Ignore low porch steps, railings, and parked cars (< 1.2 m AGL).
    elev_idx = np.flatnonzero(agl >= 1.2)
    if len(elev_idx) < 15:
        return {"valid": False, "reason": "insufficient_wall_points", "point_count": int(len(elev_idx))}

    elev_pts = pts[elev_idx]
    cam_xy = np.array([float(camera_xy[0]), float(camera_xy[1])], dtype=np.float64)

    # Deterministic 2D line RANSAC over horizontal `(E, N)` footprint for a wide vertical wall
    # (`span >= 2.5 m` prevents narrow poles or single tree trunks from winning over facades).
    rng = np.random.default_rng(42)
    best_inliers = np.empty(0, dtype=np.int64)
    n_elev = len(elev_pts)
    xy = elev_pts[:, :2]

    for _ in range(min(140, max(30, n_elev))):
        i1, i2 = rng.choice(n_elev, size=2, replace=False)
        tangent = xy[i2] - xy[i1]
        norm_t = float(np.linalg.norm(tangent))
        if norm_t < 0.35:
            continue
        tangent /= norm_t
        normal_2d = np.array([-tangent[1], tangent[0]], dtype=np.float64)
        d_ortho = np.abs((xy - xy[i1]) @ normal_2d)
        inl = np.flatnonzero(d_ortho <= float(plane_tol_m))
        if len(inl) > len(best_inliers):
            along_span = float(np.ptp((xy[inl] - xy[i1]) @ tangent))
            if along_span >= 2.5 or len(best_inliers) == 0:
                best_inliers = inl

    if len(best_inliers) < 10:
        return {"valid": False, "reason": "no_planar_facade", "point_count": int(len(best_inliers))}

    wall_idx = elev_idx[best_inliers]
    wall_pts = pts[wall_idx]
    xy_mean = wall_pts[:, :2].mean(axis=0)
    _, _, vh_2d = np.linalg.svd(wall_pts[:, :2] - xy_mean, full_matrices=False)
    tangent_2d = vh_2d[0]
    normal_2d = np.array([-tangent_2d[1], tangent_2d[0]], dtype=np.float64)
    # Orient normal toward camera and reject interior glass-wall returns (> 0.6 m behind front wall).
    if np.dot(cam_xy - xy_mean, normal_2d) < 0.0:
        normal_2d = -normal_2d
    signed_all = (xy - xy_mean) @ normal_2d
    near_band = (np.abs((xy - xy_mean) @ tangent_2d) <= (0.55 * float(np.ptp((wall_pts[:, :2] - xy_mean) @ tangent_2d)) + 1.0))
    front_offset = float(np.percentile(signed_all[best_inliers], 85))
    # If an exterior storefront wall sits closer to the camera than an interior back-wall, lock onto front plane.
    closer_candidates = np.flatnonzero(near_band & (signed_all > front_offset + 0.6) & (signed_all < front_offset + 5.0))
    if len(closer_candidates) >= max(20, int(0.5 * len(best_inliers))):
        front_med = float(np.median(signed_all[closer_candidates]))
        front_inl = np.flatnonzero(near_band & (np.abs(signed_all - front_med) <= float(plane_tol_m)))
        if len(front_inl) >= 15:
            wall_idx = elev_idx[front_inl]
            wall_pts = pts[wall_idx]
            xy_mean = wall_pts[:, :2].mean(axis=0)

    ortho_res = (wall_pts[:, :2] - xy_mean) @ normal_2d
    along_wall = (wall_pts[:, :2] - xy_mean) @ tangent_2d
    wall_agl = agl[wall_idx]

    flatness_cm = float(np.sqrt(np.mean(ortho_res * ortho_res)) * 100.0)
    wall_az_deg = float((math.degrees(math.atan2(tangent_2d[0], tangent_2d[1])) + 180.0) % 180.0)
    setback_m = float(abs(np.dot(xy_mean - cam_xy, normal_2d)))

    return {
        "valid": True,
        "wall_height_m": round(float(np.percentile(wall_agl, 98)), 3),
        "wall_width_m": round(float(np.percentile(along_wall, 98) - np.percentile(along_wall, 2)), 3),
        "flatness_rms_cm": round(flatness_cm, 2),
        "wall_azimuth_deg": round(wall_az_deg, 1),
        "setback_distance_m": round(setback_m, 3),
        "z_ground_m": round(float(z_ground_m), 3),
        "point_count": int(len(wall_idx)),
        "inlier_indices": wall_idx,
    }


def measure_corridor_cross_section(
    pts_enu: np.ndarray,
    intensity: np.ndarray | None = None,
    heading_deg: float = 0.0,
    station_along_m: float = 0.0,
    slab_length_m: float = 4.0,
    max_lateral_m: float = 14.0,
) -> dict[str, Any]:
    """Slice a perpendicular street corridor cross-section for roadway, curbs, and sidewalks.

    Rotates ENU points into `(along_m, cross_m, z_m)` aligned with `heading_deg`, detrends
    longitudinal street slope across `slab_length_m` (`4.0 m` default) so sloped streets do not
    smear curb steps, and profiles `25 cm` lateral bins to extract:
      - Curb-to-curb roadway width (`m`), road cross-slope (`%`), and curb reveal (`cm`)
      - Concrete/paved sidewalk vs. grass verge separation (using surface roughness `std(z)`
        plus laser reflectivity), sidewalk width (`m`), cross-slope (`%`), max trip step (`cm`),
        and unobstructed clear path width (`m`).
    """
    pts = np.asarray(pts_enu, dtype=np.float64)
    if len(pts) < 40:
        return {"valid": False, "reason": "insufficient_points", "point_count": len(pts)}

    psi = math.radians(float(heading_deg))
    fwd = np.array([math.sin(psi), math.cos(psi)], dtype=np.float64)
    right = np.array([math.cos(psi), -math.sin(psi)], dtype=np.float64)

    along = pts[:, :2] @ fwd
    cross = pts[:, :2] @ right
    z_raw = pts[:, 2]

    half_len = 0.5 * float(slab_length_m)
    in_slab = (
        (np.abs(along - float(station_along_m)) <= half_len)
        & (np.abs(cross) <= float(max_lateral_m))
        & (z_raw > -15.0)
    )
    if np.count_nonzero(in_slab) < 30:
        return {"valid": False, "reason": "sparse_corridor_slab", "point_count": int(np.count_nonzero(in_slab))}

    s_along = along[in_slab] - float(station_along_m)
    s_cross = cross[in_slab]
    s_z = z_raw[in_slab]
    s_int = (
        np.asarray(intensity, dtype=np.float64)[in_slab]
        if intensity is not None and len(intensity) == len(pts)
        else np.full(len(s_z), 35.0, dtype=np.float64)
    )

    # Detrend longitudinal road grade near roadway centerline (`|cross| <= 2.5 m`).
    center_road = np.abs(s_cross) <= 2.5
    if np.count_nonzero(center_road) >= 10 and float(np.ptp(s_along[center_road])) > 0.4:
        grade_slope, z0 = np.polyfit(s_along[center_road], s_z[center_road], 1)
    else:
        grade_slope, z0 = 0.0, float(np.percentile(s_z, 15))
    z_det = s_z - grade_slope * s_along

    # Keep near-ground surface points (`[-0.4 m, +0.65 m]` around roadway datum) for surface profiling,
    # while separately tracking obstacles (`[0.20 m, 2.10 m]` above surface) for sidewalk clear path.
    road_z_med = float(np.median(z_det[center_road])) if np.any(center_road) else float(z0)
    ground_band = (z_det >= (road_z_med - 0.40)) & (z_det <= (road_z_med + 0.65))

    bin_w = 0.25
    edges = np.arange(-float(max_lateral_m), float(max_lateral_m) + bin_w * 0.5, bin_w)
    n_bins = len(edges) - 1
    bin_centers = 0.5 * (edges[:-1] + edges[1:])
    bin_z = np.full(n_bins, np.nan, dtype=np.float64)
    bin_rough = np.full(n_bins, np.nan, dtype=np.float64)
    bin_int = np.full(n_bins, np.nan, dtype=np.float64)

    g_cross = s_cross[ground_band]
    g_z = z_det[ground_band]
    g_int = s_int[ground_band]
    b_ids = np.clip(np.digitize(g_cross, edges) - 1, 0, n_bins - 1)

    for b in range(n_bins):
        m = b_ids == b
        if np.count_nonzero(m) >= 3:
            z_b = g_z[m]
            floor_z = float(np.percentile(z_b, 20))
            floor_m = np.abs(z_b - floor_z) <= 0.12
            z_surf = z_b[floor_m] if np.count_nonzero(floor_m) >= 3 else z_b
            i_surf = g_int[m][floor_m] if np.count_nonzero(floor_m) >= 3 else g_int[m]
            bin_z[b] = float(np.median(z_surf))
            bin_rough[b] = float(np.std(z_surf))
            bin_int[b] = float(np.median(i_surf))

    def _find_curb_and_sidewalk(sign: int) -> dict[str, Any]:
        # sign = +1 for right side (`cross > 0`), -1 for left side (`cross < 0`).
        side_bins = (
            np.flatnonzero((bin_centers >= 1.25) & np.isfinite(bin_z))
            if sign > 0
            else np.flatnonzero((bin_centers <= -1.25) & np.isfinite(bin_z))[::-1]
        )
        curb_x: float | None = None
        curb_reveal_cm = 0.0
        for idx_pos in range(len(side_bins) - 1):
            b0 = side_bins[idx_pos]
            b1 = side_bins[idx_pos + 1]
            if abs(bin_centers[b1] - bin_centers[b0]) > 0.6:
                continue
            dz_cm = (bin_z[b1] - bin_z[b0]) * 100.0
            if 4.5 <= dz_cm <= 28.0:
                curb_x = float(0.5 * (bin_centers[b0] + bin_centers[b1]))
                curb_reveal_cm = float(dz_cm)
                break

        start_abs = abs(curb_x) + 0.12 if curb_x is not None else 3.25
        behind_mask = (
            (bin_centers >= start_abs) & (bin_centers <= start_abs + 6.5) & np.isfinite(bin_z)
            if sign > 0
            else (bin_centers <= -start_abs) & (bin_centers >= -(start_abs + 6.5)) & np.isfinite(bin_z)
        )
        b_list = np.flatnonzero(behind_mask)
        if sign < 0:
            b_list = b_list[::-1]

        # Smooth, bright paved footpath bins: find longest contiguous paved run behind the curb.
        cur_run: list[int] = []
        paved_bins: list[int] = []
        first_paved_pos: int | None = None
        for pos_i, b in enumerate(b_list):
            is_smooth = (bin_rough[b] <= 0.028) and (bin_int[b] >= 18.0)
            if is_smooth:
                cur_run.append(int(b))
                if len(cur_run) > len(paved_bins):
                    paved_bins = list(cur_run)
                    first_paved_pos = pos_i - len(cur_run) + 1
            else:
                cur_run = []
        verge_bins = int(first_paved_pos) if (first_paved_pos is not None and len(paved_bins) >= 3) else len(b_list)

        if len(paved_bins) >= 3:
            sw_xs = bin_centers[paved_bins]
            sw_zs = bin_z[paved_bins]
            sw_width_m = float(len(paved_bins) * bin_w)
            slope_fit = float(abs(np.polyfit(sw_xs, sw_zs, 1)[0]) * 100.0) if len(sw_xs) >= 2 else 0.0
            step_diffs_cm = np.abs(np.diff(sw_zs)) * 100.0 if len(sw_zs) >= 2 else np.array([0.0])
            max_trip_cm = float(np.max(step_diffs_cm))

            # Check above-surface obstacles (`0.25–2.0 m` above footpath) for clear path width.
            x_lo, x_hi = float(min(sw_xs) - 0.5 * bin_w), float(max(sw_xs) + 0.5 * bin_w)
            sw_surf_z = float(np.median(sw_zs))
            obs_m = (
                (s_cross >= x_lo)
                & (s_cross <= x_hi)
                & (z_det >= sw_surf_z + 0.25)
                & (z_det <= sw_surf_z + 2.05)
            )
            if np.count_nonzero(obs_m) >= 5:
                obs_bins = set(np.clip(np.digitize(s_cross[obs_m], edges) - 1, 0, n_bins - 1).tolist())
                clear_bins = sum(1 for b in paved_bins if b not in obs_bins)
                clear_w = float(clear_bins * bin_w)
            else:
                clear_w = sw_width_m
        else:
            sw_width_m = 0.0
            clear_w = 0.0
            slope_fit = 0.0
            max_trip_cm = 0.0

        return {
            "curb_offset_m": round(curb_x, 3) if curb_x is not None else None,
            "curb_reveal_cm": round(curb_reveal_cm, 1),
            "verge_width_m": round(float(verge_bins * bin_w), 2),
            "sidewalk_width_m": round(sw_width_m, 2),
            "clear_path_width_m": round(clear_w, 2),
            "sidewalk_cross_slope_pct": round(slope_fit, 2),
            "max_trip_step_cm": round(max_trip_cm, 1),
        }

    right_side = _find_curb_and_sidewalk(+1)
    left_side = _find_curb_and_sidewalk(-1)

    if right_side["curb_offset_m"] is not None and left_side["curb_offset_m"] is not None:
        roadway_width_m = float(right_side["curb_offset_m"] - left_side["curb_offset_m"])
    else:
        road_bins = np.flatnonzero((np.abs(bin_centers) <= 5.0) & np.isfinite(bin_z) & (bin_rough <= 0.03))
        roadway_width_m = float(len(road_bins) * bin_w) if len(road_bins) > 0 else 0.0

    crown_bins = np.flatnonzero((bin_centers >= 0.0) & (bin_centers <= 3.0) & np.isfinite(bin_z))
    road_cross_slope_pct = (
        float(abs(np.polyfit(bin_centers[crown_bins], bin_z[crown_bins], 1)[0]) * 100.0)
        if len(crown_bins) >= 3
        else 0.0
    )

    return {
        "valid": True,
        "station_along_m": round(float(station_along_m), 2),
        "slab_length_m": round(float(slab_length_m), 2),
        "longitudinal_grade_pct": round(float(grade_slope * 100.0), 2),
        "roadway_width_m": round(roadway_width_m, 2),
        "road_cross_slope_pct": round(road_cross_slope_pct, 2),
        "right_side": right_side,
        "left_side": left_side,
        "slab_point_count": int(np.count_nonzero(in_slab)),
    }


def discover_roadside_assets_3d(
    pts_enu: np.ndarray,
    intensity: np.ndarray,
    z_ground_m: float | None = None,
    max_range_m: float = 40.0,
) -> list[dict[str, Any]]:
    """Discover and measure uncataloged signs, poles, trees, and facades in 3D (for SV_PANO clouds).

    Unlike `full_frame_observations_latest`, `pano_observations_latest` provides 360-degree
    streetscape coverage without pre-cataloged `bbox` rows. This helper segments elevated
    above-ground returns on a 2D horizontal grid to extract candidate signs (via `uint16`
    retroreflectivity `>= 115`), poles, trees, and facades directly from the `.laz` point cloud.
    """
    pts = np.asarray(pts_enu, dtype=np.float64)
    inten = np.asarray(intensity, dtype=np.float64)
    if len(pts) < 30:
        return []

    if z_ground_m is None:
        z_ground_m, _ = estimate_local_ground_z(pts, outer_r_m=8.0)

    horiz_r = np.hypot(pts[:, 0], pts[:, 1])
    agl = pts[:, 2] - float(z_ground_m)
    in_zone = (horiz_r >= 2.6) & (horiz_r <= float(max_range_m)) & (agl >= 0.4)
    if np.count_nonzero(in_zone) < 20:
        return []

    discovered: list[dict[str, Any]] = []

    # 1. Retroreflective road signs (`intensity >= 115` seeds).
    retro_idx = np.flatnonzero(in_zone & (agl >= 1.2) & (inten >= 115.0))
    used_xy: list[np.ndarray] = []
    for seed_i in retro_idx:
        xy_s = pts[seed_i, :2]
        if any(float(np.linalg.norm(xy_s - prev)) < 1.8 for prev in used_xy):
            continue
        local = in_zone & (np.hypot(pts[:, 0] - xy_s[0], pts[:, 1] - xy_s[1]) <= 1.2)
        if np.count_nonzero(local) < 12:
            continue
        m = measure_sign_3d(pts[local], inten[local], z_ground_m=z_ground_m)
        if m.get("valid"):
            m.pop("inlier_indices", None)
            used_xy.append(xy_s)
            discovered.append(
                {
                    "asset_type": "ASSET_CLASS_ROAD_SIGN",
                    "centroid_enu_m": [round(float(xy_s[0]), 2), round(float(xy_s[1]), 2)],
                    "measurements_3d": m,
                }
            )
            if len(discovered) >= 6:
                break

    # 2. Dominant front building facade (`span >= 2.5 m`).
    fac = measure_facade_3d(pts[in_zone], z_ground_m=z_ground_m)
    if fac.get("valid"):
        inl = fac.pop("inlier_indices")
        fac_xy = np.median(pts[in_zone][inl, :2], axis=0)
        discovered.append(
            {
                "asset_type": "ASSET_CLASS_BUILDING",
                "centroid_enu_m": [round(float(fac_xy[0]), 2), round(float(fac_xy[1]), 2)],
                "measurements_3d": fac,
            }
        )

    # 3. Tall slender columns (poles) vs broad elevated crowns (trees) on a 2.5 m XY cell grid.
    tall_mask = in_zone & (agl >= 4.0)
    if np.count_nonzero(tall_mask) >= 15:
        t_pts = pts[tall_mask]
        gx = np.floor(t_pts[:, 0] / 2.5).astype(np.int32)
        gy = np.floor(t_pts[:, 1] / 2.5).astype(np.int32)
        cells = np.unique(np.column_stack([gx, gy]), axis=0)
        for cx_i, cy_i in cells[:16]:
            cell_center = np.array([(cx_i + 0.5) * 2.5, (cy_i + 0.5) * 2.5], dtype=np.float64)
            if any(float(np.linalg.norm(cell_center - prev)) < 3.0 for prev in used_xy):
                continue
            cyl = in_zone & (np.hypot(pts[:, 0] - cell_center[0], pts[:, 1] - cell_center[1]) <= 3.0)
            c_pts = pts[cyl]
            if len(c_pts) < 25:
                continue
            c_agl = c_pts[:, 2] - float(z_ground_m)
            upper = c_pts[c_agl >= 2.5]
            if len(upper) < 10:
                continue
            spread_m = float(
                max(np.percentile(upper[:, 0], 95) - np.percentile(upper[:, 0], 5),
                    np.percentile(upper[:, 1], 95) - np.percentile(upper[:, 1], 5))
            )
            if spread_m <= 1.1:
                pm = measure_pole_3d(c_pts, z_ground_m=z_ground_m)
                if pm.get("valid") and float(pm["height_m"]) >= 5.0:
                    pm.pop("inlier_indices", None)
                    used_xy.append(cell_center)
                    discovered.append(
                        {
                            "asset_type": "ASSET_CLASS_UTILITY_POLE",
                            "centroid_enu_m": [round(float(cell_center[0]), 2), round(float(cell_center[1]), 2)],
                            "measurements_3d": pm,
                        }
                    )
            elif spread_m >= 2.0:
                tm = measure_tree_3d(c_pts, z_ground_m=z_ground_m)
                if tm.get("valid") and float(tm["height_m"]) >= 4.0:
                    used_xy.append(cell_center)
                    discovered.append(
                        {
                            "asset_type": "ASSET_CLASS_STREET_TREE",
                            "centroid_enu_m": [round(float(cell_center[0]), 2), round(float(cell_center[1]), 2)],
                            "measurements_3d": tm,
                        }
                    )
    return discovered
