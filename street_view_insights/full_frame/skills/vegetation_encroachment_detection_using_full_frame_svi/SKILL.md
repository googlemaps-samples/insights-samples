---
name: vegetation-encroachment-detection-using-full-frame-svi
description: Group multi-view full-frame asset observations, crop target poles using BigQuery bounding boxes (bbox), and audit nearby tree and foliage encroachment or wire hazards.
---

# Vegetation Encroachment Detection Using Full-Frame SVI

Use this skill to audit utility poles and surrounding vegetation hazards across full-frame street view observations. It automatically extracts bounding box crops (`bbox`) from BigQuery `full_frame_observations_latest` to verify target assets and evaluates surrounding tree foliage clearance relative to overhead power lines.

## Prerequisites

The python environment must have:
- `google-genai`, `google-cloud-bigquery`, `google-cloud-storage`, and `pillow` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory:

### Audit All Full-Frame Observations for an Asset ID
```bash
python3 street_view_insights/full_frame/skills/vegetation_encroachment_detection_using_full_frame_svi/scripts/analyze_vegetation_encroachment.py --asset-id <asset_id>
```

### Audit a Specific Observation ID
```bash
python3 street_view_insights/full_frame/skills/vegetation_encroachment_detection_using_full_frame_svi/scripts/analyze_vegetation_encroachment.py --observation-id <observation_id>
```

### Audit a Direct Full-Frame Image
```bash
python3 street_view_insights/full_frame/skills/vegetation_encroachment_detection_using_full_frame_svi/scripts/analyze_vegetation_encroachment.py --image <image_path_or_gs_uri>
```

### Optional Arguments
- `--output` (Optional): Path to save JSON analysis result file.
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name (defaults to `imagery_insights___us`).
- `--table` (Optional): BigQuery full-frame observations table (defaults to `full_frame_observations_latest`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).
