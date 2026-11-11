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
"""Slice perpendicular roadway, curb reveal, and sidewalk cross-sections (Full-Frame & Pano LiDAR)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

LIDAR_LIB = Path(__file__).resolve().parents[3]
if str(LIDAR_LIB) not in sys.path:
    sys.path.insert(0, str(LIDAR_LIB))

from svi_lidar import (
    fetch_observation_and_laz_metadata,
    measure_corridor_cross_section,
    stream_and_merge_laz_enu,
)
from svi_lidar.synthetic_scene import make_synthetic_street_scene


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"))
    parser.add_argument("--dataset", default="imagery_insights_lidar___us")
    parser.add_argument("--mode", choices=["auto", "full_frame", "pano"], default="auto")
    parser.add_argument("--observation-id", help="Full-Frame or Pano (:5001ee) observation_id.")
    parser.add_argument("--capture-id", help="SV_PANO capture_id.")
    parser.add_argument("--pano-id", help="SV_PANO pano_id.")
    parser.add_argument("--heading-deg", type=float, help="Optional street travel heading override (deg).")
    parser.add_argument(
        "--stations",
        default="8,16,24",
        help="Comma-separated station offsets in meters along heading (default: 8,16,24).",
    )
    parser.add_argument("--slab-length-m", type=float, default=4.0, help="Longitudinal slice thickness (m).")
    parser.add_argument("--synthetic", action="store_true", help="Run offline synthetic street corridor.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

    station_list = [float(s.strip()) for s in args.stations.split(",") if s.strip()]
    has_live_id = any([args.observation_id, args.capture_id, args.pano_id])

    if args.synthetic or not has_live_id:
        scene = make_synthetic_street_scene()
        pts_enu = scene["pts_enu"]
        intensity = scene["intensity"]
        heading = float(args.heading_deg if args.heading_deg is not None else scene["camera_pose"]["heading"])
        resolved_mode = "synthetic"
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
        heading = float(args.heading_deg if args.heading_deg is not None else pose["heading"])
        resolved_mode = meta["mode"]

    slices = [
        measure_corridor_cross_section(
            pts_enu=pts_enu,
            intensity=intensity,
            heading_deg=heading,
            station_along_m=st,
            slab_length_m=args.slab_length_m,
        )
        for st in station_list
    ]
    payload = json.dumps(
        {"mode": resolved_mode, "heading_deg": round(heading, 2), "cross_sections": slices},
        indent=2,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
