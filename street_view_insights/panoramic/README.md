# Panorama and Full Scene Notebooks

This directory has Jupyter notebooks that analyse Street View Insights (SVI)
**panoramic** imagery with Gemini. It also has `svi_geo/`, the shared Python
package the notebooks use. The package holds the rosette geometry, drive
sequences, triangulation / de-duplication, smoothing, a Gemini client and the
evaluation code.

## Notebooks

- **[Analyze Sequential Images](notebooks/analyze_sequential_images.ipynb)**:
  rebuilds the drive sequence along a street and runs Gemini on
  lens-corrected views. It then triangulates houses, utility poles and signs
  across panoramas and de-duplicates them into map entities. A detection seen
  from one panorama is placed only when its ground contact is visible; otherwise
  it is listed as unlocated. Last, it runs a cross-view consistency check (not
  an accuracy measure): it projects each entity into a view that was not used
  and asks Gemini whether the object is there.
- **[Surface Material Detection](notebooks/surface_material_detection.ipynb)**:
  classifies the road surface and the left/right sidewalks at each panorama
  along a drive, from views centred on the travel direction. Labels are
  smoothed along the sequence with an HMM (Viterbi) that keeps "no sidewalk" as
  its own state and restarts at gaps. They are then merged into material
  segments. Sidewalk lines are drawn at a schematic offset from the drive.
- **[House Image Discovery with Cost](notebooks/house_image_discovery_with_cost.ipynb)**:
  picks, in each panorama, the camera that can show a whole target house without
  black border, renders an undistorted view framed on it, and asks Gemini to
  describe it. The house is triangulated from the boxes of two or more panoramas
  and its id is derived from that point. The cost of every call is logged.
- **[Roof Edge Tracing](notebooks/roof_edge_tracing.ipynb)**:
  lens-corrects the best view of a building with the calibrated rosette model.
  Gemini then traces the visible roof edges as schema-validated polylines.

Every notebook has a `MAX_GEMINI_CALLS` parameter (default 500; set it to
`None` for no limit) and a `CONCURRENCY` parameter (default 16). The estimated
cost is printed before and after each Gemini run.

## Data model notes (pano tables only)

The notebooks read only
`imagery-insights-sandbox.imagery_insights___us.pano_observations_latest` and
`pano_observations_all`.

- **7-frame rosette.** Each panorama is 7 wide-angle portrait frames
  (3648×5472). Cameras 0–5 point horizontally about 60° apart, and camera 6
  points at the sky. Each frame has its own `camera_pose` (position and
  heading/pitch/roll). **No intrinsics are provided.** `svi_geo` ships a
  fitted Kannala–Brandt (KB4) fisheye model in
  `svi_geo/svi_geo/intrinsics/rosette_kb4_v1.json`, and all views sent to
  Gemini are rendered from it. See
  [`intrinsic-calculation.md`](intrinsic-calculation.md) for the mathematical
  formulation and step-by-step instructions to reproduce the self-calibration.
- **`capture_id` identifies a single panorama, not a drive.** Drive sequences
  are rebuilt within each `snapshot_id` by ordering panoramas by
  `capture_time` and splitting at time/distance gaps (see
  `svi_geo.sequence`). The measured spacing between consecutive panoramas is
  about 10.2–10.7 m in the sampled AOIs. The code measures it and never
  hard-codes it.
- **Cheap image URIs.** Selecting the `gcs_uri` column scans about 1.9 GB, so it
  is never selected. The notebooks select only small metadata columns and build
  the URI as `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` (see
  `svi_geo.data.gcs_uri_for`). The bucket is the required `GCS_BUCKET`
  parameter; it is never discovered by a query.
- **Query cost.** The metadata query dry-runs at about 1.6 GB per run whatever
  the radius (the pano views are not clustered on location), which is inside
  the 2 GB `maximum_bytes_billed` cap. Results are cached locally for 7 days
  (`~/.cache/svi_geo/bq`), so re-runs bill 0 bytes.
- Pano rows have no prior detections, so all objects come from Gemini.
- BigQuery access is dry-run first, capped with `maximum_bytes_billed`, and
  uses parameterized SQL only. Images are downloaded with your own credentials
  and sent to Gemini inline as bytes.

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
  metrics, synthetic evaluation, and real-data self-consistency results.
- **[`svi_geo/EVALUATION.md`](svi_geo/EVALUATION.md)**: hand-label protocol for
  measuring accuracy on real imagery (label kit and scorer); no results until real labels
  exist.
