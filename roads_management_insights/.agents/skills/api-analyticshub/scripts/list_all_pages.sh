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


source "$(dirname "${BASH_SOURCE[0]}")/analyticshub_v1.sh"

# Usage: list_all_pages <function_name> [args...]
# Example: list_all_pages analyticshub_projects_locations_dataExchanges_listings_list "project" "us" "exchange"
list_all_pages() {
    local func_name="$1"
    shift
    local args=("$@")
    
    local page_token=""
    local response=""
    
    while true; do
        # Call the function with current page token
        # We assume the last argument to the list function is page_token (based on our analyticshub_v1.sh)
        # Actually, let's be more robust.
        
        response=$($func_name "${args[@]}" "" "$page_token")
        
        # Output the listings (this depends on the response structure, usually has a top-level key like 'listings')
        echo "$response" | jq -c '.[] | select(type=="array")[]'
        
        # Extract next page token
        page_token=$(echo "$response" | jq -r '.nextPageToken // empty')
        
        if [[ -z "$page_token" ]]; then
            break
        fi
    done
}
