#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
import json
import time
from io import BytesIO
from PIL import Image
from google import genai
from google.genai import types

CROPPED_INSPECTION_PROMPT = """You are an expert utility inspection engineer. Analyze the provided cropped/focused image of a utility pole:
1. **Identify Attachments**: List all attachments, including transformers, crossarms, lights, riser caps, cables, and signs.
2. **Determine Structural Material**: Identify if the pole is wood, steel, concrete, or fiberglass.
3. **Assess Leaning/Condition**: Look for visible lean angles, structural decay, splits, rust, or damage.

Provide your findings in a structured JSON format:
{
  "pole_material": "Wood/Steel/Concrete/Fiberglass",
  "attachments": ["list_of_attachments"],
  "structural_condition": "Good/Leaning/Damaged/Decayed",
  "lean_detected": true/false,
  "visual_findings_summary": "Summary of structural details."
}
"""

FULL_FRAME_INSPECTION_PROMPT = """You are an expert utility inspection engineer. Analyze the provided wide-angle full-frame street view image of a utility pole and its surroundings:
1. **Identify Attachments**: List all attachments on the pole (transformers, crossarms, lights, cables).
2. **Determine Structural Material**: Wood, steel, concrete, or fiberglass.
3. **Assess Leaning/Condition**: Leans, structural decay, splits, or rust.
4. **Scene/Contextual Audit**: Delineate road type (urban, suburban, highway), foliage encroachment, and nearby wire hazards.

Provide your findings in a structured JSON format:
{
  "pole_material": "Wood/Steel/Concrete/Fiberglass",
  "attachments": ["list_of_attachments"],
  "structural_condition": "Good/Leaning/Damaged/Decayed",
  "lean_detected": true/false,
  "road_type": "Urban/Suburban/Highway/Rural",
  "foliage_hazard": "None/Low/High",
  "visual_findings_summary": "Summary of structural details and surrounding environmental hazards."
}
"""

RECONCILE_PROMPT = """You are provided with multiple photos showing different views of the exact same utility asset over time or from different angles.

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

def parse_args():
    parser = argparse.ArgumentParser(description="Consolidated Utility Infrastructure Audit Skill.")
    parser.add_argument("--task", required=True, choices=["inspect", "reconcile", "compare"], 
                        help="Infrastructure audit task to perform.")
    parser.add_argument("--data-type", choices=["cropped", "full_frame", "auto"], default="auto",
                        help="Data format flag to adapt prompts (Default: auto-detect).")
    
    # Task inputs
    parser.add_argument("--image", help="Path to local image file or gs:// URI (required for 'inspect').")
    parser.add_argument("--asset-id", help="Target asset ID or observation ID for BigQuery lookup.")
    parser.add_argument("--cropped-image", help="Cropped image for comparison task.")
    parser.add_argument("--full-image", help="Full-frame image for comparison task.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "imagery-insights-sandbox"), 
                        help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), 
                        help="BigQuery dataset name.")
    
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

def query_image_from_bq(args, table_name):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project or args.project
        
    print(f"Querying BQ table `{project_id}.{args.dataset}.{table_name}` for: {args.asset_id}...", file=sys.stderr)
    query = f"""
    SELECT gcs_uri, bbox, asset_type
    FROM `{project_id}.{args.dataset}.{table_name}`
    WHERE observation_id = @id OR asset_id = @id OR pano_id = @id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", args.asset_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No image observation found in {table_name} for ID: {args.asset_id}")
    return rows[0].gcs_uri, rows[0].bbox, rows[0].asset_type, project_id

def query_asset_observations(args, table_name):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project or args.project
        
    query = f"""
    SELECT gcs_uri, detection_time, camera_pose.heading as heading, camera_pose.pitch as pitch
    FROM `{project_id}.{args.dataset}.{table_name}`
    WHERE asset_id = @id OR observation_id = @id
    ORDER BY detection_time ASC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", args.asset_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    return rows, project_id

def detect_data_type(image_path):
    if image_path.startswith("gs://"):
        return "full_frame"
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            if w / h > 1.5:
                return "full_frame"
    except Exception:
        pass
    return "cropped"

def main():
    args = parse_args()
    table_name = "cropped_observations_latest" if args.data_type == "cropped" else "full_frame_observations_latest"
    
    if args.task == "inspect":
        if not args.image and not args.asset_id:
            print("Error: Either --image or --asset-id is required for 'inspect' task.", file=sys.stderr)
            sys.exit(1)
            
        project_id = args.project
        bbox = None
        asset_type = "Unknown"
        
        if args.image:
            image_uri = args.image
        else:
            try:
                image_uri, bbox_raw, asset_type, project_id = query_image_from_bq(args, table_name)
            except Exception as e:
                print(f"Error querying BigQuery: {e}", file=sys.stderr)
                sys.exit(1)
                
        gcs_uri = convert_to_gs_uri(image_uri)
        
        data_type = args.data_type
        if data_type == "auto":
            data_type = detect_data_type(gcs_uri)
            
        system_prompt = FULL_FRAME_INSPECTION_PROMPT if data_type == "full_frame" else CROPPED_INSPECTION_PROMPT
        client = genai.Client(vertexai=True, project=project_id, location=args.location)
        
        try:
            if gcs_uri.startswith("gs://"):
                image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")
            else:
                img = Image.open(gcs_uri)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img_byte_arr = BytesIO()
                img.save(img_byte_arr, format='JPEG')
                image_part = types.Part.from_bytes(data=img_byte_arr.getvalue(), mime_type="image/jpeg")
                
            response = client.models.generate_content(
                model=args.model,
                contents=[image_part, system_prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            print(response.text)
        except Exception as e:
            print(f"Inspection failed: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.task == "reconcile":
        if not args.asset_id:
            print("Error: --asset-id is required for 'reconcile' task.", file=sys.stderr)
            sys.exit(1)
            
        try:
            observations, project_id = query_asset_observations(args, table_name)
            print(f"Found {len(observations)} observations for reconciliation.", file=sys.stderr)
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
        if not observations:
            print(json.dumps({"error": "No observations found for reconciliation."}))
            sys.exit(0)
            
        client = genai.Client(vertexai=True, project=project_id, location=args.location)
        
        contents = [RECONCILE_PROMPT, "\n\nBEGIN OBSERVATION LIST:\n"]
        for i, obs in enumerate(observations):
            gcs_uri = convert_to_gs_uri(obs.gcs_uri)
            obs_time = obs.detection_time.isoformat() if hasattr(obs.detection_time, "isoformat") else str(obs.detection_time)
            
            contents.append(f"\n--- Observation {i} ---")
            contents.append(f"Timestamp: {obs_time}")
            if hasattr(obs, "heading") and obs.heading:
                contents.append(f"Camera Heading: {obs.heading} degrees, Pitch: {obs.pitch} degrees")
            
            try:
                image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")
                contents.append(image_part)
            except Exception as e:
                print(f"Error preparing GCS image {gcs_uri}: {e}", file=sys.stderr)
                sys.exit(1)
                
        contents.append("\n\nEND OF OBSERVATIONS. Provide the JSON reconciliation report.")
        
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
            print(f"Reconciliation failed: {e}", file=sys.stderr)
            sys.exit(1)
            
    elif args.task == "compare":
        if not args.cropped_image or not args.full_image:
            print("Error: Both --cropped-image and --full-image are required for 'compare' task.", file=sys.stderr)
            sys.exit(1)
            
        project_id = args.project
        if not project_id:
            try:
                from google.cloud import bigquery
                client_bq = bigquery.Client()
                project_id = client_bq.project
            except Exception:
                pass
                
        client = genai.Client(vertexai=True, project=project_id, location=args.location)
        audit_prompt = """Identify and audit the utility pole or street asset present. List sub-attachments and notes on leaning or decay."""
        
        def run_inference(image_path, label):
            if image_path.startswith("gs://"):
                image_part = types.Part.from_uri(file_uri=image_path, mime_type="image/jpeg")
            else:
                img = Image.open(image_path)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img_byte_arr = BytesIO()
                img.save(img_byte_arr, format='JPEG')
                image_part = types.Part.from_bytes(data=img_byte_arr.getvalue(), mime_type="image/jpeg")
                
            start_time = time.time()
            resp = client.models.generate_content(model=args.model, contents=[image_part, audit_prompt])
            return resp.text, time.time() - start_time, resp.usage_metadata

        results = {}
        try:
            cropped_txt, cropped_time, cropped_usage = run_inference(args.cropped_image, "cropped")
            results["cropped_view"] = {"elapsed_seconds": round(cropped_time, 2), "input_tokens": cropped_usage.prompt_token_count, "output_tokens": cropped_usage.candidates_token_count, "analysis": cropped_txt}
        except Exception as e:
            results["cropped_view_error"] = str(e)
            
        time.sleep(3)
        
        try:
            full_txt, full_time, full_usage = run_inference(args.full_image, "full-frame")
            results["full_frame_view"] = {"elapsed_seconds": round(full_time, 2), "input_tokens": full_usage.prompt_token_count, "output_tokens": full_usage.candidates_token_count, "analysis": full_txt}
        except Exception as e:
            results["full_frame_view_error"] = str(e)
            
        print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
