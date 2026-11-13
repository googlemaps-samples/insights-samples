#!/bin/bash
# Script to configure IAM permissions and provision a direct-to-BigQuery Pub/Sub subscription.
# Follows production-grade infrastructure automation standards for Google Cloud.
# Supports both recommended JSON-encoded topics (-json) and binary Protobuf topics.

set -euo pipefail

# 1. Configuration variables (Configure these for your environment)
PROJECT_ID="${PROJECT_ID:-my-project-id}"
PROJECT_NUMBER="${PROJECT_NUMBER:-123456789012}"
SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-rmi-realtime-sub}"
DATASET_ID="${DATASET_ID:-rmi_realtime}"
TABLE_ID="${TABLE_ID:-roads_information_landing}"
# Topic encoding option:
# - "json":   Subscribes to rmi-roadsinformation-PROJECT_NUMBER-json (Recommended for BigQuery subscriptions)
# - "binary": Subscribes to rmi-roadsinformation-PROJECT_NUMBER (Standard Protobuf binary topic)
ENCODING="${ENCODING:-json}"

# Derived names
if [[ "${ENCODING}" == "json" ]]; then
  TOPIC_PATH="projects/maps-platform-roads-management/topics/rmi-roadsinformation-${PROJECT_NUMBER}-json"
else
  TOPIC_PATH="projects/maps-platform-roads-management/topics/rmi-roadsinformation-${PROJECT_NUMBER}"
fi
BQ_TABLE_PATH="${PROJECT_ID}:${DATASET_ID}.${TABLE_ID}"
PUBSUB_SERVICE_ACCOUNT="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

echo "=========================================================================="
echo "Configuring Direct BigQuery Ingestion for RMI Real-Time Telemetry"
echo "=========================================================================="
echo "Project ID:           ${PROJECT_ID}"
echo "Project Number:       ${PROJECT_NUMBER}"
echo "Encoding:             ${ENCODING}"
echo "Topic Path:           ${TOPIC_PATH}"
echo "Target BigQuery:      ${BQ_TABLE_PATH}"
echo "Subscription ID:      ${SUBSCRIPTION_ID}"
echo "=========================================================================="

# 2. Grant IAM permissions to the Google-managed Pub/Sub service account
# Pub/Sub requires BigQuery Data Editor and Metadata Viewer permissions on the target dataset/table.
echo "1. Granting IAM permissions to Pub/Sub Service Account..."

echo "   Adding bigquery.dataEditor to ${PUBSUB_SERVICE_ACCOUNT} on dataset ${DATASET_ID}..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${PUBSUB_SERVICE_ACCOUNT}" \
    --role="roles/bigquery.dataEditor" \
    --condition=None > /dev/null

echo "   Adding bigquery.metadataViewer to ${PUBSUB_SERVICE_ACCOUNT} on dataset ${DATASET_ID}..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${PUBSUB_SERVICE_ACCOUNT}" \
    --role="roles/bigquery.metadataViewer" \
    --condition=None > /dev/null

# 3. Create the Pub/Sub Subscription writing directly to BigQuery
# Recommended configuration for BigQuery direct subscriptions (official documentation):
# - For JSON topics (-json): use --use-table-schema and --drop-unknown-fields
# - For binary topics: use --use-topic-schema
echo "2. Creating direct BigQuery Pub/Sub subscription..."
if [[ "${ENCODING}" == "json" ]]; then
  echo "   Configuring subscription for JSON-encoded topic with --use-table-schema and --drop-unknown-fields..."
  gcloud pubsub subscriptions create "${SUBSCRIPTION_ID}" \
      --project="${PROJECT_ID}" \
      --topic="${TOPIC_PATH}" \
      --bigquery-table="${BQ_TABLE_PATH}" \
      --use-table-schema \
      --drop-unknown-fields \
      --write-metadata
else
  echo "   Configuring subscription for binary topic with --use-topic-schema..."
  gcloud pubsub subscriptions create "${SUBSCRIPTION_ID}" \
      --project="${PROJECT_ID}" \
      --topic="${TOPIC_PATH}" \
      --bigquery-table="${BQ_TABLE_PATH}" \
      --use-topic-schema \
      --write-metadata
fi

echo "=========================================================================="
echo "Configuration Completed Successfully!"
echo "Your BigQuery Pub/Sub subscription '${SUBSCRIPTION_ID}' is active."
echo "=========================================================================="