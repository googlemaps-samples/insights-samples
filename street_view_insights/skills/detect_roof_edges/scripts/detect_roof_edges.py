#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.parse
from google import genai
from google.genai import types
from PIL import Image

def parse_args():
    parser = argparse.ArgumentParser(description="Run agentic roof edge detection pipeline on an image or observation.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--image", help="Path to local image file or gs:// URI.")
    group.add_argument("--observation-id", help="Lookup observation ID in BigQuery to find the image URI.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "home_depot_full_scene"), help="BigQuery dataset name.")
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

def query_image_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID.")
        
    print(f"Querying BQ for observation: {args.observation_id}...", file=sys.stderr)
    query = f"""
    SELECT signedUrl
    FROM `{project_id}.{args.dataset}.{args.urls_table}`
    WHERE observationId = @observationId
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("observationId", "STRING", args.observation_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No image observation found for observation ID: {args.observation_id}")
    return rows[0].signedUrl, project_id

def download_gcs_blob(gcs_uri, dest_file):
    from google.cloud import storage
    storage_client = storage.Client()
    path_parts = gcs_uri[5:].split('/', 1)
    bucket = storage_client.bucket(path_parts[0])
    blob = bucket.blob(path_parts[1])
    blob.download_to_filename(dest_file)

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
            
    # Resolve GCS URI format
    gcs_uri = convert_to_gs_uri(image_uri)
    print(f"Target Image URI: {gcs_uri}", file=sys.stderr)
    
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
    
    # Step 1: Lens Distortion Correction
    print("\nStarting Lens Distortion Correction...", file=sys.stderr)
    DISTORTION_PROMPT = """Analyze the provided image for lens distortion, specifically barrel distortion.
    
    Instructions:
    1. You MUST use Python code execution (cv2, numpy) to undistort the image.
    2. Since you only have a single image, write python code that assumes reasonable parameters for moderate barrel distortion correction (e.g. focal length = width, principal point at center, and a radial distortion coefficient k1 = -0.15, k2 = 0.0).
    3. Apply this correction to the image using cv2.undistort (or similar OpenCV operations) and save the resulting rectified/undistorted image as 'corrected_image.jpg' in the current working directory.
    """
    
    image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg") if gcs_uri.startswith("gs://") else types.Part.from_bytes(data=open("original_image.jpg", "rb").read(), mime_type="image/jpeg")
    
    try:
        response = client.models.generate_content(
            model=args.model,
            contents=[image_part, DISTORTION_PROMPT],
            config=types.GenerateContentConfig(
                temperature=0.0,
                tools=[{"code_execution": {}}]
            ),
        )
        corrected_saved = False
        for part in response.candidates[0].content.parts:
            if part.code_execution_result:
                print("\n# Code Execution Output (Distortion Correction):", file=sys.stderr)
                print(part.code_execution_result.output, file=sys.stderr)
            if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                with open("corrected_image.jpg", "wb") as f:
                    f.write(part.inline_data.data)
                print("Saved corrected_image.jpg from inline data.", file=sys.stderr)
                corrected_saved = True
        
        if not corrected_saved and os.path.exists("corrected_image.jpg"):
            corrected_saved = True
            
        if not corrected_saved:
            print("Warning: corrected_image.jpg not created. Using original as fallback.", file=sys.stderr)
            import shutil
            shutil.copyfile("original_image.jpg", "corrected_image.jpg")
    except Exception as e:
        print(f"Lens correction step failed: {e}", file=sys.stderr)
        import shutil
        shutil.copyfile("original_image.jpg", "corrected_image.jpg")

    # Step 2: Roof Edge Detection
    print("\nStarting Roof Edge Detection...", file=sys.stderr)
    EDGE_PROMPT = """You are an expert computer vision assistant. Your task is to write and execute python code using PIL or cv2 to trace and draw the roof edges of ONLY the primary house in the foreground.
    
    Instructions:
    1. Use Python code execution to load 'corrected_image.jpg'.
    2. Identify the primary house in the foreground.
    3. Draw lines tracing the roof eaves, ridges, and hips.
    4. Save the resulting image as 'annotated_output.jpg' and make sure it is output.
    """
    
    try:
        with open("corrected_image.jpg", "rb") as f:
            target_part = types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")
            
        edge_response = client.models.generate_content(
            model=args.model,
            contents=[target_part, EDGE_PROMPT],
            config=types.GenerateContentConfig(
                temperature=0.0,
                tools=[{"code_execution": {}}]
            ),
        )
        for part in edge_response.candidates[0].content.parts:
            if part.text:
                print(part.text)
            if part.code_execution_result:
                print("\n# Code Execution Output (Edge Tracing):", file=sys.stderr)
                print(part.code_execution_result.output, file=sys.stderr)
            if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                with open("annotated_output.jpg", "wb") as f:
                    f.write(part.inline_data.data)
                print("Saved annotated_output.jpg to current directory.", file=sys.stderr)
    except Exception as e:
        print(f"Edge detection step failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
