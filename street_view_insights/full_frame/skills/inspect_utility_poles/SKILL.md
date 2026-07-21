---
name: inspect-utility-poles
description: Deep inspection of utility poles to classify materials, detect attachments (transformers, lights), and analyze structural leaning or damage.
---

# Inspect Utility Poles

Use this skill to inspect a street view photo containing a utility pole and classify its pole material, inventory its attachments, and assess its structural health (specifically listing if any leaning or damage is present).

## When to use

Use this skill when:
- You want to compile a structured asset inventory of attachments (riser caps, crossarms, street lights) on utility poles.
- You need to run a safety scan for pole structural damage (e.g. leaning poles or cracked timber).
- You want to classify pole materials (wood vs steel/concrete).

## Prerequisites

The python environment must have:
- `google-genai` and `pillow` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory:

### Option A: Local Image or gs:// URI
```bash
python3 street_view_insights/skills/inspect_utility_poles/scripts/inspect_pole.py --image <image_path_or_gcs_uri>
```

### Option B: Look up Observation in BigQuery
```bash
python3 street_view_insights/skills/inspect_utility_poles/scripts/inspect_pole.py --observation-id <observation_id>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--table` (Optional): BigQuery observations table name.
- `--location` (Optional): Google Cloud region (defaults to `global`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).

## Output Format

The script outputs a structured JSON description:
```json
{
  "pole_material": "Wood",
  "attachments": ["crossarms", "riser caps", "transformer"],
  "structural_condition": "Leaning",
  "lean_detected": true,
  "visual_findings_summary": "Pole exhibits a noticeable 5-10 degree lean to the left. The timber is heavily weathered with no visible decay."
}
```
