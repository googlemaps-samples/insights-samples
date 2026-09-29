---
name: surface-material-detection-using-panoramic-svi
description: Classify ground and road surface materials (Paved Asphalt, Concrete, Brick/Pavers, Cobblestone, Gravel, Dirt, Mud, Turf, Unpaved) and surface condition from one panoramic Street View Insights frame.
---

# Surface Material Detection Using Panoramic SVI

Use this skill to audit the road or ground surface material and condition at one location,
using the Street View Insights **panoramic** tables only (`pano_observations_latest`).

## How it works

1.  **Metadata lookup (code).** A parameterised, dry-run-checked BigQuery query (capped at
    2 GB billed) reads frame metadata for panos within `--radius-m` of the point, or around the
    given observation/pano id. It never selects `gcs_uri`: that column alone scans ~1.9 GB, so
    the frame path is derived as `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg`.
2.  **Camera choice (code).** The forward camera of the nearest pano is picked from the travel
    direction (neighbouring panos of the same drive); camera 0 is the fallback.
3.  **Road view (code).** The frame is downloaded with your credentials and a downward-looking
    view is rendered deterministically (rectified with `svi_geo`'s fitted fisheye model when
    `svi_geo` is installed, else a fixed crop of the lower frame).
4.  **Perception (Gemini).** The view is sent **inline as bytes** with a pydantic
    `response_schema`; the reply is validated in code (numeric confidence 0-1).

## Prerequisites

-   `google-genai`, `google-cloud-bigquery`, `google-cloud-storage`, `pydantic`,
    `opencv-python-headless` and `numpy` (`pip install -e street_view_insights/panoramic/svi_geo`
    installs all of them plus the optional rectification).
-   Application Default Credentials with BigQuery, read access to the frame bucket, and
    Vertex AI in your project.

## Instructions

Run from the repository root:

```bash
# By GPS coordinates (nearest pano within --radius-m, default 30 m)
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --project YOUR_PROJECT_ID --coordinates <lat,lng>

# By observation id or pano id
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --project YOUR_PROJECT_ID --observation-id <observation_or_pano_id>

# By a local image you already downloaded
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --project YOUR_PROJECT_ID --image frame.jpg
```

### Optional arguments

-   `--output`: path to save the JSON result.
-   `--dataset`: BigQuery dataset (default `imagery_insights___us`).
-   `--gcs-bucket`: frame bucket; skips the one-off ~1.9 GB bucket lookup (the result is also
    cached in `~/.cache/svi_geo/bucket.json`, or set `$GCS_BUCKET`).
-   `--radius-m`: search radius for the pano lookup (default 30).
-   `--model` (default `gemini-3.5-flash`) and `--location` (default `global`).

### Output

```json
{
  "primary_material": "Paved Asphalt",
  "secondary_materials": ["Concrete"],
  "confidence": 0.86,
  "surface_condition": "Fair",
  "visual_reasoning": "...",
  "source": {"pano_id": "...", "observation_id": "...", "cam_k": 0, "travel_deg": 87.1}
}
```
