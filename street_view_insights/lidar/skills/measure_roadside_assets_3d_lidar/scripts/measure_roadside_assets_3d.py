#!/usr/bin/env python3
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
"""Pure-3D physical measurements of poles, signs, trees, and walls (Full-Frame & Pano LiDAR)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np

LIDAR_LIB = Path(__file__).resolve().parents[3]
if str(LIDAR_LIB) not in sys.path:
    sys.path.insert(0, str(LIDAR_LIB))

from svi_lidar import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    discover_roadside_assets_3d,
    estimate_local_ground_z,
    fetch_observation_and_laz_metadata,
    measure_facade_3d,
    measure_point_to_point_3d,
    measure_pole_3d,
    measure_sign_3d,
    measure_tree_3d,
    project_points_to_image,
    stream_and_merge_laz_enu,
)
from svi_lidar.synthetic_scene import make_synthetic_street_scene


def _run_dispatch(
    pts_enu: np.ndarray,
    intensity: np.ndarray,
    z_ground: float,
    asset_class: str,
) -> dict[str, Any]:
    cls = asset_class.lower()
    if "sign" in cls:
        res = measure_sign_3d(pts_enu, intensity, z_ground_m=z_ground)
    elif "tree" in cls:
        res = measure_tree_3d(pts_enu, z_ground_m=z_ground)
    elif "facade" in cls or "building" in cls:
        res = measure_facade_3d(pts_enu, z_ground_m=z_ground)
    else:
        res = measure_pole_3d(pts_enu, z_ground_m=z_ground)
    res.pop("inlier_indices", None)
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"))
    parser.add_argument("--dataset", default="imagery_insights_lidar___us")
    parser.add_argument("--mode", choices=["auto", "full_frame", "pano"], default="auto")
    parser.add_argument("--observation-id", help="Full-Frame or Pano (:5001ee) observation_id.")
    parser.add_argument("--capture-id", help="SV_PANO capture_id for 360-deg 3D asset discovery.")
    parser.add_argument("--pano-id", help="SV_PANO pano_id for 360-deg 3D asset discovery.")
    parser.add_argument(
        "--asset-class",
        choices=["auto", "pole", "sign", "tree", "facade"],
        default="auto",
        help="Override 3D geometry measurement rule.",
    )
    parser.add_argument("--synthetic", action="store_true", help="Run offline synthetic 3D scene.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

    has_live_id = any([args.observation_id, args.capture_id, args.pano_id])
    if args.synthetic or not has_live_id:
        scene = make_synthetic_street_scene()
        pts_enu = scene["pts_enu"]
        intensity = scene["intensity"]
        ranges = scene["label_ranges"]
        z_ground, _ = estimate_local_ground_z(pts_enu, center_xy=(0.0, 12.0), outer_r_m=6.0)

        p_lo, _ = ranges["pole"]
        _, w_hi = ranges["wire"]
        pole = _run_dispatch(pts_enu[p_lo:w_hi], intensity[p_lo:w_hi], z_ground, "pole")

        sp_lo, _ = ranges["sign_post"]
        _, sf_hi = ranges["sign_face"]
        sign = _run_dispatch(pts_enu[sp_lo:sf_hi], intensity[sp_lo:sf_hi], z_ground, "sign")

        tt_lo, _ = ranges["tree_trunk"]
        _, tc_hi = ranges["tree_canopy"]
        tree = _run_dispatch(pts_enu[tt_lo:tc_hi], intensity[tt_lo:tc_hi], z_ground, "tree")

        bf_lo, bf_hi = ranges["building_facade"]
        facade = _run_dispatch(pts_enu[bf_lo:bf_hi], intensity[bf_lo:bf_hi], z_ground, "facade")

        pole_base = np.median(pts_enu[ranges["pole"][0] : ranges["pole"][1]], axis=0)
        sign_center = np.median(pts_enu[ranges["sign_face"][0] : ranges["sign_face"][1]], axis=0)
        report: dict[str, Any] = {
            "mode": "synthetic",
            "local_road_datum_z_m": round(z_ground, 3),
            "utility_pole_3d": pole,
            "road_sign_3d": sign,
            "street_tree_3d": tree,
            "building_facade_3d": facade,
            "pole_to_sign_distance_3d": measure_point_to_point_3d(pole_base, sign_center),
            "pano_style_uncataloged_discovery_count": len(
                discover_roadside_assets_3d(pts_enu, intensity, z_ground_m=z_ground)
            ),
        }
    else:
        meta = fetch_observation_and_laz_metadata(
            observation_id=args.observation_id,
            project_id=args.project,
            dataset=args.dataset,
            mode=args.mode,
            capture_id=args.capture_id,
            pano_id=args.pano_id,
        )
        pose = meta["camera_pose"]
        merged = stream_and_merge_laz_enu(
            meta["laz_uris"],
            origin_lat_deg=float(pose["latitude"]),
            origin_lon_deg=float(pose["longitude"]),
            origin_alt_m=float(pose["altitude"]),
        )
        pts_enu = merged["enu"]
        intensity = merged["intensity"]
        z_ground, _ = estimate_local_ground_z(pts_enu, outer_r_m=8.0)

        if meta["catalog_assets"]:
            proj = project_points_to_image(
                pts_enu,
                heading_deg=float(pose["heading"]),
                pitch_deg=float(pose["pitch"]),
                roll_deg=float(pose["roll"]),
                image_wh=(IMAGE_WIDTH, IMAGE_HEIGHT),
            )
            measured_assets: list[dict[str, Any]] = []
            for item in meta["catalog_assets"]:
                box = item["bbox"]
                cone = (
                    proj["in_bounds"]
                    & (proj["u"] >= float(box.get("xmin", 0)))
                    & (proj["u"] <= float(box.get("xmax", IMAGE_WIDTH)))
                    & (proj["v"] >= float(box.get("ymin", 0)))
                    & (proj["v"] <= float(box.get("ymax", IMAGE_HEIGHT)))
                    & (proj["range_m"] <= 75.0)
                )
                sub_pts = pts_enu[cone]
                sub_int = intensity[cone]
                target_cls = item["asset_type"] if args.asset_class == "auto" else args.asset_class
                local_zg, _ = (
                    estimate_local_ground_z(pts_enu, center_xy=tuple(np.median(sub_pts[:, :2], axis=0)))
                    if len(sub_pts) >= 10
                    else (z_ground, np.empty(0, dtype=bool))
                )
                measured_assets.append(
                    {
                        "asset_id": item["asset_id"],
                        "asset_type": item["asset_type"],
                        "measurements_3d": _run_dispatch(sub_pts, sub_int, local_zg, target_cls),
                    }
                )
        else:
            # Pano mode (uncataloged 360-degree cloud): discover assets directly in 3D!
            measured_assets = discover_roadside_assets_3d(pts_enu, intensity, z_ground_m=z_ground)

        report = {
            "mode": meta["mode"],
            "observation_id": meta["observation_id"],
            "rig_type": meta["rig_type"],
            "total_merged_points": int(len(pts_enu)),
            "assets": measured_assets,
        }

    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
