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
# Client for the Roads Selection API v1.
# Implements all 8 RPC methods defined in roads_selection_service.proto.
#
# Endpoint: https://roads.googleapis.com/selection/v1
#

# Source the common helper script
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/roadsselection_v1_helpers.sh"

ROADSSELECTION_BASE_URL="${ROADSSELECTION_BASE_URL:-https://roads.googleapis.com/selection/v1}"

# --- Methods ---

# Creates a SelectedRoute and starts a schedule to periodically retrieve cache information.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string request_body Required. JSON string (SelectedRoute).
# @param string selected_route_id Optional. The ID for the route (4-63 chars).
roadsselection_v1_selectedroute_create() {
  local pid="$1"
  local request_body="$2"
  local selected_route_id="${3:-}"

  local query_params
  query_params=$(_build_query_params "selectedRouteId=${selected_route_id}")
  local url="${ROADSSELECTION_BASE_URL}/projects/${pid}/selectedRoutes${query_params}"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Creates multiple SelectedRoute resources in batch (up to 1,000 routes).
#
# @param string project_id Required. The Google Cloud project ID.
# @param string request_body Required. JSON string (BatchCreateSelectedRoutesRequest).
roadsselection_v1_selectedroute_batchcreate() {
  local pid="$1"
  local request_body="$2"
  local url="${ROADSSELECTION_BASE_URL}/projects/${pid}/selectedRoutes:batchCreate"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Gets a SelectedRoute as specified by its name.
#
# @param string name Required. Resource name (projects/{project}/selectedRoutes/{selected_route}).
# @param string project_id Optional. Project ID for quota/billing.
roadsselection_v1_selectedroute_get() {
  local name="$1"
  local pid="${2:-}"
  if [[ -z "${pid}" ]]; then
    pid=$(echo "${name}" | awk -F'/' '{print $2}')
  fi

  local url="${ROADSSELECTION_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Updates a SelectedRoute as specified by its name (PATCH).
#
# @param string name Required. Resource name (projects/{project}/selectedRoutes/{selected_route}).
# @param string request_body Required. JSON string (SelectedRoute).
# @param string update_mask Optional. Comma-separated field paths (e.g. 'display_name,route_attributes').
# @param string project_id Optional. Project ID for quota/billing.
roadsselection_v1_selectedroute_patch() {
  local name="$1"
  local request_body="$2"
  local update_mask="${3:-}"
  local pid="${4:-}"
  if [[ -z "${pid}" ]]; then
    pid=$(echo "${name}" | awk -F'/' '{print $2}')
  fi

  local query_params
  query_params=$(_build_query_params "updateMask=${update_mask}")
  local url="${ROADSSELECTION_BASE_URL}/${name}${query_params}"
  _call_api "PATCH" "${url}" "${request_body}" "${pid}"
}

# Updates multiple SelectedRoute resources in batch (up to 1,000 routes).
#
# @param string project_id Required. The Google Cloud project ID.
# @param string request_body Required. JSON string (BatchUpdateSelectedRoutesRequest).
roadsselection_v1_selectedroute_batchupdate() {
  local pid="$1"
  local request_body="$2"
  local url="${ROADSSELECTION_BASE_URL}/projects/${pid}/selectedRoutes:batchUpdate"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Lists all SelectedRoute resources for the specified project with pagination.
#
# @param string project_id Required. The Google Cloud project ID.
# @param integer page_size Optional. Number of results to return (max 5000, default 100).
# @param string page_token Optional. A page token from previous call.
roadsselection_v1_selectedroute_list() {
  local pid="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"

  local query_params
  query_params=$(_build_query_params \
    "pageSize=${page_size}" \
    "pageToken=${page_token}")

  local url="${ROADSSELECTION_BASE_URL}/projects/${pid}/selectedRoutes${query_params}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Deletes the specified SelectedRoute for the specified project.
#
# @param string name Required. Resource name (projects/{project}/selectedRoutes/{selected_route}).
# @param string project_id Optional. Project ID for quota/billing.
roadsselection_v1_selectedroute_delete() {
  local name="$1"
  local pid="${2:-}"
  if [[ -z "${pid}" ]]; then
    pid=$(echo "${name}" | awk -F'/' '{print $2}')
  fi

  local url="${ROADSSELECTION_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${pid}"
}

# Deletes multiple SelectedRoute resources for the specified project in batch (up to 1,000 routes).
#
# @param string project_id Required. The Google Cloud project ID.
# @param string request_body Required. JSON string (BatchDeleteSelectedRoutesRequest).
roadsselection_v1_selectedroute_batchdelete() {
  local pid="$1"
  local request_body="$2"
  local url="${ROADSSELECTION_BASE_URL}/projects/${pid}/selectedRoutes:batchDelete"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}
