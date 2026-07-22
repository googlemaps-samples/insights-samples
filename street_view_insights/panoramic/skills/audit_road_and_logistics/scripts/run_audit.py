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
    group.add_argument("--track-id", help="Lookup capture/pano/observation ID in BigQuery.")
    group.add_argument("--coordinates", help="Lookup nearest observation by coordinates in format 'lat,lng'.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID"), 
                        help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), 
                        help="BigQuery dataset name.")
    parser.add_argument("--table", default="pano_observations_latest", 
                        help="BigQuery table name.")
    
    # Gemini model arguments
    parser.add_argument("--location", default="global", help="Google Cloud location/region.")
    parser.add_argument("--model", default="gemini-3.5-flash", help="Model to use (e.g. gemini-3.5-flash).")
    return parser.parse_args()

def query_images_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project or args.project
    
    if args.track_id:
        print(f"Querying BQ table `{project_id}.{args.dataset}.{args.table}` for ID: {args.track_id}...", file=sys.stderr)
        query = f"""
        SELECT gcs_uri 
        FROM `{project_id}.{args.dataset}.{args.table}` 
        WHERE capture_id = @id OR pano_id = @id OR observation_id = @id 
        LIMIT 5
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", args.track_id)])
        rows = list(client_bq.query(query, job_config=job_config).result())
        if not rows:
            raise ValueError(f"No image observations found in BigQuery for ID: {args.track_id}")
        return [row.gcs_uri for row in rows], project_id
        
    elif args.coordinates:
        parts = args.coordinates.split(",")
        lat, lng = float(parts[0]), float(parts[1])
        print(f"Querying BQ table `{project_id}.{args.dataset}.{args.table}` near: {lat}, {lng}...", file=sys.stderr)
        query = f"""
        WITH nearest_pano AS (
          SELECT capture_id
          FROM `{project_id}.{args.dataset}.{args.table}`
          ORDER BY ST_DISTANCE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude), ST_GEOGPOINT(@lng, @lat)) ASC
          LIMIT 1
        )
        SELECT gcs_uri 
        FROM `{project_id}.{args.dataset}.{args.table}` 
        WHERE capture_id IN (SELECT capture_id FROM nearest_pano) 
        LIMIT 5
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("lng", "FLOAT64", lng),
            bigquery.ScalarQueryParameter("lat", "FLOAT64", lat)
        ])
        rows = list(client_bq.query(query, job_config=job_config).result())
        if not rows:
            raise ValueError(f"No image observations found near coordinates: {lat}, {lng}")
        return [row.gcs_uri for row in rows], project_id
        
    return [], project_id

def main():
    args = parse_args()
    project_id = args.project
    
    if args.image:
        image_paths = [path.strip() for path in args.image.split(",")]
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
    
    system_prompt = ROAD_MATERIAL_PROMPT if args.task == "material" else LOGISTICS_BARRIERS_PROMPT
    contents = [system_prompt, "\n\nBEGIN IMAGE SEQUENCE:\n"]
    
    for path in image_paths:
        try:
            if path.startswith("gs://"):
                image_part = types.Part.from_uri(file_uri=path, mime_type="image/jpeg")
            else:
                from PIL import Image
                img = Image.open(path)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img_byte_arr = BytesIO()
                img.save(img_byte_arr, format='JPEG')
                image_part = types.Part.from_bytes(data=img_byte_arr.getvalue(), mime_type="image/jpeg")
            contents.append(image_part)
        except Exception as e:
            print(f"Error loading image {path}: {e}", file=sys.stderr)
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
