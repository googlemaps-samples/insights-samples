#!/usr/bin/env bash
#
# Common helper utilities for BigQuery Practices
#
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "${SCRIPT_DIR}/generate_job_id.sh"

format_bq_labels() {
  local agent="${1:-}"
  local usecase="${2:-}"
  local env="${3:-}"
  local region="${4:-}"

  local labels=()
  if [[ -n "${agent}" ]]; then
    labels+=("agent:$(sanitize_label "${agent}")")
  fi
  if [[ -n "${usecase}" ]]; then
    labels+=("usecase:$(sanitize_label "${usecase}")")
  fi
  if [[ -n "${env}" ]]; then
    labels+=("env:$(sanitize_label "${env}")")
  fi
  if [[ -n "${region}" ]]; then
    labels+=("region:$(sanitize_label "${region}")")
  fi

  # Join with comma
  local IFS=","
  echo "${labels[*]}"
}

build_bq_query_command() {
  local sql="$1"
  local project_id="${2:-}"
  local location="${3:-}"
  local job_id="${4:-}"
  local labels="${5:-}"

  local cmd="bq query --use_legacy_sql=false"
  if [[ -n "${project_id}" ]]; then
    cmd+=" --project_id=${project_id}"
  fi
  if [[ -n "${location}" ]]; then
    cmd+=" --location=${location}"
  fi
  if [[ -n "${job_id}" ]]; then
    cmd+=" --job_id=${job_id}"
  fi
  if [[ -n "${labels}" ]]; then
    cmd+=" --label=${labels}"
  fi
  cmd+=" \"${sql}\""
  echo "${cmd}"
}
