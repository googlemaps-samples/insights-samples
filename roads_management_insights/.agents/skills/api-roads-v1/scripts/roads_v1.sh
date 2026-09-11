#!/bin/bash
#
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
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

# Source internal helper scripts
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
# shellcheck source=/dev/null
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/roads_v1_helpers.sh" ]]; then
  source "$(dirname "${BASH_SOURCE[0]}")/roads_v1_helpers.sh"
fi

ROADS_V1_BASE_URL="https://roads.googleapis.com/v1"

# Snaps GPS coordinates to the road network.
#
# @param string points Required. Pipe-separated list of lat,lng pairs (e.g. "60.170880,24.942795|60.170879,24.942796").
# @param boolean interpolate Optional. Whether to interpolate paths.
# @param string project_id Optional. Project ID for billing.
roads_v1_snaptoroads() {
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
roads_v1_nearestroads() {
  local points="$1"
  local project_id="${2:-}"

  local query_params
  query_params=$(_build_query_params "points=${points}")
  local url="${ROADS_V1_BASE_URL}/nearestRoads${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# --- Backward-Compatibility Aliases ---
roads_v1_snapToRoads() { roads_v1_snaptoroads "$@"; }
roads_v1_nearestRoads() { roads_v1_nearestroads "$@"; }

