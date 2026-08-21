#!/bin/bash
set -euo pipefail
#
# This script provides a client for the Roads Selection API v1.
# It is not meant to be used directly, but rather to be sourced by other scripts.
#
# For more information, see the official documentation:
# https://developers.google.com/maps/documentation/roads-management-insights/reference/rest

# Source the common helper script
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/roads_selection_v1_helpers.sh"

# --- Roads Selection API v1 ---

ROADS_SELECTION_BASE_URL="https://roads.googleapis.com/selection/v1"

# --- Methods ---

# Creates multiple SelectedRoutes and starts a schedule to periodically retrieve cache information for each of the routes.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string request_body Required. The request body as a JSON string (BatchCreateSelectedRoutesRequest).
# @see https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/projects.selectedRoutes/batchCreate
roads_selection_projects_selectedRoutes_batchCreate() {
  local pid="$1"
  local request_body="$2"
  local url="${ROADS_SELECTION_BASE_URL}/projects/${pid}/selectedRoutes:batchCreate"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Creates a SelectedRoute and starts a schedule to periodically retrieve cache information for the route.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string request_body Required. The request body as a JSON string (SelectedRoute).
# @param string selected_route_id Optional. The client-specified ID for the route.
# @see https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/projects.selectedRoutes/create
roads_selection_projects_selectedRoutes_create() {
  local pid="$1"
  local request_body="$2"
  local selected_route_id="${3:-}"
  local query_params
  query_params=$(_build_query_params "selectedRouteId=${selected_route_id}")
  local url="${ROADS_SELECTION_BASE_URL}/projects/${pid}/selectedRoutes${query_params}"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Deletes the specified SelectedRoute.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string selected_route_id Required. The ID of the route to delete.
# @see https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/projects.selectedRoutes/delete
roads_selection_projects_selectedRoutes_delete() {
  local pid="$1"
  local selected_route_id="$2"
  local url="${ROADS_SELECTION_BASE_URL}/projects/${pid}/selectedRoutes/${selected_route_id}"
  _call_api "DELETE" "${url}" "" "${pid}"
}

# Gets a SelectedRoute.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string selected_route_id Required. The ID of the route to retrieve.
# @see https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/projects.selectedRoutes/get
roads_selection_projects_selectedRoutes_get() {
  local pid="$1"
  local selected_route_id="$2"
  local url="${ROADS_SELECTION_BASE_URL}/projects/${pid}/selectedRoutes/${selected_route_id}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Lists all SelectedRoutes for the specified project.
#
# @param string project_id Required. The Google Cloud project ID.
# @param integer page_size Optional. The number of results to return.
# @param string page_token Optional. A page token from a previous call.
# @see https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/projects.selectedRoutes/list
roads_selection_projects_selectedRoutes_list() {
  local pid="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")
  local url="${ROADS_SELECTION_BASE_URL}/projects/${pid}/selectedRoutes${query_params}"
  _call_api "GET" "${url}" "" "${pid}"
}
