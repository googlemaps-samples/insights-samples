---
name: surface-material-detection-using-panoramic-svi
description: Classify ground and road surface materials (Paved Asphalt, Concrete, Brick/Pavers, Cobblestone, Gravel, Dirt, Mud, Turf, Unpaved) and surface condition from one panoramic Street View Insights frame.
---

# Surface Material Detection Using Panoramic SVI

Use this skill to audit the road or ground surface material and condition at one location,
using the Street View Insights **panoramic** tables only (`pano_observations_latest`).

## How it works

1.  **Metadata lookup (code).** A parameterised, dry-run-checked BigQuery query (capped at
    2 GB billed) reads frame metadata for rosettes within `--radius-m` of the point, or around the
    given id. Rosettes are keyed on `capture_id` (`pano_id` is kept as nullable publishable
    metadata; keeping `pano_id IS NULL` rosettes recovers ~69% of frames). `--observation-id`
    accepts an `observation_id`, `--capture-id` accepts a `capture_id`, or use `--pano-id`
    directly; the id lookup scans 1.632 GB (note: a miss still scans and bills 1.632 GB). It
    never selects `gcs_uri`: that column alone adds 1.201 GB (taking the scan to 2.803 GB), so
    the frame path is derived from `<bucket>/<snapshot_id>/v0/<observation_id>.jpg`.
2.  **Travel direction (code).** Measured from the neighbouring rosettes of the same drive
    (same snapshot, within 5 s). If it cannot be measured the script stops and asks for
    `--travel-deg`; it never guesses a camera.
3.  **Road view (code).** The frame(s) are downloaded with your credentials and a road view is
    rendered deterministically. With `svi_geo` installed the view is centred on the travel
    direction (not on a camera heading), 60 deg wide and pitched 22 deg below the horizon in
    world coordinates using the frames' real `camera_pose`. On the real rosette the travel
    direction falls on the seam between two cameras, so the view is composited from both
    (`sequence.road_view`). The rows showing the vehicle are cropped and the script stops if
    1 % or more of the sent view is outside the sensor (black-border check). Without `svi_geo`
    it is a fixed crop of the lower frame of the camera nearest the travel direction.
4.  **Perception (Gemini).** The view is sent **inline as bytes** with a pydantic
    `response_schema`; the reply is validated in code (numeric confidence 0-1). The token
    usage and estimated cost of the call are printed to stderr.

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

# By GPS coordinates (nearest rosette within --radius-m, default 30 m)
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --coordinates <lat,lng>

# By observation id, capture id, or pano id
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --observation-id <observation_id>
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --capture-id <capture_id>
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
  --pano-id <pano_id>

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
-   `--travel-deg`: travel direction in degrees from north, for panos whose direction
    cannot be measured from neighbouring panos.
-   `--model` (default `gemini_client.DEFAULT_MODEL`) and `--location` (default `global`).

### Output

```json
{
  "primary_material": "Paved Asphalt",
  "secondary_materials": ["Concrete"],
  "confidence": 0.86,
  "surface_condition": "Fair",
  "visual_reasoning": "...",
  "source": {"capture_id": "...", "pano_id": "...", "travel_deg": 87.1, "observation_ids": ["...", "..."],
             "cam_k": [0, 1], "black_fraction_sent": 0.0}
}
```
