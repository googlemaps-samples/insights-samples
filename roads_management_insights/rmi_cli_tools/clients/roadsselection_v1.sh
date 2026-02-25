#!/bin/bash
set -euo pipefail
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



###############################################################################
# Google API Client - Internal Utilities
#
# This script provides shared internal helper functions for authentication,
# request building, and API execution. It is intended to be sourced by
# specific service client scripts.
###############################################################################

# =============================================================================
# INTERNAL: Authentication & API Utilities
# =============================================================================

# Cache the access token to avoid calling gcloud repeatedly.
_API_CLIENT_ACCESS_TOKEN=""

# _get_access_token ensures we only call gcloud once per script execution.
_get_access_token() {
  local project_id="${1:-""}"
  local gcloud_args=()

  if [[ -n "${project_id}" ]]; then
    gcloud_args+=("--project"="${project_id}")
  fi

  if [[ -z "${_API_CLIENT_ACCESS_TOKEN}" ]]; then
    if ! command -v gcloud &> /dev/null; then
        echo "Error: gcloud CLI is not installed or not in PATH." >&2
        return 1
    fi
    _API_CLIENT_ACCESS_TOKEN=$(gcloud auth application-default print-access-token "${gcloud_args[@]}" 2>/dev/null)
  fi
  echo "${_API_CLIENT_ACCESS_TOKEN}"
}
# _build_query_params safely constructs a URL query string.
#
# @param ... Key-value pairs (e.g., "pageSize=10" "pageToken=abc").
#            Only pairs with a non-empty value are included.
_build_query_params() {
  local params=()
  for arg in "$@"; do
    local key="${arg%%=*}"
    local value="${arg#*=}"
    if [[ -n "$value" ]]; then
      # Note: For production use, value should be URL-encoded.
      params+=("${key}=${value}")
    fi
  done

  if ((${#params[@]} > 0)); then
    (
      # Join the array with '&'
      IFS='&'
      echo "?${params[*]}"
    )
  else
    echo ""
  fi
}


# _call_api is a helper function to make authenticated API calls.
#
# @param string method The HTTP method (e.g., GET, POST, DELETE).
# @param string url The full URL for the API endpoint.
# @param string body Optional. The request body as a JSON string.
# @param string project_id Optional. Project ID for quota and billing.
# @param string additional_headers Optional. A newline-separated string of additional headers.
_call_api() {
  local method="$1"
  local url="$2"
  local body="${3:-""}"
  local project_id="${4:-""}"
  local additional_headers="${5:-""}"
  local access_token

  # Log the API call to stderr (captured by logs)
  echo "[API CALL] $method $url" >&2
  if [[ -n "${body}" ]]; then
      echo "[API BODY] ${body}" >&2
  fi

  access_token=$(_get_access_token "${project_id}")

  if [[ -z "${access_token}" ]]; then
    echo "Error: Not authenticated. Please run 'gcloud auth application-default login'." >&2
    return 1
  fi

  local curl_args=("--silent" "--show-error" "--request" "${method}")
  curl_args+=("--header" "Authorization: Bearer ${access_token}")

  # Add the quota project header if a project_id was provided.
  if [[ -n "${project_id}" ]]; then
    curl_args+=("--header" "X-Goog-User-Project: ${project_id}")
  fi

  # Parse and add additional headers
  if [[ -n "${additional_headers}" ]]; then
    local OLD_IFS="$IFS"
    IFS=$'\n'
    for header in ${additional_headers}; do
      curl_args+=("--header" "${header}")
    done
    IFS="$OLD_IFS"
  fi

  if [[ -n "${body}" ]]; then
    curl_args+=("--header" "Content-Type: application/json")
    curl_args+=("--data" "${body}")
  fi

  curl "${curl_args[@]}" "${url}"
}


###############################################################################
# Roads Selection API (v1) - JSON Helpers
#
# This script provides helper functions to construct JSON request bodies
# for the Roads Selection API.
###############################################################################

# Creates a JSON object for a LatLng.
# @param float latitude
# @param float longitude
create_lat_lng() {
    jq -c --null-input --argjson lat "$1" --argjson lon "$2" \
        '{latitude: $lat, longitude: $lon}'
}

# Creates a JSON object for a DynamicRoute.
# @param string origin_json JSON object (LatLng)
# @param string destination_json JSON object (LatLng)
# @param string intermediates_json_array Optional. JSON array of LatLng objects.
create_dynamic_route() {
    local origin="$1"
    local destination="$2"
    local intermediates="${3:-null}"

    jq -c --null-input \
       --argjson origin "$origin" \
       --argjson dest "$destination" \
       --argjson inter "$intermediates" \
       '{origin: $origin, destination: $dest, intermediates: $inter} | del(..|nulls)'
}

# Creates a JSON object for a SelectedRoute.
# @param string dynamic_route_json JSON object (DynamicRoute)
# @param string display_name Optional.
# @param string route_attributes_json Optional. JSON object (map<string, string>).
create_selected_route() {
    local dynamic_route="$1"
    local display_name="${2:-null}"
    local route_attributes="${3:-null}"

    jq -c --null-input \
       --argjson dr "$dynamic_route" \
       --arg dn "$display_name" \
       --argjson ra "$route_attributes" \
       '{dynamicRoute: $dr, displayName: $dn, routeAttributes: $ra} | del(..|nulls) | if .displayName == "null" then del(.displayName) else . end'
}

# Creates a JSON object for a CreateSelectedRouteRequest.
# @param string parent Required. Format: projects/{project}
# @param string selected_route_json Required. JSON object (SelectedRoute).
# @param string selected_route_id Optional.
create_create_selected_route_request() {
    local parent="$1"
    local selected_route="$2"
    local selected_route_id="${3:-null}"

    jq -c --null-input \
       --arg p "$parent" \
       --argjson sr "$selected_route" \
       --arg srid "$selected_route_id" \
       '{parent: $p, selectedRoute: $sr, selectedRouteId: $srid} | del(..|nulls) | if .selectedRouteId == "null" then del(.selectedRouteId) else . end'
}

# Creates a JSON object for a BatchCreateSelectedRoutesRequest.
# @param string requests_json_array Required. JSON array of CreateSelectedRouteRequest objects.
create_batch_create_selected_routes_request() {
    local requests="$1"

    jq -c --null-input \
       --argjson reqs "$requests" \
       '{requests: $reqs}'
}


###############################################################################
# Roads Selection API (v1) Client
#
# This script provides a client for the Roads Selection API.
# It includes authentication helpers, request builders, and API methods.
#
# Discovery Doc Revision: 20260204
###############################################################################

# Resolve the directory of this script to locate internal helpers.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Base URL for the Roads Selection API
ROADS_SELECTION_V1_BASE_URL="https://roads.googleapis.com/selection/v1"

# Creates multiple SelectedRoutes and starts a schedule.
#
# @param string project_id Required.
# @param string request_body Required. The BatchCreateSelectedRoutesRequest JSON.
# @param string billing_project_id Optional. Defaults to project_id.
roadsselection_v1_projects_selectedRoutes_batchCreate() {
  local project_id="$1"
  local request_body="$2"
  local billing_project_id="${3:-$project_id}"
  local parent="projects/${project_id}"
  local url="${ROADS_SELECTION_V1_BASE_URL}/${parent}/selectedRoutes:batchCreate"
  _call_api "POST" "${url}" "${request_body}" "${billing_project_id}"
}

# Creates a SelectedRoute and starts a schedule.
#
# @param string project_id Required.
# @param string request_body Required. The SelectedRoute JSON.
# @param string selected_route_id Optional. The ID to use for the SelectedRoute.
# @param string billing_project_id Optional. Defaults to project_id.
roadsselection_v1_projects_selectedRoutes_create() {
  local project_id="$1"
  local request_body="$2"
  local selected_route_id="${3:-}"
  local billing_project_id="${4:-$project_id}"
  
  local parent="projects/${project_id}"
  local query_params=""
  if [[ -n "${selected_route_id}" ]]; then
      query_params=$(_build_query_params "selectedRouteId=${selected_route_id}")
  fi

  local url="${ROADS_SELECTION_V1_BASE_URL}/${parent}/selectedRoutes${query_params}"
  _call_api "POST" "${url}" "${request_body}" "${billing_project_id}"
}

# Deletes the specified SelectedRoute.
#
# @param string project_id Required.
# @param string selected_route_id Required.
# @param string billing_project_id Optional. Defaults to project_id.
roadsselection_v1_projects_selectedRoutes_delete() {
  local project_id="$1"
  local selected_route_id="$2"
  local billing_project_id="${3:-$project_id}"
  local name="projects/${project_id}/selectedRoutes/${selected_route_id}"
  local url="${ROADS_SELECTION_V1_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${billing_project_id}"
}

# Gets a SelectedRoute.
#
# @param string project_id Required.
# @param string selected_route_id Required.
# @param string billing_project_id Optional. Defaults to project_id.
roadsselection_v1_projects_selectedRoutes_get() {
  local project_id="$1"
  local selected_route_id="$2"
  local billing_project_id="${3:-$project_id}"
  local name="projects/${project_id}/selectedRoutes/${selected_route_id}"
  local url="${ROADS_SELECTION_V1_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${billing_project_id}"
}

# Lists all SelectedRoutes for the specified project.
#
# @param string project_id Required.
# @param integer page_size Optional.
# @param string page_token Optional.
# @param string billing_project_id Optional. Defaults to project_id.
roadsselection_v1_projects_selectedRoutes_list() {
  local project_id="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local billing_project_id="${4:-$project_id}"
  
  local parent="projects/${project_id}"
  local query_args=()
  if [[ -n "${page_size}" ]]; then query_args+=("pageSize=${page_size}"); fi
  if [[ -n "${page_token}" ]]; then query_args+=("pageToken=${page_token}"); fi
  
  local query_params
  query_params=$(_build_query_params "${query_args[@]}")

  local url="${ROADS_SELECTION_V1_BASE_URL}/${parent}/selectedRoutes${query_params}"
  _call_api "GET" "${url}" "" "${billing_project_id}"
}
