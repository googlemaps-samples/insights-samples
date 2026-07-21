#!/usr/bin/env python3
import os
import sys
import math
import json
import argparse
import urllib.parse
import geopy.distance
from google import genai
from google.genai import types

def parse_args():
    parser = argparse.ArgumentParser(description="Consolidated Building Envelope Audit Skill.")
    parser.add_argument("--task", required=True, choices=["vantage", "roof"], 
                        help="Building envelope audit task.")
    
    # Task 'vantage' requires coordinates, 'roof' requires image or observation-id
    parser.add_argument("--coordinates", help="Target coordinates for vantage lookup in format 'lat,lng'.")
    parser.add_argument("--image", help="Target image path or gs:// URI for roof tracing.")
    parser.add_argument("--observation-id", help="Lookup observation ID in BigQuery for roof tracing.")
    
    # Output file settings for roof tracing
    parser.add_argument("--output", default=".", help="Output directory to save images. (Default: current directory)")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "imagery-insights-sandbox"), 
                        help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "imagery_insights___us"), 
                        help="BigQuery dataset name.")
    parser.add_argument("--table", default="pano_observations_latest", 
                        help="BigQuery observations table name.")
    
    # Gemini model arguments
    parser.add_argument("--location", default="global", help="Google Cloud location/region.")
    parser.add_argument("--model", default="gemini-3.5-flash", help="Model to use (e.g. gemini-3.5-flash).")
    return parser.parse_args()

def calculate_bearing(start_cw, end_cw):
    lat1, lat2 = math.radians(start_cw[0]), math.radians(end_cw[0])
    diffLong = math.radians(end_cw[1] - start_cw[1])
    x = math.sin(diffLong) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(diffLong))
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def is_within_fov(obs_heading, target_bearing, fov_threshold=50):
    diff = abs(obs_heading - target_bearing)
    diff = min(diff, 360 - diff)
    return diff <= fov_threshold

def get_spatial_imagery(args, target_lat, target_lng):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project or args.project
        
    query = f"""
    SELECT
        observation_id,
        capture_location.latitude as lat,
        capture_location.longitude as lng,
        camera_pose.heading as heading,
        camera_pose.pitch as pitch,
        gcs_uri
    FROM `{project_id}.{args.dataset}.{args.table}`
    ORDER BY ST_DISTANCE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude), ST_GEOGPOINT({target_lng}, {target_lat})) ASC
    LIMIT 20
    """
    rows = list(client_bq.query(query).result())
    results = []
    
    for row in rows:
        bearing = calculate_bearing((row.lat, row.lng), (target_lat, target_lng))
        dist = geopy.distance.geodesic((row.lat, row.lng), (target_lat, target_lng)).meters
        if row.pitch and row.pitch > 15 and dist < 20: continue
        if row.heading and not is_within_fov(row.heading, bearing): continue
        
        results.append({
            "metadata": {
                "observation_id": row.observation_id,
                "spatial_context": {
                    "heading": row.heading,
                    "gps": [row.lat, row.lng],
                    "dist": round(dist, 2)
                }
            },
            "gs_link": row.gcs_uri
        })
    return results, project_id

def query_image_from_bq(args):
    from google.cloud import bigquery
    client_bq = bigquery.Client(project=args.project)
    project_id = client_bq.project or args.project
        
    print(f"Querying BQ table `{project_id}.{args.dataset}.{args.table}` for observation: {args.observation_id}...", file=sys.stderr)
    query = f"""
    SELECT gcs_uri
    FROM `{project_id}.{args.dataset}.{args.table}`
    WHERE observation_id = @id OR capture_id = @id OR pano_id = @id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", args.observation_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        raise ValueError(f"No image observation found for observation ID: {args.observation_id}")
    return rows[0].gcs_uri, project_id

def download_gcs_blob(gcs_uri, dest_file):
    from google.cloud import storage
    storage_client = storage.Client()
    path_parts = gcs_uri[5:].split('/', 1)
    bucket = storage_client.bucket(path_parts[0])
    blob = bucket.blob(path_parts[1])
    blob.download_to_filename(dest_file)

def main():
    args = parse_args()
    
    if args.task == "vantage":
        if not args.coordinates:
            print("Error: --coordinates lat,lng is required for 'vantage' task.", file=sys.stderr)
            sys.exit(1)
        parts = args.coordinates.split(",")
        lat, lng = float(parts[0]), float(parts[1])
        
        all_images, project_id = get_spatial_imagery(args, lat, lng)
        if not all_images:
            print(json.dumps({"error": "No spatial imagery found."}))
            sys.exit(0)
            
        client = genai.Client(vertexai=True, project=project_id, location=args.location)
        
        meta_prompt = f"Goal: Retrieve IDs that provide a direct view of {lat}, {lng}. Return JSON list of strings."
        meta_payload = [{"id": x['metadata']['observation_id'], "dist": x['metadata']['spatial_context']['dist']} for x in all_images]
        
        try:
            resp_meta = client.models.generate_content(
                model=args.model,
                contents=[meta_prompt, json.dumps(meta_payload)],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            selected_ids = json.loads(resp_meta.text)
            if isinstance(selected_ids, dict):
                for val in selected_ids.values():
                    if isinstance(val, list):
                        selected_ids = val
                        break
        except Exception as e:
            print(f"Selection failed: {e}", file=sys.stderr)
            sys.exit(1)
            
        property_clusters = {}
        for obs_id in selected_ids:
            img_obj = next((x for x in all_images if x['metadata']['observation_id'] == obs_id), None)
            if not img_obj: continue
            try:
                cluster_prompt = "Identify residential structure features and assign a Property ID. Return JSON: {'visible': bool, 'property_id': str, 'signature_bullet_points': [str], 'reason': str}"
                image_part = types.Part.from_uri(file_uri=img_obj['gs_link'], mime_type="image/jpeg")
                resp_val = client.models.generate_content(
                    model=args.model,
                    contents=[image_part, cluster_prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                analysis = json.loads(resp_val.text)
                if isinstance(analysis, list) and len(analysis) > 0:
                    analysis = analysis[0]
                if isinstance(analysis, dict) and analysis.get('visible'):
                    prop_id = analysis.get('property_id', 'Unknown Property')
                    if prop_id not in property_clusters:
                        property_clusters[prop_id] = {"images": [], "signature": analysis.get('signature_bullet_points', [])}
                    property_clusters[prop_id]["images"].append(img_obj)
            except Exception as e:
                print(f"Error processing {obs_id}: {e}", file=sys.stderr)
                
        print(json.dumps(property_clusters, indent=2))
        
    elif args.task == "roof":
        if not args.image and not args.observation_id:
            print("Error: Either --image or --observation-id is required for 'roof' task.", file=sys.stderr)
            sys.exit(1)
            
        project_id = args.project
        if args.image:
            image_uri = args.image
        else:
            try:
                image_uri, project_id = query_image_from_bq(args)
            except Exception as e:
                print(f"Error querying BigQuery: {e}", file=sys.stderr)
                sys.exit(1)
                
        os.makedirs(args.output, exist_ok=True)
        orig_img_path = os.path.join(args.output, "original_image.jpg")
        corr_img_path = os.path.join(args.output, "corrected_image.jpg")
        annotated_img_path = os.path.join(args.output, "annotated_output.jpg")
        
        try:
            if image_uri.startswith("gs://"):
                download_gcs_blob(image_uri, orig_img_path)
            else:
                import shutil
                shutil.copyfile(image_uri, orig_img_path)
        except Exception as e:
            print(f"Error downloading image: {e}", file=sys.stderr)
            sys.exit(1)
            
        client = genai.Client(vertexai=True, project=project_id, location=args.location)
        
        DISTORTION_PROMPT = """Analyze the provided image for lens distortion, specifically barrel distortion. Use Python code execution (cv2, numpy) to undistort the image (assumed focal length = width, principal point at center, and a radial distortion coefficient k1 = -0.15, k2 = 0.0), and save it as 'corrected_image.jpg' in the current working directory."""
        image_part = types.Part.from_uri(file_uri=image_uri, mime_type="image/jpeg") if image_uri.startswith("gs://") else types.Part.from_bytes(data=open(orig_img_path, "rb").read(), mime_type="image/jpeg")
        
        try:
            response = client.models.generate_content(
                model=args.model,
                contents=[image_part, DISTORTION_PROMPT],
                config=types.GenerateContentConfig(temperature=0.0, tools=[{"code_execution": {}}]),
            )
            corrected_saved = False
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                    with open(corr_img_path, "wb") as f:
                        f.write(part.inline_data.data)
                    corrected_saved = True
            
            if not corrected_saved and os.path.exists("corrected_image.jpg"):
                import shutil
                shutil.move("corrected_image.jpg", corr_img_path)
                corrected_saved = True
                
            if not corrected_saved:
                import shutil
                shutil.copyfile(orig_img_path, corr_img_path)
        except Exception as e:
            print(f"Lens correction step failed: {e}", file=sys.stderr)
            import shutil
            shutil.copyfile(orig_img_path, corr_img_path)
            
        EDGE_PROMPT = """You are an expert computer vision assistant. Write and execute python code using PIL or cv2 to trace and draw the roof edges (eaves, ridges, hips) of ONLY the primary house in the foreground. Save it as 'annotated_output.jpg'."""
        
        try:
            with open(corr_img_path, "rb") as f:
                target_part = types.Part.from_bytes(data=f.read(), mime_type="image/jpeg")
                
            edge_response = client.models.generate_content(
                model=args.model,
                contents=[target_part, EDGE_PROMPT],
                config=types.GenerateContentConfig(temperature=0.0, tools=[{"code_execution": {}}]),
            )
            
            annotated_saved = False
            for part in edge_response.candidates[0].content.parts:
                if part.text:
                    print(part.text)
                if part.inline_data and part.inline_data.mime_type.startswith('image/'):
                    with open(annotated_img_path, "wb") as f:
                        f.write(part.inline_data.data)
                    annotated_saved = True
                    
            if not annotated_saved and os.path.exists("annotated_output.jpg"):
                import shutil
                shutil.move("annotated_output.jpg", annotated_img_path)
                annotated_saved = True
                
            if annotated_saved:
                print(f"Successfully saved audit images to: {args.output}", file=sys.stderr)
        except Exception as e:
            print(f"Edge detection step failed: {e}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
