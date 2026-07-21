---
name: audit-building-envelope
description: Discover optimal building vantage points, cluster visual properties, and trace architectural roof edge geometry using agentic vision.
---

# Audit Building Envelope

Use this skill to audit building envelopes and roofs from panoramic imagery. It supports two main tasks:
1. `vantage`: Performs spatial query to identify optimal camera angles for target coordinates, and clusters properties.
2. `roof`: Rectifies lens distortion (OpenCV cv2) and traces roof edges (eaves, ridges, hips) using agentic code execution.

## Prerequisites

The python environment must have:
- `google-genai`, `pandas-gbq`, `geopy`, `opencv-python`, and `pillow` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory, specifying the task with `--task`:

### Task 1: Building Vantage Point Audit
```bash
python3 street_view_insights/pano/skills/audit_building_envelope/scripts/run_audit.py --task vantage --coordinates <lat,lng>
```

### Task 2: Roof Edge Audit
```bash
python3 street_view_insights/pano/skills/audit_building_envelope/scripts/run_audit.py --task roof --observation-id <observation_id> --output <output_directory>
```

### Input Options
- `--coordinates`: GPS coordinate in format `lat,lng` (required for `vantage`).
- `--image`: Direct GCS URI or local image path (for `roof`).
- `--observation-id`: BQ observation lookup (for `roof`).
- `--output` (Optional): Directory to save output files (defaults to current directory).

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).
