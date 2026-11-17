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

"""Authenticated Cloud Run pole height estimation service using Gemini 4 Hydrogen."""

from __future__ import annotations

from functools import wraps
import os
import re

from flask import Flask, jsonify, request
from google import genai
from google.auth.transport import requests as google_auth_requests
from google.cloud import bigquery
from google.genai import types
from google.oauth2 import id_token
import google.auth

app = Flask(__name__)


def _resolve_default_project() -> str | None:
    project = os.environ.get("PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project and project != "YOUR_PROJECT_ID":
        return project.strip()
    try:
        _, auth_project = google.auth.default()
        return auth_project
    except Exception:
        return None


PROJECT_ID = _resolve_default_project()
GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "global").strip().lower()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-4-hydrogen").strip()
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", "imagery_insights___us").strip()
BIGQUERY_TABLE = os.environ.get(
    "BIGQUERY_TABLE", "full_frame_observations_latest"
).strip()
ALLOWED_GCS_PREFIX = os.environ.get("ALLOWED_GCS_PREFIX", "").strip()
SERVICE_URL = os.environ.get("SERVICE_URL", "").strip()
SERVICE_ACCOUNT_EMAIL = os.environ.get("SERVICE_ACCOUNT_EMAIL", "").strip()
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "true").strip().lower() != "false"
MAX_BYTES_BILLED = int(os.environ.get("MAX_BYTES_BILLED", "2000000000"))
MAX_PROMPT_CHARS = 4000
MAX_OBSERVATIONS = 10

ALLOWED_DATASETS = frozenset({"imagery_insights___us", "imagery_insights___eu"})
ALLOWED_TABLES = frozenset(
    {"full_frame_observations_latest", "cropped_observations_latest"}
)
ALLOWED_MODELS = frozenset(
    {"gemini-4-hydrogen", "gemini-4-carbon", "gemini-4-argon"}
)
ALLOWED_LOCATIONS = frozenset({"global", "us", "eu"})

_BQ_PROJECT_RE = re.compile(r"^[a-z][a-z0-9:-]{4,61}[a-z0-9]$")
_GCS_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
_PLACEHOLDER_BUCKETS = frozenset(
    {"your-allowed-imagery-bucket", "your-imagery-bucket"}
)

DEFAULT_HEIGHT_PROMPT = """
Follow these steps to analyze the image and calculate the height of the utility pole:
1. Identify the utility pole in the image.
2. Find a reference object in the image with a known or easily estimable real-world size (e.g., a car, a standard door, or lane width).
3. Measure the height of the utility pole in pixels.
4. Measure the height of the reference object in pixels.
5. State the estimated real-world height of the reference object.
6. Calculate the real-world height of the utility pole using the pixel ratio and the reference object's height.
7. Provide the final calculated height of the pole in feet.
""".strip()

_bq_client = None
_genai_client = None


def _has_unsafe_uri_chars(value: str) -> bool:
    return any(
        c.isspace() or ord(c) < 32 or ord(c) == 127 or c in "\\?#" for c in value
    )


def normalize_gcs_prefix(prefix: str | None) -> str | None:
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
    normalized = normalize_gcs_prefix(
        ALLOWED_GCS_PREFIX if allowed_prefix is None else allowed_prefix
    )
    if normalized is None:
        return False
    if not isinstance(uri, str) or not uri.startswith("gs://"):
        return False
    if _has_unsafe_uri_chars(uri):
        return False
    segments = uri[5:].split("/")
    if len(segments) < 2 or any(seg in {"", ".", ".."} for seg in segments):
        return False
    return uri.startswith(normalized) and len(uri) > len(normalized)


def _get_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(
            vertexai=True, project=PROJECT_ID, location=GEMINI_LOCATION
        )
    return _genai_client


def verify_bearer_token():
    if not REQUIRE_AUTH:
        return None
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header."}), 401
    token = auth_header[7:].strip()
    if not token:
        return jsonify({"error": "Empty Bearer token."}), 401
    try:
        claims = id_token.verify_oauth2_token(
            token, google_auth_requests.Request(), audience=None
        )
    except Exception:
        return jsonify({"error": "Invalid authentication token."}), 401

    if SERVICE_URL:
        base_url = SERVICE_URL.rstrip("/")
        if claims.get("aud") not in {base_url, f"{base_url}/"}:
            return jsonify({"error": "Forbidden: invalid token audience."}), 403
    if SERVICE_ACCOUNT_EMAIL:
        if (
            claims.get("email") != SERVICE_ACCOUNT_EMAIL
            or not claims.get("email_verified")
        ):
            return jsonify({"error": "Forbidden: unauthorized caller."}), 403
    return None


def require_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        err = verify_bearer_token()
        if err is not None:
            return err
        return func(*args, **kwargs)

    return wrapper


def measure_height_with_gemini(gcs_uri: str, prompt: str) -> str:
    """Measures utility pole height from an allowlisted GCS URI using Gemini 4 Hydrogen."""
    if not is_allowed_gcs_uri(gcs_uri):
        raise ValueError("gcs_uri is outside the configured ALLOWED_GCS_PREFIX.")
    if GEMINI_MODEL not in ALLOWED_MODELS:
        raise ValueError(f"Unsupported GEMINI_MODEL {GEMINI_MODEL!r}.")
    if GEMINI_LOCATION not in ALLOWED_LOCATIONS:
        raise ValueError(f"Unsupported GEMINI_LOCATION {GEMINI_LOCATION!r}.")

    image_part = types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")
    response = _get_genai_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=[image_part, prompt],
    )
    return response.text or ""


@app.route("/", methods=["POST"])
@require_auth
def main():
    """Queries allowlisted Street View Insights observations and estimates pole height."""
    if not PROJECT_ID or not _BQ_PROJECT_RE.match(PROJECT_ID):
        return jsonify({"error": "PROJECT_ID is not configured cleanly."}), 500
    if BIGQUERY_DATASET not in ALLOWED_DATASETS or BIGQUERY_TABLE not in ALLOWED_TABLES:
        return jsonify({"error": "Configured BigQuery dataset or table is not allowlisted."}), 500
    if normalize_gcs_prefix(ALLOWED_GCS_PREFIX) is None:
        return jsonify({"error": "ALLOWED_GCS_PREFIX must be configured with a valid gs:// prefix."}), 500

    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    prompt = data.get("prompt", DEFAULT_HEIGHT_PROMPT)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        return jsonify({"error": f"prompt must be a non-empty string <= {MAX_PROMPT_CHARS} chars."}), 400

    sql = f"""
    SELECT gcs_uri
    FROM `{PROJECT_ID}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}`
    WHERE asset_type = @asset_type
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("asset_type", "STRING", "ASSET_CLASS_UTILITY_POLE"),
            bigquery.ScalarQueryParameter("limit", "INT64", MAX_OBSERVATIONS),
        ],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )

    try:
        rows = list(_get_bq_client().query(sql, job_config=job_config).result())
        gcs_uris = [row.get("gcs_uri") if isinstance(row, dict) else row.gcs_uri for row in rows]
        gcs_uris = [u for u in gcs_uris if u]
    except Exception as e:
        app.logger.error("Error executing BigQuery query: %s", e)
        return jsonify({"error": "BigQuery query failed."}), 500

    if not gcs_uris:
        return jsonify({"message": "No GCS URIs found to measure."}), 200

    measurement_results = []
    for uri in gcs_uris:
        if not is_allowed_gcs_uri(uri):
            return jsonify({"error": "BigQuery returned a gcs_uri outside ALLOWED_GCS_PREFIX."}), 400
        try:
            result = measure_height_with_gemini(uri, prompt.strip())
        except Exception as e:
            app.logger.error("Error measuring height from URI %s: %s", uri, e)
            result = "Height measurement failed."
        measurement_results.append({"gcs_uri": uri, "height_measurement": result})

    return jsonify(measurement_results), 200


if __name__ == "__main__":
    app.run(
        debug=False,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8080")),
    )
