#!/usr/bin/env bash
# ==============================================================================
# bench_table_layouts.sh: Physical Layout Builder, S2 Hilbert Range Generator &
#                         A/B Pruning Benchmark Harness for BigQuery Tables
#
# Can be sourced for helper functions or executed directly:
#   source scripts/bench_table_layouts.sh
#   scripts/bench_table_layouts.sh --help
# ==============================================================================

# Return "PARTITION_CLAUSE|CLUSTER_CLAUSE" for canonical snapshot x entity layouts
get_layout_clauses() {
  local layout="$1"
  case "${layout}" in
    L0_asis)            echo "|" ;;
    L1_part_cell)       echo "PARTITION BY DATE_TRUNC(snapshot_date, MONTH)|CLUSTER BY s2_int" ;;
    L2_part_geo)        echo "PARTITION BY DATE_TRUNC(snapshot_date, MONTH)|CLUSTER BY centroid" ;;
    L3_geo_snap)        echo "|CLUSTER BY centroid, snapshot_date" ;;
    L4_part_admin_cell) echo "PARTITION BY DATE_TRUNC(snapshot_date, MONTH)|CLUSTER BY admin_l1_name, s2_int" ;;
    L5_cell_snap)       echo "|CLUSTER BY s2_int, snapshot_date" ;;
    *) echo "ERROR: unknown layout '${layout}'" >&2; return 1 ;;
  esac
}

# Build the SQL query that converts a bounding box (xmin, ymin, xmax, ymax) into
# literal INT64 Hilbert range predicates (col BETWEEN c - (c & -c) + 1 AND c + (c & -c) - 1)
# using S2_COVERINGCELLIDS so static cluster pruning succeeds on INT64 S2 cell ID columns.
build_s2_covering_range_sql() {
  local col="$1"
  local xmin="$2"
  local ymin="$3"
  local xmax="$4"
  local ymax="$5"
  local max_cells="${6:-8}"
  cat <<EOF
SELECT FORMAT('${col} BETWEEN %d AND %d', c - (c & -c) + 1, c + (c & -c) - 1)
FROM UNNEST(
  S2_COVERINGCELLIDS(
    ST_MAKEPOLYGON(ST_MAKELINE([
      ST_GEOGPOINT(${xmin}, ${ymin}),
      ST_GEOGPOINT(${xmax}, ${ymin}),
      ST_GEOGPOINT(${xmax}, ${ymax}),
      ST_GEOGPOINT(${xmin}, ${ymax})
    ])),
    min_level => 6, max_level => 12, max_cells => ${max_cells}
  )
) AS c
EOF
}

# Build the INFORMATION_SCHEMA.JOBS_BY_USER query that collects real billed bytes,
# slot_ms, and Input-stage records_read (excluding SCRIPT parent jobs).
build_jobs_benchmark_report_sql() {
  local project="$1"
  local region="${2:-region-us}"
  local run_id="$3"
  cat <<EOF
SELECT
  REGEXP_EXTRACT(job_id, r'^${run_id}_(.*)__') AS layout,
  REGEXP_EXTRACT(job_id, r'__(.*)$') AS workload,
  total_bytes_billed,
  ROUND(total_bytes_billed / 1e9, 3) AS gb_billed,
  total_slot_ms,
  TIMESTAMP_DIFF(end_time, start_time, MILLISECOND) AS elapsed_ms,
  (SELECT SUM(records_read) FROM UNNEST(job_stages) s WHERE s.name LIKE '%Input%') AS records_read,
  error_result.reason AS error
FROM \`${project}.${region}.INFORMATION_SCHEMA.JOBS_BY_USER\`
WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 HOUR)
  AND job_id LIKE '${run_id}_%'
  AND IFNULL(statement_type, '') != 'SCRIPT'
ORDER BY workload, layout
EOF
}

# Build a cosine distance expression with an epsilon tail so all-zero vectors do not crash ML.DISTANCE
build_safe_cosine_distance_expr() {
  local vec_a="$1"
  local vec_b="$2"
  local eps="${3:-1e-9}"
  echo "IF(${vec_a} IS NULL OR ${vec_b} IS NULL, NULL, ML.DISTANCE(ARRAY_CONCAT(${vec_a}, [${eps}]), ARRAY_CONCAT(${vec_b}, [${eps}]), 'COSINE'))"
}

bench_table_layouts_usage() {
  cat <<'EOF'
Usage:
  bench_table_layouts.sh --help
  PROJECT=<proj> DATASET=<ds> PREFIX=<pfx> bench_table_layouts.sh [out.csv]

Environment variables (when running live benchmarks):
  PROJECT       GCP project ID (required)
  DATASET       Dataset holding layout tables <PREFIX>_<LAYOUT> and <PREFIX>_cells (required)
  PREFIX        Table prefix, e.g. jp_v2 (required)
  LAYOUTS       Space-separated layouts (default: "L0_asis L1_part_cell L2_part_geo L3_geo_snap L4_part_admin_cell L5_cell_snap")
  BBOX          "xmin, ymin, xmax, ymax" (default: "139.56, 35.52, 139.92, 35.82")
  SNAP          Target snapshot_date (default: "2026-09-01")
  PREV          Previous snapshot_date (default: "2026-08-01")
  CELL_TOKEN    Target S2 cell token (default: "6019307")
  PREF          Target admin_l1_name (default: "Tokyo")
  MAXB          --maximum_bytes_billed cap (default: 15000000000)

Helper functions (when sourced):
  get_layout_clauses <layout_name>
  build_s2_covering_range_sql <int64_col> <xmin> <ymin> <xmax> <ymax> [max_cells]
  build_jobs_benchmark_report_sql <project> <region> <run_id>
  build_safe_cosine_distance_expr <vec_a_expr> <vec_b_expr> [epsilon]
EOF
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  set -euo pipefail
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    bench_table_layouts_usage
    exit 0
  fi
  : "${PROJECT:?Set PROJECT}" "${DATASET:?Set DATASET}" "${PREFIX:?Set PREFIX}"
  OUT="${1:-layouts_${PREFIX}_bench.csv}"
  MAXB="${MAXB:-15000000000}"
  LAYOUTS="${LAYOUTS:-L0_asis L1_part_cell L2_part_geo L3_geo_snap L4_part_admin_cell L5_cell_snap}"
  BBOX="${BBOX:-139.56, 35.52, 139.92, 35.82}"
  SNAP="${SNAP:-2026-09-01}"
  PREV="${PREV:-2026-08-01}"
  CELL_TOKEN="${CELL_TOKEN:-6019307}"
  PREF="${PREF:-Tokyo}"
  REGION="${REGION:-region-us}"
  RUN_ID="b$(date +%s)"
  CELLS="\`${PROJECT}.${DATASET}.${PREFIX}_cells\`"

  q() { bq query --project_id="${PROJECT}" --use_legacy_sql=false --format=csv "$@"; }

  CELL_INT=$(q "SELECT s2_int FROM ${CELLS} WHERE s2_cell_token = '${CELL_TOKEN}'" | tail -1)
  read -r X1 Y1 X2 Y2 <<< "$(echo "${BBOX}" | tr -d ',')"
  RANGE_SQL="$(build_s2_covering_range_sql s2_int "${X1}" "${Y1}" "${X2}" "${Y2}" 8)"
  RANGES=$(q --max_rows=100 "${RANGE_SQL}" | tail -n +2 | paste -sd'|' - | sed 's/|/ OR /g')

  for L in ${LAYOUTS}; do
    T="\`${PROJECT}.${DATASET}.${PREFIX}_${L}\`"
    COS_EXPR="$(build_safe_cosine_distance_expr a.features b.features)"
    WORKLOADS=$(cat <<EOF
W1_one_snapshot_country|SELECT s2_cell_token, features FROM ${T} WHERE snapshot_date = '${SNAP}'
W2_cell_timeseries|SELECT snapshot_date, features FROM ${T} WHERE s2_int = ${CELL_INT}
W3_viewport_geo_one_snap|SELECT s2_cell_token, features FROM ${T} WHERE snapshot_date = '${SNAP}' AND ST_INTERSECTSBOX(centroid, ${BBOX})
W3b_viewport_s2range_one_snap|SELECT s2_cell_token, features FROM ${T} WHERE snapshot_date = '${SNAP}' AND (${RANGES})
W4_viewport_geo_all_snaps|SELECT snapshot_date, s2_cell_token, features FROM ${T} WHERE ST_INTERSECTSBOX(centroid, ${BBOX})
W5_viewport_diff_2snaps|SELECT a.s2_cell_token, ${COS_EXPR} AS d FROM ${T} a JOIN ${T} b USING (s2_cell_token) WHERE a.snapshot_date = '${SNAP}' AND b.snapshot_date = '${PREV}' AND ST_INTERSECTSBOX(a.centroid, ${BBOX}) AND ST_INTERSECTSBOX(b.centroid, ${BBOX})
W6_prefecture_all_snaps|SELECT snapshot_date, s2_cell_token, features FROM ${T} WHERE admin_l1_name = '${PREF}'
W7_viewport_via_dim_join|SELECT f.snapshot_date, f.s2_cell_token, f.features FROM ${T} f WHERE f.snapshot_date = '${SNAP}' AND f.s2_int IN (SELECT s2_int FROM ${CELLS} WHERE ST_INTERSECTSBOX(centroid, ${BBOX}))
W8_meta_only_counts|SELECT snapshot_date, COUNT(*) AS n FROM ${T} GROUP BY 1
EOF
)
    while IFS='|' read -r W SQL; do
      [[ -z "${W}" ]] && continue
      printf '%s' "${SQL}" | bq query --project_id="${PROJECT}" --use_legacy_sql=false --nouse_cache \
        --job_id="${RUN_ID}_${L}__${W}" --maximum_bytes_billed="${MAXB}" \
        --label datacloud:antigravity --format=none >/dev/null 2>&1 || echo "FAILED ${L} ${W}" >&2
    done <<< "${WORKLOADS}"
  done

  sleep 5
  REPORT_SQL="$(build_jobs_benchmark_report_sql "${PROJECT}" "${REGION}" "${RUN_ID}")"
  q --max_rows=1000 "${REPORT_SQL}" > "${OUT}"
  echo "wrote ${OUT} (run ${RUN_ID})" >&2
fi
