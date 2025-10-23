import os
import json
import base64
import requests
from flask import Flask, request
from google.cloud import bigquery, pubsub_v1, tasks_v2
from dotenv import load_dotenv
from config import (
    GCP_PROJECT,
    LOCATION,
    BIGQUERY_SOURCE_DATASET,
    BIGQUERY_SOURCE_TABLE,
    BIGQUERY_SOURCE_QUERY,
    BIGQUERY_COUNT_QUERY,
    TASK_QUEUE_PREFIX,
    SERVICE_ACCOUNT_EMAIL,
    SHARD_SIZE,
    POPULATE_TOPIC_ID_PREFIX,
    SUBSCRIPTION_ID_PREFIX,
)

load_dotenv()

SERVICE_URL = os.getenv("SERVICE_URL")
POPULATE_SERVICE_URL = os.getenv("POPULATE_SERVICE_URL")

# Configuration


# Initialize clients
bq_client = bigquery.Client(project=GCP_PROJECT)
publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()
tasks_client = tasks_v2.CloudTasksClient()

app = Flask(__name__)

def setup_and_shard():
    """
    Calls the /setup endpoint, cleans up and creates Pub/Sub
    resources, and publishes shard messages.
    """
    # Call the /setup endpoint
    print("Calling /setup endpoint...")
    if not SERVICE_URL:
        raise ValueError("SERVICE_URL environment variable not set.")
    print(f"Using SERVICE_URL: {SERVICE_URL}")
    response = requests.post(f"{SERVICE_URL}/setup")
    response.raise_for_status()
    task_queue_id = response.json()["task_queue_id"]
    run_id = task_queue_id.split("-")[-1]
    with open(".env", "a") as f:
        f.write(f"\nTASK_QUEUE_ID={task_queue_id}")
        f.write(f"\nRUN_ID={run_id}")
    print(f"Setup complete. Using task queue: {task_queue_id}")

    source_table_id = f"{GCP_PROJECT}.{BIGQUERY_SOURCE_DATASET}.{BIGQUERY_SOURCE_TABLE}"
    
    # Get the total number of rows
    query = BIGQUERY_COUNT_QUERY.format(source_table=source_table_id)
    total_rows = next(bq_client.query(query).result()).total_rows
    
    # Create unique Pub/Sub resources for this run
    topic_id = f"{POPULATE_TOPIC_ID_PREFIX}{run_id}"
    subscription_id = f"{SUBSCRIPTION_ID_PREFIX}{run_id}"
    topic_path = publisher.topic_path(GCP_PROJECT, topic_id)
    subscription_path = subscriber.subscription_path(GCP_PROJECT, subscription_id)

    # Create the Pub/Sub topic
    publisher.create_topic(request={"name": topic_path})
    print(f"Created topic: {topic_path}")

    # Create the Pub/Sub subscription
    push_config = pubsub_v1.types.PushConfig(
        push_endpoint=POPULATE_SERVICE_URL,
        oidc_token=pubsub_v1.types.PushConfig.OidcToken(
            service_account_email=SERVICE_ACCOUNT_EMAIL
        ),
    )
    subscriber.create_subscription(
        request={
            "name": subscription_path,
            "topic": topic_path,
            "push_config": push_config,
        }
    )
    print(f"Created push subscription: {subscription_path}")


    # Publish a message for each shard
    for offset in range(0, total_rows, SHARD_SIZE):
        message = {
            "limit": SHARD_SIZE,
            "offset": offset,
            "task_queue_id": task_queue_id,
        }
        publisher.publish(topic_path, json.dumps(message).encode("utf-8"))
        print(f"Published message: {message}")

@app.route("/", methods=["POST"])
def process_shard():
    """
    Receives a Pub/Sub message, queries a shard of the BigQuery table,
    and creates a Cloud Task for each row in the shard.
    """
    envelope = request.get_json()
    if not envelope:
        return "No Pub/Sub message received", 400

    pubsub_message = envelope["message"]
    data = json.loads(base64.b64decode(pubsub_message["data"]).decode("utf-8"))
    
    limit = data["limit"]
    offset = data["offset"]
    task_queue_id = data["task_queue_id"]

    source_table_id = f"{GCP_PROJECT}.{BIGQUERY_SOURCE_DATASET}.{BIGQUERY_SOURCE_TABLE}"
    query = BIGQUERY_SOURCE_QUERY.format(source_table=source_table_id) + f" LIMIT {limit} OFFSET {offset}"
    rows = bq_client.query(query).result()

    parent = tasks_client.queue_path(GCP_PROJECT, LOCATION, task_queue_id)

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
                "url": f"{SERVICE_URL}/process",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode(),
                "oidc_token": {
                    "service_account_email": SERVICE_ACCOUNT_EMAIL
                },
            }
        }
        tasks_client.create_task(parent=parent, task=task)

    return "Processing complete.", 204

# The script can be run in two modes:
# 1. Local execution to initiate the process: `python3 src/populate_with_cloud_run.py`
# 2. As a Flask app on Cloud Run to serve requests.
# The `if __name__ == '__main__':` block handles the local execution,
# while the Cloud Run entrypoint in the `deploy.sh` script will point to the `app` object.

if __name__ == "__main__":
    setup_and_shard()
else:
    # This is the entrypoint for the Cloud Run service
    gunicorn_app = app