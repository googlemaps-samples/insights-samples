# Copyright 2023 Google LLC
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

from functools import wraps
import json
import re
import time
import uuid

from flask import Flask, jsonify, request
from google.api_core import exceptions
from google.auth.transport import requests as google_auth_requests
from google.cloud import bigquery, tasks_v2
from google.oauth2 import id_token
import vertexai
from vertexai.generative_models import GenerativeModel, Part

import config

app = Flask(__name__)

# Lazily initialized clients so importing the module does not require live ADC.
bq_client = None
tasks_client = None
model = None

_BQ_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _get_bq_client():
    global bq_client
    if bq_client is None:
        bq_client = bigquery.Client(project=config.GCP_PROJECT)
    return bq_client


def _get_tasks_client():
    global tasks_client
    if tasks_client is None:
        tasks_client = tasks_v2.CloudTasksClient()
    return tasks_client


def _get_model():
    global model
    if model is None:
        vertexai.init(project=config.GCP_PROJECT, location=config.LOCATION)
        model = GenerativeModel(config.GEMINI_MODEL)
    return model


def _validate_bq_identifier(value, field_name):
    if not isinstance(value, str) or not _BQ_IDENTIFIER_RE.match(value):
        raise ValueError(f"Invalid BigQuery identifier for {field_name}.")
    return value


def _parse_non_negative_int(value, field_name):
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-negative integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        parsed = int(value.strip())
    else:
        raise ValueError(f"{field_name} must be a non-negative integer.")
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")
    return parsed


def verify_bearer_token(require_service_account=False):
    """Verifies an incoming Google-signed OIDC Bearer token."""
    if not config.REQUIRE_AUTH:
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

    if require_service_account:
        if config.ANALYZE_SERVICE_URL:
            base_url = config.ANALYZE_SERVICE_URL.rstrip("/")
            if claims.get("aud") not in {base_url, f"{base_url}/process"}:
                return jsonify({"error": "Forbidden: invalid token audience."}), 403
        if config.SERVICE_ACCOUNT_EMAIL:
            if (
                claims.get("email") != config.SERVICE_ACCOUNT_EMAIL
                or not claims.get("email_verified")
            ):
                return (
                    jsonify({"error": "Forbidden: unauthorized service account."}),
                    403,
                )

    return None


def require_auth(require_service_account=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            auth_error = verify_bearer_token(
                require_service_account=require_service_account
            )
            if auth_error is not None:
                return auth_error
            return func(*args, **kwargs)

        return wrapper

    return decorator


@app.route("/setup", methods=["POST"])
@require_auth()
def setup():
    """Creates the BigQuery results table and a new Cloud Tasks queue."""
    messages = []
    errors = []
    task_queue_id = f"{config.TASK_QUEUE_PREFIX}{uuid.uuid4()}"

    # Create BigQuery table
    try:
        schema = config.BIGQUERY_SCHEMAS[config.SELECTED_PROMPT_KEY]
        table_id = (
            f"{config.GCP_PROJECT}."
            f"{config.BIGQUERY_RESULTS_DATASET}."
            f"{config.BIGQUERY_RESULTS_TABLE}"
        )
        table = bigquery.Table(table_id, schema=schema)
        _get_bq_client().create_table(table)
        messages.append("BigQuery table created.")
    except exceptions.Conflict:
        messages.append("BigQuery table already exists.")
    except Exception as e:
        print(f"Error creating BigQuery table: {e}")
        errors.append(f"Error creating BigQuery table: {e}")

    # Create Cloud Tasks queue
    try:
        parent = tasks_v2.CloudTasksClient.common_location_path(
            config.GCP_PROJECT, config.LOCATION
        )
        tc = _get_tasks_client()
        queue = {
            "name": tc.queue_path(config.GCP_PROJECT, config.LOCATION, task_queue_id)
        }
        tc.create_queue(parent=parent, queue=queue)
        messages.append(f"Cloud Tasks queue '{task_queue_id}' created.")
        time.sleep(5)
    except exceptions.Conflict:
        messages.append(f"Cloud Tasks queue '{task_queue_id}' already exists.")
    except Exception as e:
        print(f"Error creating Cloud Tasks queue: {e}")
        errors.append(f"Error creating Cloud Tasks queue: {e}")

    if errors:
        return jsonify({"errors": errors, "messages": messages}), 500
    return jsonify({"messages": messages, "task_queue_id": task_queue_id}), 200


@app.route("/populate", methods=["POST"])
@require_auth()
def populate_tasks():
    """Reads a source BigQuery table and creates a task for each row."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid or empty JSON request body."}), 400

    task_queue_id = data.get("task_queue_id")
    if not isinstance(task_queue_id, str) or not task_queue_id.strip():
        return jsonify({"error": "task_queue_id not provided."}), 400

    try:
        offset = _parse_non_negative_int(data.get("offset", 0), "offset")
        project_id = _validate_bq_identifier(config.GCP_PROJECT, "GCP_PROJECT")
        source_dataset = _validate_bq_identifier(
            config.BIGQUERY_SOURCE_DATASET, "BIGQUERY_SOURCE_DATASET"
        )
        source_table = _validate_bq_identifier(
            config.BIGQUERY_SOURCE_TABLE, "BIGQUERY_SOURCE_TABLE"
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        source_table_id = f"{project_id}.{source_dataset}.{source_table}"
        query = (
            config.BIGQUERY_SOURCE_QUERY.format(source_table=source_table_id)
            + " LIMIT @limit OFFSET @offset"
        )
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("limit", "INT64", config.BATCH_SIZE),
                bigquery.ScalarQueryParameter("offset", "INT64", offset),
            ]
        )
        rows = _get_bq_client().query(query, job_config=job_config).result()
        tasks_created = 0
        base_url = (config.ANALYZE_SERVICE_URL or request.url_root).rstrip("/")
        tc = _get_tasks_client()

        for row in rows:
            payload = {
                "asset_id": row["asset_id"],
                "location": str(row["location"]),
                "observations": [
                    {"observation_id": o["observation_id"], "gcs_uri": o["gcs_uri"]}
                    for o in row["observations"]
                ],
            }
            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"{base_url}/process",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(payload).encode(),
                    "oidc_token": {
                        "service_account_email": config.SERVICE_ACCOUNT_EMAIL,
                        "audience": base_url,
                    },
                }
            }
            parent = tc.queue_path(
                config.GCP_PROJECT, config.LOCATION, task_queue_id
            )
            tc.create_task(parent=parent, task=task)
            tasks_created += 1

        return (
            jsonify(
                {
                    "message": f"Successfully created {tasks_created} tasks.",
                    "tasks_created": tasks_created,
                }
            ),
            202,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/process", methods=["POST"])
@require_auth(require_service_account=True)
def process_image():
    """Processes a single image analysis task."""
    if config.normalize_gcs_prefix(config.ALLOWED_GCS_PREFIX) is None:
        return (
            jsonify(
                {
                    "error": (
                        "ALLOWED_GCS_PREFIX is not configured with a valid gs:// prefix."
                    )
                }
            ),
            500,
        )

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        print("Error: Received empty or invalid JSON request body.")
        return jsonify({"error": "Invalid or empty JSON request body."}), 400

    observations = data.get("observations")
    if not isinstance(observations, list) or not observations:
        return jsonify({"error": "observations must be a non-empty list."}), 400

    for obs in observations:
        if (
            not isinstance(obs, dict)
            or not isinstance(obs.get("observation_id"), str)
            or not obs["observation_id"]
        ):
            return (
                jsonify(
                    {"error": "Each observation must include a non-empty observation_id."}
                ),
                400,
            )
        if not config.is_allowed_gcs_uri(
            obs.get("gcs_uri"), config.ALLOWED_GCS_PREFIX
        ):
            print("Rejecting observation with gcs_uri outside ALLOWED_GCS_PREFIX.")
            return (
                jsonify(
                    {"error": "gcs_uri must be under the configured ALLOWED_GCS_PREFIX."}
                ),
                400,
            )

    try:
        asset_id = data.get("asset_id")
        location = data.get("location")
        detection_time = data.get("detection_time")
        print(f"Processing task for asset_id: {asset_id}")

        image_parts = [
            Part.from_uri(o["gcs_uri"], mime_type="image/jpeg") for o in observations
        ]
        gemini_prompt = config.PROMPTS[config.SELECTED_PROMPT_KEY]
        response = _get_model().generate_content([*image_parts, gemini_prompt])

        print(f"Raw Gemini response for {asset_id}: {response.text}")
        try:
            # The response text may be enclosed in ```json ... ```, so we clean it up
            cleaned_response = (
                response.text.strip().replace("```json", "").replace("```", "")
            )
            analysis_data = json.loads(cleaned_response)
        except json.JSONDecodeError:
            analysis_data = {"error": "Invalid JSON response from model."}

        # Dynamically build the result dictionary based on the selected schema
        result = {
            "asset_id": asset_id,
            "location": location,
            "detection_time": detection_time,
            "observation_ids": [o["observation_id"] for o in observations],
            "gcs_uris": [o["gcs_uri"] for o in observations],
        }
        # Get the schema fields, skipping the base fields that are already added
        schema_fields = [
            field.name for field in config.BIGQUERY_SCHEMAS[config.SELECTED_PROMPT_KEY]
        ]
        dynamic_fields = [field for field in schema_fields if field not in result]

        for field in dynamic_fields:
            result[field] = analysis_data.get(field)
        table_id = (
            f"{config.GCP_PROJECT}."
            f"{config.BIGQUERY_RESULTS_DATASET}."
            f"{config.BIGQUERY_RESULTS_TABLE}"
        )
        errors = _get_bq_client().insert_rows_json(table_id, [result])
        if errors:
            raise Exception(f"BigQuery insert errors: {errors}")

        return "Processing complete.", 200
    except Exception as e:
        asset_id = data.get("asset_id") if data else "unknown"
        print(f"Error processing {asset_id}: {e}")
        return "Error processing image.", 500


@app.route("/teardown", methods=["POST", "DELETE"])
@require_auth()
def teardown():
    """Deletes the BigQuery results table and the Cloud Tasks queue."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid or empty JSON request body."}), 400

    task_queue_id = data.get("task_queue_id")
    if not isinstance(task_queue_id, str) or not task_queue_id.strip():
        return jsonify({"error": "task_queue_id not provided."}), 400

    try:
        # Delete BigQuery table
        table_id = (
            f"{config.GCP_PROJECT}."
            f"{config.BIGQUERY_RESULTS_DATASET}."
            f"{config.BIGQUERY_RESULTS_TABLE}"
        )
        _get_bq_client().delete_table(table_id, not_found_ok=True)

        # Delete Cloud Tasks queue
        tc = _get_tasks_client()
        name = tc.queue_path(config.GCP_PROJECT, config.LOCATION, task_queue_id)
        tc.delete_queue(name=name)

        return jsonify({"message": "Teardown complete."}), 200
    except exceptions.NotFound:
        return jsonify({"message": "Resources not found."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)