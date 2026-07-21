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
    parser = argparse.ArgumentParser(description="Find optimal street view vantage points near coordinates and cluster properties.")
    parser.add_argument("--coordinates", required=True, help="Target GPS coordinate in format 'lat,lng'.")
    
    # BigQuery connection arguments
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"), help="Google Cloud project ID.")
    parser.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", "home_depot_full_scene"), help="BigQuery dataset name.")
    parser.add_argument("--tracks-table", default="tracks_unnested", help="BigQuery tracks table name.")
    parser.add_argument("--obs-table", default="observations", help="BigQuery observations table name.")
    parser.add_argument("--urls-table", default="urls_new", help="BigQuery URLs table name.")
    
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
    project_id = client_bq.project
    if not project_id:
        raise ValueError("Could not resolve Google Cloud project ID.")
        
    print(f"Querying BigQuery for tracks near {target_lat}, {target_lng}...", file=sys.stderr)
    query_tracks = f"""
    SELECT
        t.trackId, ST_X(t.geometry) as lng, ST_Y(t.geometry) as lat,
        t.observation0, t.observation1, t.observation2, t.observation3,
        t.observation4, t.observation5, t.observation6,
        o.cameraPose.headingDeg as vehicle_heading
    FROM `{project_id}.{args.dataset}.{args.tracks_table}` t
    JOIN `{project_id}.{args.dataset}.{args.obs_table}` o ON t.observation0 = o.observationId
    ORDER BY ST_DISTANCE(t.geometry, ST_GEOGPOINT({target_lng}, {target_lat})) ASC
    LIMIT 10
    """
    tracks = list(client_bq.query(query_tracks).result())
    if not tracks: 
        print("No tracks found.", file=sys.stderr)
        return [], project_id

    track_context = []
    for idx, track in enumerate(tracks):
        bearing = calculate_bearing((track.lat, track.lng), (target_lat, target_lng))
        for cam_id in range(7):
            obs_id = getattr(track, f"observation{cam_id}")
            if obs_id:
                track_context.append({
                    "track_id": track.trackId, "obs_id": obs_id, "cam_id": cam_id,
                    "v_lat": track.lat, "v_lng": track.lng, "target_bearing": bearing, "seq_idx": idx
                })

    obs_ids_str = ",".join([f"'{x['obs_id']}'" for x in track_context])
    query_details = f"""
    SELECT o.observationId, o.cameraPose.pitchDeg as pitch, o.cameraPose.headingDeg as obs_heading, u.signedUrl
    FROM `{project_id}.{args.dataset}.{args.obs_table}` o
    JOIN `{project_id}.{args.dataset}.{args.urls_table}` u ON o.observationId = u.observationId
    WHERE o.observationId IN ({obs_ids_str})
    """
    details_map = {row.observationId: row for row in client_bq.query(query_details).result()}
    view_names = {0:"front_right", 1:"right", 2:"rear_right", 3:"rear_left", 4:"left", 5:"front_left", 6:"zenith"}
    results = []

    for item in track_context:
        obs_id = item["obs_id"]
        if obs_id in details_map:
            d = details_map[obs_id]
            dist = geopy.distance.geodesic((item["v_lat"], item["v_lng"]), (target_lat, target_lng)).meters
            if d.pitch > 15 and dist < 20: continue
            if not is_within_fov(d.obs_heading, item["target_bearing"]): continue
            gs_link = d.signedUrl.replace("https://storage.mtls.cloud.google.com/", "gs://")
            results.append({
                "metadata": {"observation_id": obs_id, "spatial_context": {"heading": d.obs_heading, "view": view_names.get(item["cam_id"], "unknown"), "gps": [item["v_lat"], item["v_lng"],], "dist": round(dist, 2)}},
                "image_link": d.signedUrl, "gs_link": gs_link
            })
    return results, project_id

def main():
    args = parse_args()
    
    parts = args.coordinates.split(",")
    if len(parts) != 2:
        print("Error: coordinates must be in format 'lat,lng'", file=sys.stderr)
        sys.exit(1)
    lat, lng = float(parts[0]), float(parts[1])
    
    try:
        all_images, project_id = get_spatial_imagery(args, lat, lng)
    except Exception as e:
        print(f"Error querying spatial imagery: {e}", file=sys.stderr)
        sys.exit(1)
        
    if not all_images:
        print(json.dumps({"error": "No spatial imagery found matching heading and distance constraints."}))
        sys.exit(0)
        
    client = genai.Client(vertexai=True, project=project_id, location=args.location)
    
    # Vantage Point Selection Prompt
    print(f"Selecting optimal vantage points from {len(all_images)} observations...", file=sys.stderr)
    meta_prompt = f"Goal: Retrieve IDs that provide a direct view of {lat}, {lng}. Return JSON list of strings."
    meta_payload = [{"id": x['metadata']['observation_id'], "dist": x['metadata']['spatial_context']['dist'], "view": x['metadata']['spatial_context']['view']} for x in all_images]
    
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
        print(f"Vantage point selection failed: {e}", file=sys.stderr)
        sys.exit(1)
        
    # Property Clustering Prompt
    print(f"Analyzing {len(selected_ids)} selected images...", file=sys.stderr)
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

if __name__ == "__main__":
    main()
