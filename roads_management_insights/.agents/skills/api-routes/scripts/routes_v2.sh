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


# Source the internal helper script
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/routes_v2_helpers.sh"

# --- Routes API v2 ---

# Base URL for the Routes API
ROUTES_V2_BASE_URL="https://routes.googleapis.com/"

# --- Methods ---

# Returns the primary route along with optional alternate routes.
#
# @param string request_body The request body as a JSON string.
# @param string field_mask The fields to return in the response.
# @param string project_id Optional. The project ID for billing.
# @see https://developers.google.com/maps/documentation/routes/reference/rest/v2/routes/computeRoutes
routes_computeRoutes() {
  local request_body="$1"
  local field_mask="${2:-*}"
  local project_id="${3:-}"
  local additional_headers
  additional_headers="X-Goog-FieldMask: ${field_mask}"
  local url="${ROUTES_V2_BASE_URL}directions/v2:computeRoutes"
  _call_api "POST" "${url}" "${request_body}" "${project_id}" "${additional_headers}"
}

# Takes a list of origins and destinations and returns a stream containing route information.
#
# @param string request_body The request body as a JSON string.
# @param string field_mask The fields to return in the response.
# @param string project_id Optional. The project ID for billing.
# @see https://developers.google.com/maps/documentation/routes/reference/rest/v2/routes/computeRouteMatrix
routes_computeRouteMatrix() {
  local request_body="$1"
  local field_mask="${2:-*}"
  local project_id="${3:-}"
  local additional_headers
  additional_headers="X-Goog-FieldMask: ${field_mask}"
  local url="${ROUTES_V2_BASE_URL}distanceMatrix/v2:computeRouteMatrix"
  _call_api "POST" "${url}" "${request_body}" "${project_id}" "${additional_headers}"
}

routes_v2_computeRoutes() {
  routes_computeRoutes "$@"
}

routes_v2_computeRouteMatrix() {
  routes_computeRouteMatrix "$@"
}
