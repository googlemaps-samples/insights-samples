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
# @param string parent Required. The parent project. Format: projects/{project}
# @param integer page_size Optional. The number of results per page.
# @param string project_id Optional. Project ID for quota/billing.
roadsselection_v1_projects_selectedRoutes_list_all() {
  local parent="$1"
  local page_size="${2:-""}"
  local project_id="${3:-""}"
  local next_page_token=""

  while true; do
    local response
    response=$(roadsselection_v1_projects_selectedRoutes_list "${parent}" "${page_size}" "${next_page_token}" "${project_id}")

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
