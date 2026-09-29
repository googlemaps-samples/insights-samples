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
  across panoramas and de-duplicates them into map entities. Last, it checks
  itself by projecting each entity into a view that was not used and asking
  Gemini whether the object is there.
- **[Surface Material Detection](notebooks/surface_material_detection.ipynb)**:
  classifies continuous assets (road, sidewalk, fence, power line) at each
  panorama along a drive. Labels are smoothed along the sequence with an HMM
  (Viterbi), then merged into road segments with material, condition and
  confidence.
- **[House Image Discovery with Cost](notebooks/house_image_discovery_with_cost.ipynb)**:
  picks the camera in each panorama that best sees a target house, renders an
  undistorted crop centred on it, and asks Gemini to describe or verify the
  house. The cost of every call is logged.
- **[Agentic Roof Edge Detection](notebooks/agentic_roof_edge_detection.ipynb)**:
  lens-corrects the best view of a building with the calibrated rosette model.
  Gemini with code execution then traces the visible roof edges.

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
  Gemini are rendered from it.
- **`capture_id` identifies a single panorama, not a drive.** Drive sequences
  are rebuilt within each `snapshot_id` by ordering panoramas by
  `capture_time` and splitting at time/distance gaps (see
  `svi_geo.sequence`). The measured spacing between consecutive panoramas is
  about 10.2–10.7 m in the sampled AOIs. The code measures it and never
  hard-codes it.
- **Cheap image URIs.** Selecting the `gcs_uri` column scans about 1.9 GB. The
  notebooks select only small columns and build the URI as
  `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg`. The bucket is
  discovered once. See `svi_geo.data.gcs_uri_for`.
- Pano rows have no prior detections, so all objects come from Gemini.
- BigQuery access is dry-run first, capped with `maximum_bytes_billed`, and
  uses parameterized SQL only. Images are downloaded with your own credentials
  and sent to Gemini inline as bytes.

### Optional environment variables

`SVI_USE_GCLOUD_TOKEN=1` (use `gcloud auth print-access-token` for
BigQuery/GCS) and `SVI_ECP_PROXY_URL` (send Vertex calls through a local
enterprise-certificate proxy) exist only to help on Google-managed
workstations. In Colab or with normal Application Default Credentials, leave
them unset.

## Calibration and evaluation

See [`svi_geo/README.md`](svi_geo/README.md) for the calibration metrics,
synthetic evaluation and real-data self-consistency results, and for how to
reproduce them.
