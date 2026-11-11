---
name: project-and-colorize-3d-lidar
description: Stream Street View Insights 3D LiDAR (.laz) scans in memory from either Full-Frame (full_frame_lidar_metadata_latest) or Panoramic 6-lens rosette (pano_lidar_metadata_latest) captures, project 3D points onto 3648x5472 photos using the calibrated 2-term radial fisheye model (fx=fy=2964.42) with 14x14 px front-surface filtering, and drape Z-buffered True Color Photo RGB into a .ply point cloud. Use when overlaying 3D LiDAR onto Full-Frame or Panoramic Street View photos, generating 360-degree RGB 3D point clouds, or exporting colored .ply files. Don't use for measuring pole/sign/tree dimensions (use measure-roadside-assets-3d-lidar) or slicing sidewalk cross-sections (use slice-road-curb-and-sidewalk-3d-lidar).
---

# Project and Colorize 3D LiDAR (`project-and-colorize-3d-lidar`)

Use this skill to align raw `.laz` 3D laser scans with calibrated `3648 × 5472` Street View photos across **both** Full-Frame (`full_frame_observations_latest` + `full_frame_lidar_metadata_latest`) and Panoramic (`pano_observations_latest` + `pano_lidar_metadata_latest`) Street View Insights deliveries.

## Full-Frame vs. Panoramic LiDAR Handling

1. **Shared Sensor & `.laz` Physics (`LAS 1.4` Point Format `1`):**
   - Both Full-Frame and Panoramic deliveries store `1 mm` geocentric **WGS84 ECEF (`EPSG:4978`)** `(X, Y, Z)`, `16-bit intensity`, and `gps_time` without native RGB, and both capture unstitched `3648 × 5472` portrait frames matching the 2-term radial fisheye model (`fx = fy = 2964.42`, `cx = 1836.95`, `cy = 2733.06`, `k1 = -0.023685`, `k2 = 0.000110`, `0.0°` pitch offset, `2.6 m` ego-car filter).
2. **Panoramic 6-Lens Rosette Resolution (`SV_PANO`):**
   - Each `capture_id` in `pano_observations_latest` comprises 7 frames (`o1:<stem>_<0..6>:5001ee`), where `k = 0..5` are horizontal (~60° apart) and `k = 6` points straight up at the sky (`pitch ≈ +87°`).
   - Because `pano_lidar_metadata_latest` caps each sensor sweep at `1,000,000` returns over a `15 s` window, rear/side lenses (`_2`, `_3`) often hold the full `0.6–0.9M`-point sweep while forward lenses hold `< 500`-point stubs. Even when passed a single `:5001ee` `observation_id`, this skill resolves the full 6-lens horizontal rosette (`k = 0..5`, skipping `k = 6`), merges all `>= 500`-point `.laz` sweeps, and drapes **360-degree True Color Photo RGB** across all 6 horizontal cameras via `d / cos(theta)` Z-buffering.
3. **Full-Frame Multi-Sensor Merging (`SV_FULL_FRAME_ASSETS`):**
   - Branches on `COUNT(DISTINCT device_number)` (`2` sensors `0, 1` vs. `4` sensors `0..3`), merges all mounted scanners with `2 cm` ENU voxel deduplication, and supports multi-observation RGB fusion via `--asset-id`.

## Prerequisites

```bash
pip install -r street_view_insights/lidar/requirements.txt
pip install -e street_view_insights/lidar
```

## Instructions

Run from the repository root (`--mode auto` detects `:5001ee` / `--capture-id` / `--pano-id` as `pano`, and cataloged IDs / `--asset-id` as `full_frame`):

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"

# 1. Full-Frame observation -> 2D front-surface overlay + True Color RGB .ply
python3 street_view_insights/lidar/skills/project_and_colorize_3d_lidar/scripts/project_and_colorize_lidar.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --observation-id "<full_frame_observation_id>" \
  --output-ply /tmp/full_frame_rgb.ply

# 2. Panoramic rosette (by capture_id, pano_id, or o1:<stem>_<k>:5001ee) -> 360-deg 6-camera RGB .ply
python3 street_view_insights/lidar/skills/project_and_colorize_3d_lidar/scripts/project_and_colorize_lidar.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --capture-id "<capture_id>" \
  --mode pano \
  --output-ply /tmp/pano_rosette_360_rgb.ply

# 3. Offline synthetic verification
python3 street_view_insights/lidar/skills/project_and_colorize_3d_lidar/scripts/project_and_colorize_lidar.py \
  --synthetic
```
