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


import json
import time
import uuid
from flask import Flask, request, jsonify
from google.cloud import bigquery, tasks_v2
from google.api_core import exceptions
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from config import (
    GCP_PROJECT,
    LOCATION,
    BIGQUERY_RESULTS_DATASET,
    BIGQUERY_RESULTS_TABLE,
    BIGQUERY_SOURCE_DATASET,
    BIGQUERY_SOURCE_TABLE,
    TASK_QUEUE_PREFIX,
    GEMINI_MODEL,
    BIGQUERY_SCHEMAS,
    PROMPTS,
    SELECTED_PROMPT_KEY,
    SERVICE_URL,
    SERVICE_ACCOUNT_EMAIL,
    BIGQUERY_SOURCE_QUERY,
    BATCH_SIZE,
)

app = Flask(__name__)

# Initialize clients
bq_client = bigquery.Client(project=GCP_PROJECT)
tasks_client = tasks_v2.CloudTasksClient()
vertexai.init(project=GCP_PROJECT, location=LOCATION)
model = GenerativeModel(GEMINI_MODEL)


@app.route("/setup", methods=["POST"])
def setup():
    """Creates the BigQuery results table and a new Cloud Tasks queue."""
    messages = []
    errors = []
    task_queue_id = f"{TASK_QUEUE_PREFIX}{uuid.uuid4()}"

    # Create BigQuery table
    try:
        schema = BIGQUERY_SCHEMAS[SELECTED_PROMPT_KEY]
        table_id = f"{GCP_PROJECT}.{BIGQUERY_RESULTS_DATASET}.{BIGQUERY_RESULTS_TABLE}"
        table = bigquery.Table(table_id, schema=schema)
        bq_client.create_table(table)
        messages.append("BigQuery table created.")
    except exceptions.Conflict:
        messages.append("BigQuery table already exists.")
    except Exception as e:
        print(f"Error creating BigQuery table: {e}")
        errors.append(f"Error creating BigQuery table: {e}")

    # Create Cloud Tasks queue
    try:
        parent = tasks_v2.CloudTasksClient.common_location_path(GCP_PROJECT, LOCATION)
        queue = {"name": tasks_client.queue_path(GCP_PROJECT, LOCATION, task_queue_id)}
        tasks_client.create_queue(parent=parent, queue=queue)
        messages.append(f"Cloud Tasks queue '{task_queue_id}' created.")
        time.sleep(5)
    except exceptions.Conflict:
        messages.append(f"Cloud Tasks queue '{task_queue_id}' already exists.")
    except Exception as e:
        print(f"Error creating Cloud Tasks queue: {e}")
        errors.append(f"Error creating Cloud Tasks queue: {e}")

    if errors:
        return jsonify({"errors": errors, "messages": messages}), 500
    else:
        return jsonify({"messages": messages, "task_queue_id": task_queue_id}), 200


@app.route("/populate", methods=["POST"])
def populate_tasks():
    """Reads a source BigQuery table and creates a task for each row."""
    data = request.get_json()
    task_queue_id = data.get("task_queue_id")
    if not task_queue_id:
        return jsonify({"error": "task_queue_id not provided."}), 400

    try:
        source_table_id = f"{GCP_PROJECT}.{BIGQUERY_SOURCE_DATASET}.{BIGQUERY_SOURCE_TABLE}"
        offset = data.get("offset", 0)
        query = BIGQUERY_SOURCE_QUERY.format(source_table=source_table_id) + f" LIMIT {BATCH_SIZE} OFFSET {offset}"
        rows = bq_client.query(query).result()
        tasks_created = 0

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
                    "url": f"{SERVICE_URL}/process",
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(payload).encode(),
                    "oidc_token": {
                        "service_account_email": SERVICE_ACCOUNT_EMAIL
                    },
                }
            }
            parent = tasks_client.queue_path(
                GCP_PROJECT, LOCATION, task_queue_id
            )
            tasks_client.create_task(parent=parent, task=task)
            tasks_created += 1

        return jsonify(
            {
                "message": f"Successfully created {tasks_created} tasks.",
                "tasks_created": tasks_created,
            }
        ), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/process", methods=["POST"])
def process_image():
    """Processes a single image analysis task."""
    data = request.get_json()
    if not data:
        print("Error: Received empty request body.")
        return "Error: Empty request body.", 400

    try:
        asset_id = data.get("asset_id")
        location = data.get("location")
        detection_time = data.get("detection_time")
        observations = data.get("observations", [])
        print(f"Processing task for asset_id: {asset_id}")

        image_parts = [
            Part.from_uri(o["gcs_uri"], mime_type="image/jpeg") for o in observations
        ]
        gemini_prompt = PROMPTS[SELECTED_PROMPT_KEY]
        response = model.generate_content([*image_parts, gemini_prompt])

        print(f"Raw Gemini response for {asset_id}: {response.text}")
        try:
            # The response text may be enclosed in ```json ... ```, so we clean it up
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
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
        schema_fields = [field.name for field in BIGQUERY_SCHEMAS[SELECTED_PROMPT_KEY]]
        dynamic_fields = [field for field in schema_fields if field not in result]

        for field in dynamic_fields:
            result[field] = analysis_data.get(field)
        table_id = f"{GCP_PROJECT}.{BIGQUERY_RESULTS_DATASET}.{BIGQUERY_RESULTS_TABLE}"
        errors = bq_client.insert_rows_json(table_id, [result])
        if errors:
            raise Exception(f"BigQuery insert errors: {errors}")

        return "Processing complete.", 200
    except Exception as e:
        asset_id = data.get("asset_id") if data else "unknown"
        print(f"Error processing {asset_id}: {e}")
        return "Error processing image.", 500


@app.route("/teardown", methods=["GET"])
def teardown():
    """Deletes the BigQuery results table and the Cloud Tasks queue."""
    try:
        data = request.get_json()
        task_queue_id = data.get("task_queue_id")
        if not task_queue_id:
            return jsonify({"error": "task_queue_id not provided."}), 400
        
        # Delete BigQuery table
        table_id = f"{GCP_PROJECT}.{BIGQUERY_RESULTS_DATASET}.{BIGQUERY_RESULTS_TABLE}"
        bq_client.delete_table(table_id, not_found_ok=True)

        # Delete Cloud Tasks queue
        name = tasks_client.queue_path(GCP_PROJECT, LOCATION, task_queue_id)
        tasks_client.delete_queue(name=name)

        return jsonify({"message": "Teardown complete."}), 200
    except exceptions.NotFound:
        return jsonify({"message": "Resources not found."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)