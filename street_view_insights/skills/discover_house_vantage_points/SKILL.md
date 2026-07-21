---
name: discover-house-vantage-points
description: Retrieve and select optimal street view vantage points facing target coordinates, and cluster visual observations by Property ID.
---

# Discover House Vantage Points

Use this skill to spatially search BigQuery for street view image frames that face a target GPS coordinate within a Field of View (FOV) threshold, invoke Gemini to select the best visual vantage points, and cluster them into properties based on architectural signatures.

## When to use

Use this skill when:
- You have a target geographic coordinate and want to look up all street-level views of the building.
- You want to identify which specific street view camera frames (e.g. front_left, left, right) have direct line of sight to a building.
- You want to perform automatic visual property clustering for tax or parcel auditing.

## Prerequisites

The python environment must have:
- `google-genai`, `pandas-gbq`, and `geopy` libraries installed.
- Valid Google Cloud credentials to run BigQuery and Vertex AI queries.

## Instructions

Run the script from the repository root directory by passing the target coordinates:

```bash
python3 street_view_insights/skills/discover_house_vantage_points/scripts/discover_vantage_points.py --coordinates <lat,lng>
```

### Optional Arguments
- `--project` (Optional): Google Cloud project ID.
- `--dataset` (Optional): BigQuery dataset name.
- `--tracks-table` (Optional): BigQuery tracks table name.
- `--location` (Optional): Google Cloud region (defaults to `global`).
- `--model` (Optional): Gemini model to use (defaults to `gemini-3.5-flash`).

## Output Format

The script prints a structured JSON object grouping the selected image metadata under distinct Property IDs:
```json
{
  "prop_1": {
    "images": [
      {
        "metadata": {
          "observation_id": "o1:1OdzKq8u3eOsyilfXgnFow_4:5001ee",
          "spatial_context": {
            "heading": 243.5,
            "view": "left",
            "gps": [32.6721, -96.8024],
            "dist": 14.2
          }
        },
        "image_link": "https://storage.googleapis.com/...",
        "gs_link": "gs://..."
      }
    ],
    "signature": [
      "White brick facade",
      "Black shutters on double-hung windows"
    ]
  }
}
```
