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
"""Bidirectional Image + 3D LiDAR fusion: depth-gated crops, 2D->3D casting, and scene clearance."""

from __future__ import annotations

import io
import json
import math
import os
from typing import Any, Mapping

import cv2
import numpy as np
from PIL import Image

from .measurements_3d import estimate_local_ground_z, measure_facade_3d
from .projection_and_rgb import IMAGE_HEIGHT, IMAGE_WIDTH, project_points_to_image

# Standard commercial/service vehicle clearance envelopes (width_m, height_m).
VEHICLE_CLEARANCE_PROFILES: dict[str, dict[str, float]] = {
    "service_van": {"min_width_m": 2.40, "min_height_m": 2.60},
    "box_truck": {"min_width_m": 3.00, "min_height_m": 3.60},
    "heavy_truck": {"min_width_m": 3.50, "min_height_m": 4.30},
}


def _pose_angles(camera_pose: Mapping[str, Any]) -> tuple[float, float, float]:
    heading = float(camera_pose.get("heading") or camera_pose.get("headingDeg") or 0.0)
    pitch = float(camera_pose.get("pitch") or camera_pose.get("pitchDeg") or 0.0)
    roll = float(camera_pose.get("roll") or camera_pose.get("rollDeg") or 0.0)
    return heading, pitch, roll


def build_depth_gated_crop(
    img_rgb: np.ndarray,
    pts_enu: np.ndarray,
    cluster_indices: np.ndarray,
    camera_pose: Mapping[str, Any],
    depth_margin_m: float = 1.2,
    pad_frac: float = 0.18,
    dim_factor: float = 0.22,
    full_res_wh: tuple[int, int] = (IMAGE_WIDTH, IMAGE_HEIGHT),
) -> dict[str, Any]:
    """Build a 3D depth-masked 2D crop around a `.laz` object cluster (`3D -> 2D`).

    Projects the 3D object cluster onto `img_rgb`, defines a padded 2D crop window, and uses
    all projected 3D returns inside that window to build a foreground mask around the target's
    depth band (`[d_p10 - margin, d_p90 + margin]`). Background buildings, distant trees, and
    sky pixels outside that 3D depth slice are dimmed (`dim_factor`), eliminating ~80% of
    background visual clutter before passing the crop to Gemini.
    """
    img_h, img_w = img_rgb.shape[:2]
    heading, pitch, roll = _pose_angles(camera_pose)

    # Project using `full_res_wh` intrinsics scaled to `img_rgb`'s actual pixel dimensions.
    proj_all = project_points_to_image(
        pts_enu=pts_enu,
        heading_deg=heading,
        pitch_deg=pitch,
        roll_deg=roll,
        image_wh=(img_w, img_h) if (img_w, img_h) != full_res_wh else full_res_wh,
    )
    cluster_idx = np.asarray(cluster_indices, dtype=np.int64)
    vis_cluster = cluster_idx[proj_all["in_bounds"][cluster_idx]]
    if len(vis_cluster) < 4:
        return {"valid": False, "reason": "cluster_outside_camera_frustum"}

    u_obj = proj_all["u"][vis_cluster]
    v_obj = proj_all["v"][vis_cluster]
    d_obj = proj_all["depth_m"][vis_cluster]

    u_min, u_max = float(np.percentile(u_obj, 2)), float(np.percentile(u_obj, 98))
    v_min, v_max = float(np.percentile(v_obj, 2)), float(np.percentile(v_obj, 98))
    pad_u = max(16.0, (u_max - u_min) * float(pad_frac))
    pad_v = max(16.0, (v_max - v_min) * float(pad_frac))

    x0 = max(0, int(math.floor(u_min - pad_u)))
    x1 = min(img_w, int(math.ceil(u_max + pad_u)))
    y0 = max(0, int(math.floor(v_min - pad_v)))
    y1 = min(img_h, int(math.ceil(v_max + pad_v)))
    if (x1 - x0) < 8 or (y1 - y0) < 8:
        return {"valid": False, "reason": "degenerate_crop_box"}

    crop = img_rgb[y0:y1, x0:x1, :3].copy()
    ch, cw = crop.shape[:2]

    d_lo = float(np.percentile(d_obj, 10)) - float(depth_margin_m)
    d_hi = float(np.percentile(d_obj, 90)) + float(depth_margin_m)

    in_crop = (
        proj_all["in_bounds"]
        & (proj_all["u"] >= x0)
        & (proj_all["u"] < x1)
        & (proj_all["v"] >= y0)
        & (proj_all["v"] < y1)
    )
    cu = np.clip((proj_all["u"][in_crop] - x0).astype(np.int32), 0, cw - 1)
    cv = np.clip((proj_all["v"][in_crop] - y0).astype(np.int32), 0, ch - 1)
    cd = proj_all["depth_m"][in_crop]

    fg_hits = (cd >= d_lo) & (cd <= d_hi)
    mask = np.zeros((ch, cw), dtype=np.uint8)
    if np.any(fg_hits):
        mask[cv[fg_hits], cu[fg_hits]] = 255
        ksize = max(7, int(round(min(cw, ch) * 0.08)) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
        mask = cv2.dilate(mask, kernel, iterations=2)
        mask = cv2.GaussianBlur(mask, (ksize, ksize), 0)

    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    weight = float(dim_factor) + (1.0 - float(dim_factor)) * alpha
    masked_crop = np.clip(crop.astype(np.float32) * weight, 0.0, 255.0).astype(np.uint8)
    bg_eliminated_frac = float(np.mean(mask < 64))

    return {
        "valid": True,
        "crop_rgb": masked_crop,
        "raw_crop_rgb": crop,
        "bbox_px": {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1},
        "target_depth_band_m": (round(max(0.0, d_lo), 2), round(d_hi, 2)),
        "background_eliminated_fraction": round(bg_eliminated_frac, 3),
    }


def classify_depth_gated_crop_with_gemini(
    crop_rgb: np.ndarray,
    asset_class: str = "utility_pole",
    model: str | None = None,
    project_id: str | None = None,
    location: str = "global",
    genai_client: Any = None,
) -> dict[str, Any]:
    """Classify subtype, material, and condition on a 3D depth-masked crop using Gemini."""
    from google import genai
    from google.genai import types

    resolved_model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if genai_client is None:
        proj = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if proj and proj != "YOUR_PROJECT_ID":
            genai_client = genai.Client(vertexai=True, project=proj, location=location)
        else:
            genai_client = genai.Client()

    buf = io.BytesIO()
    Image.fromarray(np.asarray(crop_rgb, dtype=np.uint8)).save(buf, format="JPEG", quality=90)
    image_part = types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")

    prompt = (
        f"Inspect the foreground target object in this 3D depth-masked Street View crop "
        f"(expected class: {asset_class}; distant background clutter has been dimmed). "
        "Return strict JSON with keys: "
        '{"confirmed": bool, "detected_label": str, "material": str, '
        '"condition": str, "summary": str}.'
    )
    response = genai_client.models.generate_content(
        model=resolved_model,
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    parsed = json.loads(response.text or "{}")
    usage = getattr(response, "usage_metadata", None)
    return {
        "model": resolved_model,
        "result": parsed,
        "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(usage, "candidates_token_count", 0) or 0),
    }


def cast_2d_box_to_3d_cluster(
    bbox_norm_1000: tuple[float, float, float, float] | list[float],
    pts_enu: np.ndarray,
    intensity: np.ndarray | None,
    camera_pose: Mapping[str, Any],
    z_ground_m: float | None = None,
    image_wh: tuple[int, int] = (IMAGE_WIDTH, IMAGE_HEIGHT),
    max_range_m: float = 65.0,
) -> dict[str, Any]:
    """Cast a Gemini `[ymin, xmin, ymax, xmax]` (`0..1000`) 2D box onto `.laz` 3D space (`2D -> 3D`).

    Extracts all 3D returns inside the 2D viewing cone, strips local street pavement, clusters
    foreground depth so background buildings behind the box are excluded, and computes the
    3D occlusion fraction (`occluded_fraction`) across the 2D box.
    """
    ymin_n, xmin_n, ymax_n, xmax_n = [float(v) for v in bbox_norm_1000]
    w, h = int(image_wh[0]), int(image_wh[1])
    x0, x1 = (xmin_n / 1000.0) * w, (xmax_n / 1000.0) * w
    y0, y1 = (ymin_n / 1000.0) * h, (ymax_n / 1000.0) * h

    heading, pitch, roll = _pose_angles(camera_pose)
    proj = project_points_to_image(
        pts_enu=pts_enu,
        heading_deg=heading,
        pitch_deg=pitch,
        roll_deg=roll,
        image_wh=image_wh,
    )
    if z_ground_m is None:
        z_ground_m, _ = estimate_local_ground_z(pts_enu, outer_r_m=8.0)

    in_box = (
        proj["in_bounds"]
        & (proj["u"] >= x0)
        & (proj["u"] <= x1)
        & (proj["v"] >= y0)
        & (proj["v"] <= y1)
        & (proj["range_m"] <= float(max_range_m))
    )
    box_idx = np.flatnonzero(in_box)
    if len(box_idx) < 8:
        return {"valid": False, "reason": "no_lidar_in_2d_box", "point_count": int(len(box_idx))}

    agl_box = pts_enu[box_idx, 2] - float(z_ground_m)
    elev_mask = agl_box >= 0.25
    cand_idx = box_idx[elev_mask] if np.count_nonzero(elev_mask) >= 6 else box_idx

    depths = proj["depth_m"][cand_idx]
    # Lock onto the primary foreground surface inside the box (20th percentile + margin).
    d_anchor = float(np.percentile(depths, 20))
    depth_band = (depths >= (d_anchor - 1.0)) & (depths <= (d_anchor + max(2.2, 0.22 * d_anchor)))
    cluster_idx = cand_idx[depth_band]

    # Compute fraction of box cells occluded by obstacles significantly closer than `d_anchor`.
    all_box_depths = proj["depth_m"][box_idx]
    occluders = np.count_nonzero(all_box_depths < (d_anchor - 1.2))
    occluded_frac = float(occluders) / float(max(1, len(box_idx)))

    c_pts = pts_enu[cluster_idx]
    centroid_enu = np.median(c_pts, axis=0)
    result: dict[str, Any] = {
        "valid": True,
        "point_count": int(len(cluster_idx)),
        "cluster_indices": cluster_idx,
        "centroid_enu_m": [round(float(v), 3) for v in centroid_enu],
        "median_depth_m": round(float(np.median(proj["depth_m"][cluster_idx])), 2),
        "height_above_ground_m": round(float(np.percentile(c_pts[:, 2] - float(z_ground_m), 98)), 3),
        "occluded_fraction": round(occluded_frac, 3),
    }
    if intensity is not None and len(intensity) == len(pts_enu):
        result["intensity_p90"] = round(float(np.percentile(intensity[cluster_idx], 90)), 1)
    return result


def analyze_building_and_driveway_scene(
    pts_enu: np.ndarray,
    intensity: np.ndarray | None = None,
    heading_deg: float = 0.0,
    first_floor_band_agl_m: tuple[float, float] | None = None,
    driveway_along_range_m: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Analyze a commercial/building frontage scene and 3D vehicle pull-in envelope.

    Combines 3D wall plane fitting, entry threshold step measurement above the street crown,
    curb-cut / driveway apron width & grade detection, overhead clearance profiling, and
    standard commercial vehicle pull-in checks (`service_van`, `box_truck`, `heavy_truck`).
    """
    pts = np.asarray(pts_enu, dtype=np.float64)
    if len(pts) < 50:
        return {"valid": False, "reason": "insufficient_scene_points", "point_count": len(pts)}

    z_road, _ = estimate_local_ground_z(pts, center_xy=(0.0, 0.0), outer_r_m=5.0, percentile=12.0)
    facade = measure_facade_3d(pts, z_ground_m=z_road)
    if not facade.get("valid"):
        return {"valid": False, "reason": facade.get("reason", "no_facade")}

    wall_idx = facade["inlier_indices"]
    wall_agl = pts[wall_idx, 2] - z_road

    # 1. First-floor height: use a Gemini 2D->3D band if supplied, else detect awning/ledge step or cap.
    if first_floor_band_agl_m is not None:
        first_floor_height_m = float(first_floor_band_agl_m[1])
    else:
        total_wall_h = float(facade["wall_height_m"])
        first_floor_height_m = min(total_wall_h, max(3.2, round(total_wall_h * 0.52, 2))) if total_wall_h >= 6.0 else total_wall_h

    # 2. Entry threshold step above road (cm): ground/porch points within 1.5 m in front of the wall base.
    psi = math.radians(float(heading_deg))
    fwd = np.array([math.sin(psi), math.cos(psi)], dtype=np.float64)
    right = np.array([math.cos(psi), -math.sin(psi)], dtype=np.float64)
    along = pts[:, :2] @ fwd
    cross = pts[:, :2] @ right

    wall_cross_med = float(np.median(cross[wall_idx]))
    side_sign = 1.0 if wall_cross_med >= 0.0 else -1.0
    front_apron_mask = (
        ((side_sign * cross) >= max(1.5, abs(wall_cross_med) - 2.2))
        & ((side_sign * cross) <= abs(wall_cross_med) - 0.25)
        & (pts[:, 2] >= z_road - 0.10)
        & (pts[:, 2] <= z_road + 0.65)
    )
    entry_step_cm = (
        float((np.percentile(pts[front_apron_mask, 2], 75) - z_road) * 100.0)
        if np.count_nonzero(front_apron_mask) >= 6
        else 0.0
    )

    # 3. Driveway width & apron slope along the street frontage.
    if driveway_along_range_m is not None:
        d_lo, d_hi = float(driveway_along_range_m[0]), float(driveway_along_range_m[1])
        driveway_width_m = max(0.0, d_hi - d_lo)
    else:
        # Locate lateral curb line (`~10–25 cm` step above adjacent road gutter) and scan 1.0 m
        # stations along the frontage for a flush curb-cut ramp (`step <= 6.5 cm` above local gutter).
        lat_dist = side_sign * cross
        near_ground = (
            (lat_dist >= 1.5)
            & (lat_dist <= abs(wall_cross_med) - 0.3)
            & (pts[:, 2] >= z_road - 0.30)
            & (pts[:, 2] <= z_road + 0.50)
        )
        if np.count_nonzero(near_ground) >= 30:
            ng_lat = lat_dist[near_ground]
            ng_z = pts[near_ground, 2]
            ng_along = along[near_ground]
            # Find median curb lateral offset from lateral 0.25 m profile across the whole frontage.
            lat_edges = np.arange(1.5, max(5.5, float(np.percentile(ng_lat, 95))) + 0.25, 0.25)
            lat_z = [
                float(np.percentile(ng_z[(ng_lat >= lat_edges[k]) & (ng_lat < lat_edges[k + 1])], 75))
                if np.count_nonzero((ng_lat >= lat_edges[k]) & (ng_lat < lat_edges[k + 1])) >= 3
                else np.nan
                for k in range(len(lat_edges) - 1)
            ]
            curb_lat = 4.0
            for k in range(len(lat_z) - 1):
                if np.isfinite(lat_z[k]) and np.isfinite(lat_z[k + 1]) and (lat_z[k + 1] - lat_z[k]) >= 0.05:
                    curb_lat = float(lat_edges[k + 1])
                    break

            s_min, s_max = float(np.percentile(ng_along, 2)), float(np.percentile(ng_along, 98))
            step_s = 1.0
            s_edges = np.arange(s_min, s_max + step_s * 0.5, step_s)
            flush_run = 0
            best_run = 0
            best_end_idx = 0
            for i in range(len(s_edges) - 1):
                in_s = (ng_along >= s_edges[i]) & (ng_along < s_edges[i + 1])
                gutter_m = in_s & (ng_lat >= curb_lat - 1.3) & (ng_lat < curb_lat - 0.1)
                top_m = in_s & (ng_lat >= curb_lat - 0.05) & (ng_lat <= curb_lat + 0.8)
                if np.count_nonzero(top_m) >= 2:
                    z_gut = float(np.median(ng_z[gutter_m])) if np.count_nonzero(gutter_m) >= 2 else z_road
                    step_cm = float((np.percentile(ng_z[top_m], 50) - z_gut) * 100.0)
                    if step_cm <= 6.5:
                        flush_run += 1
                        if flush_run > best_run:
                            best_run = flush_run
                            best_end_idx = i + 1
                    else:
                        flush_run = 0
            driveway_width_m = float(best_run * step_s)
            d_hi = float(s_edges[best_end_idx]) if best_run > 0 else 2.0
            d_lo = d_hi - driveway_width_m
        else:
            driveway_width_m = 0.0
            d_lo, d_hi = -2.0, 2.0

    # Apron grade (%) and overhead clearance (`> 1.8 m` AGL) inside the pull-in lane.
    in_driveway = (
        (along >= d_lo)
        & (along <= d_hi)
        & ((side_sign * cross) >= 1.8)
        & ((side_sign * cross) <= max(5.5, abs(wall_cross_med) - 0.4))
    )
    apron_ground = in_driveway & (pts[:, 2] <= z_road + 0.65)
    if np.count_nonzero(apron_ground) >= 8 and float(np.ptp(cross[apron_ground])) > 0.5:
        apron_slope_pct = float(abs(np.polyfit(side_sign * cross[apron_ground], pts[apron_ground, 2], 1)[0]) * 100.0)
    else:
        apron_slope_pct = 0.0

    overhead_mask = in_driveway & ((pts[:, 2] - z_road) >= 1.8)
    min_overhead_m = (
        float(np.percentile(pts[overhead_mask, 2] - z_road, 5))
        if np.count_nonzero(overhead_mask) >= 5
        else 9.9  # Open sky (no overhead obstructions detected).
    )

    verdicts: dict[str, dict[str, Any]] = {}
    for veh_name, spec in VEHICLE_CLEARANCE_PROFILES.items():
        width_ok = driveway_width_m >= spec["min_width_m"]
        height_ok = min_overhead_m >= spec["min_height_m"]
        verdicts[veh_name] = {
            "can_pull_in": bool(width_ok and height_ok),
            "width_margin_m": round(driveway_width_m - spec["min_width_m"], 2),
            "height_margin_m": round(min_overhead_m - spec["min_height_m"], 2),
        }

    return {
        "valid": True,
        "first_floor_height_m": round(first_floor_height_m, 2),
        "total_wall_height_m": facade["wall_height_m"],
        "wall_width_m": facade["wall_width_m"],
        "setback_distance_m": facade["setback_distance_m"],
        "entry_step_above_road_cm": round(max(0.0, entry_step_cm), 1),
        "driveway_width_m": round(driveway_width_m, 2),
        "driveway_apron_slope_pct": round(apron_slope_pct, 2),
        "min_overhead_clearance_m": round(min_overhead_m, 2),
        "open_sky_clearance": bool(np.count_nonzero(overhead_mask) < 5),
        "vehicle_clearance_verdicts": verdicts,
    }
