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
# @param string project_id Required.
# @param string location Required.
# @param integer page_size Optional.
# @param string page_token Optional.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_list_all() {
  local project_id="$1"
  local location="$2"
  local page_size="${3:-""}"
  local next_page_token="${4:-""}"
  local billing_project_id="${5:-$project_id}"

  while true; do
    local response
    response=$(analyticshub_v1_projects_locations_dataExchanges_list "${project_id}" "${location}" "${page_size}" "${next_page_token}" "${billing_project_id}")

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
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param integer page_size Optional.
# @param string page_token Optional.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_listings_list_all() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local page_size="${4:-""}"
  local next_page_token="${5:-""}"
  local billing_project_id="${6:-$project_id}"

  while true; do
    local response
    response=$(analyticshub_v1_projects_locations_dataExchanges_listings_list "${project_id}" "${location}" "${data_exchange_id}" "${page_size}" "${next_page_token}" "${billing_project_id}")

    if echo "$response" | jq --exit-status '.error' > /dev/null 2>&1; then
        echo "API Error: $(echo "$response" | jq --compact-output '.error')" >&2
        return 1
    fi

    echo "$response" | jq -c '.listings[]? // empty'

    next_page_token=$(echo "$response" | jq -r '.nextPageToken // empty')
    if [[ -z "${next_page_token}" ]]; then break; fi
  done
}
