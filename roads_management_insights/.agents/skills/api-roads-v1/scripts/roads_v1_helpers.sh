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
# Sibling resolution
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${DIR}/api-common.sh" ]]; then
  source "${DIR}/api-common.sh"
fi


# This script provides helper functions for creating JSON objects and parameter strings
# for the legacy Roads API v1.
# It is meant to be sourced by other scripts.

# Creates a JSON object for a LatLng coordinate pair.
# @param number latitude
# @param number longitude
roads_v1_latlng_json() {
  local lat="$1"
  local lng="$2"
  jq -n --argjson lat "$lat" --argjson lng "$lng" '{latitude: $lat, longitude: $lng}'
}

# Formats an array of "lat,lng" string arguments or a JSON array of lat,lng objects into a pipe-separated string.
# @param ... list of "lat,lng" coordinates (e.g. "60.170880,24.942795" "60.170879,24.942796")
roads_v1_latlng_pipe_string() {
  local IFS="|"
  echo "$*"
}
