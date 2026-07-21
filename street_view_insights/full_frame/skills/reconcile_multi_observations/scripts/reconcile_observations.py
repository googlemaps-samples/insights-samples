#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
import json
import time
from google import genai
from google.genai import types

def parse_args():
    parser = argparse.ArgumentParser(description="Reconcile multiple street view observations of the same asset over time and views.")
    parser.add_argument("--asset-id", required=True, help="Target asset ID to reconcile in BigQuery.")
    
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

def query_asset_observations(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID.")
        
    print(f"Querying BQ for observations of asset ID: {args.asset_id}...", file=sys.stderr)
    query = f"""
    SELECT gcs_uri, bbox, detection_time, pano_id, heading, pitch
    FROM `{project_id}.{args.dataset}.{args.table}`
    WHERE asset_id = @assetId
    ORDER BY detection_time ASC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("assetId", "STRING", args.asset_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No observations found for asset ID: {args.asset_id}")
    return rows, project_id

def main():
    args = parse_args()
    
    try:
        observations, project_id = query_asset_observations(args)
        print(f"Found {len(observations)} observations for this asset.", file=sys.stderr)
    except Exception as e:
        print(f"Error querying BigQuery: {e}", file=sys.stderr)
        sys.exit(1)
        
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    reconcile_prompt = """You are provided with multiple photos showing different views of the exact same utility asset over time or from different angles.
    
    Your task is to reconcile these observations and construct a single source of truth report for this asset:
    1. Confirm if they are indeed the same physical asset (verify unique attachments or background features).
    2. Identify all attachments (transformers, lights, crossarms).
    3. Note if any change occurred in attachments or conditions between the observation timestamps.
    4. Provide a unified status (e.g. Active, Damaged, Removed).
    
    Please return your findings in structured JSON format:
    {
      "asset_id": "resolved_id",
      "same_asset_verification": "Yes/No with justification",
      "unified_attachments": ["transformer", "etc"],
      "chronological_changes": "Describe changes or 'None'",
      "unified_status": "Active/Damaged/Removed",
      "visual_audit_reasoning": "A concise summary of your logic."
    }
    """
    
    contents = [reconcile_prompt, "\n\nBEGIN OBSERVATION LIST:\n"]
    
    for i, obs in enumerate(observations):
        gcs_uri = convert_to_gs_uri(obs.gcs_uri)
        obs_time = obs.detection_time.isoformat() if hasattr(obs.detection_time, "isoformat") else str(obs.detection_time)
        print(f"Loading observation {i} from GCS: {gcs_uri} (Time: {obs_time})...", file=sys.stderr)
        
        contents.append(f"\n--- Observation {i} ---")
        contents.append(f"Timestamp: {obs_time}")
        contents.append(f"Camera Heading: {obs.heading} degrees, Pitch: {obs.pitch} degrees")
        
        try:
            image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")
            contents.append(image_part)
        except Exception as e:
            print(f"Error preparing GCS image {gcs_uri}: {e}", file=sys.stderr)
            sys.exit(1)
            
    contents.append("\n\nEND OF OBSERVATIONS. Provide the JSON reconciliation report.")
    
    try:
        print("Sending request to Gemini...", file=sys.stderr)
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
