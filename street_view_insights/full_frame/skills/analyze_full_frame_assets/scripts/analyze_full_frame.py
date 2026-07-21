#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
import json
from io import BytesIO
from PIL import Image, ImageDraw
from google import genai
from google.genai import types

def parse_args():
    parser = argparse.ArgumentParser(description="Analyze full-frame street view images and programmed crops for asset contextual audits.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", help="Path to local image file or gs:// URI.")
    group.add_argument("--asset-id", help="Lookup asset ID in BigQuery to find the image and bounding box.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), help="BigQuery dataset name.")
    parser.add_argument("--table", default="full_frame_observations_latest", help="BigQuery observations table name.")
    
    # Crop config
    parser.add_argument("--bbox", help="Optional custom bounding box in format 'ymin,xmin,ymax,xmax' (normalized 0-1000).")
    
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

def download_gcs_blob(gcs_uri, dest_file):
    from google.cloud import storage
    storage_client = storage.Client()
    path_parts = gcs_uri[5:].split('/', 1)
    bucket = storage_client.bucket(path_parts[0])
    blob = bucket.blob(path_parts[1])
    blob.download_to_filename(dest_file)

def query_asset_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID.")
        
    print(f"Querying BQ for asset: {args.asset_id}...", file=sys.stderr)
    query = f"""
    SELECT gcs_uri, bbox, asset_type
    FROM `{project_id}.{args.dataset}.{args.table}`
    WHERE asset_id = @assetId OR observation_id = @assetId
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("assetId", "STRING", args.asset_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No asset/observation found for ID: {args.asset_id}")
    return rows[0].gcs_uri, rows[0].bbox, rows[0].asset_type, project_id

def crop_image(img_path, bbox_dict):
    img = Image.open(img_path)
    w, h = img.size
    # Bounding box is typically in normalized format 0-1000 or raw coordinates
    # Let's extract coordinates: ymin, xmin, ymax, xmax
    # Assuming normalized coordinates in 0-1000:
    ymin = bbox_dict.get('ymin', bbox_dict.get('lo', {}).get('y', 0))
    xmin = bbox_dict.get('xmin', bbox_dict.get('lo', {}).get('x', 0))
    ymax = bbox_dict.get('ymax', bbox_dict.get('hi', {}).get('y', 1000))
    xmax = bbox_dict.get('xmax', bbox_dict.get('hi', {}).get('x', 1000))
    
    # If coordinates are 0-1000, scale them to image width and height
    left = int(xmin * w / 1000)
    top = int(ymin * h / 1000)
    right = int(xmax * w / 1000)
    bottom = int(ymax * h / 1000)
    
    # Ensure bounds are within image size
    left = max(0, min(left, w - 1))
    top = max(0, min(top, h - 1))
    right = max(left + 1, min(right, w))
    bottom = max(top + 1, min(bottom, h))
    
    return img.crop((left, top, right, bottom))

def main():
    args = parse_args()
    project_id = args.project
    bbox = None
    asset_type = "Unknown"
    
    if args.image:
        image_uri = args.image
        if not project_id:
            try:
                from google.cloud import bigquery
                client_bq = bigquery.Client()
                project_id = client_bq.project
            except Exception:
                pass
        if args.bbox:
            parts = [float(p) for p in args.bbox.split(",")]
            if len(parts) == 4:
                bbox = {"ymin": parts[0], "xmin": parts[1], "ymax": parts[2], "xmax": parts[3]}
    else:
        try:
            image_uri, bbox_raw, asset_type, project_id = query_asset_from_bq(args)
            if bbox_raw:
                # If bbox is a string or dict from BQ record
                if isinstance(bbox_raw, str):
                    bbox = json.loads(bbox_raw)
                else:
                    bbox = dict(bbox_raw)
        except Exception as e:
            print(f"Error querying BigQuery: {e}", file=sys.stderr)
            sys.exit(1)
            
    gcs_uri = convert_to_gs_uri(image_uri)
    
    # Download original image locally
    print("Downloading original image to original_image.jpg...", file=sys.stderr)
    try:
        if gcs_uri.startswith("gs://"):
            download_gcs_blob(gcs_uri, "original_image.jpg")
        else:
            import shutil
            shutil.copyfile(gcs_uri, "original_image.jpg")
    except Exception as e:
        print(f"Error downloading image: {e}", file=sys.stderr)
        sys.exit(1)
        
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    crop_saved = False
    if bbox:
        print(f"Cropping image based on coordinates: {bbox}...", file=sys.stderr)
        try:
            cropped = crop_image("original_image.jpg", bbox)
            cropped.save("cropped_asset.jpg")
            crop_saved = True
            print("Saved cropped_asset.jpg to current directory.", file=sys.stderr)
        except Exception as e:
            print(f"Cropping failed: {e}", file=sys.stderr)
            
    # Perform Multimodal Analysis
    print("Performing scene analysis with Gemini...", file=sys.stderr)
    
    # Prompt for cropped asset classification
    crop_prompt = f"Analyze the cropped image of a road asset (Type: {asset_type}). Classify its specific sub-type, physical material, and note any visual signs of wear, rust, or damage."
    # Prompt for full frame context
    context_prompt = "Analyze the wide-angle full-frame image. Identify: 1. Road classification (urban, suburban, highway). 2. Weather/lighting conditions. 3. Surroundings (residential, commercial, foliage). 4. Nearby physical hazards or attachments."
    
    results = {}
    
    # Run Crop classification
    if crop_saved:
        try:
            with open("cropped_asset.jpg", "rb") as f:
                crop_part = types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")
            resp_crop = client.models.generate_content(
                model=args.model,
                contents=[crop_part, crop_prompt]
            )
            results["asset_analysis"] = resp_crop.text
        except Exception as e:
            results["asset_analysis_error"] = str(e)
            
    # Run full frame context analysis
    try:
        with open("original_image.jpg", "rb") as f:
            full_part = types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")
        resp_full = client.models.generate_content(
            model=args.model,
            contents=[full_part, context_prompt]
        )
        results["contextual_analysis"] = resp_full.text
    except Exception as e:
        results["contextual_analysis_error"] = str(e)
        
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
