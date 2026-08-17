---
name: surface-material-detection-using-panoramic-svi
description: Classify ground and road surface materials (Paved Asphalt, Concrete, Gravel, Dirt, Mud, Cobblestone, Unpaved) and evaluate surface degradation/cracking from panoramic imagery.
---

# Surface Material Detection Using Panoramic SVI

Use this skill to audit road, driveway, or terrain surface materials and assess ground conditions using panoramic street view imagery.

## Prerequisites

The python environment must have:
- `google-genai`, `google-cloud-bigquery`, and `pillow` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory:

### Audit by BigQuery Observation or Capture ID
```bash
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py --observation-id <observation_id>
```

### Audit by GPS Coordinates
```bash
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py --coordinates <lat,lng>
```

### Audit by Direct Image Path or GCS URI
```bash
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py --image <image_path_or_gs_uri>
```

### Optional Arguments
- `--output` (Optional): Path to save JSON analysis result file.
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name (defaults to `imagery_insights___us`).
- `--table` (Optional): BigQuery panoramic observations table (defaults to `pano_observations_latest`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.7-flash`).
