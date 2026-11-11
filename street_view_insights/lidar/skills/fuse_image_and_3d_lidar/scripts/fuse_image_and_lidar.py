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
"""Bidirectional Image + 3D LiDAR fusion for Full-Frame and Panoramic Street View Insights."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
from PIL import Image

LIDAR_LIB = Path(__file__).resolve().parents[3]
if str(LIDAR_LIB) not in sys.path:
    sys.path.insert(0, str(LIDAR_LIB))

from svi_lidar import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    build_depth_gated_crop,
    cast_2d_box_to_3d_cluster,
    classify_depth_gated_crop_with_gemini,
    estimate_local_ground_z,
    fetch_observation_and_laz_metadata,
    project_points_to_image,
    stream_and_merge_laz_enu,
)
from svi_lidar.synthetic_scene import make_synthetic_street_scene


def _download_rgb_from_gcs(image_gcs_uri: str) -> np.ndarray:
    from google.cloud import storage

    bucket_name, blob_path = image_gcs_uri[5:].split("/", 1)
    raw = storage.Client().bucket(bucket_name).blob(blob_path).download_as_bytes()
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"))
    parser.add_argument("--dataset", default="imagery_insights_lidar___us")
    parser.add_argument("--mode", choices=["auto", "full_frame", "pano"], default="auto")
    parser.add_argument("--observation-id", help="Full-Frame or Pano (:5001ee) observation_id.")
    parser.add_argument("--capture-id", help="SV_PANO capture_id.")
    parser.add_argument("--pano-id", help="SV_PANO pano_id.")
    parser.add_argument("--task", choices=["both", "3d-to-2d", "2d-to-3d"], default="both")
    parser.add_argument("--bbox-norm", help="Normalized 'ymin,xmin,ymax,xmax' (0..1000) for 2d-to-3d.")
    parser.add_argument("--call-gemini", action="store_true", help="Call Gemini on depth-gated crop.")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--synthetic", action="store_true", help="Run offline synthetic scene.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

    has_live_id = any([args.observation_id, args.capture_id, args.pano_id])
    if args.synthetic or not has_live_id:
        scene = make_synthetic_street_scene()
        pts_enu = scene["pts_enu"]
        intensity = scene["intensity"]
        pose = scene["camera_pose"]
        img_rgb = scene["img_rgb"]
        img_h, img_w = img_rgb.shape[:2]
        z_ground = float(scene["z_road_m"])
        resolved_mode = "synthetic"

        t_lo, _ = scene["label_ranges"]["tree_trunk"]
        _, t_hi = scene["label_ranges"]["tree_canopy"]
        cluster_idx = np.arange(t_lo, t_hi, dtype=np.int64)
        asset_class = "street_tree"

        s_lo, s_hi = scene["label_ranges"]["sign_face"]
        proj = project_points_to_image(
            pts_enu[s_lo:s_hi],
            heading_deg=float(pose["heading"]),
            pitch_deg=float(pose["pitch"]),
            roll_deg=float(pose["roll"]),
            image_wh=(img_w, img_h),
        )
        default_box_norm = [
            max(0.0, float(proj["v"].min() / img_h * 1000.0 - 15.0)),
            max(0.0, float(proj["u"].min() / img_w * 1000.0 - 15.0)),
            min(1000.0, float(proj["v"].max() / img_h * 1000.0 + 15.0)),
            min(1000.0, float(proj["u"].max() / img_w * 1000.0 + 15.0)),
        ]
    else:
        meta = fetch_observation_and_laz_metadata(
            observation_id=args.observation_id,
            project_id=args.project,
            dataset=args.dataset,
            mode=args.mode,
            capture_id=args.capture_id,
            pano_id=args.pano_id,
        )
        resolved_mode = meta["mode"]
        pose = meta["camera_pose"]
        merged = stream_and_merge_laz_enu(
            meta["laz_uris"],
            origin_lat_deg=float(pose["latitude"]),
            origin_lon_deg=float(pose["longitude"]),
            origin_alt_m=float(pose["altitude"]),
        )
        pts_enu = merged["enu"]
        intensity = merged["intensity"]
        img_rgb = _download_rgb_from_gcs(meta["image_gcs_uri"])
        img_h, img_w = img_rgb.shape[:2]
        z_ground, _ = estimate_local_ground_z(pts_enu, outer_r_m=8.0)

        cat = meta["catalog_assets"][0] if meta["catalog_assets"] else None
        asset_class = str(cat["asset_type"]).lower() if cat else "roadside_object"
        if cat and cat.get("bbox"):
            b = cat["bbox"]
            default_box_norm = [
                float(b.get("ymin", 0)) / IMAGE_HEIGHT * 1000.0,
                float(b.get("xmin", 0)) / IMAGE_WIDTH * 1000.0,
                float(b.get("ymax", IMAGE_HEIGHT)) / IMAGE_HEIGHT * 1000.0,
                float(b.get("xmax", IMAGE_WIDTH)) / IMAGE_WIDTH * 1000.0,
            ]
        else:
            default_box_norm = [250.0, 300.0, 750.0, 700.0]

        seed_box = (
            [float(x.strip()) for x in args.bbox_norm.split(",")]
            if args.bbox_norm
            else default_box_norm
        )
        seed_cast = cast_2d_box_to_3d_cluster(
            bbox_norm_1000=seed_box,
            pts_enu=pts_enu,
            intensity=intensity,
            camera_pose=pose,
            z_ground_m=z_ground,
            image_wh=(img_w, img_h),
        )
        cluster_idx = seed_cast.get("cluster_indices", np.empty(0, dtype=np.int64))

    bbox_norm = (
        [float(x.strip()) for x in args.bbox_norm.split(",")]
        if args.bbox_norm
        else default_box_norm
    )

    output: dict[str, Any] = {"mode": resolved_mode, "task": args.task}
    if args.task in ("both", "3d-to-2d"):
        gated = build_depth_gated_crop(
            img_rgb=img_rgb,
            pts_enu=pts_enu,
            cluster_indices=cluster_idx,
            camera_pose=pose,
            full_res_wh=(img_w, img_h),
        )
        output["3d_to_2d_depth_gated_crop"] = {
            "valid": gated["valid"],
            "bbox_px": gated.get("bbox_px"),
            "target_depth_band_m": gated.get("target_depth_band_m"),
            "background_eliminated_fraction": gated.get("background_eliminated_fraction"),
        }
        if args.call_gemini and gated.get("valid"):
            output["gemini_classification"] = classify_depth_gated_crop_with_gemini(
                crop_rgb=gated["crop_rgb"],
                asset_class=asset_class,
                model=args.model,
                project_id=args.project,
            )

    if args.task in ("both", "2d-to-3d"):
        cast_res = cast_2d_box_to_3d_cluster(
            bbox_norm_1000=bbox_norm,
            pts_enu=pts_enu,
            intensity=intensity,
            camera_pose=pose,
            z_ground_m=z_ground,
            image_wh=(img_w, img_h),
        )
        cast_res.pop("cluster_indices", None)
        output["2d_to_3d_box_cast"] = cast_res

    payload = json.dumps(output, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
