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

A utility script to merge new routes from a CSV file into an RMI project export JSON.
This allows for bulk registration of routes by updating the local export file
and then re-importing it into the RMI interface.
"""

import json
import csv
import uuid
import re
import yaml
import sys
import os
import logging
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

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

def parse_wkt_points(wkt: str) -> List[Tuple[float, float]]:
    """
    Parses a WKT geometry string (LINESTRING or MULTILINESTRING) into points.
    Returns a list of (latitude, longitude) tuples.
    """
    # Find all sequences of numbers separated by spaces
    matches = re.findall(r"(-?\d+\.?\d*)\s+(-?\d+\.?\d*)", wkt)
    if not matches:
        return []
    
    # WKT is typically (longitude latitude) -> convert to (latitude longitude)
    try:
        points = [(float(lat), float(lng)) for lng, lat in matches]
        return points
    except ValueError as e:
        logger.warning(f"Failed to parse coordinates in WKT: {e}")
        return []

def update_export(config_path: str):
    """Main execution logic to update the export file."""
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML config: {e}")
        sys.exit(1)

    # Extract configuration
    p_info = config.get('project_info', {})
    paths = config.get('paths', {})
    csv_fmt = config.get('csv_format', {})
    route_set = config.get('route_settings', {})

    base_json_path = paths.get('base_export_json_file')
    input_csv_path = paths.get('input_csv_file')
    output_json_path = paths.get('output_export_json_file')

    # Validate paths
    if not all([base_json_path, input_csv_path, output_json_path]):
        logger.error("Missing required file paths in config.yaml.")
        sys.exit(1)

    # Load base JSON
    logger.info(f"Reading base export file: {base_json_path}")
    try:
        with open(base_json_path, 'r') as f:
            export_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load base JSON: {e}")
        sys.exit(1)

    # Update project metadata from config if provided
    if 'project' in export_data:
        for key, val in p_info.items():
            if key in export_data['project']:
                export_data['project'][key] = val
    
    project_id = export_data.get('project', {}).get('id', 1)
    tag = p_info.get('tag', 'default')

    # Process CSV
    logger.info(f"Processing input CSV: {input_csv_path}")
    if not os.path.exists(input_csv_path):
        logger.error(f"CSV file not found: {input_csv_path}")
        sys.exit(1)

    new_routes = []
    try:
        with open(input_csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                wkt = row.get(csv_fmt.get('geometry_wkt_column', ''))
                if not wkt:
                    logger.warning(f"Row {i} skipped: Missing geometry column.")
                    continue
                
                points = parse_wkt_points(wkt)
                if not points:
                    logger.warning(f"Row {i} skipped: Could not parse WKT geometry.")
                    continue
                
                start_lat, start_lng = points[0]
                end_lat, end_lng = points[-1]
                waypoints = points[1:-1] if len(points) > 2 else None
                
                center_lat = sum(p[0] for p in points) / len(points)
                center_lng = sum(p[1] for p in points) / len(points)
                
                # Metadata from config
                prefix = route_set.get('route_name_prefix', 'new-route-')
                route_name = f"{prefix}{row.get(csv_fmt.get('segment_id_column', ''), i)}"
                
                route_entry = {
                    "uuid": str(uuid.uuid4()),
                    "project_id": project_id,
                    "route_name": route_name,
                    "origin": json.dumps({"lat": start_lat, "lng": start_lng}),
                    "destination": json.dumps({"lat": end_lat, "lng": end_lng}),
                    "waypoints": json.dumps([[p[1], p[0]] for p in waypoints]) if waypoints else None,
                    "center": json.dumps({"lat": center_lat, "lng": center_lng}),
                    "encoded_polyline": encode_polyline(points),
                    "route_type": route_set.get('route_type', 'imported'),
                    "length": float(row.get(csv_fmt.get('length_column', ''), 0.0)),
                    "parent_route_id": None,
                    "has_children": 0,
                    "is_segmented": 0,
                    "segmentation_type": None,
                    "segmentation_points": None,
                    "segmentation_config": None,
                    "sync_status": route_set.get('sync_status', 'unsynced'),
                    "is_enabled": route_set.get('is_enabled', 1),
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "deleted_at": None,
                    "tag": tag,
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
                new_routes.append(route_entry)
    except Exception as e:
        logger.error(f"Error processing CSV file: {e}")
        sys.exit(1)

    # Merge and Save
    export_data['routes'].extend(new_routes)
    logger.info(f"Added {len(new_routes)} routes. Total routes in export: {len(export_data['routes'])}")

    try:
        with open(output_json_path, 'w') as f:
            json.dump(export_data, f, indent=4)
        logger.info(f"Updated export saved to: {output_json_path}")
    except Exception as e:
        logger.error(f"Failed to save output JSON: {e}")
        sys.exit(1)

if __name__ == "__main__":
    config_file = "config.yaml"
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    
    update_export(config_file)
