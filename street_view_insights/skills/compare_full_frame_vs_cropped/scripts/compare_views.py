#!/usr/bin/env python3
import os
import sys
import argparse
import time
import json
from google import genai
from google.genai import types

def parse_args():
    parser = argparse.ArgumentParser(description="Compare detection and audit capabilities of cropped vs full-frame street view images.")
    parser.add_argument("--cropped-image", required=True, help="Path to cropped asset image (local file or gs:// URI).")
    parser.add_argument("--full-image", required=True, help="Path to full-frame street view image (local file or gs:// URI).")
    
    # Gemini model arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), help="Google Cloud project ID.")
    parser.add_argument("--location", default="global", help="Google Cloud location/region.")
    parser.add_argument("--model", default="gemini-3.5-flash", help="Model to use (e.g. gemini-3.5-flash).")
    return parser.parse_args()

def main():
    args = parse_args()
    project_id = args.project
    if not project_id:
        try:
            from google.cloud import bigquery
            client_bq = bigquery.Client()
            project_id = client_bq.project
        except Exception:
            pass
            
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    # Common audit prompt
    audit_prompt = """Identify and audit the utility pole or street asset present in the image.
    List:
    1. Sub-attachments (transformers, street lights, crossarms, riser caps).
    2. Structural condition (leaning, rust, wood decay, cracked crossarms).
    3. Surrounding hazards (foliage encroachments, nearby utility wires).
    """
    
    def run_inference(image_path, label):
        print(f"Running inference on {label} image...", file=sys.stderr)
        if image_path.startswith("gs://"):
            image_part = types.Part.from_uri(file_uri=image_path, mime_type="image/jpeg")
        else:
            from PIL import Image
            from io import BytesIO
            img = Image.open(image_path)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='JPEG')
            image_part = types.Part.from_bytes(data=img_byte_arr.getvalue(), mime_type="image/jpeg")
            
        start_time = time.time()
        resp = client.models.generate_content(
            model=args.model,
            contents=[image_part, audit_prompt]
        )
        elapsed = time.time() - start_time
        return resp.text, elapsed, resp.usage_metadata

    results = {}
    try:
        cropped_txt, cropped_time, cropped_usage = run_inference(args.cropped_image, "cropped")
        results["cropped_view"] = {
            "elapsed_seconds": round(cropped_time, 2),
            "input_tokens": cropped_usage.prompt_token_count if cropped_usage else None,
            "output_tokens": cropped_usage.candidates_token_count if cropped_usage else None,
            "analysis": cropped_txt
        }
    except Exception as e:
        results["cropped_view_error"] = str(e)

    # Delay to avoid rate limits
    time.sleep(3)

    try:
        full_txt, full_time, full_usage = run_inference(args.full_image, "full-frame")
        results["full_frame_view"] = {
            "elapsed_seconds": round(full_time, 2),
            "input_tokens": full_usage.prompt_token_count if full_usage else None,
            "output_tokens": full_usage.candidates_token_count if full_usage else None,
            "analysis": full_txt
        }
    except Exception as e:
        results["full_frame_view_error"] = str(e)
        
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
