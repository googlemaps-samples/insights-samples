#!/usr/bin/env python3
import os
import sys
import json
import argparse
import urllib.parse
from io import BytesIO
from PIL import Image
from google import genai
from google.genai import types

PROMPT = """You are an expert utility vegetation management & asset inspection engineer.
You are provided with multiple panoramic/full-frame street view images and cropped asset views of a utility pole.

Your task is to perform a comprehensive Vegetation Encroachment & Hazard Audit:
1. **Asset Verification**: Confirm if the cropped pole views across all observations represent the same physical utility asset.
2. **Vegetation & Tree Encroachment Analysis**:
   - Inspect surrounding trees, branches, and foliage relative to the pole and overhead lines.
   - Detect if branches are touching, overhanging, or dangerously close (< 10 feet) to wires or pole attachments.
   - Rate the overall Vegetation Hazard Level: [None | Low | Moderate | Severe / High Risk].
3. **Actionable Findings**: Provide a clear 1-3 sentence summary of vegetation hazards and recommended trimming actions.

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
    parser = argparse.ArgumentParser(description="Utility Pole Vegetation Encroachment Detection Skill.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--asset-id", help="Lookup all full-frame observations for an asset ID in BigQuery.")
    group.add_argument("--observation-id", help="Lookup a specific full-frame observation ID in BigQuery.")
    group.add_argument("--image", help="Direct full-frame local image path or gs:// URI.")
    
    parser.add_argument("--output", help="Optional output JSON file path.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"), 
                        help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), 
                        help="BigQuery dataset name.")
    parser.add_argument("--table", default="full_frame_observations_latest", 
                        help="BigQuery full-frame observations table name.")
    
    # Gemini model arguments
    parser.add_argument("--location", default="global", help="Google Cloud location/region.")
    parser.add_argument("--model", default="gemini-3.5-flash", help="Model to use (e.g. gemini-3.5-flash).")
    return parser.parse_args()

def convert_to_gs_uri(image_url: str) -> str:
    if image_url.startswith("gs://"):
        return image_url
    try:
        clean_url = image_url.replace("https://", "")
        domain, path = clean_url.split("/", 1)
        if "storage" in domain or "googleapis" in domain:
            path = urllib.parse.unquote(path)
            return f"gs://{path}"
    except Exception as e:
        print(f"Warning: failed to convert URL to GCS URI: {e}", file=sys.stderr)
    return image_url

def query_observations_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project if args.project != "YOUR_PROJECT_ID" else None)
    project_id = client_bq.project or args.project
    
    target_id = args.asset_id or args.observation_id
    print(f"Querying BigQuery table `{project_id}.{args.dataset}.{args.table}` for ID: {target_id}...", file=sys.stderr)
    
    query = f"""
    SELECT
        asset_id,
        observation_id,
        gcs_uri,
        bbox,
        detection_time
    FROM `{project_id}`.`{args.dataset}`.`{args.table}`
    WHERE asset_id = @id OR observation_id = @id
    ORDER BY detection_time ASC
    LIMIT 5
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", target_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No full-frame observations found in BigQuery for ID: {target_id}")
    return rows, project_id

def download_and_crop_asset(gcs_uri: str, bbox: dict, project_id: str):
    """Downloads image bytes from GCS and returns (full_image_bytes, cropped_image_bytes)."""
    from google.cloud import storage
    storage_client = storage.Client(project=project_id if project_id != "YOUR_PROJECT_ID" else None)
    
    if gcs_uri.startswith("gs://"):
        path_parts = gcs_uri[5:].split('/', 1)
        bucket = storage_client.bucket(path_parts[0])
        blob = bucket.blob(path_parts[1])
        full_bytes = blob.download_as_bytes()
    else:
        with open(gcs_uri, "rb") as f:
            full_bytes = f.read()
            
    img = Image.open(BytesIO(full_bytes)).convert("RGB")
    
    cropped_bytes = full_bytes
    if bbox and isinstance(bbox, dict) and 'lo' in bbox and 'hi' in bbox:
        try:
            xmin = bbox['lo']['x']
            ymin = bbox['lo']['y']
            xmax = bbox['hi']['x']
            ymax = bbox['hi']['y']
            
            w, h = img.size
            # Clamp coordinates
            left = max(0, min(xmin, w - 1))
            top = max(0, min(ymin, h - 1))
            right = max(left + 1, min(xmax, w))
            bottom = max(top + 1, min(ymax, h))
            
            cropped_img = img.crop((left, top, right, bottom))
            crop_buf = BytesIO()
            cropped_img.save(crop_buf, format="JPEG", quality=95)
            cropped_bytes = crop_buf.getvalue()
        except Exception as e:
            print(f"Warning: Bounding box crop failed ({e}), using full image.", file=sys.stderr)
            
    return full_bytes, cropped_bytes

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
        observations_data.append({"gcs_uri": gcs_uri, "bbox": None, "obs_id": "local"})
    else:
        try:
            rows, project_id = query_observations_from_bq(args)
            for row in rows:
                observations_data.append({
                    "gcs_uri": row.gcs_uri,
                    "bbox": row.bbox,
                    "obs_id": row.observation_id,
                    "asset_id": row.asset_id
                })
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    contents = [PROMPT, "\n\nBEGIN ASSET OBSERVATION IMAGES:\n"]
    
    for i, obs in enumerate(observations_data):
        gcs_uri = convert_to_gs_uri(obs["gcs_uri"])
        bbox = obs.get("bbox")
        obs_id = obs.get("obs_id")
        
        print(f"Loading observation {obs_id} ({gcs_uri})...", file=sys.stderr)
        try:
            full_bytes, cropped_bytes = download_and_crop_asset(gcs_uri, bbox, project_id)
            
            contents.append(f"\n--- Observation {i+1} (ID: {obs_id}) ---")
            contents.append("Full Frame View (Context):")
            contents.append(types.Part.from_bytes(data=full_bytes, mime_type="image/jpeg"))
            
            if bbox:
                contents.append("Cropped Bounding Box Asset View (Target Pole):")
                contents.append(types.Part.from_bytes(data=cropped_bytes, mime_type="image/jpeg"))
        except Exception as e:
            print(f"Error loading observation {obs_id}: {e}", file=sys.stderr)
            sys.exit(1)
            
    contents.append("\n\nEND OBSERVATIONS. Provide structured JSON audit.")
    
    try:
        response = client.models.generate_content(
            model=args.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        output_json = response.text
        print(output_json)
        
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as f:
                f.write(output_json)
            print(f"Successfully saved vegetation encroachment report to {args.output}", file=sys.stderr)
            
    except Exception as e:
        print(f"Encroachment analysis failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
