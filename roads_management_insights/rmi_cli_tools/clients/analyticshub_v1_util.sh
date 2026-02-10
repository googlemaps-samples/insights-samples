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
# UTILITY SCRIPT FOR: analyticshub_v1
###############################################################################

# Source the main client script
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_SCRIPT_DIR}/analyticshub_v1.sh"


###############################################################################
# Analytics Hub API (v1) - Utility Functions
###############################################################################

# Lists all Data Exchanges by automatically handling pagination.
#
# Output: Stream of DataExchange resources in JSONL (Newline Delimited JSON) format.
#
# @param string parent Required.
# @param integer page_size Optional.
# @param string project_id Optional.
analyticshub_v1_projects_locations_dataExchanges_list_all() {
  local parent="$1"
  local page_size="${2:-""}"
  local project_id="${3:-""}"
  local next_page_token=""

  while true; do
    local response
    response=$(analyticshub_v1_projects_locations_dataExchanges_list "${parent}" "${page_size}" "${next_page_token}" "${project_id}")

    if echo "$response" | jq --exit-status '.error' > /dev/null 2>&1; then
        echo "API Error: $(echo "$response" | jq --compact-output '.error')" >&2
        return 1
    fi

    echo "$response" | jq -c '.dataExchanges[]? // empty'

    next_page_token=$(echo "$response" | jq -r '.nextPageToken // empty')
    if [[ -z "${next_page_token}" ]]; then break; fi
  done
}

# Lists all Listings by automatically handling pagination.
#
# Output: Stream of Listing resources in JSONL (Newline Delimited JSON) format.
#
# @param string parent Required.
# @param integer page_size Optional.
# @param string project_id Optional.
analyticshub_v1_projects_locations_dataExchanges_listings_list_all() {
  local parent="$1"
  local page_size="${2:-""}"
  local project_id="${3:-""}"
  local next_page_token=""

  while true; do
    local response
    response=$(analyticshub_v1_projects_locations_dataExchanges_listings_list "${parent}" "${page_size}" "${next_page_token}" "${project_id}")

    if echo "$response" | jq --exit-status '.error' > /dev/null 2>&1; then
        echo "API Error: $(echo "$response" | jq --compact-output '.error')" >&2
        return 1
    fi

    echo "$response" | jq -c '.listings[]? // empty'

    next_page_token=$(echo "$response" | jq -r '.nextPageToken // empty')
    if [[ -z "${next_page_token}" ]]; then break; fi
  done
}
