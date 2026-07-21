---
name: detect-roof-edges
description: Perform agentic vision to detect, undistort, and trace roof edges of primary residential houses from street view images.
---

# Detect Roof Edges

Use this skill to detect the roof outline (eaves, ridges, hips) of the primary house in a street-level image. The skill uses Gemini's python code execution capability to run OpenCV lens distortion correction and image annotation.

## When to use

Use this skill when:
- You need to detect roof outlines and segments (eaves, ridges, hips).
- You want to apply visual annotations of structural features on a building.
- You want to undistort raw wide-angle lens images using assumed or calculated distortion coefficients.

## Prerequisites

The python environment must have:
- `google-genai`, `pandas-gbq`, `opencv-python`, `numpy`, and `pillow` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory. You must specify either `--image` or `--observation-id`:

### Option A: Local Image or gs:// URI
```bash
python3 street_view_insights/skills/detect_roof_edges/scripts/detect_roof_edges.py --image <image_path_or_gcs_uri>
```

### Option B: Look up Image by Observation ID in BigQuery
```bash
python3 street_view_insights/skills/detect_roof_edges/scripts/detect_roof_edges.py --observation-id <observation_id>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--location` (Optional): Google Cloud region (defaults to `global`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).

## Outputs

The script outputs three files to the current working directory:
1. `original_image.jpg`: The original downloaded or loaded image.
2. `corrected_image.jpg`: The image after lens distortion correction.
3. `annotated_output.jpg`: The image with visual lines drawn over the roof edges.
