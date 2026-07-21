---
name: compare-full-frame-vs-cropped
description: Compare detection quality, token usage, and latency between cropped and full-frame street view images of physical assets.
---

# Compare Full-Frame vs Cropped

Use this skill to compare the quality and efficiency of analyzing a cropped/focused asset image vs the full-frame wide-angle view. This comparison helps audit cost vs detection completeness.

## When to use

Use this skill when:
- You want to benchmark if cropping an image saves token costs while preserving utility pole attachment classifications.
- You need to determine if a full-frame view is needed for detecting surrounding hazards (like foliage) compared to a tight crop.
- You want to run comparative latency tests for wide vs narrow views.

## Prerequisites

The python environment must have:
- `google-genai` and `pillow` libraries installed.
- Valid Google Cloud credentials to run Vertex AI queries.

## Instructions

Run the script from the repository root directory:

```bash
python3 street_view_insights/skills/compare_full_frame_vs_cropped/scripts/compare_views.py --cropped-image <cropped_image_path> --full-image <full_image_path>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--location` (Optional): Google Cloud region (defaults to `global`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).

## Output Format

The script prints a structured JSON response containing:
- `cropped_view`: Time, token counts, and detailed visual asset audit.
- `full_frame_view`: Time, token counts, and detailed visual asset audit.
