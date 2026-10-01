# Panorama and Full Scene Notebooks

This directory has Jupyter notebooks that analyse Street View Insights (SVI)
**panoramic** imagery with Gemini. It also has `svi_geo/`, the shared Python
package the notebooks use. The package holds the rosette geometry, drive
sequences, triangulation / de-duplication, smoothing, a Gemini client and the
evaluation code.

## Notebooks

- **[00 — Explore Coverage & 360° Rosette Strip](notebooks/00_explore_coverage.ipynb)**:
  zero-Gemini warm-up notebook (`$0.00` Gemini cost, `<= 3 min`). Discovers live
  `SV_PANO` snapshots (`snapshot_catalog_sql`), summarizes geohash-6 spatial coverage
  (`coverage_sql`), reconstructs drive sequences in BigQuery (`rosette_sql`), and
  renders a calibrated 360° equirectangular strip (`rosette.render_equirect_strip`) and
  drive-track map (`maps.rosette_tracks_map`).
- **[House Image Discovery with Cost](notebooks/house_image_discovery_with_cost.ipynb)** (UC1,
  ceiling `<= $0.15`, `<= 6 min`): picks, in each rosette (`capture_id`), the camera
  that frames a target house with `< 1%` black border, asks Gemini for structured
  `HouseView` attributes, runs one validated agentic-vision (`code_execution=True`)
  storey-count cross-check against local Sobel-y row peaks, and triangulates the house
  facade from 2+ sighting rays.
- **[Analyze Sequential Images](notebooks/analyze_sequential_images.ipynb)** (UC2,
  ceiling `<= $0.60`, `<= 12 min`): walks a drive sequence keyed on `capture_id`,
  detects `HOUSE`, `UTILITY_POLE`, and `ROAD_SIGN` across all 6 horizontal cameras,
  gates pole/sign boxes with OpenCV LSD vertical-post support, clusters rays into 3D
  entities (cross-checked with 0-byte BigQuery `ST_CLUSTERDBSCAN`), runs one validated
  agentic-vision pole-lean measurement, evaluates held-out cross-view consistency (not
  accuracy), and audits repeat-pass pairs (`O1`) and `cropped_assets_latest` (`O2`).
- **[Surface Material Detection](notebooks/surface_material_detection.ipynb)** (UC3,
  ceiling `<= $0.25`, `<= 8 min`): classifies road (`CENTER`) and left/right sidewalk
  materials along a drive sequence from travel-aligned views, fuses bird's-eye IPM
  kerb-line priors with Viterbi HMM smoothing (`ABSENT` state + gap breaks) into
  schematic WKT segments, and runs one validated agentic-vision road-texture check.
- **[Roof Edge Tracing](notebooks/roof_edge_tracing.ipynb)** (UC4, ceiling `<= $0.10`,
  `<= 5 min`): ranks upward-pitched roof views, screens tree/sky occlusion
  (`occlusion_screen`), traces roof polylines (`RoofEdges`), validates and snaps edges
  to Sobel/LSD gradients while rejecting wall/sky/foliage decoys, and runs one
  validated agentic-vision LSD eave-angle measurement.

Every UC notebook has explicit `MAX_GEMINI_CALLS`, `MAX_USD`, and `CONCURRENCY` (default `8`)
parameters, prints token/cost estimates before and after each Gemini run, and enforces per-notebook
cost ceilings via `scripts/ceilings.json`.

## Data model notes (`capture_id` key & dry-run byte manifest)

The notebooks query `imagery-insights-sandbox.imagery_insights___us` (`pano_observations_latest`,
`pano_observations_all`, `snapshots`, and `cropped_assets_latest`).

- **7-frame rosette keyed on `capture_id`.** Each panoramic capture is 7 wide-angle portrait frames
  (`3648x5472`) sharing a `capture_id`. Cameras `0..5` point horizontally ~60° apart, and camera `6`
  points at the sky. The publishable Street View key `pano_id` is nullable (~69% of captures in
  standard AOIs have `pano_id IS NULL`) and is kept as attribution metadata alongside `map_url`. Set
  `INCLUDE_UNPUBLISHED_PANOS = False` in the parameter cell to restrict to published `pano_id` rows.
  **No intrinsics are provided in the table;** `svi_geo` ships a fitted Kannala–Brandt (`KB4`)
  fisheye model in `svi_geo/svi_geo/intrinsics/rosette_kb4_v1.json` (see
  [`intrinsic-calculation.md`](intrinsic-calculation.md)).
- **Server-side BigQuery sequencing (`rosette_sql`).** `svi_geo.data.rosette_sql` aggregates each
  rosette's 7 cameras via `ARRAY_AGG(STRUCT(k, observation_id, heading, pitch, roll, cam_lat,
  cam_lng) ORDER BY k)` and computes drive sequences (`seq_id`, `seq_idx`, `step_m`, `travel_deg`),
  `ST_ASTEXT(geog) AS wkt`, and `ST_GEOHASH(geog, 7) AS gh7` directly in BigQuery using `LAG`
  gaps-and-islands window functions.
- **Cheap image URIs (`0 B` `gcs_uri` scan).** Selecting `gcs_uri` scans ~1.9 GB of string data, so
  it is never selected. `data.frames_from_rosettes` builds
  `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` locally from `GCS_BUCKET`.
- **Measured BigQuery dry-run byte estimates (`svi_geo/data/bytes_manifest.json`).** All queries
  dry-run first and enforce `maximum_bytes_billed <= 2 GB` (`$6.25/TB` on-demand; cached locally as
  snapshot-keyed Parquet files for up to 35 days in `~/.cache/svi_geo/bq` so warm re-runs bill `0 B`):

| SQL Template (`svi_geo.data`) | Dry-Run Bytes | Cold Scan (GB) | Est. On-Demand Cost (`$6.25/TB`) |
|---|---:|---:|---:|
| `snapshot_catalog_sql` | `2,318 B` | `0.000002 GB` | `< $0.0001` |
| `cluster_points_sql` (`allow_table_free=True`) | `0 B` | `0.000 GB` | `$0.0000` |
| `assets_in_aoi_sql` (`cropped_assets_latest`) | `53,341,246 B` | `0.053 GB` | `$0.0003` |
| `coverage_sql` (geohash-6 cells) | `1,039,581,254 B` | `1.040 GB` | `$0.0065` |
| `tracks_sql` (drive LineStrings) | `1,426,014,915 B` | `1.426 GB` | `$0.0089` |
| `rosette_sql` / `multi_aoi_sql` | `1,831,615,879 B` | `1.832 GB` | `$0.0114` |
| `repeat_pairs_sql` | `1,892,835,442 B` | `1.893 GB` | `$0.0118` |

## Running the notebooks

Set two parameters, either in the notebook's parameters cell or as environment
variables (the notebook stops with a `ConfigError` if either is missing; the
`GOOGLE_CLOUD_PROJECT` / ADC project is never used as a silent fallback):

- `PROJECT_ID`: your billing project for BigQuery and Vertex AI.
- `GCS_BUCKET`: the frame bucket linked to your Imagery Insights dataset.

```bash
export PROJECT_ID=YOUR_PROJECT_ID GCS_BUCKET=YOUR_FRAME_BUCKET
jupyter nbconvert --to notebook --execute --output-dir /tmp/nbrun \
  street_view_insights/panoramic/notebooks/house_image_discovery_with_cost.ipynb
```

Outside a clone of this repo, the first cell pip-installs `svi_geo` from GitHub
at `SVI_GEO_REF` (currently the `svi-gemini-improvements` branch; it switches
to `main` after the merge; set `$SVI_GEO_REF` to a commit SHA for a
reproducible run). In a clone the local copy is used.

IAM roles needed (the notebooks change no IAM settings):
`roles/bigquery.jobUser` on `PROJECT_ID`, `roles/bigquery.dataViewer` on the
linked dataset, `roles/storage.objectViewer` on the frame bucket and
`roles/aiplatform.user` for Gemini.

### Optional environment variables

`SVI_USE_GCLOUD_TOKEN=1` (use `gcloud auth print-access-token` for
BigQuery/GCS/Vertex AI) and `SVI_ECP_PROXY_URL` (send Vertex calls through a
local enterprise-certificate proxy) exist only to help on managed workstations
where plain Application Default Credentials return 401. In Colab or with
normal Application Default Credentials, leave them unset.

`svi_geo` only queries the pano views of allow-listed datasets
(`imagery_insights___us` by default). If your dataset has another name, set
`DATASET_ID` in the notebook and add the name to `SVI_ALLOWED_DATASETS`
(comma-separated), e.g. `SVI_ALLOWED_DATASETS=imagery_insights___eu`.

## Terms of use, attribution and caching

- The frames come from your Imagery Insights dataset and are governed by the
  Imagery Insights terms of your Google Cloud agreement. Do not redistribute
  frames, or crops rendered from them, outside your organisation.
- Every figure that shows imagery is labelled "Imagery © Google"
  (`svi_geo.attribution.add_to_axes`). Every map passes
  `attr=attribution.FOLIUM_ATTR`, which keeps the base-map credit and adds the
  imagery credit. Keep these labels when you reuse the figures.
- Frames are downloaded with your own credentials and sent to Gemini inline.
  `GcsImageFetcher` does not cache them on disk unless you pass `cache_dir=`.
  Cached frames expire after 24 hours (`cache_ttl_s`), and
  `fetcher.purge_expired()` deletes stale files.

## Calibration and evaluation

- **[`intrinsic-calculation.md`](intrinsic-calculation.md)**: detailed guide on
  how the 7-camera rosette intrinsics (`rosette_kb4_v1.json`) were
  self-calibrated from multi-view panoramic imagery and how to reproduce the
  calibration test yourself.
- **[`svi_geo/README.md`](svi_geo/README.md)**: package overview, calibration
  metrics, and how to re-run the synthetic, self-consistency, and label-free evaluations.
- **[`svi_geo/EVALUATION.md`](svi_geo/EVALUATION.md)**: label-free evaluation protocol and
  baseline-vs-final results across `lakeland_fl` (tune), `salt_lake_ut` (held-out), and
  `osaka_jp` (stress test), plus the hand-label protocol for ground-truth accuracy.
