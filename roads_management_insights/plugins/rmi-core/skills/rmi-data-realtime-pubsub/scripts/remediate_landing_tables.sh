#!/usr/bin/env bash
# ====================================================================================
# Script: remediate_landing_tables.sh
# Description:
#   Automates the diagnosis, schema migration, and resilience hardening for RMI
#   Real-Time landing tables and Pub/Sub subscriptions following the October 8, 2026
#   schema evolution.
#
#   Performs:
#   1. Pre-flight schema audit (identifies missing columns across JSON and Binary tables).
#   2. Non-breaking BigQuery schema migration (ALTER TABLE ADD COLUMN IF NOT EXISTS).
#   3. Pub/Sub subscription hardening (enables --drop-unknown-fields to prevent future lockups).
#   4. Post-remediation health check and subscription state verification.
#
# Modes:
#   - Check / Dry-run (default): Inspects current state, performs DDL dry-runs, outputs plan.
#   - Apply (--apply or APPLY=true): Executes DDL migrations and updates subscriptions.
#
# Usage:
#   # 1. Check current state and view planned changes (Dry Run):
#   ./scripts/remediate_landing_tables.sh
#
#   # 2. Apply remediation to active project:
#   ./scripts/remediate_landing_tables.sh --apply
#
#   # 3. Custom parameters:
#   PROJECT_ID="my-project" DATASET_ID="rmi" ./scripts/remediate_landing_tables.sh --apply
# ====================================================================================

set -euo pipefail

# --- Configuration & Defaults ---
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
DATASET_ID="${DATASET_ID:-rmi}"
JSON_TABLE_ID="${JSON_TABLE_ID:-rmi_realtime_json}"
BINARY_TABLE_ID="${BINARY_TABLE_ID:-rmi_realtime_binary}"
JSON_SUBSCRIPTION_ID="${JSON_SUBSCRIPTION_ID:-rmi-json-to-bigquery-subscription}"
BINARY_SUBSCRIPTION_ID="${BINARY_SUBSCRIPTION_ID:-rmi-binary-to-bigquery-subscription}"

APPLY="${APPLY:-false}"
for arg in "$@"; do
  case "${arg}" in
    --apply|-a)
      APPLY="true"
      ;;
    --dry-run|-d)
      APPLY="false"
      ;;
    --help|-h)
      echo "Usage: $0 [--dry-run | --apply]"
      echo "  --dry-run (default): Inspects state, validates DDL, prints planned actions without mutating."
      echo "  --apply:             Executes ALTER TABLE schema migrations and updates subscriptions."
      exit 0
      ;;
  esac
done

if [ -z "${PROJECT_ID}" ]; then
  echo "❌ Error: PROJECT_ID is not set and could not be detected via gcloud." >&2
  echo "Please export PROJECT_ID or run: gcloud config set project <PROJECT_ID>" >&2
  exit 1
fi

echo "=========================================================================="
echo "🔧 RMI Real-Time Schema Evolution Remediation Engine"
echo "=========================================================================="
echo "• Project ID:           ${PROJECT_ID}"
echo "• Dataset ID:           ${DATASET_ID}"
echo "• JSON Landing Table:   ${JSON_TABLE_ID}"
echo "• Binary Landing Table: ${BINARY_TABLE_ID}"
echo "• JSON Subscription:    ${JSON_SUBSCRIPTION_ID}"
echo "• Binary Subscription:  ${BINARY_SUBSCRIPTION_ID}"
echo "• Execution Mode:       $([ "${APPLY}" = "true" ] && echo "⚡ APPLY (LIVE MUTATION)" || echo "🔍 DRY-RUN / CHECK ONLY")"
echo "=========================================================================="

# -----------------------------------------------------------------------------
# Function: Check missing columns in a BigQuery table
# -----------------------------------------------------------------------------
check_missing_columns() {
  local table_name="$1"
  local target_table="${PROJECT_ID}:${DATASET_ID}.${table_name}"
  
  if ! bq show --format=prettyjson "${target_table}" >/dev/null 2>&1; then
    echo "TABLE_NOT_FOUND"
    return
  fi

  local existing_fields
  existing_fields=$(bq show --format=prettyjson "${target_table}" | jq -r '.schema.fields[].name')

  local missing=()
  for col in speed_reading_offsets duration_in_seconds static_duration_in_seconds retrieval_timestamp has_road_closure; do
    if ! echo "${existing_fields}" | grep -qx "${col}"; then
      missing+=("${col}")
    fi
  done

  echo "${missing[@]+"${missing[@]}"}"
}

# -----------------------------------------------------------------------------
# Step 1: Pre-flight Audit
# -----------------------------------------------------------------------------
echo -e "\n[Step 1] Auditing current BigQuery landing tables..."

JSON_MISSING=$(check_missing_columns "${JSON_TABLE_ID}")
BINARY_MISSING=$(check_missing_columns "${BINARY_TABLE_ID}")

echo "• Table '${JSON_TABLE_ID}':"
if [ "${JSON_MISSING}" == "TABLE_NOT_FOUND" ]; then
  echo "  ⚠️ Table does not exist in dataset '${DATASET_ID}'."
elif [ -z "${JSON_MISSING}" ]; then
  echo "  ✅ All 5 October 2026 columns already present."
else
  echo "  ❌ Missing columns: ${JSON_MISSING}"
fi

echo "• Table '${BINARY_TABLE_ID}':"
if [ "${BINARY_MISSING}" == "TABLE_NOT_FOUND" ]; then
  echo "  ⚠️ Table does not exist in dataset '${DATASET_ID}'."
elif [ -z "${BINARY_MISSING}" ]; then
  echo "  ✅ All 5 October 2026 columns already present."
else
  echo "  ❌ Missing columns: ${BINARY_MISSING}"
fi

# -----------------------------------------------------------------------------
# Step 2: DDL Migration Generation & Execution
# -----------------------------------------------------------------------------
generate_alter_ddl() {
  local table_name="$1"
  cat <<EOF
ALTER TABLE \`${PROJECT_ID}.${DATASET_ID}.${table_name}\`
ADD COLUMN IF NOT EXISTS speed_reading_offsets ARRAY<STRUCT<start_offset INT64, end_offset INT64, speed STRING>>
  OPTIONS(description="Offset-based speed reading intervals. Supports TRAFFIC_JAM_HEAVY. Omitted when has_road_closure is true."),
ADD COLUMN IF NOT EXISTS duration_in_seconds FLOAT64
  OPTIONS(description="The duration of travel through the route based on current traffic conditions. Omitted when has_road_closure is true."),
ADD COLUMN IF NOT EXISTS static_duration_in_seconds FLOAT64
  OPTIONS(description="The duration of travel through the route without taking traffic conditions into consideration."),
ADD COLUMN IF NOT EXISTS retrieval_timestamp TIMESTAMP
  OPTIONS(description="The time the traffic data was collected, as an RFC 3339 UTC timestamp converted to TIMESTAMP."),
ADD COLUMN IF NOT EXISTS has_road_closure BOOL
  OPTIONS(description="Whether there is a full road closure on the route. When true, duration_in_seconds and speed_reading_offsets are omitted.");
EOF
}

echo -e "\n[Step 2] Evaluating BigQuery Schema Migration..."

for tbl in "${JSON_TABLE_ID}" "${BINARY_TABLE_ID}"; do
  echo "• Validating DDL for table '${tbl}'..."
  DDL=$(generate_alter_ddl "${tbl}")
  
  # Perform dry run
  if bq query --dry_run --nouse_legacy_sql "${DDL}" >/dev/null 2>&1; then
    echo "  ✅ DDL syntax successfully validated against BigQuery."
  else
    echo "  ⚠️ Table '${tbl}' cannot be altered (table may not exist or permission denied)."
    continue
  fi

  if [ "${APPLY}" == "true" ]; then
    echo "  🚀 Executing ALTER TABLE on '${tbl}'..."
    bq query --nouse_legacy_sql "${DDL}"
    echo "  ✅ Schema migration completed for '${tbl}'."
  else
    echo "  💡 [DRY-RUN] To apply this migration, run with --apply."
  fi
done

# -----------------------------------------------------------------------------
# Step 3: Pub/Sub Subscription Hardening
# -----------------------------------------------------------------------------
echo -e "\n[Step 3] Auditing and Hardening Pub/Sub Subscriptions..."

for sub in "${JSON_SUBSCRIPTION_ID}" "${BINARY_SUBSCRIPTION_ID}"; do
  echo "• Inspecting subscription '${sub}'..."
  SUB_PATH="projects/${PROJECT_ID}/subscriptions/${sub}"
  
  if ! gcloud pubsub subscriptions describe "${SUB_PATH}" >/dev/null 2>&1; then
    echo "  ⚠️ Subscription '${sub}' does not exist in project '${PROJECT_ID}'. Skipping."
    continue
  fi

  SUB_STATE=$(gcloud pubsub subscriptions describe "${SUB_PATH}" --format="value(state)")
  BQ_STATE=$(gcloud pubsub subscriptions describe "${SUB_PATH}" --format="value(bigqueryConfig.state)" 2>/dev/null || echo "N/A")
  DROP_UNKNOWN=$(gcloud pubsub subscriptions describe "${SUB_PATH}" --format="value(bigqueryConfig.dropUnknownFields)" 2>/dev/null || echo "false")

  echo "  Current status: Subscription State='${SUB_STATE}', BigQuery Config State='${BQ_STATE}', dropUnknownFields='${DROP_UNKNOWN}'"

  if [ "${APPLY}" == "true" ]; then
    echo "  🚀 Hardening subscription '${sub}' with --drop-unknown-fields..."
    bq_table=$(gcloud pubsub subscriptions describe "${SUB_PATH}" --format="value(bigqueryConfig.table)" 2>/dev/null || echo "")
    use_topic=$(gcloud pubsub subscriptions describe "${SUB_PATH}" --format="value(bigqueryConfig.useTopicSchema)" 2>/dev/null || echo "false")
    
    if [ -n "${bq_table}" ]; then
      if [ "${use_topic}" = "true" ] || [ "${use_topic}" = "True" ]; then
        gcloud pubsub subscriptions update "${sub}" \
          --project="${PROJECT_ID}" \
          --bigquery-table="${bq_table}" \
          --use-topic-schema \
          --write-metadata \
          --drop-unknown-fields
      else
        gcloud pubsub subscriptions update "${sub}" \
          --project="${PROJECT_ID}" \
          --bigquery-table="${bq_table}" \
          --use-table-schema \
          --write-metadata \
          --drop-unknown-fields
      fi
      echo "  ✅ Subscription '${sub}' updated."
    else
      echo "  ⚠️ Subscription '${sub}' has no bigqueryConfig table configured. Skipping."
    fi
  else
    if [ "${DROP_UNKNOWN}" != "true" ]; then
      echo "  💡 [DRY-RUN] Subscription is missing --drop-unknown-fields. Will be enabled with --apply."
    else
      echo "  ✅ Subscription already has --drop-unknown-fields enabled."
    fi
  fi
done

# -----------------------------------------------------------------------------
# Step 4: Verification & Diagnostic Summary
# -----------------------------------------------------------------------------
echo -e "\n=========================================================================="
echo "📊 Remediation Status Summary"
echo "=========================================================================="

if [ "${APPLY}" == "true" ]; then
  echo "🎉 Live remediation commands executed successfully!"
  echo "• Re-inspecting table columns:"
  echo "  - ${JSON_TABLE_ID}:   Missing -> '$(check_missing_columns "${JSON_TABLE_ID}")'"
  echo "  - ${BINARY_TABLE_ID}: Missing -> '$(check_missing_columns "${BINARY_TABLE_ID}")'"
  echo "• You can now monitor live ingestion into '${JSON_TABLE_ID}' via:"
  echo "  bq query --nouse_legacy_sql 'SELECT COUNT(*), MAX(publish_time) FROM \`${PROJECT_ID}.${DATASET_ID}.${JSON_TABLE_ID}\` WHERE publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR);'"
else
  echo "🔍 Dry-run check completed. No modifications were made."
  echo "To apply this remediation to '${PROJECT_ID}', execute:"
  echo "  $0 --apply"
fi
echo "=========================================================================="
