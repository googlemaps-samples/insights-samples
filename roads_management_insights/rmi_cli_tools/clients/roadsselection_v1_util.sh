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
# UTILITY SCRIPT FOR: roadsselection_v1
###############################################################################

# Source the main client script
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${_SCRIPT_DIR}/roadsselection_v1.sh"


###############################################################################
# Roads Selection API (v1) - Utility Functions
#
# This script provides higher-level convenience functions for the Roads 
# Selection API, such as automatic pagination for list methods.
###############################################################################

# Lists all SelectedRoutes by automatically handling pagination.
#
# Output: Stream of SelectedRoute resources in JSONL (Newline Delimited JSON) format.
#
# @param string project_id Required.
# @param integer page_size Optional.
# @param string page_token Optional.
# @param string billing_project_id Optional. Defaults to project_id.
roadsselection_v1_projects_selectedRoutes_list_all() {
  local project_id="$1"
  local page_size="${2:-""}"
  local next_page_token="${3:-""}"
  local billing_project_id="${4:-$project_id}"

  while true; do
    local response
    response=$(roadsselection_v1_projects_selectedRoutes_list "${project_id}" "${page_size}" "${next_page_token}" "${billing_project_id}")

    # Check for API Error
    if echo "$response" | jq --exit-status '.error' > /dev/null 2>&1; then
        echo "API Error: $(echo "$response" | jq --compact-output '.error')" >&2
        return 1
    fi

    # Output the current page of routes (JSONL format)
    echo "$response" | jq -c '.selectedRoutes[]? // empty'

    # Extract next page token
    next_page_token=$(echo "$response" | jq -r '.nextPageToken // empty')

    if [[ -z "${next_page_token}" ]]; then
      break
    fi
  done
}
