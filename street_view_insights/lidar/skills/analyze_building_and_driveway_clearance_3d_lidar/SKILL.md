---
name: analyze-building-and-driveway-clearance-3d-lidar
description: Analyze commercial and building frontage scenes from Full-Frame or Panoramic Street View Insights 3D LiDAR (.laz) scans to measure first-floor height, entry step above road (cm), driveway curb-cut width and apron grade (%), minimum overhead clearance, and vehicle pull-in fit (service van, box truck, heavy truck). Use when evaluating commercial property frontage, threshold freeboard, or truck/delivery pull-in clearance in full_frame_lidar_metadata_latest or pano_lidar_metadata_latest. Don't use for general road/sidewalk cross-sections without building frontage (use slice-road-curb-and-sidewalk-3d-lidar) or utility pole/sign sizing (use measure-roadside-assets-3d-lidar).
---

# Analyze Building Frontage and Driveway Clearance (`analyze-building-and-driveway-clearance-3d-lidar`)

Use this skill to evaluate commercial and building frontage scenes—measuring first-floor height, threshold height above street level (`cm`), driveway curb-cut width & apron grade (`%`), and 3D vehicle pull-in headroom from `.laz` scans in **both** Full-Frame (`full_frame_lidar_metadata_latest`) and Panoramic (`pano_lidar_metadata_latest`) Street View Insights deliveries.

## Why Panoramic & Full-Frame LiDAR Both Excel Here

1. **Panoramic Rosettes (`--mode pano` via `--capture-id` / `:5001ee`) Cover Arbitrary Commercial Properties:**
   - Because `pano_observations_latest` + `pano_lidar_metadata_latest` capture continuous 360° street blocks (not only cataloged poles/signs), you can evaluate any commercial storefront, warehouse bay, or retail driveway along a drive pass.
2. **Wide-Footprint Facade RANSAC (`span >= 2.5 m`) + Storefront Glass Rejection:**
   - Rejects closer roadside poles/trees and interior back-walls behind storefront windows (`> 0.6 m` behind the exterior wall plane).
3. **Gutter-Referenced Curb-Cut Detection & Vehicle Pull-In Profiles:**
   - Detects flush driveway openings where curb step drops `<= 6.5 cm` above the local gutter and checks 3D width × overhead height against `service_van` (`2.4 × 2.6 m`), `box_truck` (`3.0 × 3.6 m`), and `heavy_truck` (`3.5 × 4.3 m`).

## Prerequisites

```bash
pip install -r street_view_insights/lidar/requirements.txt
pip install -e street_view_insights/lidar
```

## Instructions

Run from the repository root:

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"

# 1. Panoramic capture stop in front of a commercial property
python3 street_view_insights/lidar/skills/analyze_building_and_driveway_clearance_3d_lidar/scripts/analyze_building_and_driveway.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --capture-id "<capture_id>" \
  --mode pano

# 2. Full-Frame observation with an optional Gemini 2D->3D first-floor band (min_m,max_m)
python3 street_view_insights/lidar/skills/analyze_building_and_driveway_clearance_3d_lidar/scripts/analyze_building_and_driveway.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --observation-id "<full_frame_observation_id>" \
  --first-floor-band-m "0.0,3.85"

# 3. Offline synthetic commercial building + driveway verification
python3 street_view_insights/lidar/skills/analyze_building_and_driveway_clearance_3d_lidar/scripts/analyze_building_and_driveway.py \
  --synthetic
```
