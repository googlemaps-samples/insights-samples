#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
import json
from io import BytesIO
from PIL import Image
from google import genai
from google.cloud import bigquery, storage
from google.genai import types

SURFACE_MATERIAL_PROMPT = """Act as a civil engineering material analyst specializing in road and ground surfaces. 
Analyze the provided panoramic street view image, accurately identify the dominant surface material, and assess pavement condition.

Follow these evaluation steps:
1. **Identify Primary Ground Surface**: Delineate the main traveled road, pathway, or ground surface area.
2. **Granular Material Classification**: Classify into standard civil surface types:
   - Asphalt Concrete (Paved)
   - Portland Cement Concrete (Paved)
   - Pavers / Cobblestone
   - Unpaved Gravel
   - Dirt / Soil
   - Mud
3. **Pavement Condition Index (PCI) & Distress Detection**:
   - Pavement Health: Good | Fair | Poor | N/A (Unpaved)
   - Distresses Detected: Potholes, Alligator Cracking, Longitudinal Cracks, Rutting, Sealed Cracks, Ruts, None

Return your analysis strictly in structured JSON format matching this schema:
{
  "primary_material": "[Asphalt Concrete (Paved) | Portland Cement Concrete (Paved) | Pavers / Cobblestone | Unpaved Gravel | Dirt / Soil | Mud]",
  "pavement_condition": "[Good | Fair | Poor | N/A (Unpaved)]",
  "distress_features_detected": ["Potholes", "Alligator Cracking", "None"],
  "confidence_score": "High | Medium | Low",
  "visual_reasoning": "[1-3 sentences describing specific visual cues supporting the classification]"
}
"""

def parse_args():
    parser = argparse.ArgumentParser(description="Dedicated Surface Material Detection Skill.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", help="Path to local image file or gs:// URI.")
    group.add_argument("--observation-id", "--track-id", dest="observation_id", 
                       help="Lookup observation ID, pano ID, or capture ID in BigQuery.")
    group.add_argument("--coordinates", help="Lookup nearest observation by coordinates in format 'lat,lng'.")
    
    parser.add_argument("--output", help="Optional path to save JSON result file.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), 
                        help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), 
                        help="BigQuery dataset name.")
    parser.add_argument("--table", default="pano_observations_latest", 
                        help="BigQuery panoramic observations table name.")
    
    # Gemini model arguments
    parser.add_argument("--location", default="global", help="Google Cloud location/region.")
    parser.add_argument("--model", default="gemini-3.7-flash", help="Model to use (e.g. gemini-3.7-flash).")
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
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project or args.project
    
    if args.observation_id:
        print(f"Querying BigQuery table `{project_id}.{args.dataset}.{args.table}` for ID: {args.observation_id}...", file=sys.stderr)
        query = f"""
        SELECT gcs_uri 
        FROM `{project_id}`.`{args.dataset}`.`{args.table}` 
        WHERE observation_id = @id OR capture_id = @id OR pano_id = @id 
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", args.observation_id)])
        rows = list(client_bq.query(query, job_config=job_config).result())
        if not rows:
            raise ValueError(f"No image observation found in BigQuery for ID: {args.observation_id}")
        return rows[0].gcs_uri, project_id
        
    elif args.coordinates:
        parts = args.coordinates.split(",")
        lat, lng = float(parts[0]), float(parts[1])
        print(f"Querying BigQuery table `{project_id}.{args.dataset}.{args.table}` near: {lat}, {lng}...", file=sys.stderr)
        query = f"""
        SELECT gcs_uri 
        FROM `{project_id}`.`{args.dataset}`.`{args.table}` 
        ORDER BY ST_DISTANCE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude), ST_GEOGPOINT(@lng, @lat)) ASC
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("lng", "FLOAT64", lng),
            bigquery.ScalarQueryParameter("lat", "FLOAT64", lat)
        ])
        rows = list(client_bq.query(query, job_config=job_config).result())
        if not rows:
            raise ValueError(f"No image observation found near coordinates: {lat}, {lng}")
        return rows[0].gcs_uri, project_id
        
    return None, project_id

def main():
    args = parse_args()
    project_id = args.project
    
    if args.image:
        gcs_uri = convert_to_gs_uri(args.image)
    else:
        try:
            gcs_uri, project_id = query_image_from_bq(args)
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
    if not gcs_uri:
        print(json.dumps({"error": "No image observation found."}))
        sys.exit(1)
        
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    try:
        if gcs_uri.startswith("gs://"):
            try:
                bucket_name, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
                storage_client = storage.Client(project=project_id)
                bucket = storage_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                img_data = blob.download_as_bytes()
                image_part = types.Part.from_bytes(data=img_data, mime_type="image/jpeg")
            except Exception as download_err:
                print(f"Warning: GCS direct download failed ({download_err}), trying from_uri...", file=sys.stderr)
                image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")
        else:
            img = Image.open(gcs_uri)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='JPEG')
            image_part = types.Part.from_bytes(data=img_byte_arr.getvalue(), mime_type="image/jpeg")
    except Exception as e:
        print(f"Error loading image {gcs_uri}: {e}", file=sys.stderr)
        sys.exit(1)
        
    contents = [image_part, SURFACE_MATERIAL_PROMPT]
    
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
            print(f"Successfully saved surface material analysis to {args.output}", file=sys.stderr)
            
    except Exception as e:
        print(f"Material detection failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
