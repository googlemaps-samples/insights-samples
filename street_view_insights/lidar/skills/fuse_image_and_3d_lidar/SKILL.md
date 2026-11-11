---
name: fuse-image-and-3d-lidar
description: Fuse Full-Frame or Panoramic Street View photos with 3D LiDAR (.laz) scans bidirectionally using Gemini—either projecting 3D object clusters into background-dimmed depth-gated 2D crops (3D -> 2D) for semantic material/condition classification, or casting normalized [ymin, xmin, ymax, xmax] 2D detections into 3D .laz viewing cones (2D -> 3D) with occlusion scoring. Use when combining Gemini photo inspection with 3D .laz point clouds in full_frame_lidar_metadata_latest or pano_lidar_metadata_latest. Don't use for pure-3D geometry without photos (use measure-roadside-assets-3d-lidar) or building/driveway pull-in clearance checks (use analyze-building-and-driveway-clearance-3d-lidar).
---

# Fuse Image and 3D LiDAR (`fuse-image-and-3d-lidar`)

Use this skill to combine semantic visual understanding from Gemini on `3648 × 5472` Street View photos with `1 mm` 3D geometry from `.laz` point clouds across **both** Full-Frame (`full_frame_observations_latest`) and Panoramic (`pano_observations_latest`, `k = 0..5`) Street View Insights deliveries.

## Bidirectional Fusion Across Full-Frame & Panoramic LiDAR

1. **`3d-to-2d` — 3D Depth-Masked Crops Before Gemini Classification:**
   - Projects a 3D `.laz` object cluster onto its clearest camera frame (or best-centered horizontal rosette camera `k = 0..5` in `pano` mode!) and dims pixels outside `[d_p10 - 1.2 m, d_p90 + 1.2 m]`, eliminating ~80% of background visual clutter before calling Gemini at compact crop token cost.
2. **`2d-to-3d` — Casting Gemini 2D Boxes (`0..1000`) into `.laz` 3D Space with Occlusion Gating:**
   - Casts normalized `[ymin, xmin, ymax, xmax]` (`0..1000`) 2D boxes from any Full-Frame or Panoramic lens frame into the merged `.laz` 3D point cloud, isolating foreground depth above `Z_ground` and computing `occluded_fraction` (discard views blocked `>= 50%` by closer cars or trees).

## Prerequisites

```bash
pip install -r street_view_insights/lidar/requirements.txt
pip install -e street_view_insights/lidar
```

## Instructions

Run from the repository root:

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"

# 1. Full-Frame observation: 3D depth-masked crop -> Gemini classification
python3 street_view_insights/lidar/skills/fuse_image_and_3d_lidar/scripts/fuse_image_and_lidar.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --observation-id "<full_frame_observation_id>" \
  --task 3d-to-2d \
  --call-gemini

# 2. Panoramic lens frame (o1:<stem>_<k>:5001ee): cast a 2D detection box onto merged rosette .laz
python3 street_view_insights/lidar/skills/fuse_image_and_3d_lidar/scripts/fuse_image_and_lidar.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --observation-id "o1:<pano_stem>_1:5001ee" \
  --mode pano \
  --task 2d-to-3d \
  --bbox-norm "310,420,760,590"

# 3. Offline synthetic verification of both 3D->2D and 2D->3D directions
python3 street_view_insights/lidar/skills/fuse_image_and_3d_lidar/scripts/fuse_image_and_lidar.py \
  --synthetic
```
