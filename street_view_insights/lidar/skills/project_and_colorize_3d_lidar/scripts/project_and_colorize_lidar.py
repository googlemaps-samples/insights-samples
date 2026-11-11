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
"""Project 3D .laz scans (Full-Frame or Pano rosette) and drape Z-buffered True Color Photo RGB."""

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
    colorize_multiview_point_cloud,
    export_colored_ply,
    fetch_observation_and_laz_metadata,
    filter_front_surface_overlay,
    stream_and_merge_laz_enu,
)
from svi_lidar.synthetic_scene import make_synthetic_street_scene


def _download_rgb_from_gcs(image_gcs_uri: str) -> np.ndarray:
    from google.cloud import storage

    bucket_name, blob_path = image_gcs_uri[5:].split("/", 1)
    raw = storage.Client().bucket(bucket_name).blob(blob_path).download_as_bytes()
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.uint8)


def _fetch_asset_observation_ids(
    asset_id: str, project_id: str, dataset: str, max_views: int
) -> list[str]:
    from google.cloud import bigquery

    sql = f"""
    SELECT DISTINCT o.observation_id, o.capture_time
    FROM `{project_id}.{dataset}.full_frame_observations_latest` AS o
    JOIN `{project_id}.{dataset}.full_frame_lidar_metadata_latest` AS l
      ON o.observation_id = l.observation_id
    WHERE o.asset_id = @asset_id
    ORDER BY o.capture_time DESC
    LIMIT @max_views
    """
    client = bigquery.Client(project=project_id)
    params = [
        bigquery.ScalarQueryParameter("asset_id", "STRING", asset_id),
        bigquery.ScalarQueryParameter("max_views", "INT64", int(max_views)),
    ]
    dry = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params, dry_run=True))
    if int(dry.total_bytes_processed or 0) > 10_000_000_000:
        raise RuntimeError("Asset lookup exceeded 10 GB dry-run cap.")
    cfg = bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=10_000_000_000)
    return [str(r["observation_id"]) for r in client.query(sql, job_config=cfg).result()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"))
    parser.add_argument("--dataset", default="imagery_insights_lidar___us")
    parser.add_argument("--mode", choices=["auto", "full_frame", "pano"], default="auto")
    parser.add_argument("--observation-id", help="Full-Frame or Pano (:5001ee) observation_id.")
    parser.add_argument("--capture-id", help="SV_PANO capture_id for 6-lens rosette RGB draping.")
    parser.add_argument("--pano-id", help="SV_PANO pano_id for 6-lens rosette RGB draping.")
    parser.add_argument("--asset-id", help="Full-Frame cataloged asset_id for multi-view RGB draping.")
    parser.add_argument("--max-views", type=int, default=6, help="Max camera views to fuse.")
    parser.add_argument("--cell-px", type=int, default=14, help="2D front-surface grid cell size in px.")
    parser.add_argument("--synthetic", action="store_true", help="Run offline on synthetic 3D street scene.")
    parser.add_argument("--output-ply", type=Path, help="Optional binary RGB .ply output path.")
    parser.add_argument("--output", type=Path, help="Optional JSON report output path.")
    args = parser.parse_args()

    has_live_id = any([args.observation_id, args.capture_id, args.pano_id, args.asset_id])
    if args.synthetic or not has_live_id:
        scene = make_synthetic_street_scene()
        pts_enu = scene["pts_enu"]
        intensity = scene["intensity"]
        anchor_pose = scene["camera_pose"]
        views = [{"img_rgb": scene["img_rgb"], "camera_pose": anchor_pose}]
        full_wh = scene["full_res_wh"]
        resolved_mode = "synthetic"
        rig_type = "synthetic"
    elif args.asset_id:
        obs_ids = _fetch_asset_observation_ids(args.asset_id, args.project, args.dataset, args.max_views)
        if not obs_ids:
            raise LookupError("No LiDAR-backed observations found for asset_id.")
        metas = [
            fetch_observation_and_laz_metadata(
                oid, project_id=args.project, dataset=args.dataset, mode="full_frame"
            )
            for oid in obs_ids
        ]
        ref_date = str(metas[0]["capture_time"])[:10]
        same_day = [m for m in metas if str(m["capture_time"])[:10] == ref_date]
        anchor_pose = same_day[0]["camera_pose"]
        all_laz = list(dict.fromkeys(u for m in same_day for u in m["laz_uris"]))
        merged = stream_and_merge_laz_enu(
            all_laz,
            origin_lat_deg=float(anchor_pose["latitude"]),
            origin_lon_deg=float(anchor_pose["longitude"]),
            origin_alt_m=float(anchor_pose["altitude"]),
        )
        pts_enu, intensity = merged["enu"], merged["intensity"]
        views = [
            {"img_rgb": _download_rgb_from_gcs(m["image_gcs_uri"]), "camera_pose": m["camera_pose"]}
            for m in same_day
        ]
        full_wh = (IMAGE_WIDTH, IMAGE_HEIGHT)
        resolved_mode = "full_frame"
        rig_type = same_day[0]["rig_type"]
    else:
        meta = fetch_observation_and_laz_metadata(
            observation_id=args.observation_id,
            project_id=args.project,
            dataset=args.dataset,
            mode=args.mode,
            capture_id=args.capture_id,
            pano_id=args.pano_id,
        )
        anchor_pose = meta["camera_pose"]
        merged = stream_and_merge_laz_enu(
            meta["laz_uris"],
            origin_lat_deg=float(anchor_pose["latitude"]),
            origin_lon_deg=float(anchor_pose["longitude"]),
            origin_alt_m=float(anchor_pose["altitude"]),
        )
        pts_enu, intensity = merged["enu"], merged["intensity"]
        cam_specs = meta["rosette_cameras"][: max(1, int(args.max_views))]
        views = [
            {"img_rgb": _download_rgb_from_gcs(c["image_gcs_uri"]), "camera_pose": c["camera_pose"]}
            for c in cam_specs
            if c.get("image_gcs_uri")
        ]
        full_wh = (IMAGE_WIDTH, IMAGE_HEIGHT)
        resolved_mode = meta["mode"]
        rig_type = meta["rig_type"]

    overlay = filter_front_surface_overlay(
        pts_enu=pts_enu,
        heading_deg=float(anchor_pose["heading"]),
        pitch_deg=float(anchor_pose["pitch"]),
        roll_deg=float(anchor_pose["roll"]),
        cell_px=args.cell_px,
        max_per_cell=2,
    )
    colored = colorize_multiview_point_cloud(
        points=pts_enu,
        camera_views=views,
        is_enu=True,
        anchor_pose=anchor_pose,
        full_res_wh=full_wh,
        uncolored_fallback_intensity=intensity,
    )

    report: dict[str, Any] = {
        "mode": resolved_mode,
        "rig_type": rig_type,
        "camera_views_fused": len(views),
        "total_3d_points": int(len(pts_enu)),
        "front_surface_2d_overlay_points": int(len(overlay["keep_indices"])),
        "true_color_rgb_points": int(np.count_nonzero(colored["colored_mask"])),
        "true_color_coverage_pct": round(100.0 * float(np.mean(colored["colored_mask"])), 1),
    }
    if args.output_ply:
        out_ply = export_colored_ply(args.output_ply, pts_enu, colored["colors_rgb"])
        report["exported_ply"] = str(out_ply)

    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
