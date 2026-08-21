#!/bin/bash
# Helper script to list all items from an Analytics Hub list call by paging through tokens.

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
