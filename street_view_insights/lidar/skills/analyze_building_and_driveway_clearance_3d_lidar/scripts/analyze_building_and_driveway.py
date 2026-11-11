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
"""Analyze building frontage height, entry step, driveway width, and vehicle pull-in clearance."""

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
    analyze_building_and_driveway_scene,
    fetch_observation_and_laz_metadata,
    stream_and_merge_laz_enu,
)
from svi_lidar.synthetic_scene import make_synthetic_street_scene


def _parse_pair(raw: str | None) -> tuple[float, float] | None:
    if not raw:
        return None
    a, b = [float(x.strip()) for x in raw.split(",", 1)]
    return (a, b)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"))
    parser.add_argument("--dataset", default="imagery_insights_lidar___us")
    parser.add_argument("--mode", choices=["auto", "full_frame", "pano"], default="auto")
    parser.add_argument("--observation-id", help="Full-Frame or Pano (:5001ee) observation_id.")
    parser.add_argument("--capture-id", help="SV_PANO capture_id.")
    parser.add_argument("--pano-id", help="SV_PANO pano_id.")
    parser.add_argument("--heading-deg", type=float, help="Optional street travel heading override (deg).")
    parser.add_argument("--first-floor-band-m", help="Optional 'min_m,max_m' first-floor AGL band.")
    parser.add_argument("--driveway-along-m", help="Optional 'start_m,end_m' driveway station span.")
    parser.add_argument("--synthetic", action="store_true", help="Run offline synthetic frontage scene.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()

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

    scene_report = analyze_building_and_driveway_scene(
        pts_enu=pts_enu,
        intensity=intensity,
        heading_deg=heading,
        first_floor_band_agl_m=_parse_pair(args.first_floor_band_m),
        driveway_along_range_m=_parse_pair(args.driveway_along_m),
    )
    scene_report["mode"] = resolved_mode
    payload = json.dumps(scene_report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
