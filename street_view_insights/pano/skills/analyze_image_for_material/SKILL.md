---
name: analyze-image-for-material
description: Analyze street view images to identify the dominant road surface material (Paved, Gravel, Mud, Dirt).
---

# Analyze Image for Material

Use this skill to inspect a street-level, panoramic, or wide-angle photo (or sequence of photos) and determine the pavement or surface material of the primary road. The skill can accept a direct image path, or query BigQuery automatically given a track ID or location coordinates.

## When to use

Use this skill when:
- You need to classify the road surface material at a location (e.g., paved asphalt/concrete vs gravel, mud, or dirt).
- Visual evidence of road texture, specularity, and markings is required for an asset audit.
- You have a BigQuery `track_id` or coordinates (`lat,lng`) and want to look up the image sequence automatically before analysis.

## Prerequisites

The python environment must have:
- `google-genai` and `google-cloud-bigquery` libraries installed.
- Valid Google Cloud credentials (via application default credentials) to run BigQuery queries and Vertex AI prompts.

## Instructions

Run the helper script from the repository root directory. You must specify **exactly one** of `--image`, `--track-id`, or `--coordinates`:

### Option A: Direct Image Path
```bash
python3 skills/analyze_image_for_material/scripts/analyze_material.py --image <image_path_or_gcs_uri>
```

### Option B: Look up Image by Track ID in BigQuery
```bash
python3 skills/analyze_image_for_material/scripts/analyze_material.py --track-id <track_id>
```

### Option C: Look up Image by nearest Coordinates in BigQuery
```bash
python3 skills/analyze_image_for_material/scripts/analyze_material.py --coordinates <lat,lng>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID (falls back to `GOOGLE_CLOUD_PROJECT` env var).
- `--dataset` (Optional): BigQuery dataset name (falls back to `BIGQUERY_DATASET` env var).
- `--location` (Optional): Google Cloud region (defaults to `us-central1` or `GOOGLE_CLOUD_LOCATION` env var).
- `--model` (Optional): The Gemini model to use (defaults to `gemini-2.5-flash`).
- `--vertex` (Optional): Use Vertex AI (enabled by default).
- `--no-vertex` (Optional): Use standard Gemini Developer API (requires `GEMINI_API_KEY` env var).

## Expected Output Format

The script prints a structured JSON response to stdout representing the civil engineering analysis:
```json
{
  "road_surface_material": "Paved | Gravel | Mud | Dirt | Other",
  "confidence_score": "e.g., 95%",
  "visual_reasoning": "A short summary describing the visual evidence (e.g., aggregate texture, markings, joints) that led to the classification."
}
```
