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

"""
Route Registration Export Tool

A utility script to convert a GeoJSON file (extracted from the Route Registration Tool)
into an RMI project export JSON format.
"""

import json
import uuid
import yaml
import sys
import os
import logging
from datetime import datetime
from typing import List, Tuple, Dict, Any

# --- Configuration & Logging ---
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def encode_polyline(points: List[Tuple[float, float]]) -> str:
    """Encodes a list of (lat, lng) coordinates into a Google Polyline string."""
    res = ""
    last_lat = 0
    last_lng = 0
    for lat, lng in points:
        lat_int = int(round(lat * 1e5))
        lng_int = int(round(lng * 1e5))
        d_lat = lat_int - last_lat
        d_lng = lng_int - last_lng
        for val in [d_lat, d_lng]:
            val = ~(val << 1) if val < 0 else (val << 1)
            while val >= 0x20:
                res += chr((0x20 | (val & 0x1f)) + 63)
                val >>= 5
            res += chr(val + 63)
        last_lat = lat_int
        last_lng = lng_int
    return res

def process_geojson_to_routes(geojson_path: str, project_id: int, tag: str, route_set: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parses GeoJSON features and converts them to RMI route entries."""
    if not os.path.exists(geojson_path):
        logger.error(f"GeoJSON file not found: {geojson_path}")
        sys.exit(1)

    try:
        with open(geojson_path, 'r') as f:
            geojson_data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load GeoJSON: {e}")
        sys.exit(1)

    routes = []
    features = geojson_data.get('features', [])
    logger.info(f"Found {len(features)} features in GeoJSON.")

    for feat in features:
        geom = feat.get('geometry', {})
        props = feat.get('properties', {})
        
        if geom.get('type') != 'LineString':
            logger.warning(f"Skipping non-LineString feature: {geom.get('type')}")
            continue
        
        # GeoJSON is [lng, lat] -> convert to [lat, lng]
        points = [(p[1], p[0]) for p in geom.get('coordinates', [])]
        if not points:
            continue
        
        start_lat, start_lng = points[0]
        end_lat, end_lng = points[-1]
        waypoints = points[1:-1] if len(points) > 2 else None
        
        center_lat = sum(p[0] for p in points) / len(points)
        center_lng = sum(p[1] for p in points) / len(points)
        
        route_entry = {
            "uuid": props.get('uuid', str(uuid.uuid4())),
            "project_id": project_id,
            "route_name": props.get('name', f"route-{uuid.uuid4().hex[:8]}"),
            "origin": json.dumps({"lat": start_lat, "lng": start_lng}),
            "destination": json.dumps({"lat": end_lat, "lng": end_lng}),
            "waypoints": json.dumps([[p[1], p[0]] for p in waypoints]) if waypoints else None,
            "center": json.dumps({"lat": center_lat, "lng": center_lng}),
            "encoded_polyline": encode_polyline(points),
            "route_type": props.get('route_type', route_set.get('route_type', 'imported')),
            "length": float(props.get('length', 0.0)),
            "parent_route_id": None,
            "has_children": 0,
            "is_segmented": 0,
            "segmentation_type": None,
            "segmentation_points": None,
            "segmentation_config": None,
            "sync_status": props.get('sync_status', route_set.get('sync_status', 'unsynced')),
            "is_enabled": route_set.get('is_enabled', 1),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "deleted_at": None,
            "tag": props.get('tag', tag),
            "start_lat": start_lat,
            "start_lng": start_lng,
            "end_lat": end_lat,
            "end_lng": end_lng,
            "min_lat": min(p[0] for p in points),
            "max_lat": max(p[0] for p in points),
            "min_lng": min(p[1] for p in points),
            "max_lng": max(p[1] for p in points),
            "latest_data_update_time": None,
            "static_duration_seconds": None,
            "current_duration_seconds": None,
            "routes_status": None,
            "synced_at": None,
            "original_route_geo_json": None,
            "match_percentage": None,
            "temp_geometry": None,
            "validation_status": None,
            "traffic_status": None,
            "segment_order": None
        }
        routes.append(route_entry)
    
    return routes

def main(config_path: str):
    """Main execution entry point."""
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    paths = config.get('paths', {})
    p_info = config.get('project_info', {})
    route_set = config.get('route_settings', {})

    geojson_path = paths.get('input_geojson_file')
    output_json_path = paths.get('output_export_json_file')

    if not all([geojson_path, output_json_path]):
        logger.error("Missing required paths in config.yaml")
        sys.exit(1)

    # Build Project Object
    project_id = p_info.get('id', 1)
    project_name = p_info.get('project_name', 'sample-project')
    
    export_data = {
        "project": {
            "id": project_id,
            "project_name": project_name,
            "jurisdiction_boundary_geojson": p_info.get('jurisdiction_boundary_geojson', '{}'),
            "google_cloud_project_id": p_info.get('google_cloud_project_id', ''),
            "google_cloud_project_number": p_info.get('google_cloud_project_number', ''),
            "subscription_id": p_info.get('subscription_id', ''),
            "dataset_name": p_info.get('dataset_name', 'historical_roads_data'),
            "viewstate": p_info.get('viewstate', '{}'),
            "map_snapshot": ""
        },
        "routes": []
    }

    tag = p_info.get('tag', 'default')

    # Extract routes from GeoJSON
    logger.info(f"Processing routes from: {geojson_path}")
    new_routes = process_geojson_to_routes(geojson_path, project_id, tag, route_set)
    
    # Merge
    export_data['routes'] = new_routes
    logger.info(f"Generated {len(new_routes)} routes in RMI format.")

    # Save
    with open(output_json_path, 'w') as f:
        json.dump(export_data, f, indent=4)
    logger.info(f"Successfully saved export JSON to: {output_json_path}")

if __name__ == "__main__":
    config_file = "config.yaml"
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    main(config_file)
