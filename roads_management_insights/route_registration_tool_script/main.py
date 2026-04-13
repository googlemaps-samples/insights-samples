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
import zipfile
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional
from pyproj import Geod

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


_WGS84_GEOD = Geod(ellps="WGS84")


def _polyline_length_km(points: List[Tuple[float, float]]) -> float:
    """Returns total geodesic polyline length in kilometers using pyproj."""
    if len(points) < 2:
        return 0.0
    lats = [lat for lat, _ in points]
    lngs = [lng for _, lng in points]
    return _WGS84_GEOD.line_length(lngs, lats) / 1000.0


def _load_geojson_data(geojson_path: str) -> Dict[str, Any]:
    """Loads GeoJSON from a .geojson file or from a .zip archive."""
    if not os.path.exists(geojson_path):
        logger.error(f"GeoJSON file not found: {geojson_path}")
        sys.exit(1)

    lower_path = geojson_path.lower()
    try:
        if lower_path.endswith(".zip"):
            with zipfile.ZipFile(geojson_path, "r") as zf:
                members = [
                    name for name in zf.namelist()
                    if not name.endswith("/") and name.lower().endswith(".geojson")
                ]
                if not members:
                    logger.error(
                        "Input ZIP does not contain a .geojson file: %s",
                        geojson_path,
                    )
                    sys.exit(1)
                selected = members[0]
                logger.info("Reading GeoJSON from ZIP member: %s", selected)
                with zf.open(selected) as f:
                    return json.load(f)
        if lower_path.endswith(".geojson"):
            with open(geojson_path, "r") as f:
                return json.load(f)
        logger.error("Unsupported input file format (use .geojson or .zip): %s", geojson_path)
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load GeoJSON: {e}")
        sys.exit(1)


def _save_export_data(output_path: str, export_data: Dict[str, Any]) -> None:
    """Saves export JSON inside a ZIP file."""
    lower_path = output_path.lower()
    if not lower_path.endswith(".zip"):
        logger.error("Unsupported output format (use .zip): %s", output_path)
        sys.exit(1)

    inner_name = f"{os.path.splitext(os.path.basename(output_path))[0]}.json"
    payload = json.dumps(export_data, indent=4).encode("utf-8")
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_name, payload)
    logger.info("Wrote export JSON to ZIP member: %s", inner_name)


def _load_export_data(base_export_path: str) -> Dict[str, Any]:
    """Loads export JSON from a .zip archive."""
    lower_path = base_export_path.lower()
    if not lower_path.endswith(".zip"):
        logger.error("Unsupported base export format (use .zip): %s", base_export_path)
        sys.exit(1)

    try:
        with zipfile.ZipFile(base_export_path, "r") as zf:
            members = [
                name for name in zf.namelist()
                if not name.endswith("/") and name.lower().endswith(".json")
            ]
            if not members:
                logger.error(
                    "Base export ZIP does not contain a .json file: %s",
                    base_export_path,
                )
                sys.exit(1)
            selected = members[0]
            logger.info("Reading base export from ZIP member: %s", selected)
            with zf.open(selected) as f:
                return json.load(f)
    except Exception as e:
        logger.error("Failed to load base export: %s", e)
        sys.exit(1)


def process_geojson_to_routes(geojson_path: str, project_id: int, tag: str, route_set: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parses GeoJSON features and converts them to RMI route entries."""
    geojson_data = _load_geojson_data(geojson_path)

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
            # Always generate fresh UUIDs for imported routes (ignore input UUID).
            "uuid": str(uuid.uuid4()),
            "project_id": project_id,
            "route_name": props.get('name', f"route-{uuid.uuid4().hex[:8]}"),
            "origin": json.dumps({"lat": start_lat, "lng": start_lng}),
            "destination": json.dumps({"lat": end_lat, "lng": end_lng}),
            "waypoints": json.dumps([[p[1], p[0]] for p in waypoints]) if waypoints else None,
            "center": json.dumps({"lat": center_lat, "lng": center_lng}),
            "encoded_polyline": encode_polyline(points),
            # Route type is fixed for imported registrations.
            "route_type": "drawn",
            # Always calculate length from geometry; input length is ignored.
            "length": _polyline_length_km(points),
            "parent_route_id": None,
            "has_children": 0,
            "is_segmented": 0,
            "segmentation_type": None,
            "segmentation_points": None,
            "segmentation_config": None,
            # Sync status is fixed for imported registrations.
            "sync_status": "unsynced",
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


# Keys allowed under project_info in YAML that apply to routes only, not export project.*
_PROJECT_INFO_NON_PROJECT_KEYS = frozenset({"tag"})


def _merge_project_overrides(project: Dict[str, Any], p_info: Dict[str, Any]) -> None:
    """Apply project_info keys onto export project; skip route-only keys like tag."""
    for key, val in p_info.items():
        if key in _PROJECT_INFO_NON_PROJECT_KEYS:
            continue
        project[key] = val


def _default_route_tag(export_data: Dict[str, Any], p_info: Dict[str, Any]) -> str:
    """Tag for new routes: config override, else first existing route, else 'default'."""
    if "tag" in p_info and p_info["tag"] is not None:
        return str(p_info["tag"])
    for route in export_data.get("routes") or []:
        t = route.get("tag")
        if t:
            return str(t)
    return "default"


def main(config_path: str):
    """Main execution entry point."""
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    paths = config.get('paths', {})
    p_info = config.get('project_info') or {}
    route_set = config.get('route_settings', {})

    geojson_path = paths.get('input_geojson_file')
    base_json_path = paths.get('base_export_file') or paths.get('base_export_json_file')
    output_json_path = paths.get('output_export_file') or paths.get('output_export_json_file')

    if not all([geojson_path, output_json_path]):
        logger.error("Missing required paths in config.yaml")
        sys.exit(1)

    # Initialize or Load Export Data
    if base_json_path and os.path.exists(base_json_path):
        logger.info(f"Loading base export: {base_json_path}")
        export_data = _load_export_data(base_json_path)
        # Project metadata comes entirely from the base file; project_info only overrides
        # keys you list (omit project_info or use {} to keep the base project unchanged).
        if p_info:
            proj = export_data.setdefault("project", {})
            _merge_project_overrides(proj, p_info)
            applied = sorted(k for k in p_info if k not in _PROJECT_INFO_NON_PROJECT_KEYS)
            if applied:
                logger.info("Applied project_info overrides: %s", ", ".join(applied))
    else:
        logger.info("Generating new project structure from config.")
        export_data = {
            "project": {
                "id": p_info.get('id', 1),
                "project_name": p_info.get('project_name', 'sample-project'),
                "jurisdiction_boundary_geojson": p_info.get('jurisdiction_boundary_geojson', '{}'),
                "google_cloud_project_id": p_info.get('google_cloud_project_id', ''),
                "google_cloud_project_number": p_info.get('google_cloud_project_number', ''),
                "subscription_id": p_info.get('subscription_id', ''),
                "dataset_name": p_info.get('dataset_name', 'historical_roads_data'),
                "viewstate": p_info.get('viewstate', '{}'),
                "map_snapshot": p_info.get("map_snapshot", "")
            },
            "routes": []
        }

    project_id = export_data['project'].get('id', 1)
    tag = _default_route_tag(export_data, p_info)

    # Extract routes from GeoJSON
    logger.info(f"Processing routes from: {geojson_path}")
    new_routes = process_geojson_to_routes(geojson_path, project_id, tag, route_set)
    
    # Merge (append if base exists, otherwise replace)
    export_data['routes'].extend(new_routes)
    logger.info(f"Merged {len(new_routes)} new routes. Total: {len(export_data['routes'])}")

    # Save
    _save_export_data(output_json_path, export_data)
    logger.info(f"Successfully saved export JSON to: {output_json_path}")

if __name__ == "__main__":
    config_file = "config.yaml"
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    main(config_file)
