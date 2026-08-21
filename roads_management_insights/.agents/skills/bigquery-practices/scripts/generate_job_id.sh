#!/usr/bin/env bash
#
# Standardized BigQuery Job ID Generator
#
# Format: <app_indicator>_<category>_<yyyymmdd>_<hhmmsssss>[_<country_iso>_<admin_area>]
# Padded with 3-digit milliseconds to prevent collision on high-frequency queries.
#
set -euo pipefail

sanitize_label() {
  local val="$1"
  echo "${val}" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_]+/_/g' | sed -E 's/_+/_/g' | sed -E 's/^_|_$//g'
}

generate_bigquery_job_id() {
  local app_indicator="${1:-workspace}"
  local category="${2:-query}"
  local country_iso="${3:-}"
  local admin_area="${4:-}"

  local clean_app
  local clean_cat
  local clean_country
  local clean_admin

  clean_app=$(sanitize_label "${app_indicator}")
  clean_cat=$(sanitize_label "${category}")

  local date_part
  date_part=$(date -u +"%Y%m%d")
  
  local ms_part
  if command -v python3 >/dev/null 2>&1; then
    ms_part=$(python3 -c "import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S%f')[:9])")
  else
    ms_part="$(date -u +"%H%M%S")000"
  fi

  local job_id="${clean_app}_${clean_cat}_${date_part}_${ms_part}"

  if [[ -n "${country_iso}" ]]; then
    clean_country=$(sanitize_label "${country_iso}")
    job_id="${job_id}_${clean_country}"
    if [[ -n "${admin_area}" ]]; then
      clean_admin=$(sanitize_label "${admin_area}")
      job_id="${job_id}_${clean_admin}"
    fi
  fi

  echo "${job_id}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  APP="${1:-workspace}"
  CAT="${2:-analysis}"
  COUNTRY="${3:-}"
  ADMIN="${4:-}"
  generate_bigquery_job_id "${APP}" "${CAT}" "${COUNTRY}" "${ADMIN}"
fi
