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
# RMI API Access Verification
#
# This script demonstrates and tests the Create, Read, List, and Delete
# operations for the Roads Selection API.
#
# Usage: ./rmi_verify_api_access.sh <PROJECT_RMI_ID>
###############################################################################

PROJECT_RMI_ID="${1:-}"

if [[ -z "$PROJECT_RMI_ID" ]]; then
    echo "Usage: $0 <PROJECT_RMI_ID>"
    exit 1
fi

# Locate and source the bundled utility script
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_SCRIPT="${_SCRIPT_DIR}/../clients/roadsselection_v1_util.sh"

if [[ ! -f "$DIST_SCRIPT" ]]; then
    echo "Error: Bundled script not found at $DIST_SCRIPT"
    echo "Please run 'scripts/bash/bundle.sh' first."
    exit 1
fi

source "$DIST_SCRIPT"

# Displays usage information and available commands for the API access test script.
usage() {
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  all <PROJECT_RMI_ID>           Run all CRUD tests sequentially"
    echo "  step_prepare_data              Prepare sample route data"
    echo "  step_create_route <PROJECT_ID> Create a selected route"
    echo "  step_get_route <PROJECT_ID>    Retrieve the created route"
    echo "  step_list_routes <PROJECT_ID>  List routes and verify presence"
    echo "  step_delete_route <PROJECT_ID> Delete the created route"
    echo "  step_verify_deletion <PROJECT_ID> Verify the route is gone (404)"
}

# Global variables to store test state (for sequential 'all' run)
ORIGIN=""
DESTINATION=""
DYNAMIC_ROUTE=""
DISPLAY_NAME=""
SELECTED_ROUTE=""
ROUTE_NAME=""

# Prepares the necessary data structures (LatLng, Route) for the test.
step_prepare_data() {
    echo "--- Step 1: Preparing Data ---"
    # Tokyo Tower
    ORIGIN=$(create_lat_lng 35.658581 139.745433)
    # Roppongi Hills
    DESTINATION=$(create_lat_lng 35.660456 139.729067)
    # Simple Route
    DYNAMIC_ROUTE=$(create_dynamic_route "$ORIGIN" "$DESTINATION")
    DISPLAY_NAME="CRUD Test Route $(date +%s)"
    SELECTED_ROUTE=$(create_selected_route "$DYNAMIC_ROUTE" "$DISPLAY_NAME")

    echo "Origin: $ORIGIN"
    echo "Destination: $DESTINATION"
    echo "Display Name: $DISPLAY_NAME"
}

# Creates a new selected route in the specified project.
step_create_route() {
    local project_id="${1:-$PROJECT_RMI_ID}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_RMI_ID required"; exit 1; fi
    if [[ -z "$SELECTED_ROUTE" ]]; then step_prepare_data; fi

    echo "--- Step 2: Create Selected Route in $project_id ---"
    local response_create
    response_create=$(roadsselection_v1_projects_selectedRoutes_create "$project_id" "$SELECTED_ROUTE")

    # Check for errors
    if echo "$response_create" | jq -e '.error' >/dev/null; then
        echo "Error Creating Route:"
        echo "$response_create" | jq .
        exit 1
    fi

    ROUTE_NAME=$(echo "$response_create" | jq -r '.name')
    echo "Created Route Name: $ROUTE_NAME"
}

# Retrieves the details of a specific selected route.
step_get_route() {
    local project_id="${1:-$PROJECT_RMI_ID}"
    local route_name="${2:-$ROUTE_NAME}"
    if [[ -z "$project_id" || -z "$route_name" ]]; then echo "Usage: step_get_route <PROJECT_ID> <ROUTE_NAME>"; exit 1; fi

    local route_id
    route_id=$(echo "$route_name" | sed 's|.*/selectedRoutes/||')

    echo "--- Step 3: Get Selected Route $route_id ---"
    local response_get
    response_get=$(roadsselection_v1_projects_selectedRoutes_get "$project_id" "$route_id")

    if echo "$response_get" | jq -e '.error' >/dev/null; then
        echo "Error Getting Route:"
        echo "$response_get" | jq .
        exit 1
    fi

    local get_display_name
    get_display_name=$(echo "$response_get" | jq -r '.displayName')
    echo "Retrieved Route Display Name: $get_display_name"
}

# Lists all selected routes in the project and checks if a specific route exists.
step_list_routes() {
    local project_id="${1:-$PROJECT_RMI_ID}"
    local route_name="${2:-$ROUTE_NAME}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_RMI_ID required"; exit 1; fi

    echo "--- Step 4: List Selected Routes in $project_id ---"
    local response_list
    response_list=$(roadsselection_v1_projects_selectedRoutes_list "$project_id" "100")

    if echo "$response_list" | jq -e '.error' >/dev/null; then
        echo "Error Listing Routes:"
        echo "$response_list" | jq .
        exit 1
    fi

    if [[ -n "$route_name" ]]; then
        local found_in_list
        found_in_list=$(echo "$response_list" | jq --arg name "$route_name" '[.selectedRoutes[]? | select(.name == $name)] | length')
        if [[ "$found_in_list" -gt 0 ]]; then
            echo "PASS: Route $route_name found in list."
        else
            echo "FAIL: Route $route_name not found in list."
        fi
    fi
}

# Deletes a specific selected route from the project.
step_delete_route() {
    local project_id="${1:-$PROJECT_RMI_ID}"
    local route_name="${2:-$ROUTE_NAME}"
    if [[ -z "$project_id" || -z "$route_name" ]]; then echo "Usage: step_delete_route <PROJECT_ID> <ROUTE_NAME>"; exit 1; fi

    local route_id
    route_id=$(echo "$route_name" | sed 's|.*/selectedRoutes/||')

    echo "--- Step 5: Delete Selected Route $route_id ---"
    local response_delete
    response_delete=$(roadsselection_v1_projects_selectedRoutes_delete "$project_id" "$route_id")

    if echo "$response_delete" | jq -e '.error' >/dev/null; then
        echo "Error Deleting Route:"
        echo "$response_delete" | jq .
        exit 1
    fi

    echo "Delete command executed successfully."
}

# Verifies that a route has been successfully deleted by attempting to retrieve it.
step_verify_deletion() {
    local project_id="${1:-$PROJECT_RMI_ID}"
    local route_name="${2:-$ROUTE_NAME}"
    if [[ -z "$project_id" || -z "$route_name" ]]; then echo "Usage: step_verify_deletion <PROJECT_ID> <ROUTE_NAME>"; exit 1; fi

    local route_id
    route_id=$(echo "$route_name" | sed 's|.*/selectedRoutes/||')

    echo "--- Step 6: Verify Deletion of $route_id ---"
    local response_get_again
    response_get_again=$(roadsselection_v1_projects_selectedRoutes_get "$project_id" "$route_id")

    if echo "$response_get_again" | jq -e '.error.code == 404' >/dev/null; then
        echo "PASS: Route successfully deleted (Received 404 as expected)."
    else
        echo "FAIL: Route might still exist or unexpected error."
        echo "Response: $response_get_again"
        exit 1
    fi
}

# Executes the complete CRUD test scenario sequentially.
run_all() {
    PROJECT_RMI_ID="${1:-}"
    if [[ -z "$PROJECT_RMI_ID" ]]; then usage; exit 1; fi

    echo "=== Starting CRUD Test for RMI Project: $PROJECT_RMI_ID ==="
    
    step_prepare_data
    step_create_route "$PROJECT_RMI_ID"
    step_get_route "$PROJECT_RMI_ID" "$ROUTE_NAME"
    step_list_routes "$PROJECT_RMI_ID" "$ROUTE_NAME"
    step_delete_route "$PROJECT_RMI_ID" "$ROUTE_NAME"
    step_verify_deletion "$PROJECT_RMI_ID" "$ROUTE_NAME"

    echo "=== CRUD Test Scenario Complete ==="
}

# Command dispatcher
if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

case "" in
    all)
        shift
        run_all "$@"
        ;;
    step_*)
        cmd=""
        shift
        "$cmd" "$@"
        ;;
    *)
        usage
        exit 1
        ;;
esac
