# Street View Insights — 3D LiDAR Library & Skills (`lidar/`)

Top-level **3D LiDAR (`.laz`)** Python library (`svi_lidar`) and 5 production agent skills supporting **both** Street View Insights delivery modes:

1. **Full-Frame + 3D LiDAR (`SV_FULL_FRAME_ASSETS`):** `full_frame_observations_latest` + `full_frame_lidar_metadata_latest` (cataloged roadside poles and signs with pre-computed 2D `bbox`).
2. **Panoramic + 3D LiDAR (`SV_PANO`):** `pano_observations_latest` + `pano_lidar_metadata_latest` (continuous 360° streetscape coverage across 6 horizontal rosette cameras `k = 0..5`, skipping sky camera `k = 6`).

---

## Why One Unified `lidar/` Package Serves Both Modes

| Layer | Full-Frame LiDAR (`--mode full_frame`) | Panoramic LiDAR (`--mode pano`) |
| :--- | :--- | :--- |
| **Raw `.laz` Format** | `LAS 1.4` Point Format `1` (`1 mm` `EPSG:4978` ECEF, `uint16` intensity, `gps_time`, no native RGB) | Identical `LAS 1.4` Point Format `1` (`1 mm` `EPSG:4978` ECEF, `uint16` intensity, `gps_time`, no native RGB) |
| **Camera Sensor & Lens** | `3648 × 5472` portrait 2-term radial fisheye (`fx = fy = 2964.42`, `cx = 1836.95`, `cy = 2733.06`) | Identical `3648 × 5472` portrait 2-term radial fisheye across horizontal lenses `k = 0..5` (~60° apart) |
| **`.laz` Sweep Merging** | Merge `device_number 0..N-1` (`2` or `4` roof scanners) + `2 cm` ENU voxel deduplication | Resolve full `capture_id` rosette (`k = 0..5`), prioritize `>= 500`-point sweeps over forward-lens stubs + `2 cm` voxel dedup |
| **Asset Discovery** | Crop `.laz` viewing cones to BigQuery `bbox` (`catalog_assets`) or `--bbox-norm` | Pure-3D `discover_roadside_assets_3d` (retroreflective signs, poles, trees, walls) or Gemini 2D→3D `--bbox-norm` |
| **True Color Photo RGB** | Single-frame or `--asset-id` multi-observation Z-buffer (`2 × 2 px` + `3 × 3` foreground splat) | Full **360° 6-camera rosette** Z-buffer fusion (`d / cos(theta)` view selection) |

All 5 skills default to `--mode auto` (detecting `:5001ee` observation IDs, `--capture-id`, or `--pano-id` as `pano`, and cataloged IDs or `--asset-id` as `full_frame`).

---

## Directory Structure

```
street_view_insights/lidar/
├── pyproject.toml
├── requirements.txt
├── svi_lidar/                                              # Shared Python package
│   ├── io_and_frames.py                                    # Full-Frame & Pano SQL, .laz streaming, ECEF/ENU/Camera math
│   ├── projection_and_rgb.py                               # 2964.42 fisheye, 14x14 overlay, Z-buffer True Color RGB, .ply
│   ├── measurements_3d.py                                  # Z_ground, poles, signs, trees, walls, corridor slices & 3D discovery
│   ├── multimodal_fusion.py                                # 3D->2D depth-masked crops, 2D->3D box casting & driveway scenes
│   └── synthetic_scene.py                                  # Offline synthetic 3D street generator for tests & smoke runs
├── skills/                                                 # 5 standalone agent skills
│   ├── project_and_colorize_3d_lidar/
│   ├── measure_roadside_assets_3d_lidar/
│   ├── slice_road_curb_and_sidewalk_3d_lidar/
│   ├── fuse_image_and_3d_lidar/
│   └── analyze_building_and_driveway_clearance_3d_lidar/
└── tests/
    └── test_svi_lidar.py
```

---

## Production Skills (`skills/`)

| Skill (`name`) | Folder | What It Does |
| :--- | :--- | :--- |
| `project-and-colorize-3d-lidar` | [`skills/project_and_colorize_3d_lidar/`](skills/project_and_colorize_3d_lidar/SKILL.md) | `14 × 14 px` front-surface 2D overlays + single-view or 360° 6-camera Z-buffered **True Color Photo RGB** `.ply` export. |
| `measure-roadside-assets-3d-lidar` | [`skills/measure_roadside_assets_3d_lidar/`](skills/measure_roadside_assets_3d_lidar/SKILL.md) | Pure-3D (`LiDAR Only`) pole height & lean angle, retroreflective sign `W × H`, tree crown/clearance, wall flatness, and uncataloged 3D discovery. |
| `slice-road-curb-and-sidewalk-3d-lidar` | [`skills/slice_road_curb_and_sidewalk_3d_lidar/`](skills/slice_road_curb_and_sidewalk_3d_lidar/SKILL.md) | Grade-detrended `4.0 m` perpendicular corridor slices: roadway width, curb step (`cm`), and sidewalk width, slope, and clear path. |
| `fuse-image-and-3d-lidar` | [`skills/fuse_image_and_3d_lidar/`](skills/fuse_image_and_3d_lidar/SKILL.md) | Bidirectional `Image + 3D LiDAR` fusion: `3D → 2D` depth-masked Gemini crops and `2D → 3D` box-to-LiDAR casting with occlusion scoring. |
| `analyze-building-and-driveway-clearance-3d-lidar` | [`skills/analyze_building_and_driveway_clearance_3d_lidar/`](skills/analyze_building_and_driveway_clearance_3d_lidar/SKILL.md) | Commercial frontage & vehicle pull-in envelopes: first-floor height, entry step (`cm`), driveway width, and van / box truck / heavy truck fit. |

---

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r street_view_insights/lidar/requirements.txt
pip install -e street_view_insights/lidar
pytest street_view_insights/lidar/tests -q
```
