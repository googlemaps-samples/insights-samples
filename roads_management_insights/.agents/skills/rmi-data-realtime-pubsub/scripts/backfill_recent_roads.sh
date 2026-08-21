#!/usr/bin/env bash
# ====================================================================================
# Script: backfill_recent_roads.sh
# Description:
#   Performs a highly optimized, cost-controlled daily backfill to transform
#   historical raw telemetry from 'rmi_realtime_json' into the production-optimized
#   'recent_roads_data' table partition-by-partition.
#
#   Enforces partition pruning on 'partitioning_ts' to scan only one partition
#   per day, keeping costs predictable and performance extremely fast.
#
# Usage:
#   PROJECT_ID="moritani-roads" \
#   DATASET_ID="rmi" \
#   SOURCE_TABLE_ID="rmi_realtime_json" \
#   ./backfill_recent_roads.sh "2026-05-15" "2026-06-12"
# ====================================================================================

set -euo pipefail

# --- Configuration & Defaults ---
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
DATASET_ID="${DATASET_ID:-rmi_realtime}"
TARGET_TABLE_ID="${TARGET_TABLE_ID:-recent_roads_data}"

SOURCE_PROJECT_ID="${SOURCE_PROJECT_ID:-${PROJECT_ID}}"
SOURCE_DATASET_ID="${SOURCE_DATASET_ID:-${DATASET_ID}}"
SOURCE_TABLE_ID="${SOURCE_TABLE_ID:-roads_information_landing}"

# --- Help Block & Arguments Check ---
if [ "$#" -lt 2 ]; then
  echo "❌ Error: Missing required date arguments." >&2
  echo "Usage: $0 <START_DATE_YYYY_MM_DD> <END_DATE_YYYY_MM_DD>" >&2
  echo "Example: PROJECT_ID=\"moritani-roads\" DATASET_ID=\"historical_roads_data_derived\" SOURCE_DATASET_ID=\"rmi\" SOURCE_TABLE_ID=\"rmi_realtime_json\" $0 \"2026-05-15\" \"2026-06-12\"" >&2
  exit 1
fi

START_DATE="$1"
END_DATE="$2"

if [ -z "${PROJECT_ID}" ]; then
  echo "❌ Error: PROJECT_ID is not set and could not be detected via gcloud." >&2
  exit 1
fi

echo "========================================================================"
echo "🚀 Initiating Partition-Pruned Historical Backfill Pipeline"
echo "========================================================================"
echo "• Target Project:  ${PROJECT_ID}"
echo "• Target Dataset:  ${DATASET_ID}"
echo "• Target Table:    ${TARGET_TABLE_ID} (Partitioned on record_time)"
echo "• Source Project:  ${SOURCE_PROJECT_ID}"
echo "• Source Dataset:  ${SOURCE_DATASET_ID}"
echo "• Source Table:    ${SOURCE_TABLE_ID} (Partitioned on partitioning_ts)"
echo "• Start Date:      ${START_DATE}"
echo "• End Date:        ${END_DATE}"
echo "========================================================================"

# --- Dynamic Date Generator ---
# Generate daily dates sequence portably using Python to avoid GNU/BSD date mismatches on macOS vs Linux
echo "Resolving date sequence..."
DAYS=$(python3 -c "
import datetime
try:
    start = datetime.date.fromisoformat('${START_DATE}')
    end = datetime.date.fromisoformat('${END_DATE}')
    if start > end:
        print('ERROR: Start date must be before or equal to End date.', file=sys.stderr)
        exit(1)
    curr = start
    while curr <= end:
        print(curr.isoformat())
        curr += datetime.timedelta(days=1)
except ValueError as e:
    import sys
    print(f'ERROR: Invalid ISO date format. {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)

# Check for Python validation errors
if [[ "${DAYS}" == ERROR* ]]; then
  echo "❌ ${DAYS}" >&2
  exit 1
fi

# --- Loop Day-by-Day ---
for DAY in ${DAYS}; do
  NEXT_DAY=$(python3 -c "
import datetime
d = datetime.date.fromisoformat('${DAY}')
print((d + datetime.timedelta(days=1)).isoformat())
")

  echo "------------------------------------------------------------------------"
  echo "📅 Processing Partition: ${DAY} (pruning range: [${DAY}T00:00:00, ${NEXT_DAY}T00:00:00))"
  echo "------------------------------------------------------------------------"

  # Construct the unique tracing job ID required by workspace governance standards
  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
  JOB_ID="rmi_realtime_backfill_${DAY//-/_}_${TIMESTAMP}"

  # SQL command to execute partition-pruned merge
  SQL_QUERY="
  MERGE \`${PROJECT_ID}.${DATASET_ID}.${TARGET_TABLE_ID}\` T
  USING (
    WITH raw_dedup AS (
      SELECT
        selected_route_id,
        display_name,
        TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND) AS record_time,
        travel_duration.duration_in_seconds AS duration_in_seconds,
        travel_duration.static_duration_in_seconds AS static_duration_in_seconds,
        SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
        speed_reading_intervals,
        publish_time,
        ROW_NUMBER() OVER (
          PARTITION BY selected_route_id, retrieval_time.seconds 
          ORDER BY publish_time DESC
        ) AS rn
      FROM
        \`${SOURCE_PROJECT_ID}.${SOURCE_DATASET_ID}.${SOURCE_TABLE_ID}\`
      WHERE
        -- Critical partition pruning: Restrict scan strictly to the targeted partition date
        partitioning_ts >= TIMESTAMP('${DAY} 00:00:00')
        AND partitioning_ts < TIMESTAMP('${NEXT_DAY} 00:00:00')
    )
    SELECT
      selected_route_id,
      display_name,
      record_time,
      duration_in_seconds,
      static_duration_in_seconds,
      route_geometry,
      ARRAY(
        SELECT AS STRUCT
          [ST_MAKELINE(ARRAY(
            SELECT ST_GEOGPOINT(CAST(coord.longitude AS FLOAT64), CAST(coord.latitude AS FLOAT64))
            FROM UNNEST(interv.interval_coordinates) AS coord
          ))] AS interval_coordinates,
          interv.speed AS speed
        FROM UNNEST(speed_reading_intervals) AS interv
      ) AS speed_reading_intervals
    FROM raw_dedup
    WHERE rn = 1
  ) S
  ON T.selected_route_id = S.selected_route_id AND T.record_time = S.record_time
  WHEN NOT MATCHED THEN
    INSERT (selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry, speed_reading_intervals)
    VALUES (selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry, speed_reading_intervals);
  "

  # Perform Dry Run first to let the user see the exact scanning size for this partition
  echo "Performing dry-run..."
  DRY_RUN_OUT=$(bq query --dry_run --use_legacy_sql=false "${SQL_QUERY}" 2>&1)
  BYTES_SCANNED=$(echo "${DRY_RUN_OUT}" | grep -o -E '[0-9]+ bytes' | head -n1 || echo "unknown")
  echo "💡 Dry-run prediction: Will scan ${BYTES_SCANNED}."

  # Execute the merge
  echo "Executing MERGE with Job ID: ${JOB_ID}..."
  bq query \
    --use_legacy_sql=false \
    --job_id="${JOB_ID}" \
    "${SQL_QUERY}"

  echo "✅ Partition ${DAY} Backfilled successfully!"
done

echo "========================================================================"
echo "🎉 Historical Backfill Completed Successfully for all partitions!"
echo "========================================================================"
