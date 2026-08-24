#!/bin/bash
set -euo pipefail
#
# Client for the legacy Roads API (v1).
# It is not meant to be used directly, but rather to be sourced by other scripts.
#
# Discovery Doc Revision: 20260819
# Base URL: https://roads.googleapis.com/v1
#
# For more information, see official documentation:
# https://developers.google.com/maps/documentation/roads

# Source internal helper script
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"

ROADS_V1_BASE_URL="https://roads.googleapis.com/v1"

# Snaps GPS coordinates to the road network.
#
# @param string points Required. Pipe-separated list of lat,lng pairs (e.g. "60.170880,24.942795|60.170879,24.942796").
# @param boolean interpolate Optional. Whether to interpolate paths.
# @param string project_id Optional. Project ID for billing.
roads_v1_snapToRoads() {
  local path="$1"
  local interpolate="${2:-false}"
  local project_id="${3:-}"

  local query_params
  query_params=$(_build_query_params "path=${path}" "interpolate=${interpolate}")
  local url="${ROADS_V1_BASE_URL}/snapToRoads${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Finds the closest road segments for given points.
#
# @param string points Required. Pipe-separated list of lat,lng pairs.
# @param string project_id Optional. Project ID for billing.
roads_v1_nearestRoads() {
  local points="$1"
  local project_id="${2:-}"

  local query_params
  query_params=$(_build_query_params "points=${points}")
  local url="${ROADS_V1_BASE_URL}/nearestRoads${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}
