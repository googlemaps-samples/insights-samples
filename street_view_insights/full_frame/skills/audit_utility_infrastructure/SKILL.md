---
name: audit-utility-infrastructure
description: Perform visual audits on utility poles/infrastructure using either cropped or full-frame images. Reconciles observations over time or benchmarks cropped vs full-frame views.
---

# Audit Utility Infrastructure

Use this skill to audit utility pole attachments, materials, and conditions. It supports both cropped (object-level) and full-frame (scene-level) images, adapting prompts based on input data-type.

It supports three main tasks:
1. `inspect`: Perform detailed inspection of a pole for attachments, timber/steel materials, and leans or damage.
2. `reconcile`: Retrieve chronologically grouped observations for the same asset from BigQuery and generate a unified state history.
3. `compare`: Benchmark crop vs full-frame token counts, latencies, and visual audits.

## Prerequisites

The python environment must have:
- `google-genai`, `pandas-gbq`, and `pillow` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory, specifying the task with `--task`:

### Task 1: Utility Pole Audit (Cropped or Full-Frame)
```bash
python3 street_view_insights/full_frame/skills/audit_utility_infrastructure/scripts/run_audit.py --task inspect --observation-id <observation_id>
```

#### Explicit Data-Type Selection
By default, the script auto-detects if the input image is cropped or full-frame. You can explicitly override this with `--data-type`:
```bash
python3 street_view_insights/full_frame/skills/audit_utility_infrastructure/scripts/run_audit.py --task inspect --image <crop_image.jpg> --data-type cropped
```

### Task 2: Reconcile Chronological Observations
```bash
python3 street_view_insights/full_frame/skills/audit_utility_infrastructure/scripts/run_audit.py --task reconcile --asset-id <asset_id>
```

### Task 3: Compare Cropped vs Full-Frame Efficiency
```bash
python3 street_view_insights/full_frame/skills/audit_utility_infrastructure/scripts/run_audit.py --task compare --cropped-image <cropped_pole.jpg> --full-image <full_pole.jpg>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--table` (Optional): BigQuery observations table name.
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).
