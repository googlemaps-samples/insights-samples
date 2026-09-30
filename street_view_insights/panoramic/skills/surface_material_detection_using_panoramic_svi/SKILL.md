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
    given id. `--observation-id` accepts an `observation_id`, a `pano_id` or a `capture_id`
    (each pano has one `capture_id`). It never selects `gcs_uri`: that column alone scans
    ~1.9 GB, so the frame path is derived as
    `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg`.
2.  **Camera choice (code).** The forward camera of the nearest pano is picked from the travel
    direction (neighbouring panos of the same drive); camera 0 is the fallback.
3.  **Road view (code).** The frame is downloaded with your credentials and a road view is
    rendered deterministically. With `svi_geo` installed it is rectified with the fitted
    fisheye model along the camera's calibrated heading, pitched 22 deg below the horizon
    using the frame's real `camera_pose`, and the rows showing the vehicle are cropped.
    Without `svi_geo` it is a fixed crop of the lower frame.
4.  **Perception (Gemini).** The view is sent **inline as bytes** with a pydantic
    `response_schema`; the reply is validated in code (numeric confidence 0-1).

## Prerequisites

-   `google-genai`, `google-cloud-bigquery`, `google-cloud-storage`, `pydantic`,
    `opencv-python-headless` and `numpy` (`pip install -e street_view_insights/panoramic/svi_geo`
    installs all of them plus the optional rectification).
-   Application Default Credentials with BigQuery, read access to the frame bucket, and
    Vertex AI in your project.
-   Your billing project (`--project`, or `$PROJECT_ID`, then `$GOOGLE_CLOUD_PROJECT`) and the
    frame bucket linked to your Imagery Insights dataset (`--gcs-bucket` or `$GCS_BUCKET`). The
    bucket is required unless you pass `--image`; it is never looked up by selecting `gcs_uri`.

## Instructions

Run from the repository root:

```bash
export PROJECT_ID=YOUR_PROJECT_ID GCS_BUCKET=YOUR_FRAME_BUCKET

# By GPS coordinates (nearest pano within --radius-m, default 30 m)
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --coordinates <lat,lng>

# By observation id, pano id or capture id
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --observation-id <observation_pano_or_capture_id>

# By a local image you already downloaded (no bucket needed)
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --image frame.jpg
```

### Optional arguments

-   `--project`: billing project (default `$PROJECT_ID`, then `$GOOGLE_CLOUD_PROJECT`; the
    script stops if neither is set).
-   `--gcs-bucket`: frame bucket (default `$GCS_BUCKET`; required unless `--image`).
-   `--output`: path to save the JSON result.
-   `--dataset`: BigQuery dataset (default `imagery_insights___us`).
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
