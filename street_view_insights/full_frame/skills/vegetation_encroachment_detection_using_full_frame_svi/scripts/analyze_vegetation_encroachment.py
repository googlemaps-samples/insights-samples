#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import urllib.parse
from google import genai
from google.genai import types

_BQ_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,29}(?::[a-z0-9-]+)?$")
_BQ_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]{1,128}$")
ALLOWED_DATASETS = frozenset(
    {
        "imagery_insights___us",
        "imagery_insights___eu",
        *(
            x.strip()
            for x in os.getenv("SVI_ALLOWED_DATASETS", "").split(",")
            if x.strip()
        ),
    }
)
ALLOWED_TABLES = frozenset({"full_frame_observations_latest", "cropped_observations_latest"})
MAX_QUERY_BYTES_BILLED = 2_000_000_000

PROMPT = """You are an expert utility vegetation management & asset inspection engineer.
You are provided with full-frame street view images from Google Cloud Storage along with target asset bounding box coordinates from BigQuery.

Your task is to perform a remote Vegetation Encroachment & Hazard Audit:
1. **Target Asset Bounding Box**: Use the provided bounding box coordinates [xmin, ymin, xmax, ymax] to focus on the target utility pole within the full-frame scene. If needed, write and run Python code execution to inspect crop coordinates.
2. **Multi-Observation Asset Verification**: Confirm if the target utility pole across all provided image URIs represents the exact same physical asset.
3. **Vegetation Encroachment & Clearance Audit**:
   - Inspect surrounding trees, branches, and foliage relative to the pole and overhead lines.
   - Detect if branches are touching, overhanging, or dangerously close (< 10 feet) to wires or pole attachments.
   - Rate the overall Vegetation Hazard Level: [None | Low | Moderate | Severe / High Risk].
4. **Actionable Findings**: Provide a clear summary of vegetation hazards and recommended trimming actions.

Return your response strictly in structured JSON format matching this schema:
{
  "asset_id": "[Asset ID or resolved ID]",
  "same_asset_verification": {
    "is_same_asset": true/false,
    "reasoning": "[Brief justification]"
  },
  "vegetation_hazard": {
    "hazard_level": "[None | Low | Moderate | Severe]",
    "wire_contact_detected": true/false,
    "encroaching_tree_species_or_type": "[Description of encroaching trees/foliage or None]",
    "proximity_details": "[Description of clearance distance and overhang]"
  },
  "recommended_action": "[No Action Required | Routine Trimming | Priority Trim | Emergency Clearance]",
  "visual_audit_summary": "[1-3 sentence summary of audit findings]"
}
"""

def parse_args():
    parser = argparse.ArgumentParser(description="Cloud-Native Utility Pole Vegetation Encroachment Detection Skill.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--asset-id", help="Lookup all full-frame observations for an asset ID in BigQuery.")
    group.add_argument("--observation-id", help="Lookup a specific full-frame observation ID in BigQuery.")
    group.add_argument("--image", help="Direct gs:// URI to full-frame image in Google Cloud Storage.")
    
    parser.add_argument("--output", help="Optional output JSON file path.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"), 
                        help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), 
                        help="BigQuery dataset name.")
    parser.add_argument("--table", default="full_frame_observations_latest", 
                        help="BigQuery full-frame observations table name.")
    
    # Gemini model arguments
    parser.add_argument("--location", default="global", help="Google Cloud location/region (global, us, or eu).")
    parser.add_argument("--model", default="gemini-4-hydrogen", help="Model to use (defaults to gemini-4-hydrogen).")
    return parser.parse_args()

def convert_to_gs_uri(image_url: str) -> str:
    if image_url.startswith("gs://"):
        return image_url
    try:
        parsed = urllib.parse.urlparse(image_url)
        if parsed.scheme == "https" and parsed.netloc in {
            "storage.googleapis.com",
            "storage.cloud.google.com",
        }:
            path = urllib.parse.unquote(parsed.path.lstrip("/"))
            if path and "/" in path:
                return f"gs://{path}"
    except Exception as e:
        print(f"Warning: failed to convert URL to GCS URI: {e}", file=sys.stderr)
    return image_url

def query_observations_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project if args.project != "YOUR_PROJECT_ID" else None)
    project_id = (client_bq.project or args.project or "").strip()
    dataset_id = (args.dataset or "").strip()
    table_id = (args.table or "").strip()
    if not _BQ_PROJECT_RE.fullmatch(project_id):
        raise ValueError(f"Invalid Google Cloud project ID: {project_id!r}")
    if not _BQ_IDENTIFIER_RE.fullmatch(dataset_id) or dataset_id not in ALLOWED_DATASETS:
        raise ValueError(
            f"Dataset {dataset_id!r} must match an allowlisted dataset {sorted(ALLOWED_DATASETS)}"
        )
    if not _BQ_IDENTIFIER_RE.fullmatch(table_id) or table_id not in ALLOWED_TABLES:
        raise ValueError(
            f"Table {table_id!r} must be one of {sorted(ALLOWED_TABLES)}"
        )
    
    target_id = args.asset_id or args.observation_id
    print(f"Querying BigQuery table `{project_id}.{dataset_id}.{table_id}` for ID: {target_id}...", file=sys.stderr)
    
    query = f"""
    SELECT
        asset_id,
        observation_id,
        gcs_uri,
        bbox,
        detection_time
    FROM `{project_id}`.`{dataset_id}`.`{table_id}`
    WHERE asset_id = @id OR observation_id = @id
    ORDER BY detection_time ASC
    LIMIT 5
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", target_id)],
        maximum_bytes_billed=MAX_QUERY_BYTES_BILLED,
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No full-frame observations found in BigQuery for ID: {target_id}")
    return rows, project_id

def main():
    args = parse_args()
    project_id = args.project
    
    observations_data = []
    if args.image:
        gcs_uri = convert_to_gs_uri(args.image)
        if project_id == "YOUR_PROJECT_ID":
            try:
                from google.cloud import bigquery
                client_bq = bigquery.Client()
                project_id = client_bq.project
            except Exception:
                pass
        observations_data.append({"gcs_uri": gcs_uri, "bbox": None, "obs_id": "remote"})
    else:
        try:
            rows, project_id = query_observations_from_bq(args)
            for row in rows:
                observations_data.append({
                    "gcs_uri": convert_to_gs_uri(row.gcs_uri),
                    "bbox": row.bbox,
                    "obs_id": row.observation_id,
                    "asset_id": row.asset_id
                })
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    contents = [PROMPT, "\n\nREMOTE GCS OBSERVATION IMAGES & BOUNDING BOXES:\n"]
    
    for i, obs in enumerate(observations_data):
        gcs_uri = obs["gcs_uri"]
        bbox = obs.get("bbox")
        obs_id = obs.get("obs_id")
        
        contents.append(f"\n--- Observation {i+1} (ID: {obs_id}) ---")
        contents.append(f"GCS URI: {gcs_uri}")
        if bbox and isinstance(bbox, dict) and 'lo' in bbox and 'hi' in bbox:
            contents.append(f"Target Bounding Box (xmin, ymin, xmax, ymax): [{bbox['lo']['x']}, {bbox['lo']['y']}, {bbox['hi']['x']}, {bbox['hi']['y']}]")
            
        # Pass GCS URI directly without downloading local bytes
        try:
            image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")
            contents.append(image_part)
        except Exception as e:
            print(f"Error attaching GCS URI {gcs_uri}: {e}", file=sys.stderr)
            sys.exit(1)
            
    contents.append("\n\nEND OBSERVATIONS. Analyze GCS images and target bounding boxes remotely and return structured JSON audit.")
    
    try:
        response = client.models.generate_content(
            model=args.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        output_text_parts = [part.text for part in response.candidates[0].content.parts if part.text]
        output_json = "\n".join(output_text_parts).strip()
        print(output_json)
        
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as f:
                f.write(output_json)
            print(f"Successfully saved vegetation encroachment report to {args.output}", file=sys.stderr)
            
    except Exception as e:
        print(f"Remote encroachment analysis failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
