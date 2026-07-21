---
name: analyze-full-frame-assets
description: Perform contextual and visual analysis of road assets (e.g. utility poles, signs) by combining full-frame wide view and cropped asset zoom-in analysis.
---

# Analyze Full-Frame Assets

Use this skill to audit a roadside asset and its surroundings. The skill takes a wide-angle full-frame street view image and its asset bounding box (either directly or queried from BigQuery by `asset_id`), crops the asset out of the image, and then performs a double-pass Gemini audit:
1. Classification of the asset's sub-type, materials, and damage conditions.
2. Contextual scene understanding of the street environment (road type, foliage, hazards, weather).

## When to use

Use this skill when:
- You want to identify damage (rust, cracks, leaning) on specific utility poles or street attachments.
- You need to log environmental context (e.g. foliage density, road type) around a physical asset.
- You have an asset ID and want to fetch its image and bounding box automatically from BigQuery.

## Prerequisites

The python environment must have:
- `google-genai`, `pandas-gbq`, and `pillow` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory:

### Option A: Local Image or gs:// URI with manual bounding box
```bash
python3 street_view_insights/skills/analyze_full_frame_assets/scripts/analyze_full_frame.py --image <image_path_or_gcs_uri> --bbox <ymin,xmin,ymax,xmax>
```

### Option B: Look up Asset in BigQuery
```bash
python3 street_view_insights/skills/analyze_full_frame_assets/scripts/analyze_full_frame.py --asset-id <asset_id>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--table` (Optional): BigQuery observations table name.
- `--location` (Optional): Google Cloud region (defaults to `global`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).

## Outputs

The script prints a structured JSON response containing:
- `asset_analysis`: Details of the cropped asset.
- `contextual_analysis`: Contextual street details of the full wide-angle view.
It also saves `original_image.jpg` and `cropped_asset.jpg` in the current working directory.
