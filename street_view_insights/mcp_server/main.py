import os
import io
import json
import urllib.parse
import numpy as np
from PIL import Image, ImageDraw
from google.cloud import bigquery
from google.cloud import storage
from google import genai
from google.genai import types
from fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("Street View Imagery Insights")

CACHE_DIR = "/tmp/mcp_image_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def convert_to_gs_uri(image_url: str) -> str:
    if image_url.startswith("gs://"):
        return image_url
    try:
        clean_url = image_url.replace("https://", "")
        domain, path = clean_url.split("/", 1)
        if "storage" in domain or "googleapis" in domain:
            path = urllib.parse.unquote(path)
            return f"gs://{path}"
    except Exception:
        pass
    return image_url

def download_image_cached(gcs_uri: str) -> str:
    gcs_uri = convert_to_gs_uri(gcs_uri)
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {gcs_uri}")
        
    clean_name = gcs_uri[5:].replace("/", "_").replace(":", "_")
    local_path = os.path.join(CACHE_DIR, clean_name)
    
    if os.path.exists(local_path):
        return local_path
        
    storage_client = storage.Client()
    parts = gcs_uri[5:].split("/", 1)
    bucket = storage_client.bucket(parts[0])
    blob = bucket.blob(parts[1])
    blob.download_to_filename(local_path)
    return local_path

def equirectangular_to_perspective(src_image_path, heading_deg, pitch_deg, fov_deg, out_size=(640, 480)):
    src_img = Image.open(src_image_path)
    src_w, src_h = src_img.size
    src_data = np.array(src_img)
    
    out_w, out_h = out_size
    
    # Degrees to radians
    heading = np.radians(heading_deg)
    pitch = np.radians(pitch_deg)
    fov = np.radians(fov_deg)
    
    # Calculate focal length
    f = 0.5 * out_w / np.tan(0.5 * fov)
    
    # Coordinate grid
    x = np.arange(out_w) - out_w / 2
    y = np.arange(out_h) - out_h / 2
    xx, yy = np.meshgrid(x, y)
    
    # 3D points
    xyz = np.stack((xx, yy, np.full_like(xx, f)), axis=-1)
    norm = np.linalg.norm(xyz, axis=-1, keepdims=True)
    xyz /= norm
    
    # Pitch rotation matrix (X-axis)
    R_x = np.array([
        [1, 0, 0],
        [0, np.cos(-pitch), -np.sin(-pitch)],
        [0, np.sin(-pitch), np.cos(-pitch)]
    ])
    
    # Heading rotation matrix (Y-axis)
    R_y = np.array([
        [np.cos(-heading), 0, np.sin(-heading)],
        [0, 1, 0],
        [-np.sin(-heading), 0, np.cos(-heading)]
    ])
    
    R = R_y @ R_x
    
    xyz_flat = xyz.reshape(-1, 3)
    xyz_rot = (R @ xyz_flat.T).T
    xyz_rot = xyz_rot.reshape(out_h, out_w, 3)
    
    rx = xyz_rot[..., 0]
    ry = xyz_rot[..., 1]
    rz = xyz_rot[..., 2]
    
    theta = np.arctan2(rx, rz)
    phi = np.arcsin(-ry)
    
    px_x = ((theta + np.pi) / (2 * np.pi)) * src_w
    px_y = ((np.pi/2 - phi) / np.pi) * src_h
    
    px_x = np.clip(px_x, 0, src_w - 1).astype(np.int32)
    px_y = np.clip(px_y, 0, src_h - 1).astype(np.int32)
    
    out_data = src_data[px_y, px_x]
    return Image.fromarray(out_data)

def resolve_dataset(dataset_ref: str, default_project: str) -> tuple[str, str]:
    """Resolves dataset reference to project and dataset IDs.
    
    Handles:
      - "dataset_id" -> (default_project, "dataset_id")
      - "project_id.dataset_id" -> ("project_id", "dataset_id")
      - "project_id:dataset_id" -> ("project_id", "dataset_id")
    """
    if "." in dataset_ref:
        project_id, dataset_id = dataset_ref.split(".", 1)
        return project_id, dataset_id
    elif ":" in dataset_ref:
        project_id, dataset_id = dataset_ref.split(":", 1)
        return project_id, dataset_id
    return default_project, dataset_ref

# --- MCP Tools ---

@mcp.tool()
def list_assets(
    dataset_id: str,
    asset_type: str = None,
    latitude: float = None,
    longitude: float = None,
    radius_meters: float = 100.0,
    limit: int = 10
) -> str:
    """
    List assets in the dataset, optionally filtered by asset class or geographic proximity.
    """
    client_bq = bigquery.Client()
    project_id, dataset_id = resolve_dataset(dataset_id, client_bq.project)
    
    where_clauses = []
    query_params = []
    
    if asset_type:
        where_clauses.append("asset_type = @asset_type")
        query_params.append(bigquery.ScalarQueryParameter("asset_type", "STRING", asset_type))
        
    if latitude is not None and longitude is not None:
        where_clauses.append("ST_DWithin(ST_GEOGPOINT(location.longitude, location.latitude), ST_GEOGPOINT(@lng, @lat), @radius)")
        query_params.append(bigquery.ScalarQueryParameter("lat", "FLOAT64", latitude))
        query_params.append(bigquery.ScalarQueryParameter("lng", "FLOAT64", longitude))
        query_params.append(bigquery.ScalarQueryParameter("radius", "FLOAT64", radius_meters))
        
    where_str = ""
    if where_clauses:
        where_str = "WHERE " + " AND ".join(where_clauses)
        
    query = f"""
    SELECT asset_id, asset_type, location, detection_time
    FROM `{project_id}.{dataset_id}.latest_assets`
    {where_str}
    LIMIT @limit
    """
    query_params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    rows = list(client_bq.query(query, job_config=job_config).result())
    
    results = []
    for r in rows:
        results.append({
            "asset_id": r.asset_id,
            "asset_type": r.asset_type,
            "location": {"latitude": r.location.get("latitude"), "longitude": r.location.get("longitude")} if r.location else None,
            "detection_time": str(r.detection_time) if r.detection_time else None
        })
        
    return json.dumps(results, indent=2)

@mcp.tool()
def get_asset_observations(dataset_id: str, asset_id: str) -> str:
    """
    Retrieve all historical observations for a specific asset ID.
    """
    client_bq = bigquery.Client()
    project_id, dataset_id = resolve_dataset(dataset_id, client_bq.project)
    
    query = f"""
    SELECT observation_id, gcs_uri, bbox, pano_id, capture_time, camera_pose, asset_type
    FROM `{project_id}.{dataset_id}.latest_observations`
    WHERE asset_id = @asset_id
    ORDER BY capture_time DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("asset_id", "STRING", asset_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    
    results = []
    for r in rows:
        results.append({
            "observation_id": r.observation_id,
            "gcs_uri": r.gcs_uri,
            "bbox": dict(r.bbox) if r.bbox else None,
            "pano_id": r.pano_id,
            "capture_time": str(r.capture_time) if r.capture_time else None,
            "camera_pose": dict(r.camera_pose) if r.camera_pose else None,
            "asset_type": r.asset_type
        })
        
    return json.dumps(results, indent=2)

@mcp.tool()
def analyze_cropped_asset(
    dataset_id: str,
    observation_id: str,
    prompt: str,
    padding_pixels: int = 50,
    model_name: str = "gemini-3.5-flash"
) -> str:
    """
    Downloads the full-frame image for the given observation, crops it to the asset's bounding box
    (with context padding), submits the crop to Gemini in Vertex AI, and returns the analysis.
    The raw image never leaves GCP.
    """
    client_bq = bigquery.Client()
    project_id, dataset_id = resolve_dataset(dataset_id, client_bq.project)
    
    query = f"""
    SELECT gcs_uri, bbox, asset_type
    FROM `{project_id}.{dataset_id}.cropped_observations_all`
    WHERE observation_id = @observation_id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("observation_id", "STRING", observation_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        return json.dumps({"error": f"Observation not found: {observation_id}"})
        
    row = rows[0]
    gcs_uri = row.gcs_uri
    bbox = row.bbox
    asset_type = row.asset_type
    
    if not gcs_uri or not bbox:
        return json.dumps({"error": "Observation lacks gcs_uri or bbox metadata"})
        
    try:
        local_path = download_image_cached(gcs_uri)
    except Exception as e:
        return json.dumps({"error": f"Failed to download image: {str(e)}"})
        
    try:
        img = Image.open(local_path)
        w, h = img.size
        
        y1 = bbox.get('ymin', bbox.get('lo', {}).get('y', 0))
        x1 = bbox.get('xmin', bbox.get('lo', {}).get('x', 0))
        y2 = bbox.get('ymax', bbox.get('hi', {}).get('y', h))
        x2 = bbox.get('xmax', bbox.get('hi', {}).get('x', w))
        
        xmin = min(x1, x2)
        xmax = max(x1, x2)
        ymin = min(y1, y2)
        ymax = max(y1, y2)
        
        if xmax <= w and ymax <= h:
            left = max(0, xmin - padding_pixels)
            top = max(0, ymin - padding_pixels)
            right = min(w, xmax + padding_pixels)
            bottom = min(h, ymax + padding_pixels)
            
            if left < right and top < bottom:
                img_to_send = img.crop((left, top, right, bottom))
            else:
                img_to_send = img
        else:
            img_to_send = img
        
        img_byte_arr = io.BytesIO()
        img_to_send.save(img_byte_arr, format='JPEG')
        img_bytes = img_byte_arr.getvalue()
    except Exception as e:
        return json.dumps({"error": f"Failed to crop image: {str(e)}"})
        
    try:
        genai_client = genai.Client(vertexai=True, project=project_id, location="global")
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        
        full_prompt = f"Asset Type: {asset_type}\n\nInstructions: {prompt}"
        
        response = genai_client.models.generate_content(
            model=model_name,
            contents=[image_part, full_prompt]
        )
        return json.dumps({"analysis_result": response.text})
    except Exception as e:
        return json.dumps({"error": f"Failed to run model analysis: {str(e)}"})

@mcp.tool()
def analyze_full_frame_context(
    dataset_id: str,
    observation_id: str,
    prompt: str,
    draw_bbox: bool = True,
    model_name: str = "gemini-3.5-flash"
) -> str:
    """
    Downloads the full-frame image, optionally overlays the asset bounding box in solid red,
    submits it to Gemini in Vertex AI, and returns the analysis.
    The raw image never leaves GCP.
    """
    client_bq = bigquery.Client()
    project_id, dataset_id = resolve_dataset(dataset_id, client_bq.project)
    
    query = f"""
    SELECT gcs_uri, bbox, asset_type
    FROM `{project_id}.{dataset_id}.full_frame_observations_all`
    WHERE observation_id = @observation_id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("observation_id", "STRING", observation_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        return json.dumps({"error": f"Observation not found: {observation_id}"})
        
    row = rows[0]
    gcs_uri = row.gcs_uri
    bbox = row.bbox
    asset_type = row.asset_type
    
    if not gcs_uri:
        return json.dumps({"error": "Observation lacks gcs_uri"})
        
    try:
        local_path = download_image_cached(gcs_uri)
    except Exception as e:
        return json.dumps({"error": f"Failed to download image: {str(e)}"})
        
    try:
        img = Image.open(local_path)
        w, h = img.size
        
        max_dim = 1600
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_w = int(w * scale)
            new_h = int(h * scale)
        else:
            scale = 1.0
            new_w, new_h = w, h
            
        if draw_bbox and bbox:
            draw_img = img.copy()
            draw = ImageDraw.Draw(draw_img)
            
            y1 = bbox.get('ymin', bbox.get('lo', {}).get('y', 0))
            x1 = bbox.get('xmin', bbox.get('lo', {}).get('x', 0))
            y2 = bbox.get('ymax', bbox.get('hi', {}).get('y', h))
            x2 = bbox.get('xmax', bbox.get('hi', {}).get('x', w))
            
            xmin = min(x1, x2)
            xmax = max(x1, x2)
            ymin = min(y1, y2)
            ymax = max(y1, y2)
            
            draw.rectangle([xmin, ymin, xmax, ymax], outline="red", width=12)
            draw.text((xmin + 20, ymin + 20), f"[Asset: {asset_type}]", fill="red")
            
            if scale != 1.0:
                draw_img = draw_img.resize((new_w, new_h))
            img_to_send = draw_img
        else:
            if scale != 1.0:
                img_to_send = img.resize((new_w, new_h))
            else:
                img_to_send = img
                
        img_byte_arr = io.BytesIO()
        img_to_send.save(img_byte_arr, format='JPEG')
        img_bytes = img_byte_arr.getvalue()
    except Exception as e:
        return json.dumps({"error": f"Failed to process image: {str(e)}"})
        
    try:
        genai_client = genai.Client(vertexai=True, project=project_id, location="global")
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        
        full_prompt = f"Wide-angle Context Analysis for Asset class {asset_type}.\n\nInstructions: {prompt}"
        
        response = genai_client.models.generate_content(
            model=model_name,
            contents=[image_part, full_prompt]
        )
        return json.dumps({"analysis_result": response.text})
    except Exception as e:
        return json.dumps({"error": f"Failed to run model analysis: {str(e)}"})

@mcp.tool()
def analyze_panorama_perspective(
    dataset_id: str,
    pano_id: str,
    heading: float,
    pitch: float,
    prompt: str,
    fov: float = 90.0,
    model_name: str = "gemini-3.5-flash"
) -> str:
    """
    Extracts a perspective projection crop from a spherical panorama pano_id,
    submits it to Gemini in Vertex AI, and returns the analysis.
    The raw image never leaves GCP.
    """
    client_bq = bigquery.Client()
    project_id, dataset_id = resolve_dataset(dataset_id, client_bq.project)
    
    query = f"""
    SELECT gcs_uri
    FROM `{project_id}.{dataset_id}.pano_observations_latest`
    WHERE pano_id = @pano_id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("pano_id", "STRING", pano_id)]
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        query_all = f"""
        SELECT gcs_uri
        FROM `{project_id}.{dataset_id}.pano_observations_all`
        WHERE pano_id = @pano_id
        LIMIT 1
        """
        rows = list(client_bq.query(query_all, job_config=job_config).result())
        if not rows:
            return json.dumps({"error": f"Panorama ID not found: {pano_id}"})
            
    gcs_uri = rows[0].gcs_uri
    
    try:
        local_path = download_image_cached(gcs_uri)
    except Exception as e:
        return json.dumps({"error": f"Failed to download panorama image: {str(e)}"})
        
    try:
        perspective_img = equirectangular_to_perspective(local_path, heading, pitch, fov)
        
        img_byte_arr = io.BytesIO()
        perspective_img.save(img_byte_arr, format='JPEG')
        img_bytes = img_byte_arr.getvalue()
    except Exception as e:
        return json.dumps({"error": f"Failed to reproject panorama: {str(e)}"})
        
    try:
        genai_client = genai.Client(vertexai=True, project=project_id, location="global")
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        
        response = genai_client.models.generate_content(
            model=model_name,
            contents=[image_part, prompt]
        )
        return json.dumps({"analysis_result": response.text})
    except Exception as e:
        return json.dumps({"error": f"Failed to run model analysis: {str(e)}"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    transport = os.getenv("MCP_TRANSPORT", "sse")
    mcp.run(transport=transport, host="0.0.0.0", port=port)
