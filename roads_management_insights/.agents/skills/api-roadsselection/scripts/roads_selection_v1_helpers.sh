#!/bin/bash
set -euo pipefail
#
# Helper functions for creating JSON request bodies for the Roads Selection API v1.
# It is meant to be sourced by other scripts.
#
# For more information, see the official documentation:
# https://developers.google.com/maps/documentation/roads-management-insights/reference/rest

# --- Request Body Helper Functions ---

# Validates a SelectedRoute request locally before API execution.
#
# @param string selected_route_id Optional. The ID to check.
# @param string selected_route_json Optional. The SelectedRoute JSON to check.
# @return 0 if valid, 1 if invalid (prints errors to stderr).
roads_selection_v1_validate_selected_route_request() {
  local route_id="${1:-}"
  local route_json="${2:-}"

  # 1. Check ID for underscores
  if [[ "$route_id" =~ _ ]]; then
    echo "CRITICAL VALIDATION ERROR: selectedRouteId '$route_id' contains underscores ('_'). Underscores are forbidden in RMI technical identifiers. Use hyphens ('-') instead." >&2
    return 1
  fi

  # 2. Check Intermediates Limit (Max 25)
  if [[ -n "$route_json" ]]; then
    local count
    count=$(echo "$route_json" | jq '.dynamicRoute.intermediates | length' 2>/dev/null || echo "0")
    if [[ "$count" -gt 25 ]]; then
      echo "CRITICAL VALIDATION ERROR: SelectedRoute contains $count intermediate waypoints. The limit is 25. Please simplify the route before submission." >&2
      return 1
    fi
  fi

  return 0
}

# Creates a LatLng JSON object.
#
# @param number latitude Required. The latitude in degrees.
# @param number longitude Required. The longitude in degrees.
# @return string The JSON LatLng object.
roads_selection_v1_create_lat_lng_json() {
  local lat="$1"
  local lng="$2"

  jq -n -c \
    --argjson lat "$lat" --argjson lng "$lng" \
    '{ latitude: $lat, longitude: $lng }'
}

# Creates a DynamicRoute JSON object.
#
# @param number origin_lat Required. Origin latitude.
# @param number origin_lng Required. Origin longitude.
# @param number dest_lat Required. Destination latitude.
# @param number dest_lng Required. Destination longitude.
# @param string intermediates_json Optional. JSON array of intermediate LatLngs.
# @return string The JSON DynamicRoute object.
roads_selection_v1_create_dynamic_route_json() {
  local olat="$1"
  local olng="$2"
  local dlat="$3"
  local dlng="$4"
  local intermediates="${5:-[]}"

  local origin
  origin=$(roads_selection_v1_create_lat_lng_json "$olat" "$olng")
  local destination
  destination=$(roads_selection_v1_create_lat_lng_json "$dlat" "$dlng")

  jq -n -c \
    --argjson o "$origin" \
    --argjson d "$destination" \
    --argjson ints "$intermediates" \
    '{
      origin: $o,
      destination: $d,
      intermediates: $ints
    }'
}

# Creates a SelectedRoute JSON object.
#
# @param string display_name Optional. Display name for the route.
# @param string dynamic_route_json Required. JSON object representing a DynamicRoute.
# @param string route_attributes_json Optional. JSON object for custom attributes (key-value pairs).
# @return string The JSON SelectedRoute object.
roads_selection_v1_create_selected_route_json() {
  local display_name="${1:-}"
  local dynamic_route="${2:-null}"
  local route_attrs="${3:-}"
  if [[ -z "${route_attrs}" ]]; then
    route_attrs="{}"
  fi

  jq -n -c \
    --arg dn "$display_name" \
    --argjson dr "$dynamic_route" \
    --argjson ra "$route_attrs" \
    '{
      displayName: $dn,
      dynamicRoute: $dr,
      routeAttributes: $ra
    }' | jq -c 'if .displayName == "" then del(.displayName) else . end | if .dynamicRoute == null then del(.dynamicRoute) else . end'
}

# Creates a CreateSelectedRouteRequest JSON object.
#
# @param string project Required. The project ID (e.g. "my-project").
# @param string selected_route_json Required. JSON object representing a SelectedRoute.
# @param string selected_route_id Optional. Client-specified ID for the route.
# @return string The JSON CreateSelectedRouteRequest object.
roads_selection_v1_create_create_selected_route_request_json() {
  local project="$1"
  local selected_route="$2"
  local selected_route_id="${3:-}"
  local parent="projects/${project}"

  jq -n -c \
    --arg p "$parent" \
    --argjson sr "$selected_route" \
    --arg srid "$selected_route_id" \
    '{
      parent: $p,
      selectedRoute: $sr,
      selectedRouteId: $srid
    }' | jq -c 'if .selectedRouteId == "" then del(.selectedRouteId) else . end'
}

# Creates a BatchCreateSelectedRoutesRequest JSON object.
#
# @param string requests_json Required. JSON array of CreateSelectedRouteRequest objects.
# @return string The JSON BatchCreateSelectedRoutesRequest object.
roads_selection_v1_create_batch_create_selected_routes_request_json() {
  local requests="$1"
  jq -n -c --argjson rs "$requests" '{ requests: $rs }'
}
