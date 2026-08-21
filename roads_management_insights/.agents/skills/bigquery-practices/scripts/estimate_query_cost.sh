#!/usr/bin/env bash
#
# BigQuery Query Dry-Run Cost Estimator
#
# Runs a dry-run query to inspect estimated bytes scanned and calculate projected cost.
# BigQuery on-demand analysis rate: $6.25 per TB (first 1 TB/month free).
#
set -euo pipefail

estimate_query_cost() {
  local sql_query="$1"
  local project_id="${2:-}"
  local location="${3:-}"

  local bq_args=("--use_legacy_sql=false" "--dry_run")
  if [[ -n "${project_id}" ]]; then
    bq_args+=("--project_id=${project_id}")
  fi
  if [[ -n "${location}" ]]; then
    bq_args+=("--location=${location}")
  fi

  local output
  output=$(bq query "${bq_args[@]}" "${sql_query}" 2>&1)

  # Extract bytes processed, e.g. "Query will process 1048576 bytes."
  local bytes
  bytes=$(echo "${output}" | grep -oE "process [0-9]+ bytes" | awk '{print $2}' || true)

  if [[ -n "${bytes}" ]]; then
    # Calculate GB, TB, and Cost in USD ($6.25 / TB)
    python3 -c "
bytes = int('${bytes}')
gb = bytes / (1024**3)
tb = bytes / (1024**4)
cost = tb * 6.25
print(f'Estimated Bytes Scanned: {bytes:,} bytes ({gb:.4f} GB / {tb:.6f} TB)')
print(f'Projected On-Demand Cost: \${cost:.6f} USD')
"
  else
    echo "${output}"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [[ $# -lt 1 ]]; then
    echo "Usage: $0 \"<SQL_QUERY>\" [PROJECT_ID] [LOCATION]"
    exit 1
  fi
  SQL="$1"
  PROJECT="${2:-}"
  LOC="${3:-}"
  estimate_query_cost "${SQL}" "${PROJECT}" "${LOC}"
fi
