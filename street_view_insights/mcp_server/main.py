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

"""Street View Imagery Insights MCP Server (authenticated, in-memory, allowlisted)."""

from __future__ import annotations

import io
import json
import os
import re
from typing import Any

from google import genai
from google.auth.transport import requests as google_auth_requests
from google.cloud import bigquery, storage
from google.genai import types
from google.oauth2 import id_token
from mcp.server.fastmcp import FastMCP
import numpy as np
from PIL import Image, ImageDraw
import uvicorn

DEFAULT_MODEL = "gemini-4-hydrogen"
ALLOWED_MODELS = frozenset(
    {
        m.strip()
        for m in os.getenv(
            "ALLOWED_MODELS",
            "gemini-4-hydrogen,gemini-4-carbon,gemini-4-argon",
        ).split(",")
        if m.strip()
    }
)
ALLOWED_LOCATIONS = frozenset({"global", "us", "eu"})
GEMINI_LOCATION = os.getenv("GEMINI_LOCATION", "global").strip().lower()

DEFAULT_ALLOWED_DATASETS = ("imagery_insights___us", "imagery_insights___eu")
MAX_BYTES_BILLED = int(os.getenv("MAX_BYTES_BILLED", "2000000000"))
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(25 * 1024 * 1024)))
MAX_PROMPT_CHARS = 4000
MAX_ASSET_LIMIT = 100
MAX_OBSERVATIONS_LIMIT = 50
MAX_RADIUS_METERS = 5000.0

REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "true").strip().lower() != "false"
MCP_SERVICE_URL = os.getenv("MCP_SERVICE_URL", "").strip()
ALLOWED_GCS_PREFIX = os.getenv("ALLOWED_GCS_PREFIX", "").strip()

_BQ_PROJECT_RE = re.compile(r"^[a-z][a-z0-9:-]{4,61}[a-z0-9]$")
_BQ_DATASET_RE = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
_GCS_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
_PLACEHOLDER_BUCKETS = frozenset(
    {"your-allowed-imagery-bucket", "your-imagery-bucket", "your_frame_bucket"}
)

# Default bind host: 0.0.0.0 only on Cloud Run (K_SERVICE set), 127.0.0.1 locally.
DEFAULT_HOST = os.getenv("HOST", "0.0.0.0" if os.getenv("K_SERVICE") else "127.0.0.1")
mcp = FastMCP("Street View Imagery Insights", host=DEFAULT_HOST)


def _has_unsafe_uri_chars(value: str) -> bool:
    return any(
        c.isspace() or ord(c) < 32 or ord(c) == 127 or c in "\\?#" for c in value
    )


def normalize_gcs_prefix(prefix: str | None) -> str | None:
    """Validates and normalizes an allowed gs://bucket[/prefix]/ string."""
    if not isinstance(prefix, str):
        return None
    candidate = prefix.strip()
    if not candidate.startswith("gs://") or _has_unsafe_uri_chars(candidate):
        return None
    rest = candidate[5:]
    if not rest:
        return None
    if rest.endswith("/"):
        rest = rest[:-1]
        if rest.endswith("/"):
            return None
    parts = rest.split("/")
    bucket = parts[0]
    if (
        not _GCS_BUCKET_RE.match(bucket)
        or ".." in bucket
        or bucket.lower() in _PLACEHOLDER_BUCKETS
    ):
        return None
    if any(not seg or seg in {".", ".."} for seg in parts[1:]):
        return None
    return f"gs://{rest}/"


def is_allowed_gcs_uri(uri: str | None, allowed_prefix: str | None = None) -> bool:
    """Returns True iff uri is a clean gs:// object path under the allowed prefix."""
    normalized_prefix = normalize_gcs_prefix(
        ALLOWED_GCS_PREFIX if allowed_prefix is None else allowed_prefix
    )
    if normalized_prefix is None:
        return False
    if not isinstance(uri, str) or not uri.startswith("gs://"):
        return False
    if _has_unsafe_uri_chars(uri):
        return False
    rest = uri[5:]
    segments = rest.split("/")
    if len(segments) < 2 or any(seg in {"", ".", ".."} for seg in segments):
        return False
    return uri.startswith(normalized_prefix) and len(uri) > len(normalized_prefix)


def allowed_datasets() -> frozenset[str]:
    extra = [
        d.strip()
        for d in os.getenv("ALLOWED_DATASETS", "").split(",")
        if d.strip()
    ]
    for ds in extra:
        if not _BQ_DATASET_RE.match(ds):
            raise ValueError(f"Invalid dataset in ALLOWED_DATASETS: {ds!r}")
    return frozenset([*DEFAULT_ALLOWED_DATASETS, *extra])


def validate_project_and_dataset(project_id: str | None, dataset_id: str | None) -> tuple[str, str]:
    if not isinstance(project_id, str) or not _BQ_PROJECT_RE.match(project_id.strip()):
        raise ValueError("Invalid GCP project_id.")
    if not isinstance(dataset_id, str) or not _BQ_DATASET_RE.match(dataset_id.strip()):
        raise ValueError("Invalid BigQuery dataset_id.")
    clean_ds = dataset_id.strip()
    if clean_ds not in allowed_datasets():
        raise ValueError(
            f"Dataset {clean_ds!r} is not in ALLOWED_DATASETS {sorted(allowed_datasets())}."
        )
    return project_id.strip(), clean_ds


def validate_model_and_prompt(model_name: str, prompt: str) -> tuple[str, str]:
    clean_model = (model_name or DEFAULT_MODEL).strip()
    if clean_model not in ALLOWED_MODELS:
        raise ValueError(
            f"Model {clean_model!r} is not in ALLOWED_MODELS {sorted(ALLOWED_MODELS)}."
        )
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt exceeds maximum length ({MAX_PROMPT_CHARS} chars).")
    if GEMINI_LOCATION not in ALLOWED_LOCATIONS:
        raise ValueError(
            f"GEMINI_LOCATION {GEMINI_LOCATION!r} must be one of {sorted(ALLOWED_LOCATIONS)}."
        )
    return clean_model, prompt.strip()


def download_image_bytes(gcs_uri: str, project_id: str | None = None) -> bytes:
    """Downloads an allowlisted gs:// object strictly in memory (zero disk writes)."""
    if not is_allowed_gcs_uri(gcs_uri):
        raise ValueError(
            "gcs_uri must be a valid gs:// object under the configured ALLOWED_GCS_PREFIX."
        )
    bucket_name, blob_name = gcs_uri[5:].split("/", 1)
    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.reload(timeout=15)
    if blob.size is not None and blob.size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"GCS object exceeds maximum allowed size ({MAX_IMAGE_BYTES} bytes)."
        )
    data = blob.download_as_bytes(timeout=30)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Downloaded image exceeds maximum allowed size ({MAX_IMAGE_BYTES} bytes)."
        )
    return data


def equirectangular_to_perspective(
    src_img: Image.Image,
    heading_deg: float,
    pitch_deg: float,
    fov_deg: float,
    out_size: tuple[int, int] = (640, 480),
) -> Image.Image:
    if not (10.0 <= float(fov_deg) <= 140.0):
        raise ValueError("fov must be between 10.0 and 140.0 degrees.")
    if not (-90.0 <= float(pitch_deg) <= 90.0):
        raise ValueError("pitch must be between -90.0 and 90.0 degrees.")

    rgb_img = src_img.convert("RGB")
    src_w, src_h = rgb_img.size
    src_data = np.array(rgb_img)

    out_w, out_h = out_size
    heading = np.radians(float(heading_deg))
    pitch = np.radians(float(pitch_deg))
    fov = np.radians(float(fov_deg))

    f = 0.5 * out_w / np.tan(0.5 * fov)
    x = np.arange(out_w) - out_w / 2
    y = np.arange(out_h) - out_h / 2
    xx, yy = np.meshgrid(x, y)

    xyz = np.stack((xx, yy, np.full_like(xx, f)), axis=-1)
    norm = np.linalg.norm(xyz, axis=-1, keepdims=True)
    xyz /= norm

    r_x = np.array(
        [
            [1, 0, 0],
            [0, np.cos(-pitch), -np.sin(-pitch)],
            [0, np.sin(-pitch), np.cos(-pitch)],
        ]
    )
    r_y = np.array(
        [
            [np.cos(-heading), 0, np.sin(-heading)],
            [0, 1, 0],
            [-np.sin(-heading), 0, np.cos(-heading)],
        ]
    )
    rot = r_y @ r_x

    xyz_flat = xyz.reshape(-1, 3)
    xyz_rot = (rot @ xyz_flat.T).T.reshape(out_h, out_w, 3)

    rx = xyz_rot[..., 0]
    ry = xyz_rot[..., 1]
    rz = xyz_rot[..., 2]

    theta = np.arctan2(rx, rz)
    phi = np.arcsin(np.clip(-ry, -1.0, 1.0))

    px_x = np.clip(((theta + np.pi) / (2 * np.pi)) * src_w, 0, src_w - 1).astype(np.int32)
    px_y = np.clip(((np.pi / 2 - phi) / np.pi) * src_h, 0, src_h - 1).astype(np.int32)

    return Image.fromarray(src_data[px_y, px_x])


def _get_bq_client() -> bigquery.Client:
    explicit_project = os.getenv("PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    return bigquery.Client(project=explicit_project or None)


# --- MCP Tools ---


@mcp.tool()
def list_assets(
    dataset_id: str,
    asset_type: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_meters: float = 100.0,
    limit: int = 10,
) -> str:
    """List assets in an allowlisted dataset, filtered by asset class or geographic proximity."""
    try:
        client_bq = _get_bq_client()
        project_id, clean_ds = validate_project_and_dataset(client_bq.project, dataset_id)
        safe_limit = max(1, min(int(limit), MAX_ASSET_LIMIT))
        safe_radius = float(radius_meters)
        if safe_radius <= 0 or safe_radius > MAX_RADIUS_METERS:
            return json.dumps(
                {"error": f"radius_meters must be in (0, {MAX_RADIUS_METERS}]."}
            )
    except (ValueError, TypeError) as e:
        return json.dumps({"error": str(e)})

    where_clauses: list[str] = []
    query_params: list[Any] = []

    if asset_type:
        where_clauses.append("asset_type = @asset_type")
        query_params.append(
            bigquery.ScalarQueryParameter("asset_type", "STRING", str(asset_type))
        )

    if latitude is not None and longitude is not None:
        where_clauses.append(
            "ST_DWITHIN(ST_GEOGPOINT(location.longitude, location.latitude), "
            "ST_GEOGPOINT(@lng, @lat), @radius)"
        )
        query_params.append(
            bigquery.ScalarQueryParameter("lat", "FLOAT64", float(latitude))
        )
        query_params.append(
            bigquery.ScalarQueryParameter("lng", "FLOAT64", float(longitude))
        )
        query_params.append(
            bigquery.ScalarQueryParameter("radius", "FLOAT64", safe_radius)
        )

    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
    SELECT asset_id, asset_type, location, detection_time
    FROM `{project_id}.{clean_ds}.full_frame_assets_latest`
    {where_str}
    LIMIT @limit
    """
    query_params.append(bigquery.ScalarQueryParameter("limit", "INT64", safe_limit))

    job_config = bigquery.QueryJobConfig(
        query_parameters=query_params,
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = list(client_bq.query(query, job_config=job_config).result())

    results = [
        {
            "asset_id": r.asset_id,
            "asset_type": r.asset_type,
            "location": (
                {
                    "latitude": r.location.get("latitude"),
                    "longitude": r.location.get("longitude"),
                }
                if r.location
                else None
            ),
            "detection_time": str(r.detection_time) if r.detection_time else None,
        }
        for r in rows
    ]
    return json.dumps(results, indent=2)


@mcp.tool()
def get_asset_observations(dataset_id: str, asset_id: str) -> str:
    """Retrieve latest full-frame observations for a specific asset ID."""
    try:
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError("asset_id must be a non-empty string.")
        client_bq = _get_bq_client()
        project_id, clean_ds = validate_project_and_dataset(client_bq.project, dataset_id)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    query = f"""
    SELECT observation_id, gcs_uri, bbox, pano_id, capture_time, camera_pose, asset_type
    FROM `{project_id}.{clean_ds}.full_frame_observations_latest`
    WHERE asset_id = @asset_id
    ORDER BY capture_time DESC
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("asset_id", "STRING", asset_id.strip()),
            bigquery.ScalarQueryParameter("limit", "INT64", MAX_OBSERVATIONS_LIMIT),
        ],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = list(client_bq.query(query, job_config=job_config).result())

    results = [
        {
            "observation_id": r.observation_id,
            "gcs_uri": r.gcs_uri,
            "bbox": dict(r.bbox) if r.bbox else None,
            "pano_id": r.pano_id,
            "capture_time": str(r.capture_time) if r.capture_time else None,
            "camera_pose": dict(r.camera_pose) if r.camera_pose else None,
            "asset_type": r.asset_type,
        }
        for r in rows
    ]
    return json.dumps(results, indent=2)


@mcp.tool()
def analyze_cropped_asset(
    dataset_id: str,
    observation_id: str,
    prompt: str,
    padding_pixels: int = 50,
    model_name: str = DEFAULT_MODEL,
) -> str:
    """Streams the full-frame observation in memory, crops to bbox, and runs Gemini on GCP."""
    try:
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise ValueError("observation_id must be a non-empty string.")
        clean_model, clean_prompt = validate_model_and_prompt(model_name, prompt)
        safe_padding = max(0, min(int(padding_pixels), 500))
        client_bq = _get_bq_client()
        project_id, clean_ds = validate_project_and_dataset(client_bq.project, dataset_id)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": str(e)})

    query = f"""
    SELECT gcs_uri, bbox, asset_type
    FROM `{project_id}.{clean_ds}.full_frame_observations_latest`
    WHERE observation_id = @observation_id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "observation_id", "STRING", observation_id.strip()
            )
        ],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        return json.dumps({"error": f"Observation not found: {observation_id}"})

    row = rows[0]
    gcs_uri = row.gcs_uri
    bbox = row.bbox
    asset_type = row.asset_type

    if not gcs_uri or not bbox:
        return json.dumps({"error": "Observation lacks gcs_uri or bbox metadata."})

    try:
        raw_bytes = download_image_bytes(gcs_uri, project_id=project_id)
    except Exception as e:
        return json.dumps({"error": f"Failed to download image: {e}"})

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            rgb_img = img.convert("RGB")
            w, h = rgb_img.size
            y1 = bbox.get("ymin", bbox.get("lo", {}).get("y", 0))
            x1 = bbox.get("xmin", bbox.get("lo", {}).get("x", 0))
            y2 = bbox.get("ymax", bbox.get("hi", {}).get("y", h))
            x2 = bbox.get("xmax", bbox.get("hi", {}).get("x", w))

            xmin, xmax = min(x1, x2), max(x1, x2)
            ymin, ymax = min(y1, y2), max(y1, y2)

            if xmax <= w and ymax <= h:
                left = max(0, xmin - safe_padding)
                top = max(0, ymin - safe_padding)
                right = min(w, xmax + safe_padding)
                bottom = min(h, ymax + safe_padding)
                img_to_send = (
                    rgb_img.crop((left, top, right, bottom))
                    if left < right and top < bottom
                    else rgb_img
                )
            else:
                img_to_send = rgb_img

            img_byte_arr = io.BytesIO()
            img_to_send.save(img_byte_arr, format="JPEG", quality=90)
            img_bytes = img_byte_arr.getvalue()
    except Exception as e:
        return json.dumps({"error": f"Failed to crop image: {e}"})

    try:
        genai_client = genai.Client(
            vertexai=True, project=project_id, location=GEMINI_LOCATION
        )
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        full_prompt = f"Asset Type: {asset_type}\n\nInstructions: {clean_prompt}"
        response = genai_client.models.generate_content(
            model=clean_model,
            contents=[image_part, full_prompt],
        )
        return json.dumps({"analysis_result": response.text})
    except Exception as e:
        return json.dumps({"error": f"Failed to run model analysis: {e}"})


@mcp.tool()
def analyze_full_frame_context(
    dataset_id: str,
    observation_id: str,
    prompt: str,
    draw_bbox: bool = True,
    model_name: str = DEFAULT_MODEL,
) -> str:
    """Streams the full-frame observation in memory, optionally overlays bbox, and runs Gemini."""
    try:
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise ValueError("observation_id must be a non-empty string.")
        clean_model, clean_prompt = validate_model_and_prompt(model_name, prompt)
        client_bq = _get_bq_client()
        project_id, clean_ds = validate_project_and_dataset(client_bq.project, dataset_id)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": str(e)})

    query = f"""
    SELECT gcs_uri, bbox, asset_type
    FROM `{project_id}.{clean_ds}.full_frame_observations_latest`
    WHERE observation_id = @observation_id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "observation_id", "STRING", observation_id.strip()
            )
        ],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        return json.dumps({"error": f"Observation not found: {observation_id}"})

    row = rows[0]
    gcs_uri = row.gcs_uri
    bbox = row.bbox
    asset_type = row.asset_type

    if not gcs_uri:
        return json.dumps({"error": "Observation lacks gcs_uri."})

    try:
        raw_bytes = download_image_bytes(gcs_uri, project_id=project_id)
    except Exception as e:
        return json.dumps({"error": f"Failed to download image: {e}"})

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            rgb_img = img.convert("RGB")
            w, h = rgb_img.size
            max_dim = 1600
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                new_w, new_h = int(w * scale), int(h * scale)
            else:
                scale = 1.0
                new_w, new_h = w, h

            if draw_bbox and bbox:
                draw_img = rgb_img.copy()
                draw = ImageDraw.Draw(draw_img)
                y1 = bbox.get("ymin", bbox.get("lo", {}).get("y", 0))
                x1 = bbox.get("xmin", bbox.get("lo", {}).get("x", 0))
                y2 = bbox.get("ymax", bbox.get("hi", {}).get("y", h))
                x2 = bbox.get("xmax", bbox.get("hi", {}).get("x", w))
                xmin, xmax = min(x1, x2), max(x1, x2)
                ymin, ymax = min(y1, y2), max(y1, y2)
                draw.rectangle([xmin, ymin, xmax, ymax], outline="red", width=12)
                draw.text((xmin + 20, ymin + 20), f"[Asset: {asset_type}]", fill="red")
                img_to_send = (
                    draw_img.resize((new_w, new_h)) if scale != 1.0 else draw_img
                )
            else:
                img_to_send = (
                    rgb_img.resize((new_w, new_h)) if scale != 1.0 else rgb_img
                )

            img_byte_arr = io.BytesIO()
            img_to_send.save(img_byte_arr, format="JPEG", quality=90)
            img_bytes = img_byte_arr.getvalue()
    except Exception as e:
        return json.dumps({"error": f"Failed to process image: {e}"})

    try:
        genai_client = genai.Client(
            vertexai=True, project=project_id, location=GEMINI_LOCATION
        )
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        full_prompt = (
            f"Wide-angle Context Analysis for Asset class {asset_type}.\n\n"
            f"Instructions: {clean_prompt}"
        )
        response = genai_client.models.generate_content(
            model=clean_model,
            contents=[image_part, full_prompt],
        )
        return json.dumps({"analysis_result": response.text})
    except Exception as e:
        return json.dumps({"error": f"Failed to run model analysis: {e}"})


@mcp.tool()
def analyze_panorama_perspective(
    dataset_id: str,
    pano_id: str,
    heading: float,
    pitch: float,
    prompt: str,
    fov: float = 90.0,
    model_name: str = DEFAULT_MODEL,
) -> str:
    """Extracts an in-memory perspective crop from a panoramic capture and runs Gemini."""
    try:
        if not isinstance(pano_id, str) or not pano_id.strip():
            raise ValueError("pano_id must be a non-empty string.")
        clean_model, clean_prompt = validate_model_and_prompt(model_name, prompt)
        client_bq = _get_bq_client()
        project_id, clean_ds = validate_project_and_dataset(client_bq.project, dataset_id)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": str(e)})

    query = f"""
    SELECT gcs_uri
    FROM `{project_id}.{clean_ds}.pano_observations_latest`
    WHERE pano_id = @pano_id OR capture_id = @pano_id OR observation_id = @pano_id
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("pano_id", "STRING", pano_id.strip())
        ],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = list(client_bq.query(query, job_config=job_config).result())
    if not rows:
        return json.dumps({"error": f"Panorama ID not found: {pano_id}"})

    gcs_uri = rows[0].gcs_uri
    try:
        raw_bytes = download_image_bytes(gcs_uri, project_id=project_id)
    except Exception as e:
        return json.dumps({"error": f"Failed to download panorama image: {e}"})

    try:
        with Image.open(io.BytesIO(raw_bytes)) as src_img:
            perspective_img = equirectangular_to_perspective(
                src_img, heading, pitch, fov
            )
            img_byte_arr = io.BytesIO()
            perspective_img.save(img_byte_arr, format="JPEG", quality=90)
            img_bytes = img_byte_arr.getvalue()
    except Exception as e:
        return json.dumps({"error": f"Failed to reproject panorama: {e}"})

    try:
        genai_client = genai.Client(
            vertexai=True, project=project_id, location=GEMINI_LOCATION
        )
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
        response = genai_client.models.generate_content(
            model=clean_model,
            contents=[image_part, clean_prompt],
        )
        return json.dumps({"analysis_result": response.text})
    except Exception as e:
        return json.dumps({"error": f"Failed to run model analysis: {e}"})


def _allowed_caller_emails() -> frozenset[str]:
    emails = {
        e.strip().lower()
        for e in os.getenv("ALLOWED_CALLER_EMAILS", "").split(",")
        if e.strip()
    }
    sa = os.getenv("SERVICE_ACCOUNT_EMAIL", "").strip().lower()
    if sa:
        emails.add(sa)
    return frozenset(emails)


def verify_oidc_bearer_header(auth_header: str | None) -> tuple[int, str] | None:
    """Verifies a Google-signed OIDC Bearer token; returns (status, message) on failure."""
    if not REQUIRE_AUTH:
        return None
    if not isinstance(auth_header, str) or not auth_header.startswith("Bearer "):
        return 401, "Missing or invalid Authorization Bearer header."
    token = auth_header[7:].strip()
    if not token:
        return 401, "Empty Bearer token."

    try:
        claims = id_token.verify_oauth2_token(
            token, google_auth_requests.Request(), audience=None
        )
    except Exception:
        return 401, "Invalid authentication token."

    if MCP_SERVICE_URL:
        base_url = MCP_SERVICE_URL.rstrip("/")
        valid_audiences = {base_url, f"{base_url}/sse", f"{base_url}/messages"}
        if claims.get("aud") not in valid_audiences:
            return 403, "Forbidden: invalid token audience."

    allowed_emails = _allowed_caller_emails()
    if allowed_emails:
        email = str(claims.get("email") or "").strip().lower()
        if not claims.get("email_verified") or email not in allowed_emails:
            return 403, "Forbidden: caller is not an authorized principal."

    return None


class BearerAuthMiddleware:
    """ASGI middleware enforcing Google OIDC Bearer authentication on HTTP/SSE endpoints."""

    def __init__(self, inner_app: Any):
        self.inner_app = inner_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.inner_app(scope, receive, send)
            return

        headers = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in scope.get("headers", [])
        }
        err = verify_oidc_bearer_header(headers.get("authorization"))
        if err is not None:
            status_code, message = err
            payload = json.dumps({"error": message}).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": status_code,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(payload)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": payload})
            return

        await self.inner_app(scope, receive, send)


# Mount authenticated SSE transport Starlette app
app = BearerAuthMiddleware(mcp.sse_app())


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "sse").strip().lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        port = int(os.getenv("PORT", "8080"))
        uvicorn.run(app, host=DEFAULT_HOST, port=port)
