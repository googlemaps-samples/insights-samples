#!/bin/bash
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

# This script calls the /teardown endpoint of the main service
# to clean up the BigQuery table and the Cloud Tasks queue.

set -e

if [ ! -f .env ]; then
    echo "Error: .env file not found. Please run deploy.sh first."
    exit 1
fi

# Load variables from .env file
source .env

TARGET_URL="${ANALYZE_SERVICE_URL:-$SERVICE_URL}"

# Check if TASK_QUEUE_ID exists and call teardown endpoint for the main service resources
if [ -n "$TASK_QUEUE_ID" ] && [ -n "$TARGET_URL" ]; then
    echo "Calling /teardown endpoint for queue: $TASK_QUEUE_ID..."
    curl -fsS -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
        -H "Content-Type: application/json" \
        -d "{\"task_queue_id\": \"$TASK_QUEUE_ID\"}" \
        "${TARGET_URL%/}/teardown"
else
    echo "TASK_QUEUE_ID or service URL not found in .env, skipping Cloud Tasks and BigQuery teardown."
fi

# Check if RUN_ID exists and delete Pub/Sub resources
if [ -n "$RUN_ID" ]; then
    echo "Deleting Pub/Sub resources for run: $RUN_ID..."
    # Use || true to prevent the script from exiting if the resource is already deleted
    gcloud pubsub subscriptions delete "populate-tasks-sub-${RUN_ID}" --quiet || true
    gcloud pubsub topics delete "populate-tasks-topic-${RUN_ID}" --quiet || true
else
    echo "RUN_ID not found in .env, skipping Pub/Sub teardown."
fi

# Delete Cloud Run services
echo "Deleting Cloud Run services..."
gcloud run services delete analyze-volume-images --region "$REGION" --quiet || true
gcloud run services delete populate-tasks --region "$REGION" --quiet || true

echo "Teardown complete. Removing .env file."
rm .env