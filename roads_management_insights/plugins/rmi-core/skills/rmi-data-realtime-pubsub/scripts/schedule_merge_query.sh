#!/usr/bin/env bash
# ====================================================================================
# Script: schedule_merge_query.sh
# Description:
#   Automates the creation of a BigQuery Scheduled Query (Option B) to run the DML
#   MERGE transformation that populates 'recent_roads_data' from raw landing records.
#
# Requirements:
#   1. Google Cloud SDK (gcloud, bq CLI).
#   2. BigQuery Data Transfer Service API enabled in the target project.
#   3. BigQuery Admin or Data Transfer Admin permissions for the executing identity.
# ====================================================================================

set -euo pipefail

# --- Configuration & Defaults ---
# Resolve default project if not set in environment
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
DATASET_ID="${DATASET_ID:-rmi_realtime}"
TARGET_TABLE_ID="${TARGET_TABLE_ID:-recent_roads_data}"

SOURCE_PROJECT_ID="${SOURCE_PROJECT_ID:-${PROJECT_ID}}"
SOURCE_DATASET_ID="${SOURCE_DATASET_ID:-${DATASET_ID}}"
SOURCE_TABLE_ID="${SOURCE_TABLE_ID:-roads_information_landing}"

LOCATION="${LOCATION:-US}"
SCHEDULE_INTERVAL="${SCHEDULE:-every 10 minutes}"
DISPLAY_NAME="RMI Real-Time Telemetry Incremental MERGE"

# Directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_FILE="${SCRIPT_DIR}/../references/queries/scheduled_merge_recent_roads.sql"

# --- Validations ---
if [ -z "${PROJECT_ID}" ]; then
  echo "❌ Error: PROJECT_ID is not set and could not be detected via gcloud." >&2
  echo "Please set PROJECT_ID environment variable (e.g. export PROJECT_ID='my-project')." >&2
  exit 1
fi

if [ ! -f "${SQL_FILE}" ]; then
  echo "❌ Error: SQL query file not found at ${SQL_FILE}" >&2
  exit 1
fi

echo "========================================================================"
echo "🚀 Preparing BigQuery Scheduled Query Deployment"
echo "========================================================================"
echo "• Target Project:  ${PROJECT_ID}"
echo "• Target Dataset:  ${DATASET_ID}"
echo "• Target Table:    ${TARGET_TABLE_ID}"
echo "• Source Project:  ${SOURCE_PROJECT_ID}"
echo "• Source Dataset:  ${SOURCE_DATASET_ID}"
echo "• Source Table:    ${SOURCE_TABLE_ID}"
echo "• Location:        ${LOCATION}"
echo "• Query Schedule:  ${SCHEDULE_INTERVAL}"
echo "• Display Name:    ${DISPLAY_NAME}"
echo "========================================================================"

# --- SQL Processing & Placeholder Sub ---
# Read the query file and replace generic placeholders with environment configuration
echo "Reading and substituting placeholders in ${SQL_FILE}..."
RAW_SQL=$(cat "${SQL_FILE}")

# Substitute using exact fully qualified table name mappings
PROCESSED_SQL=$(echo "${RAW_SQL}" | \
  sed "s/my_project.rmi_realtime.recent_roads_data/${PROJECT_ID}.${DATASET_ID}.${TARGET_TABLE_ID}/g" | \
  sed "s/my_project.rmi_realtime.roads_information_landing/${SOURCE_PROJECT_ID}.${SOURCE_DATASET_ID}.${SOURCE_TABLE_ID}/g")

# --- Escape SQL for JSON Parameter Block ---
# Scheduled Queries are managed via BigQuery Data Transfer configurations, which require
# queries to be JSON-escaped in the parameters block.
echo "Escaping SQL for JSON payload..."
JSON_ESCAPED_SQL=$(echo "${PROCESSED_SQL}" | jq -a -R -s '.')

# Build the transfer config params
PARAMS="{\"query\":${JSON_ESCAPED_SQL}}"

# --- Create Scheduled Query ---
echo "Registering Scheduled Query with BigQuery..."
bq mk \
  --transfer_config \
  --project_id="${PROJECT_ID}" \
  --location="${LOCATION}" \
  --data_source=scheduled_query \
  --display_name="${DISPLAY_NAME}" \
  --schedule="${SCHEDULE_INTERVAL}" \
  --params="${PARAMS}"

echo "========================================================================"
echo "✅ Scheduled Query Successfully Registered!"
echo "========================================================================"
echo "You can manage, trigger, or monitor this query in:"
echo "👉 BigQuery Console -> Scheduled Queries"
echo "========================================================================"
