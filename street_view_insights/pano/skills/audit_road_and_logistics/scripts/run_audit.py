#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
import json
from io import BytesIO
from google import genai
from google.genai import types

ROAD_MATERIAL_PROMPT = """Act as a civil engineering material analyst specializing in road surfaces. Your task is to analyze the provided sequence of Google Street View images and accurately identify the dominant road surface material present.

Your analysis must follow these steps to ensure accuracy:
1.  **Identify Road Surface Area**: Clearly delineate the primary road surface in the images, ignoring sidewalks, shoulders, or surrounding terrain.
2.  **Visual Evidence Extraction**: For the identified road surface, describe the visual cues that indicate its material type across the sequence of images. Focus specifically on:
    *   **Texture & Micro-structure**: Look for paved (asphalt/concrete), gravel, mud, or dirt textures.
    *   **Reflectance & Specularity**: Observe matte, reflective, or highlight characteristics.
    *   **Contextual Cues**: Surrounding vegetation, drainage, road signs.

**Output Format**:
Provide your findings in a structured JSON format:
{
  "road_surface_material": "[Material classification: Paved, Gravel, Mud, Dirt, or Other]",
  "confidence_score": "[0-100%]",
  "visual_reasoning": "[1-3 sentences describing specific visual evidence supporting the classification]"
}
"""

LOGISTICS_BARRIERS_PROMPT = """Analyze this sequence of street view images for a logistics driver context.
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
    parser = argparse.ArgumentParser(description="Consolidated Road and Logistics Audit Skill.")
    parser.add_argument("--task", required=True, choices=["material", "barriers"], 
                        help="The audit task to perform.")
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", help="Path to local image file(s) or gs:// URI(s), comma-separated.")
    group.add_argument("--track-id", help="Lookup track ID in BigQuery to find the image sequence.")
    group.add_argument("--coordinates", help="Lookup nearest track by coordinates in format 'lat,lng'.")
    
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

def check_table_exists(client_bq, project_id, dataset, table_name) -> bool:
    from google.cloud import bigquery
    query = f"""
    SELECT table_name 
    FROM `{project_id}`.`{dataset}`.INFORMATION_SCHEMA.TABLES 
    WHERE table_name = @table_name
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("table_name", "STRING", table_name)]
    )
    try:
        rows = list(client_bq.query(query, job_config=job_config).result())
        return len(rows) > 0
    except Exception:
        return False

def query_images_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID.")
        
    is_new_schema = check_table_exists(client_bq, project_id, args.dataset, "pano_observations_latest")
    
    if is_new_schema:
        print(f"Detected Pano Observations schema in dataset '{args.dataset}'...", file=sys.stderr)
        pano_table = "pano_observations_latest"
        
        if args.track_id:
            query = f"SELECT gcs_uri FROM `{project_id}`.`{args.dataset}`.`{pano_table}` WHERE capture_id = @trackId OR pano_id = @trackId LIMIT 5"
            job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("trackId", "STRING", args.track_id)])
            rows = list(client_bq.query(query, job_config=job_config).result())
            return [row.gcs_uri for row in rows], project_id
            
        elif args.coordinates:
            parts = args.coordinates.split(",")
            lat, lng = float(parts[0]), float(parts[1])
            query = f"""
            WITH nearest_pano AS (
              SELECT capture_id
              FROM `{project_id}`.`{args.dataset}`.`{pano_table}`
              ORDER BY ST_DISTANCE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude), ST_GEOGPOINT(@lng, @lat)) ASC
              LIMIT 1
            )
            SELECT gcs_uri FROM `{project_id}`.`{args.dataset}`.`{pano_table}` WHERE capture_id IN (SELECT capture_id FROM nearest_pano) LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("lng", "FLOAT64", lng),
                bigquery.ScalarQueryParameter("lat", "FLOAT64", lat)
            ])
            rows = list(client_bq.query(query, job_config=job_config).result())
            return [row.gcs_uri for row in rows], project_id
            
    else:
        print(f"Using classic Tracks/URLs schema in dataset '{args.dataset}'...", file=sys.stderr)
        if args.track_id:
            query = f"""
            SELECT u.signedUrl FROM `{project_id}`.`{args.dataset}`.`{args.tracks_table}` AS t,
            UNNEST(t.observationIds) AS observationId WITH OFFSET AS offset
            INNER JOIN `{project_id}`.`{args.dataset}`.`{args.urls_table}` AS u ON observationId = u.observationId
            WHERE t.trackId = @trackId ORDER BY offset ASC LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("trackId", "STRING", args.track_id)])
            rows = list(client_bq.query(query, job_config=job_config).result())
            return [row.signedUrl for row in rows], project_id
            
        elif args.coordinates:
            parts = args.coordinates.split(",")
            lat, lng = float(parts[0]), float(parts[1])
            query = f"""
            WITH nearest_track AS (
              SELECT trackId, observationIds
              FROM `{project_id}`.`{args.dataset}`.`{args.tracks_table}`
              ORDER BY ST_DISTANCE(geometry, ST_GEOGPOINT(@lng, @lat)) ASC
              LIMIT 1
            )
            SELECT u.signedUrl FROM nearest_track, UNNEST(observationIds) AS observationId WITH OFFSET AS offset
            INNER JOIN `{project_id}`.`{args.dataset}`.`{args.urls_table}` AS u ON observationId = u.observationId
            ORDER BY offset ASC LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("lng", "FLOAT64", lng),
                bigquery.ScalarQueryParameter("lat", "FLOAT64", lat)
            ])
            rows = list(client_bq.query(query, job_config=job_config).result())
            return [row.signedUrl for row in rows], project_id
            
    return [], project_id

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
            
    if not image_paths:
        print(json.dumps({"error": "No image observations found."}))
        sys.exit(0)
        
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    # Select prompt based on task
    system_prompt = ROAD_MATERIAL_PROMPT if args.task == "material" else LOGISTICS_BARRIERS_PROMPT
    contents = [system_prompt, "\n\nBEGIN IMAGE SEQUENCE:\n"]
    
    for path in image_paths:
        clean_path = convert_to_gs_uri(path)
        try:
            if clean_path.startswith("gs://"):
                image_part = types.Part.from_uri(file_uri=clean_path, mime_type="image/jpeg")
            else:
                from PIL import Image
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
