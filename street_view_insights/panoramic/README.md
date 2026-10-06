# Street View Insights — Panoramic & Full-Scene Analysis Tutorials

This directory contains end-to-end Jupyter notebooks that analyze **Google Maps Platform Street
View Insights (SVI) panoramic (`SV_PANO`)** imagery using **BigQuery Spatial SQL**, **calibrated
7-camera fisheye geometry & OpenCV**, and **Vertex AI Gemini** (structured outputs, multimodal
visual few-shot prompting, and agentic vision code execution). It also includes [`svi_geo/`](svi_geo/),
the shared Python package used across the tutorials.

## Recommended Learning Path

| Tutorial Notebook | Primary Industry Use Case | Key Capabilities Demonstrated | Expected Runtime | Gemini Budget Ceiling |
|---|---|---|---|---|
| **[00 — Explore Street View Insights Coverage & 360° Rosette Geometry](notebooks/00_explore_coverage.ipynb)** | Territory discovery, snapshot inventory & sensor calibration warm-up | Live `SV_PANO` snapshot discovery (`snapshot_catalog_sql`), Geohash-6 spatial density (`coverage_sql`), BigQuery `LAG` drive sequencing (`rosette_sql`), calibrated `360°` equirectangular strip (`rosette.render_equirect_strip`), and interactive WKT track maps | `<= 3 min` | **`$0.00`** (`0` Gemini calls) |
| **[Sequential Street View Asset & Urban Forestry Detection](notebooks/analyze_sequential_images.ipynb)** *(Hero Tutorial)* | Municipal public works, electric/telecom utility pole audits & roadside urban forestry inventories | 6-camera corridor scanning (`UTILITY_POLE`, `ROAD_SIGN`, `STREET_LIGHT`, `FIRE_HYDRANT`, `STREET_TREE`), multimodal visual few-shot prompting (`build_uc2_fewshot_parts`), OpenCV structural & canopy gating (`vertical_post_support`, `street_tree_support`), 3D ray triangulation & deduplication, 0-byte BigQuery `ST_CLUSTERDBSCAN` cross-check, agentic pole-lean verification, multi-date repeat-pass change detection, and `cropped_assets_latest` reconciliation | `<= 12 min` | **`<= $0.60`** |
| **[Road & Sidewalk Surface Material Mapping](notebooks/surface_material_detection.ipynb)** | Transportation pavement management & pedestrian sidewalk accessibility mapping | Travel-aligned front/left/right perspective rendering, bird's-eye Inverse Perspective Mapping (`IPM`) kerb-line priors, Hidden Markov Model (`HMM`) Viterbi sequence smoothing (`ABSENT` state + gap breaks), schematic WKT `LineString` segments, and agentic CIE Lab/gradient texture verification | `<= 8 min` | **`<= $0.25`** |
| **[Multi-View Building Discovery, Facade Analysis & Cost Tracking](notebooks/house_image_discovery_with_cost.ipynb)** | Property insurance underwriting, municipal assessment & retrofit screening | Spatial radius search & target bearing framing, sensor-coverage view ranking (`< 1%` black border), structured `HouseView` extraction (`stories`, `exterior_material`, `roof_type`), agentic Sobel-y storey-count verification, and multi-view 3D facade triangulation | `<= 6 min` | **`<= $0.15`** |
| **[Roof Edge Polyline Tracing with Gradient Validation & Snapping](notebooks/roof_edge_tracing.ipynb)** | Solar installation design, storm underwriting & 3D roof geometry extraction | Adaptive upward-pitched roof view ranking, tree/sky occlusion screening (`occlusion_screen`), high-resolution Gemini polyline tracing (`RoofEdges`), deterministic Sobel/LSD gradient validation, vertex snapping & wall-siding decoy rejection, and agentic LSD eave-angle verification | `<= 5 min` | **`<= $0.10`** |

Every Gemini tutorial includes explicit `MAX_GEMINI_CALLS`, `MAX_USD`, and `CONCURRENCY` (default
`8`) parameters, previews multimodal token counts across `LOW`, `MEDIUM`, and `HIGH` media
resolutions before execution, and enforces per-notebook budget ceilings via
[`svi_geo/scripts/ceilings.json`](svi_geo/scripts/ceilings.json).

## 4-Layer Architecture Overview

Rather than sending raw, distorted fisheye frames directly to a vision-language model, these
tutorials divide work across four complementary layers:

1. **BigQuery Spatial SQL (`<= 2 GB` dry-run guard)**: Groups each panoramic capture's 7 camera
   frames by `capture_id`, reconstructs continuous vehicle drive sequences using `LAG()` window
   functions (`rosette_sql`), pairs multi-date repeat passes (`repeat_pairs_sql`), and cross-checks
   3D spatial clustering via zero-byte server-side `ST_CLUSTERDBSCAN` (`cluster_points_sql`).
2. **Calibrated Kannala–Brandt (`KB4`) Fisheye Geometry & OpenCV**: Unprojects raw `3648 × 5472`
   fisheye frames using the fitted `rosette_kb4_v1.json` lens model into rectilinear perspective
   crops with `< 1%` analytic black border, screens tree/sky occlusion, gates detections with
   OpenCV LSD vertical-post and Excess Green canopy support, snaps roof polylines to Sobel
   gradients, and triangulates 3D rays across panoramas.
3. **Vertex AI Gemini Multimodal Perception & Agentic Vision**: Combines Pydantic-typed structured
   outputs and multimodal visual few-shot prompting with targeted **Agentic Vision**
   (`code_execution=True`) cells where Gemini writes and executes Python/OpenCV measurement code in
   its cloud sandbox, cross-checked against local deterministic OpenCV references.
4. **Attributed GIS Maps & Visual QA Grids**: Exports interactive Folium maps (`map.html`) from
   BigQuery WKT geometries and attribution-stamped QA overlay grids (`overlay_grid.png`) showing
   accepted detections in green and rejected candidates in red with their deterministic rejection
   reason.

## Data Model Notes (`capture_id` Key & Dry-Run Byte Manifest)

The notebooks query `imagery_insights___us` (`pano_observations_latest`, `pano_observations_all`,
`snapshots`, and `cropped_assets_latest`).

- **7-frame rosette keyed on `capture_id`.** Each panoramic capture consists of 7 wide-angle
  portrait frames (`3648 × 5472`) sharing a `capture_id`. Cameras `0..5` point horizontally ~60°
  apart around an `8.44 cm` ring, and camera `6` points upward at the sky. The publishable Street
  View key `pano_id` is nullable (~69% of captures in typical corridors have `pano_id IS NULL`) and
  is preserved as attribution metadata alongside `map_url`. Set
  `INCLUDE_UNPUBLISHED_PANOS = False` in the parameter cell to restrict to published `pano_id`
  rows. **No intrinsics are provided in the BigQuery table;** `svi_geo` ships a fitted
  Kannala–Brandt (`KB4`) fisheye model in `svi_geo/svi_geo/intrinsics/rosette_kb4_v1.json` (see
  [`intrinsic-calculation.md`](intrinsic-calculation.md)).
- **Server-side BigQuery sequencing (`rosette_sql`).** `svi_geo.data.rosette_sql` aggregates each
  rosette's 7 cameras via `ARRAY_AGG(STRUCT(k, observation_id, heading, pitch, roll, cam_lat,
  cam_lng) ORDER BY k)` and computes drive sequences (`seq_id`, `seq_idx`, `step_m`, `travel_deg`),
  `ST_ASTEXT(geog) AS wkt`, and `ST_GEOHASH(geog, 7) AS gh7` directly in BigQuery using `LAG`
  gaps-and-islands window functions.
- **Zero-byte image URI construction (`0 B` `gcs_uri` scan).** Selecting the `gcs_uri` column scans
  ~1.9 GB of string data, so it is never selected in SQL. `data.frames_from_rosettes` constructs
  `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` locally from `GCS_BUCKET`.
- **Measured BigQuery dry-run byte estimates (`svi_geo/data/bytes_manifest.json`).** All queries
  execute a dry-run first and enforce `maximum_bytes_billed <= 2 GB` (`$6.25/TB` on-demand; cached
  locally as snapshot-keyed Parquet files for up to 35 days in `~/.cache/svi_geo/bq` so warm
  re-runs bill `0 B`):

| SQL Template (`svi_geo.data`) | Dry-Run Bytes | Cold Scan (GB) | Est. On-Demand Cost (`$6.25/TB`) |
|---|---:|---:|---:|
| `snapshot_catalog_sql` | `2,022 B` | `0.000002 GB` | `< $0.0001` |
| `cluster_points_sql` (`allow_table_free=True`) | `0 B` | `0.000 GB` | `$0.0000` |
| `assets_in_aoi_sql` (`cropped_assets_latest`) | `52,951,813 B` | `0.053 GB` | `$0.0003` |
| `coverage_sql` (geohash-6 cells) | `1,040,162,652 B` | `1.040 GB` | `$0.0065` |
| `repeat_pairs_sql` (`pano_observations_all`) | `1,361,514,060 B` | `1.362 GB` | `$0.0085` |
| `tracks_sql` (drive LineStrings) | `1,424,622,420 B` | `1.425 GB` | `$0.0089` |
| `multi_aoi_sql` / `skill_id_sql` / `skill_coords_sql` | `1,627,581,204 B` | `1.628 GB` | `$0.0102` |
| `rosette_sql` / `rosette_target_sql` | `1,830,539,988 B` | `1.831 GB` | `$0.0114` |

## Running the Notebooks

Set two required parameters, either in the notebook's configuration cell or as environment
variables (the notebook raises a `ConfigError` if either is missing; the `GOOGLE_CLOUD_PROJECT` /
ADC project is never used as a silent fallback):

- `PROJECT_ID`: your Google Cloud billing project for BigQuery and Vertex AI.
- `GCS_BUCKET`: the Cloud Storage frame bucket linked to your Street View Insights dataset.

```bash
export PROJECT_ID=YOUR_PROJECT_ID GCS_BUCKET=YOUR_FRAME_BUCKET
jupyter nbconvert --to notebook --execute --output-dir /tmp/nbrun \
  street_view_insights/panoramic/notebooks/analyze_sequential_images.ipynb
```

Outside a clone of this repository, the first code cell pip-installs `svi_geo` from GitHub at
`SVI_GEO_REF` (pinned to a verified commit on the `svi-gemini-improvements` branch until merged to
`main`). Inside a local repository clone, the local `svi_geo` package is discovered automatically.

Required IAM roles (the notebooks do not modify IAM settings):
`roles/bigquery.jobUser` on `PROJECT_ID`, `roles/bigquery.dataViewer` on the linked dataset,
`roles/storage.objectViewer` on the frame bucket, and `roles/aiplatform.user` for Vertex AI Gemini.

### Optional Environment Variables

`SVI_USE_GCLOUD_TOKEN=1` (uses `gcloud auth print-access-token` for BigQuery/GCS/Vertex AI) and
`SVI_ECP_PROXY_URL` (routes Vertex AI calls through a local enterprise-certificate proxy) are
available for managed corporate workstations where default credentials require proxy routing. In
Google Colab or standard local environments, leave them unset.

`svi_geo` queries only the panoramic views of allow-listed datasets (`imagery_insights___us` by
default). If your subscription uses another dataset name, set `DATASET_ID` in the notebook and add
the name to `SVI_ALLOWED_DATASETS` (comma-separated), e.g.
`SVI_ALLOWED_DATASETS=imagery_insights___eu`.

## Terms of Use, Attribution & Caching

- Imagery frames come from your Street View Insights subscription and are governed by the Street
  View Insights terms of your Google Cloud agreement. Do not redistribute raw frames, or crops
  rendered from them, outside your organisation.
- Every figure that displays imagery is stamped with `"Imagery © Google"`
  (`svi_geo.attribution.add_to_axes`). Every interactive map passes `attr=attribution.FOLIUM_ATTR`,
  which preserves the base-map credit and adds the Google imagery credit. Retain these attributions
  whenever figures are shared internally.
- Frames are downloaded with your credentials and passed to Gemini inline (`Part.from_bytes`).
  `GcsImageFetcher` does not cache frames on disk unless `cache_dir=` is provided; cached frames
  expire after 24 hours (`cache_ttl_s`), and `fetcher.purge_expired()` removes expired files.

## Calibration & Evaluation Documentation

- **[`intrinsic-calculation.md`](intrinsic-calculation.md)**: Detailed mathematical walkthrough of
  how the 7-camera rosette intrinsics (`rosette_kb4_v1.json`) were self-calibrated from multi-view
  panoramic imagery and how to reproduce the calibration check.
- **[`svi_geo/README.md`](svi_geo/README.md)**: Package architecture, module reference,
  calibration metrics, and production indexing patterns.
- **[`svi_geo/EVALUATION.md`](svi_geo/EVALUATION.md)**: Multi-view geometric consistency,
  cross-day repeat-pass stability, OpenCV evidence gates, and zoom-tile silver-teacher evaluation
  across `lakeland_fl` (tune), `salt_lake_ut` (held-out), and `osaka_jp` (dense urban stress test),
  plus the human annotation kit protocol.
