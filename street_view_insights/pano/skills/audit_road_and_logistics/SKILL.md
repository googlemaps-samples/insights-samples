---
name: audit-road-and-logistics
description: Perform road surface material audits and detect logistics barriers/roadblocks/gates along travel paths from panoramic street view sequences.
---

# Audit Road and Logistics

Use this skill to audit road conditions and identify drive path barriers. It supports two main tasks:
1. `material`: Detects road surface material (Paved, Gravel, Mud, Dirt).
2. `barriers`: Identifies driveway obstructions, fencing, gate presence/status, and restricted parking signage.

## Prerequisites

The python environment must have:
- `google-genai` and `google-cloud-bigquery` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory, specifying the task with `--task`:

### Task 1: Road Material Audit
```bash
python3 street_view_insights/pano/skills/audit_road_and_logistics/scripts/run_audit.py --task material --track-id <track_id>
```

### Task 2: Logistics Barrier Audit
```bash
python3 street_view_insights/pano/skills/audit_road_and_logistics/scripts/run_audit.py --task barriers --coordinates <lat,lng>
```

### Input Options
- `--image`: Direct local image path(s) or GCS URI(s).
- `--track-id`: Look up track in BigQuery.
- `--coordinates`: Look up nearest track by `lat,lng` in BigQuery.

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).
