---
name: analyze-logistics-barriers
description: Analyze street view image sequences along a path for logistics driver barriers (driveway gates, fences, roadblocks, parking signage).
---

# Analyze Logistics Barriers

Use this skill to inspect a sequence of street-level images along a travel path (or track) and identify potential roadblocks, driveway obstructions, fencing, gate statuses, and restricted-parking/size limit signs.

## When to use

Use this skill when:
- You are planning a delivery route and need to verify if the destination has a gate or height limit.
- You want to identify physical barriers that might prevent a truck from entering a driveway.
- You have a BigQuery `track_id` representing a vehicle drive path and want to audit the path for restrictions.

## Prerequisites

The python environment must have:
- `google-genai` and `google-cloud-bigquery` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory. You must specify either `--image` or `--track-id`:

### Option A: Local Image Sequence (comma-separated) or gs:// URIs
```bash
python3 street_view_insights/skills/analyze_logistics_barriers/scripts/analyze_logistics_barriers.py --image <image1_path,image2_path>
```

### Option B: Look up Track in BigQuery
```bash
python3 street_view_insights/skills/analyze_logistics_barriers/scripts/analyze_logistics_barriers.py --track-id <track_id>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--tracks-table` (Optional): BigQuery tracks table name.
- `--location` (Optional): Google Cloud region (defaults to `global`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).

## Output Format

The script outputs a structured JSON description:
```json
{
  "driveway_obstructions": "e.g., Chain-link fence along lawn",
  "street_obstructions": "None",
  "signage": "No parking on school days sign",
  "gated_entry": {
    "present": true,
    "status": "open",
    "description": "Double swing gate is open"
  }
}
```
