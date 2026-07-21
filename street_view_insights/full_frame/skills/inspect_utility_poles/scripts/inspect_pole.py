#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
import json
from google import genai
from google.genai import types

POLE_INSPECTION_PROMPT = """You are an expert utility inspection engineer. Analyze the provided image of a utility pole:
1. **Identify Attachments**: List all attachments, including transformers, crossarms, lights, riser caps, cables, and signs.
2. **Determine Structural Material**: Identify if the pole is wood, steel, concrete, or fiberglass.
3. **Assess Leaning/Condition**: Look for visible lean angles, structural decay, splits, rust, or damage.
4. **attachment_bbox**: Locate the main pole structure and key attachments using bounding boxes.

Provide your findings in a structured JSON format:
{
  "pole_material": "Wood/Steel/Concrete/Fiberglass",
  "attachments": ["list_of_attachments"],
  "structural_condition": "Good/Leaning/Damaged/Decayed",
  "lean_detected": true/false,
  "visual_findings_summary": "1-3 sentences summarizing structural details."
}
"""

def parse_args():
    parser = argparse.ArgumentParser(description="Inspect a utility pole for attachments, materials, and leaning condition.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", help="Path to local image file or gs:// URI.")
    group.add_argument("--observation-id", help="Lookup observation ID in BigQuery to find the image URI.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), help="BigQuery dataset name.")
    parser.add_argument("--table", default="full_frame_observations_latest", help="BigQuery observations table name.")
    
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

def query_image_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID.")
        
    print(f"Querying BQ for observation: {args.observation_id}...", file=sys.stderr)
    query = f"""
    SELECT gcs_uri
    FROM `{project_id}.{args.dataset}.{args.table}`
    WHERE observation_id = @observationId OR asset_id = @observationId
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("observationId", "STRING", args.observation_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No image observation found for ID: {args.observation_id}")
    return rows[0].gcs_uri, project_id

def main():
    args = parse_args()
    project_id = args.project
    
    if args.image:
        image_uri = args.image
        if not project_id:
            try:
                from google.cloud import bigquery
                client_bq = bigquery.Client()
                project_id = client_bq.project
            except Exception:
                pass
    else:
        try:
            image_uri, project_id = query_image_from_bq(args)
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
    gcs_uri = convert_to_gs_uri(image_uri)
    print(f"Target GCS URI: {gcs_uri}", file=sys.stderr)
    
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    try:
        if gcs_uri.startswith("gs://"):
            image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")
        else:
            from PIL import Image
            from io import BytesIO
            img = Image.open(gcs_uri)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='JPEG')
            image_part = types.Part.from_bytes(data=img_byte_arr.getvalue(), mime_type="image/jpeg")
            
        print("Sending inspection request to Gemini...", file=sys.stderr)
        response = client.models.generate_content(
            model=args.model,
            contents=[image_part, POLE_INSPECTION_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        print(response.text)
    except Exception as e:
        print(f"Pole inspection failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
