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

import base64
from functools import wraps
import json
import os
import re

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from google.auth.transport import requests as google_auth_requests
from google.cloud import bigquery, pubsub_v1, tasks_v2
from google.oauth2 import id_token
import requests

import config

load_dotenv()

ANALYZE_SERVICE_URL = os.getenv("ANALYZE_SERVICE_URL") or config.ANALYZE_SERVICE_URL
POPULATE_SERVICE_URL = os.getenv("POPULATE_SERVICE_URL") or config.POPULATE_SERVICE_URL

# Lazily initialized clients so importing the module does not require live ADC.
bq_client = None
publisher = None
subscriber = None
tasks_client = None

app = Flask(__name__)

_BQ_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _get_bq_client():
    global bq_client
    if bq_client is None:
        bq_client = bigquery.Client(project=config.GCP_PROJECT)
    return bq_client


def _get_publisher():
    global publisher
    if publisher is None:
        publisher = pubsub_v1.PublisherClient()
    return publisher


def _get_subscriber():
    global subscriber
    if subscriber is None:
        subscriber = pubsub_v1.SubscriberClient()
    return subscriber


def _get_tasks_client():
    global tasks_client
    if tasks_client is None:
        tasks_client = tasks_v2.CloudTasksClient()
    return tasks_client


def _validate_bq_identifier(value, field_name):
    if not isinstance(value, str) or not _BQ_IDENTIFIER_RE.match(value):
        raise ValueError(f"Invalid BigQuery identifier for {field_name}.")
    return value


def _parse_int(value, field_name, min_value=0, max_value=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer.")
    if value < min_value:
        raise ValueError(f"{field_name} must be >= {min_value}.")
    if max_value is not None and value > max_value:
        raise ValueError(f"{field_name} must be <= {max_value}.")
    return value


def require_auth(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not config.REQUIRE_AUTH:
            return func(*args, **kwargs)

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

        if config.SERVICE_ACCOUNT_EMAIL:
            if (
                claims.get("email") != config.SERVICE_ACCOUNT_EMAIL
                or not claims.get("email_verified")
            ):
                return (
                    jsonify({"error": "Forbidden: unauthorized service account."}),
                    403,
                )

        return func(*args, **kwargs)

    return wrapper


def setup_and_shard(source_project_id=None):
    """
    Calls the /setup endpoint, cleans up and creates Pub/Sub
    resources, and publishes shard messages.
    """
    print("Calling /setup endpoint...")
    if not ANALYZE_SERVICE_URL:
        raise ValueError("ANALYZE_SERVICE_URL environment variable not set.")
    print(f"Using ANALYZE_SERVICE_URL: {ANALYZE_SERVICE_URL}")

    import google.oauth2.id_token

    auth_req = google_auth_requests.Request()
    token = google.oauth2.id_token.fetch_id_token(
        auth_req, audience=ANALYZE_SERVICE_URL.rstrip("/")
    )
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(
        f"{ANALYZE_SERVICE_URL.rstrip('/')}/setup", headers=headers
    )
    response.raise_for_status()
    task_queue_id = response.json()["task_queue_id"]
    run_id = task_queue_id.split("-")[-1]
    with open(".env", "a") as f:
        f.write(f"\nTASK_QUEUE_ID={task_queue_id}")
        f.write(f"\nRUN_ID={run_id}")
    print(f"Setup complete. Using task queue: {task_queue_id}")

    project_to_use = _validate_bq_identifier(
        source_project_id if source_project_id else config.GCP_PROJECT,
        "source_project_id",
    )
    source_dataset = _validate_bq_identifier(
        config.BIGQUERY_SOURCE_DATASET, "BIGQUERY_SOURCE_DATASET"
    )
    source_table = _validate_bq_identifier(
        config.BIGQUERY_SOURCE_TABLE, "BIGQUERY_SOURCE_TABLE"
    )
    source_table_id = f"{project_to_use}.{source_dataset}.{source_table}"

    # Get the total number of rows
    query = config.BIGQUERY_COUNT_QUERY.format(source_table=source_table_id)
    total_rows = next(_get_bq_client().query(query).result()).total_rows

    # Create unique Pub/Sub resources for this run
    topic_id = f"{config.POPULATE_TOPIC_ID_PREFIX}{run_id}"
    subscription_id = f"{config.SUBSCRIPTION_ID_PREFIX}{run_id}"
    pub = _get_publisher()
    sub = _get_subscriber()
    topic_path = pub.topic_path(config.GCP_PROJECT, topic_id)
    subscription_path = sub.subscription_path(config.GCP_PROJECT, subscription_id)

    pub.create_topic(request={"name": topic_path})
    print(f"Created topic: {topic_path}")

    push_config = pubsub_v1.types.PushConfig(
        push_endpoint=POPULATE_SERVICE_URL,
        oidc_token=pubsub_v1.types.PushConfig.OidcToken(
            service_account_email=config.SERVICE_ACCOUNT_EMAIL
        ),
    )
    sub.create_subscription(
        request={
            "name": subscription_path,
            "topic": topic_path,
            "push_config": push_config,
        }
    )
    print(f"Created push subscription: {subscription_path}")

    for offset in range(0, total_rows, config.SHARD_SIZE):
        message = {
            "limit": config.SHARD_SIZE,
            "offset": offset,
            "task_queue_id": task_queue_id,
        }
        pub.publish(topic_path, json.dumps(message).encode("utf-8"))
        print(f"Published message: {message}")


@app.route("/", methods=["POST"])
@require_auth
def process_shard():
    """
    Receives a Pub/Sub message, queries a shard of the BigQuery table,
    and creates a Cloud Task for each row in the shard.
    """
    envelope = request.get_json(silent=True)
    if not isinstance(envelope, dict) or "message" not in envelope:
        return jsonify({"error": "No Pub/Sub message received."}), 400

    analyze_url = (
        os.getenv("ANALYZE_SERVICE_URL")
        or ANALYZE_SERVICE_URL
        or config.ANALYZE_SERVICE_URL
    )
    if not analyze_url or not config.SERVICE_ACCOUNT_EMAIL:
        return (
            jsonify(
                {
                    "error": (
                        "ANALYZE_SERVICE_URL and SERVICE_ACCOUNT_EMAIL must be configured."
                    )
                }
            ),
            500,
        )

    try:
        pubsub_message = envelope["message"]
        data = json.loads(base64.b64decode(pubsub_message["data"]).decode("utf-8"))
        limit = _parse_int(data.get("limit"), "limit", min_value=1, max_value=1000)
        offset = _parse_int(data.get("offset"), "offset", min_value=0)
        task_queue_id = data.get("task_queue_id")
        if not isinstance(task_queue_id, str) or not task_queue_id.strip():
            raise ValueError("task_queue_id must be a non-empty string.")

        project_id = _validate_bq_identifier(config.GCP_PROJECT, "GCP_PROJECT")
        source_dataset = _validate_bq_identifier(
            config.BIGQUERY_SOURCE_DATASET, "BIGQUERY_SOURCE_DATASET"
        )
        source_table = _validate_bq_identifier(
            config.BIGQUERY_SOURCE_TABLE, "BIGQUERY_SOURCE_TABLE"
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
        return jsonify({"error": f"Invalid shard payload: {e}"}), 400

    source_table_id = f"{project_id}.{source_dataset}.{source_table}"
    query = (
        config.BIGQUERY_SOURCE_QUERY.format(source_table=source_table_id)
        + " LIMIT @limit OFFSET @offset"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
            bigquery.ScalarQueryParameter("offset", "INT64", offset),
        ]
    )
    rows = _get_bq_client().query(query, job_config=job_config).result()

    tc = _get_tasks_client()
    parent = tc.queue_path(config.GCP_PROJECT, config.LOCATION, task_queue_id)
    base_url = analyze_url.rstrip("/")

    for row in rows:
        payload = {
            "asset_id": row["asset_id"],
            "location": {
                "latitude": row["location"]["latitude"],
                "longitude": row["location"]["longitude"],
            },
            "detection_time": row["detection_time"].isoformat(),
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
        tc.create_task(parent=parent, task=task)

    return "Processing complete.", 204


# The script can be run in two modes:
# 1. Local execution to initiate the process: `python3 src/populate_with_cloud_run.py`
# 2. As a Flask app on Cloud Run to serve requests.
# The `if __name__ == '__main__':` block handles the local execution,
# while the Cloud Run entrypoint in the `deploy.sh` script will point to the `app` object.

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Populate Cloud Tasks for Batch Processing."
    )
    parser.add_argument(
        "--project-id",
        type=str,
        help=(
            "The GCP project ID containing the source BigQuery dataset. "
            "Defaults to the configured GCP_PROJECT."
        ),
        default=None,
    )
    args = parser.parse_args()

    setup_and_shard(source_project_id=args.project_id)
else:
    # This is the entrypoint for the Cloud Run service
    gunicorn_app = app