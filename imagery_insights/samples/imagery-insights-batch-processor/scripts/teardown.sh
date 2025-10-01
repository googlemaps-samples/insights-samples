#!/bin/bash
# This script calls the /teardown endpoint of the main service
# to clean up the BigQuery table and the Cloud Tasks queue.

set -e

if [ ! -f .env ]; then
    echo "Error: .env file not found. Please run deploy.sh first."
    exit 1
fi

SERVICE_URL=$(grep ^SERVICE_URL .env | cut -d '=' -f2 | tr -d '\r')
TASK_QUEUE_ID=$(grep ^TASK_QUEUE_ID .env | cut -d '=' -f2 | tr -d '\r')
RUN_ID=$(grep ^RUN_ID .env | cut -d '=' -f2 | tr -d '\r')

echo "Calling /teardown endpoint..."
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d "{\"task_queue_id\": \"$TASK_QUEUE_ID\"}" \
    "${SERVICE_URL}/teardown"

echo "Deleting Pub/Sub resources..."
gcloud pubsub subscriptions delete "populate-tasks-sub-${RUN_ID}" --quiet
gcloud pubsub topics delete "populate-tasks-topic-${RUN_ID}" --quiet

echo "Teardown complete. Removing .env file."
rm .env