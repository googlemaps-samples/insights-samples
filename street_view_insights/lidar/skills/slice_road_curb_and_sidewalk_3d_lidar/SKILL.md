---
name: slice-road-curb-and-sidewalk-3d-lidar
description: Slice perpendicular 4.0 m street-corridor cross-sections from Full-Frame or Panoramic Street View Insights 3D LiDAR (.laz) scans to measure curb-to-curb roadway width, road cross-slope, left/right curb step height (cm), and concrete sidewalk width, clear path width, cross-slope (%), and trip steps vs. grass verges. Use when measuring road widths, curb reveals, or sidewalk widths/slopes in 3D from full_frame_lidar_metadata_latest or pano_lidar_metadata_latest. Don't use for 2D-only road surface material classification without LiDAR (use surface-material-detection-using-panoramic-svi) or driveway truck clearance envelopes (use analyze-building-and-driveway-clearance-3d-lidar).
---

# Slice Road, Curb, and Sidewalk Cross-Sections (`slice-road-curb-and-sidewalk-3d-lidar`)

Use this skill to extract centimeter-scale perpendicular street cross-sections (`roadway_width_m`, `curb_reveal_cm`, `sidewalk_width_m`, `clear_path_width_m`, `sidewalk_cross_slope_pct`, `max_trip_step_cm`, and `verge_width_m`) from `.laz` point clouds in **both** Full-Frame (`full_frame_lidar_metadata_latest`) and Panoramic (`pano_lidar_metadata_latest`) Street View Insights deliveries.

## Why Corridor Cross-Sections Work Across Full-Frame & Pano LiDAR

1. **Both Modes Share `1 mm` `EPSG:4978` ECEF `.laz` Ground Sweeps:**
   - Whether `.laz` files are joined via `full_frame_observations_latest` or across a 6-lens `pano_observations_latest` rosette (`capture_id`), merging all `>= 500`-point scanner sweeps into local ENU meters yields a continuous street-corridor ground mesh. In `pano` mode, stations can be sliced both behind and ahead of the capture (`e.g., --stations -10,0,10`).
2. **Longitudinal Grade Detrending & Gutter-Referenced Curb Steps:**
   - Rotates ENU points along `--heading-deg` (or `camera_pose.heading`), subtracts linear street grade along the roadway centerline (`|cross_m| <= 2.5 m`), and measures curb steps (`4.5–28 cm`) relative to the adjacent gutter rather than the crowned street center.
3. **Floor-Clamped Sidewalk vs. Grass Verge Separation:**
   - Clamping floor roughness `std(z)` within `±12 cm` of each `25 cm` bin's `20th-percentile` floor separates smooth, bright concrete footpaths (`std(z) <= 2.8 cm`, `intensity >= 18`) from rougher, dimmer grass verges while counting standing sign posts or trunks (`0.25–2.05 m` above floor) in `clear_path_width_m`.

## Prerequisites

```bash
pip install -r street_view_insights/lidar/requirements.txt
pip install -e street_view_insights/lidar
```

## Instructions

Run from the repository root:

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"

# 1. Full-Frame observation cross-sections (+8 m, +16 m, +24 m ahead)
python3 street_view_insights/lidar/skills/slice_road_curb_and_sidewalk_3d_lidar/scripts/slice_corridor_cross_sections.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --observation-id "<full_frame_observation_id>" \
  --stations 8,16,24

# 2. Panoramic rosette cross-sections (-10 m, 0 m, +10 m along street heading)
python3 street_view_insights/lidar/skills/slice_road_curb_and_sidewalk_3d_lidar/scripts/slice_corridor_cross_sections.py \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --capture-id "<capture_id>" \
  --mode pano \
  --stations -10,0,10

# 3. Offline synthetic corridor verification
python3 street_view_insights/lidar/skills/slice_road_curb_and_sidewalk_3d_lidar/scripts/slice_corridor_cross_sections.py \
  --synthetic
```
