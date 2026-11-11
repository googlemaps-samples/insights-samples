---
name: measure-roadside-assets-3d-lidar
description: Measure physical 3D dimensions of utility poles (height AGL and 3D lean angle), road signs (face width x height, mounting clearance, and retroreflectivity), street trees (height, crown spread, and canopy clearance), building walls (height, width, flatness), and 3D point-to-point spans directly from Full-Frame or Panoramic Street View Insights .laz scans with zero LLM calls. Use when computing centimeter-accurate 3D asset geometry from full_frame_lidar_metadata_latest or pano_lidar_metadata_latest. Don't use for 2D-only pole attachment sub-classification without LiDAR (use utility-pole-subclassification-using-full-frame-svi or utility-pole-subclassification-using-panoramic-svi) or sidewalk cross-sections (use slice-road-curb-and-sidewalk-3d-lidar).
---

# Measure Roadside Assets in 3D LiDAR (`measure-roadside-assets-3d-lidar`)

Use this skill to compute pure-3D (`LiDAR Only`, zero LLM calls) physical measurements on roadside infrastructure from `.laz` point clouds in **both** Full-Frame (`full_frame_lidar_metadata_latest`) and Panoramic (`pano_lidar_metadata_latest`) Street View Insights datasets.

## How Full-Frame vs. Panoramic Asset Measurement Works

1. **Full-Frame Mode (`--mode full_frame`):**
   - Uses pre-cataloged `bbox` rows on `full_frame_observations_latest` to crop `.laz` viewing cones around each cataloged pole or road sign and dispatches `measure_pole_3d` or `measure_sign_3d`.
2. **Panoramic Mode (`--mode pano` via `:5001ee`, `--capture-id`, or `--pano-id`):**
   - Because `pano_observations_latest` provides uncataloged 360° streetscape coverage (no `bbox` column), this skill merges all `>= 500`-point `.laz` sweeps across the 6 horizontal rosette lenses (`k = 0..5`) and runs `discover_roadside_assets_3d` directly on the 3D point cloud—automatically isolating retroreflective road signs (`intensity >= 115`), slender vertical poles, broad tree crowns, and building facades in 3D (or cropping to an optional `--bbox-norm` on a chosen lens).
3. **Shared 3D Physics Guards:**
   - Anchors heights to `5th–12th` percentile local street `Z_ground` (stripping `-15..-26 m` wet-asphalt glare), fits tilted SVD pole lines stopping at `>= 1.2 m` wire air gaps, trims `< 16 cm` sign posts beneath planar sign faces, and rejects storefront glass interior back-walls (`> 0.6 m` behind the facade).

## Prerequisites

```bash
pip install -r street_view_insights/lidar/requirements.txt
pip install -e street_view_insights/lidar
```

## Instructions

Run from the repository root:

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"

# 1. Full-Frame observation: measure cataloged 2D-boxed poles/signs in 3D
python3 street_view_insights/lidar/skills/measure_roadside_assets_3d_lidar/scripts/measure_roadside_assets_3d.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --observation-id "<full_frame_observation_id>"

# 2. Panoramic rosette: pure-3D uncataloged discovery across poles, signs, trees & facades
python3 street_view_insights/lidar/skills/measure_roadside_assets_3d_lidar/scripts/measure_roadside_assets_3d.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --capture-id "<capture_id>" \
  --mode pano

# 3. Offline synthetic benchmark
python3 street_view_insights/lidar/skills/measure_roadside_assets_3d_lidar/scripts/measure_roadside_assets_3d.py \
  --synthetic
```
