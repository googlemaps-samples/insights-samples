# Road Surface Material Detection Skill

A reusable AI-native capability to identify and analyze dominant road surface materials (Paved, Gravel, Mud, Dirt) from street level or wide-angle imagery using Google Gemini models.

This skill is designed for civil engineering inspections, logistics planning, and infrastructure asset audits. It supports direct image files, remote GCS objects, and automatic BigQuery lookups via track IDs or geographical coordinates.

---

## Prerequisites

Before running the skill, ensure your environment has the required libraries:
```bash
pip install google-genai google-cloud-bigquery pillow
```

You must also authenticate with Google Cloud to execute Vertex AI and BigQuery requests:
```bash
gcloud auth application-default login
```

---

## Configuration

To run the script, configure your specific BigQuery project, dataset, and table details.

### Option A: Environment Variables (Recommended)
Set the following variables in your environment or a `.env` file:
```bash
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export BIGQUERY_DATASET="your_dataset_name"
export BIGQUERY_TRACKS_TABLE="your_tracks_table_name"
export BIGQUERY_URLS_TABLE="your_urls_table_name"
export GOOGLE_CLOUD_LOCATION="us-central1"
```

### Option B: Command Line Arguments
You can override the defaults on every execution using CLI parameters:
*   `--project`: Google Cloud project ID (billing/execution project)
*   `--dataset`: BigQuery dataset name
*   `--tracks-table`: BigQuery tracks table name
*   `--urls-table`: BigQuery URLs table name

---

## Usage Instructions

The skill script requires **exactly one** of the following input parameters:

### 1. Direct Image File or GCS URI
Runs visual analysis directly on a local file path or GCS URI:
```bash
python3 skills/analyze_image_for_material/scripts/analyze_material.py --image "path/to/image.jpg"
# Or GCS URI:
```
```bash
python3 skills/analyze_image_for_material/scripts/analyze_material.py --image "gs://my-bucket/road_pano_1.jpg"
```

### 2. BigQuery Track ID Lookup
Queries BigQuery for the track's observation images, resolves the storage URI, and runs analysis:
```bash
python3 skills/analyze_image_for_material/scripts/analyze_material.py --track-id "your_track_id"
```

### 3. Geographical Coordinates Lookup
Finds the nearest track to the given coordinates, extracts its camera observations, and analyzes the road surface material:
```bash
python3 skills/analyze_image_for_material/scripts/analyze_material.py --coordinates "33.1212321,-97.1833475"
```

---

## Other CLI Options

*   `--model`: Gemini model ID to use (Default: `gemini-2.5-flash`).
*   `--location`: Vertex AI region endpoint (Default: `us-central1`).
*   `--no-vertex`: Disables Vertex AI mode and uses standard Gemini Developer API (requires `GEMINI_API_KEY` to be set in environment).

---

## Output Schema

The tool prints a clean JSON block to stdout containing the classification:
```json
{
  "road_surface_material": "Paved | Gravel | Mud | Dirt | Other",
  "confidence_score": "0-100%",
  "visual_reasoning": "Description of texture, joints, aggregate, or reflectance details supporting the classification."
}
```
