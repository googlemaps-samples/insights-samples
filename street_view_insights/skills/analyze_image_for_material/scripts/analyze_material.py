#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import json
import argparse
import urllib.parse
from io import BytesIO
from google import genai
from google.genai import types
from PIL import Image

SURFACE_MATERIAL_SYSTEM_PROMPT = """Act as a civil engineering material analyst specializing in road surfaces. Your task is to analyze the provided sequence of Google Street View images and accurately identify the dominant road surface material present.

Your analysis must follow these steps to ensure accuracy:

1.  **Identify Road Surface Area**: Clearly delineate the primary road surface in the images, ignoring sidewalks, shoulders, or surrounding terrain.
2.  **Visual Evidence Extraction**: For the identified road surface, describe the visual cues that indicate its material type across the sequence of images. Focus specifically on:
    *   **Texture & Micro-structure**: Look for characteristics such as:
        *   **Paved**: Smooth, uniform, often dark or light grey. May show aggregate, cracks, patches, or lane markings. If asphalt, a granular, somewhat coarse texture. If concrete, a finer, often broom-finished texture with expansion joints.
        *   **Gravel**: Loose, irregularly shaped stones of varying sizes with visible gaps and an uneven surface. Often exhibits tire tracks or displacement.
        *   **Mud**: Soft, wet, or dried soil, often with ruts, puddles, or deep impressions from vehicles. Can vary widely in color and consistency.
        *   **Dirt**: Unpaved, dry, compacted soil. Less uniform than paved, but more stable than mud, often exhibiting dust or tire marks.
    *   **Reflectance & Specularity**: Observe how light interacts with the surface. Is it matte (dirt, some mud), somewhat reflective (wet mud, new asphalt), or does it show clear highlights (wet paved roads, standing water)?
    *   **Contextual Cues**: Consider environmental factors such as surrounding vegetation, drainage, and road infrastructure (e.g., presence of road signs, guardrails nearby, but not directly on the road surface).

**Output Format**:
Provide your findings in a structured JSON format:
{
  "road_surface_material": "[Material classification: Paved, Gravel, Mud, Dirt, or Other]",
  "confidence_score": "[0-100%]",
  "visual_reasoning": "[1-3 sentences describing specific visual evidence supporting the classification, e.g., 'Surface exhibits uniform dark gray color with visible aggregate and clear lane markings, consistent with asphalt pavement.']"
}

**Important Considerations**:
*   Focus exclusively on the material directly comprising the main driving surface.
*   Ignore temporary conditions like standing water or debris unless they are definitive indicators of the underlying road material.
*   If the material is ambiguous or mixed, classify based on the dominant type and note ambiguity in reasoning.
"""

def parse_args():
    parser = argparse.ArgumentParser(description="Analyze an image sequence or BigQuery location to detect road surface material.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", help="Path to local image file(s) or gs:// URI(s), comma-separated.")
    group.add_argument("--track-id", help="Lookup track ID in BigQuery to find the image sequence.")
    group.add_argument("--coordinates", help="Lookup nearest track by coordinates in format 'lat,lng'.")
    
    # BigQuery connection arguments (read from args or fallback to env vars / defaults)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), 
                        help="Google Cloud project ID. (Defaults to Application Default Credentials)")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "home_depot_full_scene"), 
                        help="BigQuery dataset name. (Default: home_depot_full_scene)")
    parser.add_argument("--tracks-table", default=os.getenv("BIGQUERY_TRACKS_TABLE", "tracks"), 
                        help="BigQuery tracks table name. (Default: tracks)")
    parser.add_argument("--urls-table", default=os.getenv("BIGQUERY_URLS_TABLE", "urls_new"), 
                        help="BigQuery URLs table name. (Default: urls_new)")
    
    # Gemini model arguments
    parser.add_argument("--location", default=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"), help="Google Cloud location/region.")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Model to use (e.g. gemini-2.5-flash).")
    parser.add_argument("--vertex", action="store_true", default=True, help="Use Vertex AI endpoint.")
    parser.add_argument("--no-vertex", dest="vertex", action="store_false", help="Use standard Gemini API instead of Vertex AI.")
    return parser.parse_args()

def convert_to_gs_uri(image_url: str) -> str:
    """Format HTTP signed GCS url into gs:// URI format if possible."""
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
    """Check if a table or view exists in the BigQuery dataset."""
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
    """Connect to BigQuery and query for the image signedUrl based on inputs."""
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID from environment, default credentials or arguments.")
    
    # Check if the dataset has the new single-table pano schema
    is_new_schema = check_table_exists(client_bq, project_id, args.dataset, "pano_observations_latest")
    
    if is_new_schema:
        print(f"Detected Pano Observations schema in dataset '{args.dataset}'. Using single-table query...", file=sys.stderr)
        pano_table = "pano_observations_latest"
        
        if args.track_id:
            print(f"Querying BQ for track: {args.track_id} (Project: {project_id})...", file=sys.stderr)
            query = f"""
            SELECT
              gcs_uri
            FROM
              `{project_id}`.`{args.dataset}`.`{pano_table}`
            WHERE
              capture_id = @trackId OR pano_id = @trackId
            LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("trackId", "STRING", args.track_id)]
            )
            rows = list(client_bq.query(query, job_config=job_config).result())
            if not rows:
                raise ValueError(f"No image observations found in BigQuery for track ID: {args.track_id}")
            return [row.gcs_uri for row in rows], project_id
            
        elif args.coordinates:
            parts = args.coordinates.split(",")
            if len(parts) != 2:
                raise ValueError("Coordinates must be in format 'lat,lng'")
            lat = float(parts[0])
            lng = float(parts[1])
            print(f"Querying BQ for nearest track to: {lat}, {lng} (Project: {project_id})...", file=sys.stderr)
            
            query = f"""
            WITH nearest_pano AS (
              SELECT
                capture_id
              FROM
                `{project_id}`.`{args.dataset}`.`{pano_table}`
              ORDER BY
                ST_DISTANCE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude), ST_GEOGPOINT(@lng, @lat)) ASC
              LIMIT 1
            )
            SELECT
              gcs_uri
            FROM
              `{project_id}`.`{args.dataset}`.`{pano_table}`
            WHERE
              capture_id IN (SELECT capture_id FROM nearest_pano)
            LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("lng", "FLOAT64", lng),
                    bigquery.ScalarQueryParameter("lat", "FLOAT64", lat)
                ]
            )
            rows = list(client_bq.query(query, job_config=job_config).result())
            if not rows:
                raise ValueError(f"No track or image observations found near coordinates: {lat}, {lng}")
            return [row.gcs_uri for row in rows], project_id
            
    else:
        # Fall back to the classic tracks / urls_new schema
        print(f"Using classic Tracks/URLs schema in dataset '{args.dataset}'...", file=sys.stderr)
        
        if args.track_id:
            print(f"Querying BQ for track: {args.track_id} (Project: {project_id})...", file=sys.stderr)
            query = f"""
            SELECT
              u.signedUrl,
              offset
            FROM
              `{project_id}`.`{args.dataset}`.`{args.tracks_table}` AS t,
              UNNEST(t.observationIds) AS observationId WITH OFFSET AS offset
            INNER JOIN
              `{project_id}`.`{args.dataset}`.`{args.urls_table}` AS u
            ON
              observationId = u.observationId
            WHERE
              t.trackId = @trackId
            ORDER BY
              offset ASC
            LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("trackId", "STRING", args.track_id)]
            )
            rows = list(client_bq.query(query, job_config=job_config).result())
            if not rows:
                raise ValueError(f"No image observations found in BigQuery for track ID: {args.track_id}")
            return [row.signedUrl for row in rows], project_id
            
        elif args.coordinates:
            parts = args.coordinates.split(",")
            if len(parts) != 2:
                raise ValueError("Coordinates must be in format 'lat,lng'")
            lat = float(parts[0])
            lng = float(parts[1])
            print(f"Querying BQ for nearest track to: {lat}, {lng} (Project: {project_id})...", file=sys.stderr)
            
            query = f"""
            WITH nearest_track AS (
              SELECT
                trackId,
                observationIds
              FROM
                `{project_id}`.`{args.dataset}`.`{args.tracks_table}`
              ORDER BY
                ST_DISTANCE(geometry, ST_GEOGPOINT(@lng, @lat)) ASC
              LIMIT 1
            )
            SELECT
              u.signedUrl,
              offset
            FROM
              nearest_track,
              UNNEST(observationIds) AS observationId WITH OFFSET AS offset
            INNER JOIN
              `{project_id}`.`{args.dataset}`.`{args.urls_table}` AS u
            ON
              observationId = u.observationId
            ORDER BY
              offset ASC
            LIMIT 5
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("lng", "FLOAT64", lng),
                    bigquery.ScalarQueryParameter("lat", "FLOAT64", lat)
                ]
            )
            rows = list(client_bq.query(query, job_config=job_config).result())
            if not rows:
                raise ValueError(f"No track or image observations found near coordinates: {lat}, {lng}")
            return [row.signedUrl for row in rows], project_id
            
    return [], project_id

def main():
    args = parse_args()
    
    # Resolve image paths (either directly provided or queried from BigQuery)
    image_paths = []
    project_id = args.project
    
    if args.image:
        image_paths = [path.strip() for path in args.image.split(",")]
        if args.vertex and not project_id:
            try:
                from google.cloud import bigquery
                client_bq = bigquery.Client()
                project_id = client_bq.project
            except Exception:
                pass
    else:
        if not args.dataset:
            print("Error: --dataset or BIGQUERY_DATASET env var must be set for BigQuery lookup.", file=sys.stderr)
            sys.exit(1)
        try:
            image_paths, project_id = query_images_from_bq(args)
            print(f"Retrieved {len(image_paths)} image URL(s) from BigQuery.", file=sys.stderr)
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
    # Initialize the Gemini Client
    try:
        if args.vertex:
            if not project_id:
                print("Error: Could not resolve Google Cloud project ID from environment, credentials or arguments for Vertex AI.", file=sys.stderr)
                sys.exit(1)
            print(f"Initializing Vertex AI Client (project: {project_id}, location: {args.location})...", file=sys.stderr)
            client = genai.Client(vertexai=True, project=project_id, location=args.location)
        else:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                print("Error: GEMINI_API_KEY env var must be set for standard API mode.", file=sys.stderr)
                sys.exit(1)
            print("Initializing standard Gemini Client...", file=sys.stderr)
            client = genai.Client(api_key=api_key)
            
    except Exception as e:
        print(f"Error initializing client: {e}", file=sys.stderr)
        sys.exit(1)

    # Load image parts
    contents = [SURFACE_MATERIAL_SYSTEM_PROMPT]
    contents.append("\n\nBEGIN IMAGE SEQUENCE:\n")
    
    for i, path in enumerate(image_paths):
        # Convert image path to GCS URI format if needed for Vertex AI
        clean_path = convert_to_gs_uri(path)
        try:
            if clean_path.startswith("gs://"):
                print(f"Loading GCS image URI: {clean_path}", file=sys.stderr)
                image_part = types.Part.from_uri(file_uri=clean_path, mime_type="image/jpeg")
            else:
                print(f"Loading local image file: {clean_path}", file=sys.stderr)
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
        print(f"Sending request to model: {args.model} with {len(image_paths)} images...", file=sys.stderr)
        response = client.models.generate_content(
            model=args.model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        
        # Print JSON output to stdout
        print(response.text)
        
    except Exception as e:
        print(f"Model generation failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
