---
name: reconcile-multi-observations
description: Reconcile multiple chronological or spatial observations of the same road asset into a single unified audit history and status.
---

# Reconcile Multi-Observations

Use this skill to query BigQuery for all image observations of a target asset (e.g. utility pole, street sign) taken over time or from different street angles, send them to Gemini as a sequence, and construct a single reconciled report of the asset's history and attachments.

## When to use

Use this skill when:
- You have multiple observations of the same asset from different dates and want to verify if any change or damage occurred.
- You want to build a single consolidated inventory/state record from conflicting sensor detections.
- You want to verify if different detections at nearby coordinates actually point to the same physical asset.

## Prerequisites

The python environment must have:
- `google-genai` and `google-cloud-bigquery` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory:

```bash
python3 street_view_insights/skills/reconcile_multi_observations/scripts/reconcile_observations.py --asset-id <asset_id>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--table` (Optional): BigQuery observations table name.
- `--location` (Optional): Google Cloud region (defaults to `global`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).

## Output Format

The script prints a structured JSON response to stdout representing the reconciled history:
```json
{
  "asset_id": "resolved_id",
  "same_asset_verification": "Yes, verified by background brick structure and transformer serial",
  "unified_attachments": ["transformer", "light"],
  "chronological_changes": "Transformer was installed between 2026-01-10 and 2026-05-15",
  "unified_status": "Active",
  "visual_audit_reasoning": "Asset is active and intact."
}
```
