
import json
import csv
import uuid
import re
import yaml
import sys
from datetime import datetime

def encode_polyline(points):
    """Encodes a list of (lat, lng) tuples into a Google Polyline string."""
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

def parse_wkt(wkt):
    """Parses a WKT MULTILINESTRING or LINESTRING into a list of (lat, lng) points."""
    match = re.search(r"\((.*)\)", wkt)
    if not match:
        return []
    coords_str = match.group(1).replace("(", "").replace(")", "")
    points = []
    for pair in coords_str.split(","):
        parts = pair.strip().split()
        if len(parts) < 2: continue
        lng, lat = map(float, parts)
        points.append((lat, lng))
    return points

def load_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

def update_export(config_path):
    config = load_config(config_path)
    
    # Extract config sections
    p_info = config['project_info']
    paths = config['paths']
    csv_fmt = config['csv_format']
    route_set = config['route_settings']

    # Load base JSON
    print(f"Loading base JSON from {paths['base_json']}...")
    with open(paths['base_json'], 'r') as f:
        data = json.load(f)

    # Optionally override project metadata from config
    for key, val in p_info.items():
        if key in data['project']:
            data['project'][key] = val

    print(f"Loading new routes from {paths['input_csv']}...")
    existing_count = len(data['routes'])

    # Process CSV
    with open(paths['input_csv'], 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            wkt = row.get(csv_fmt['wkt_column'])
            if not wkt:
                continue
            
            points = parse_wkt(wkt)
            if not points:
                continue
            
            start_lat, start_lng = points[0]
            end_lat, end_lng = points[-1]
            waypoints = points[1:-1] if len(points) > 2 else None
            
            center_lat = sum(p[0] for p in points) / len(points)
            center_lng = sum(p[1] for p in points) / len(points)
            
            route_name = f"{route_set['name_prefix']}{i}"
            
            route = {
                "uuid": str(uuid.uuid4()),
                "project_id": data["project"]["id"],
                "route_name": route_name,
                "origin": json.dumps({"lat": start_lat, "lng": start_lng}),
                "destination": json.dumps({"lat": end_lat, "lng": end_lng}),
                "waypoints": json.dumps([[p[1], p[0]] for p in waypoints]) if waypoints else None,
                "center": json.dumps({"lat": center_lat, "lng": center_lng}),
                "encoded_polyline": encode_polyline(points),
                "route_type": route_set['route_type'],
                "length": float(row.get(csv_fmt['length_column'], 0.0)),
                "parent_route_id": None,
                "has_children": 0,
                "is_segmented": 0,
                "segmentation_type": None,
                "segmentation_points": None,
                "segmentation_config": None,
                "sync_status": route_set['sync_status'],
                "is_enabled": route_set['is_enabled'],
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "deleted_at": None,
                "tag": p_info.get("tag", "default"),
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
            data["routes"].append(route)

    # Save output
    print(f"Saving output to {paths['output_json']}...")
    with open(paths['output_json'], 'w') as f:
        json.dump(data, f, indent=4)

    print(f"Done. Added {len(data['routes']) - existing_count} routes. Total: {len(data['routes'])}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 update_boston_export.py <config_path>")
        sys.exit(1)
    update_export(sys.argv[1])
