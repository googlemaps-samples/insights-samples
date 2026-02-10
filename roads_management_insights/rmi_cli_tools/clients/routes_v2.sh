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
# Routes API (v2) - JSON Helpers
#
# This script provides helper functions to construct JSON request bodies
# for the Routes API v2.
###############################################################################

# Creates a JSON object for a LatLng.
# @param float latitude
# @param float longitude
create_lat_lng() {
    jq -c --null-input --argjson lat "$1" --argjson lon "$2" \
        '{latitude: $lat, longitude: $lon}'
}

# Creates a JSON object for a Location.
# @param string lat_lng_json Required.
# @param integer heading Optional.
create_location() {
    local lat_lng="$1"
    local heading="${2:-null}"

    jq -c --null-input \
       --argjson ll "$lat_lng" \
       --argjson h "$heading" \
       '{latLng: $ll, heading: $h} | del(..|select(. == null))'
}

# Creates a JSON object for a Waypoint.
# @param string location_json Optional. Location JSON.
# @param string place_id Optional.
# @param string address Optional.
# @param boolean via Optional.
create_waypoint() {
    local location="${1:-null}"
    local place_id="${2:-null}"
    local address="${3:-null}"
    local via="${4:-null}"

    jq -c --null-input \
       --argjson loc "$location" \
       --arg pid "$place_id" \
       --arg addr "$address" \
       --argjson via "$via" \
       '{location: $loc, placeId: $pid, address: $addr, via: $via} | del(..|select(. == "null" or . == null))'
}

# Creates a JSON object for RouteModifiers.
# @param boolean avoid_tolls Optional.
# @param boolean avoid_highways Optional.
# @param boolean avoid_ferries Optional.
create_route_modifiers() {
    local tolls="${1:-null}"
    local highways="${2:-null}"
    local ferries="${3:-null}"

    jq -c --null-input \
       --argjson tolls "$tolls" \
       --argjson highways "$highways" \
       --argjson ferries "$ferries" \
       '{avoidTolls: $tolls, avoidHighways: $highways, avoidFerries: $ferries} | del(..|select(. == null))'
}

# Creates a JSON object for TransitPreferences.
# @param string allowed_travel_modes_array_json Optional. Array of strings (e.g. ["BUS", "SUBWAY"]).
# @param string routing_preference Optional. e.g. LESS_WALKING.
create_transit_preferences() {
    local modes="${1:-null}"
    local pref="${2:-null}"

    jq -c --null-input \
       --argjson modes "$modes" \
       --arg pref "$pref" \
       '{allowedTravelModes: $modes, routingPreference: $pref} | del(..|select(. == "null" or . == null))'
}

# Creates a JSON object for a ComputeRoutesRequest.
# @param string origin_waypoint_json Required.
# @param string destination_waypoint_json Required.
# @param string travel_mode Optional. e.g. DRIVE, WALK, BICYCLE.
# @param string routing_preference Optional. e.g. TRAFFIC_AWARE, TRAFFIC_AWARE_OPTIMAL.
# @param string intermediates_array_json Optional. Array of Waypoint JSONs.
create_compute_routes_request() {
    local origin="$1"
    local destination="$2"
    local travel_mode="${3:-null}"
    local routing_pref="${4:-null}"
    local intermediates="${5:-null}"

    jq -c --null-input \
       --argjson origin "$origin" \
       --argjson dest "$destination" \
       --arg tm "$travel_mode" \
       --arg rp "$routing_pref" \
       --argjson inter "$intermediates" \
       '{origin: $origin, destination: $dest, travelMode: $tm, routingPreference: $rp, intermediates: $inter} | del(..|select(. == "null" or . == null))'
}

# Creates a JSON object for a RouteMatrixOrigin.
# @param string waypoint_json Required.
# @param string route_modifiers_json Optional.
create_route_matrix_origin() {
    local waypoint="$1"
    local modifiers="${2:-null}"

    jq -c --null-input \
       --argjson wp "$waypoint" \
       --argjson mod "$modifiers" \
       '{waypoint: $wp, routeModifiers: $mod} | del(..|select(. == null))'
}

# Creates a JSON object for a RouteMatrixDestination.
# @param string waypoint_json Required.
create_route_matrix_destination() {
    local waypoint="$1"

    jq -c --null-input \
       --argjson wp "$waypoint" \
       '{waypoint: $wp}'
}

# Creates a JSON object for a ComputeRouteMatrixRequest.
# @param string origins_array_json Required. Array of RouteMatrixOrigin JSONs.
# @param string destinations_array_json Required. Array of RouteMatrixDestination JSONs.
# @param string travel_mode Optional.
# @param string routing_preference Optional.
create_compute_route_matrix_request() {
    local origins="$1"
    local destinations="$2"
    local travel_mode="${3:-null}"
    local routing_pref="${4:-null}"

    jq -c --null-input \
       --argjson origins "$origins" \
       --argjson destinations "$destinations" \
       --arg tm "$travel_mode" \
       --arg rp "$routing_pref" \
       '{origins: $origins, destinations: $destinations, travelMode: $tm, routingPreference: $rp} | del(..|select(. == "null" or . == null))'
}


###############################################################################
# Routes API (v2) Client
#
# This script provides a client for the Routes API v2.
#
# Discovery Doc Revision: 20260202
###############################################################################

# Resolve the directory of this script to locate internal helpers.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Base URL for the Routes API
ROUTES_V2_BASE_URL="https://routes.googleapis.com"

# Returns the primary route along with optional alternate routes.
#
# @param string request_body Required. ComputeRoutesRequest JSON.
# @param string field_mask Required. Response field mask (e.g., "*").
# @param string project_id Optional.
# @see https://developers.google.com/maps/documentation/routes/reference/rest/v2/directions/computeRoutes
routes_v2_computeRoutes() {
  local request_body="$1"
  local field_mask="${2:-"*"}"
  local project_id="${3:-""}"
  
  local url="${ROUTES_V2_BASE_URL}/directions/v2:computeRoutes"
  local headers="X-Goog-FieldMask: ${field_mask}"
  
  _call_api "POST" "${url}" "${request_body}" "${project_id}" "${headers}"
}

# Takes in a list of origins and destinations and returns a stream of route information.
#
# @param string request_body Required. ComputeRouteMatrixRequest JSON.
# @param string field_mask Required. Response field mask.
# @param string project_id Optional.
# @see https://developers.google.com/maps/documentation/routes/reference/rest/v2/distanceMatrix/computeRouteMatrix
routes_v2_computeRouteMatrix() {
  local request_body="$1"
  local field_mask="${2:-"*"}"
  local project_id="${3:-""}"
  
  local url="${ROUTES_V2_BASE_URL}/distanceMatrix/v2:computeRouteMatrix"
  local headers="X-Goog-FieldMask: ${field_mask}"
  
  _call_api "POST" "${url}" "${request_body}" "${project_id}" "${headers}"
}
