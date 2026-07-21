#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
from google import genai
from google.genai import types

LOGISTICS_SYSTEM_PROMPT = """Analyze this sequence of street view images for a logistics driver context.
Identify and describe the following features:
- **Obstructions to driveway entry / fences**: Describe any physical barriers.
- **Obstructions to street entry / Roadblocks**: Note any road blocks.
- **Signage**: Look for vehicle size/weight restrictions.
- **Gated entry**: State if a gate is present and its status (open/closed).

Provide your findings in a structured JSON format:
{
  "driveway_obstructions": "[Description of barriers/fences or None]",
  "street_obstructions": "[Description of road blocks or None]",
  "signage": "[Description of vehicle limits/signs or None]",
  "gated_entry": {
    "present": true/false,
    "status": "open/closed/unknown",
    "description": "[Details or None]"
  }
}
"""

def parse_args():
    parser = argparse.ArgumentParser(description="Analyze image sequence along a track for logistics obstacles and gates.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", help="Comma-separated path to local image files or gs:// URIs.")
    group.add_argument("--track-id", help="Lookup track ID in BigQuery to find the image sequence.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "home_depot_full_scene"), help="BigQuery dataset name.")
    parser.add_argument("--tracks-table", default="tracks_unnested", help="BigQuery tracks table name.")
    parser.add_argument("--urls-table", default="urls_new", help="BigQuery URLs table name.")
    
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

def query_images_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID.")
        
    print(f"Querying BQ for track ID: {args.track_id}...", file=sys.stderr)
    query = f"""
    SELECT urls.signedUrl
    FROM `{project_id}.{args.dataset}.{args.tracks_table}` AS obs
    JOIN `{project_id}.{args.dataset}.{args.urls_table}` AS urls ON obs.observation0 = urls.observationId
    WHERE obs.trackId = @trackId
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("trackId", "STRING", args.track_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No image observations found in BigQuery for track ID: {args.track_id}")
    return [row.signedUrl for row in rows], project_id

def main():
    args = parse_args()
    project_id = args.project
    
    if args.image:
        image_paths = [path.strip() for path in args.image.split(",")]
        if not project_id:
            try:
                from google.cloud import bigquery
                client_bq = bigquery.Client()
                project_id = client_bq.project
            except Exception:
                pass
    else:
        try:
            image_paths, project_id = query_images_from_bq(args)
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
    # Resolve GenAI Client
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    # Load image parts
    contents = [LOGISTICS_SYSTEM_PROMPT, "\n\nBEGIN IMAGE SEQUENCE:\n"]
    
    for path in image_paths:
        clean_path = convert_to_gs_uri(path)
        try:
            if clean_path.startswith("gs://"):
                image_part = types.Part.from_uri(file_uri=clean_path, mime_type="image/jpeg")
            else:
                from PIL import Image
                from io import BytesIO
                img = Image.open(clean_path)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img_byte_arr = BytesIO()
                img.save(img_byte_arr, format='JPEG')
                image_part = types.Part.from_bytes(data=img_byte_arr.getvalue(), mime_type="image/jpeg")
            contents.append(image_part)
        except Exception as e:
            print(f"Error loading image {clean_path}: {e}", file=sys.stderr)
            sys.exit(1)
            
    contents.append("\n\nEND IMAGE SEQUENCE. Provide the JSON analysis.")
    
    # Run generation
    try:
        response = client.models.generate_content(
            model=args.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        print(response.text)
    except Exception as e:
        print(f"Model generation failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
