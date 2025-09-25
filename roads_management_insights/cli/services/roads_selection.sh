#!/bin/bash
#
# This script provides client functions for the Google Roads Management Insights
# Road Selection API v1.
#
# It is intended to be sourced by other scripts, not executed directly.
# It depends on 'auth.sh' to be in the same directory.
#
# For example:
#   source ./services/roads_selection.sh

set -euo pipefail

# Source the authentication helper script.
# shellcheck source=./auth.sh
#source ./auth.sh

# Creates multiple selected routes in a batch operation.
# API: https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/selection.v1.projects.selectedRoutes/batchCreate
#
# Args:
#   $1: PROJECT_ID - The Google Cloud project ID.
#   $2: REQUEST_BODY_FILE - A path to a JSON file containing the request body.
#       The body should conform to the batchCreate method's request format,
#       containing a list of `create` requests.
#
# Outputs:
#   The JSON response from the API to stdout.
function selectedroutes_batch_create() {
    local PROJECT_ID="$1"
    local REQUEST_BODY_FILE="$2"

    local PARENT="projects/${PROJECT_ID}"
    local URL="https://roads.googleapis.com/selection/v1/${PARENT}/selectedRoutes:batchCreate"
    local BODY
    BODY=$(cat "${REQUEST_BODY_FILE}")

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT_ID}"
}

# Creates a single selected route.
# API: https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/selection.v1.projects.selectedRoutes/create
#
# Args:
#   $1: PROJECT_ID - The Google Cloud project ID.
#   $2: ROUTE_ID - The ID for the new selected route.
#   $3: REQUEST_BODY_FILE - A path to a JSON file containing the request body
#       with route details (e.g., source, display name).
#
# Outputs:
#   The JSON response from the API to stdout.
function selectedroutes_create() {
    local PROJECT_ID="$1"
    local ROUTE_ID="$2"
    local REQUEST_BODY_FILE="$3"

    local PARENT="projects/${PROJECT_ID}"
    local URL="https://roads.googleapis.com/selection/v1/${PARENT}/selectedRoutes"
    if [[ -n "$ROUTE_ID" ]]; then
        URL="${URL}?selectedRouteId=${ROUTE_ID}"
    fi

    local BODY
    BODY=$(cat "${REQUEST_BODY_FILE}")

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT_ID}"
}

# Internal function to delete a selected route by its full resource name.
# This function is exported for use with `xargs` in batch operations.
#
# Args:
#   $1: PROJECT_ID - The Google Cloud project ID.
#   $2: NAME - The full resource name of the route to delete,
#       e.g., "projects/my-project/selectedRoutes/my-route".
#
# Outputs:
#   The JSON response from the API to stdout (usually an empty JSON object `{}`).
_selectedroutes_delete_by_name() {
    local PROJECT_ID="$1"
    local NAME="$2"

    local URL="https://roads.googleapis.com/selection/v1/${NAME}"

    _call_api "DELETE" "${URL}" "" "${PROJECT_ID}"
}
export -f _selectedroutes_delete_by_name

# Deletes a selected route.
# API: https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/selection.v1.projects.selectedRoutes/delete
#
# Args:
#   $1: PROJECT_ID - The Google Cloud project ID.
#   $2: ROUTE_ID - The ID of the route to delete.
#
# Outputs:
#   The JSON response from the API to stdout.
function selectedroutes_delete() {
    local PROJECT_ID="$1"
    local ROUTE_ID="$2"

    local NAME="projects/${PROJECT_ID}/selectedRoutes/${ROUTE_ID}"

    _selectedroutes_delete_by_name "$PROJECT_ID" "$NAME"
}

# Deletes multiple selected routes listed in a file.
# The file should contain one full resource name per line.
# e.g., projects/my-project/selectedRoutes/route-1
#       projects/my-project/selectedRoutes/route-2
#
# Args:
#   $1: FILE - Path to the file containing route names.
#   $2: PROJECT_ID - The Google Cloud project ID.
function selectedroutes_batch_delete_from_file() {
    local FILE="$1"
    local PROJECT_ID="$2"

    # Uses xargs for parallel deletion. -P5 runs up to 5 jobs in parallel.
    # The _selectedroutes_delete_by_name function must be exported.
    cat "$FILE" | xargs -n1 -P5 _selectedroutes_delete_by_name "$PROJECT_ID"
}

# Gets a selected route.
# API: https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/selection.v1.projects.selectedRoutes/get
#
# Args:
#   $1: PROJECT_ID - The Google Cloud project ID.
#   $2: ROUTE_ID - The ID of the route to retrieve.
#
# Outputs:
#   The JSON response from the API to stdout.
function selectedroutes_get() {
    local PROJECT_ID="$1"
    local ROUTE_ID="$2"

    local NAME="projects/${PROJECT_ID}/selectedRoutes/${ROUTE_ID}"
    local URL="https://roads.googleapis.com/selection/v1/${NAME}"

    _call_api "GET" "${URL}" "" "${PROJECT_ID}"
}

# Lists all selected routes in a project.
# Handles pagination automatically, streaming results to stdout.
# API: https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/selection.v1.projects.selectedRoutes/list
#
# Args:
#   $1: PROJECT_ID - The Google Cloud project ID.
#   $2: [PAGE_SIZE] - Optional. The number of results to fetch per page.
#       Defaults to 1000.
#
# Outputs:
#   A stream of JSON objects, one for each selected route, to stdout.
function selectedroutes_list() {
    local PROJECT_ID="$1"
    local PAGE_SIZE="${2:-1000}"

    local BASE_URL="https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes"

    local PAGE_TOKEN=""
    while :; do
        local URL="${BASE_URL}?pageSize=${PAGE_SIZE}"
        if [[ -n "$PAGE_TOKEN" ]]; then
            URL="${URL}&pageToken=${PAGE_TOKEN}"
        fi

        local RESPONSE
        RESPONSE=$(_call_api "GET" "${URL}" "" "${PROJECT_ID}")

        # Output the routes from the current page.
        echo "$RESPONSE" | jq -c '.selectedRoutes[]?'

        # Get the next page token and break if it's the end.
        PAGE_TOKEN=$(echo "$RESPONSE" | jq -r '.nextPageToken')
        if [[ -z "$PAGE_TOKEN" || "$PAGE_TOKEN" == "null" ]]; then
            break
        fi
    done
}
