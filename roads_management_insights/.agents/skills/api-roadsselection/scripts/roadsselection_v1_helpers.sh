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
#
# Helper functions for creating JSON request bodies and query parameters for the Roads Selection API v1.
# Derived directly from roads_selection_service.proto specifications.
#

# Validates a SelectedRoute request locally before API execution.
#
# @param string selected_route_id Optional. The ID to check.
# @param string selected_route_json Optional. The SelectedRoute JSON to check.
# @return 0 if valid, 1 if invalid (prints errors to stderr).
roadsselection_v1_selectedroute_validate() {
  local route_id="${1:-}"
  local route_json="${2:-}"

  # 1. Check ID for valid characters: [a-zA-Z0-9-]*, 4-63 characters if provided
  if [[ -n "$route_id" ]]; then
    if [[ "$route_id" =~ _ ]]; then
      echo "CRITICAL VALIDATION ERROR: selectedRouteId '$route_id' contains underscores ('_'). Underscores are forbidden in RMI technical identifiers. Use hyphens ('-') instead." >&2
      return 1
    fi
    if [[ ${#route_id} -lt 4 || ${#route_id} -gt 63 ]]; then
      echo "CRITICAL VALIDATION ERROR: selectedRouteId '$route_id' length (${#route_id}) must be between 4 and 63 characters." >&2
      return 1
    fi
  fi

  # 2. Check Display Name Length (Max 100 bytes UTF-8)
  if [[ -n "$route_json" ]]; then
    local dname
    dname=$(echo "$route_json" | jq -r '.displayName // empty' 2>/dev/null || echo "")
    if [[ -n "$dname" ]]; then
      local dname_bytes
      dname_bytes=$(printf "%s" "$dname" | wc -c | tr -d ' ')
      if [[ $dname_bytes -gt 100 ]]; then
        echo "CRITICAL VALIDATION ERROR: displayName UTF-8 byte length ($dname_bytes) exceeds 100 bytes limit." >&2
        return 1
      fi
    fi

    # 3. Check Intermediates Limit (Max 25)
    local count
    count=$(echo "$route_json" | jq '.dynamicRoute.intermediates | length' 2>/dev/null || echo "0")
    if [[ "$count" -gt 25 ]]; then
      echo "CRITICAL VALIDATION ERROR: SelectedRoute contains $count intermediate waypoints. The limit is 25. Please simplify the route before submission." >&2
      return 1
    fi

    # 4. Check Route Attributes (Max 10, keys 1-100 bytes, values <= 100 bytes, keys cannot start with 'goog')
    local attr_keys
    attr_keys=$(echo "$route_json" | jq -r '.routeAttributes | keys[]?' 2>/dev/null || echo "")
    local attr_count
    attr_count=$(echo "$route_json" | jq '.routeAttributes | length' 2>/dev/null || echo "0")
    if [[ "$attr_count" -gt 10 ]]; then
      echo "CRITICAL VALIDATION ERROR: routeAttributes count ($attr_count) exceeds maximum limit of 10." >&2
      return 1
    fi
    for k in ${attr_keys}; do
      local k_bytes
      k_bytes=$(printf "%s" "$k" | wc -c | tr -d ' ')
      if [[ $k_bytes -lt 1 || $k_bytes -gt 100 ]]; then
        echo "CRITICAL VALIDATION ERROR: routeAttributes key '$k' UTF-8 byte length ($k_bytes) must be between 1 and 100 bytes." >&2
        return 1
      fi
      local v
      v=$(echo "$route_json" | jq -r --arg key "$k" '.routeAttributes[$key] // empty' 2>/dev/null || echo "")
      local v_bytes
      v_bytes=$(printf "%s" "$v" | wc -c | tr -d ' ')
      if [[ $v_bytes -gt 100 ]]; then
        echo "CRITICAL VALIDATION ERROR: routeAttributes value for key '$k' UTF-8 byte length ($v_bytes) exceeds 100 bytes limit." >&2
        return 1
      fi
      if [[ "$k" =~ ^goog ]]; then
        echo "CRITICAL VALIDATION ERROR: routeAttributes key '$k' starts with 'goog', which is prohibited." >&2
        return 1
      fi
    done
  fi

  return 0
}

# Creates a LatLng JSON object.
#
# @param number latitude Required. The latitude in degrees (-90 to 90).
# @param number longitude Required. The longitude in degrees (-180 to 180).
# @return string The JSON LatLng object.
roadsselection_v1_latlng_json() {
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
roadsselection_v1_dynamicroute_json() {
  local olat="$1"
  local olng="$2"
  local dlat="$3"
  local dlng="$4"
  local intermediates="${5:-[]}"

  local origin
  origin=$(roadsselection_v1_latlng_json "$olat" "$olng")
  local destination
  destination=$(roadsselection_v1_latlng_json "$dlat" "$dlng")

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
# @param string display_name Optional. Display name for the route (max 100 bytes UTF-8).
# @param string dynamic_route_json Required. JSON object representing a DynamicRoute.
# @param string route_attributes_json Optional. JSON object for custom attributes (max 10 pairs).
# @param string name Optional. Resource name for update/patch operations.
# @return string The JSON SelectedRoute object.
roadsselection_v1_selectedroute_json() {
  local display_name="${1:-}"
  local dynamic_route="${2:-null}"
  local route_attrs="${3:-}"
  local name="${4:-}"
  if [[ -z "${route_attrs}" ]]; then
    route_attrs="{}"
  fi

  jq -n -c \
    --arg dn "$display_name" \
    --argjson dr "$dynamic_route" \
    --argjson ra "$route_attrs" \
    --arg nm "$name" \
    '{
      displayName: $dn,
      dynamicRoute: $dr,
      routeAttributes: $ra,
      name: $nm
    }' | jq -c '
      if .displayName == "" then del(.displayName) else . end |
      if .dynamicRoute == null then del(.dynamicRoute) else . end |
      if .name == "" then del(.name) else . end
    '
}

# Creates a CreateSelectedRouteRequest JSON object.
#
# @param string parent Required. The parent project (projects/{project}).
# @param string selected_route_json Required. JSON object representing a SelectedRoute.
# @param string selected_route_id Optional. Client-specified ID for the route (4-63 chars).
# @return string The JSON CreateSelectedRouteRequest object.
roadsselection_v1_selectedroute_create_request_json() {
  local parent="$1"
  local selected_route="$2"
  local selected_route_id="${3:-}"

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
# @param string requests_json Required. JSON array of CreateSelectedRouteRequest objects (max 1000).
# @param string parent Optional. Top-level parent project.
# @return string The JSON BatchCreateSelectedRoutesRequest object.
roadsselection_v1_selectedroute_batchcreate_request_json() {
  local requests="$1"
  local parent="${2:-}"

  jq -n -c \
    --arg p "$parent" \
    --argjson rs "$requests" \
    '{
      parent: $p,
      requests: $rs
    }' | jq -c 'if .parent == "" then del(.parent) else . end'
}

# Creates an UpdateSelectedRouteRequest JSON object.
#
# @param string selected_route_json Required. JSON object representing the SelectedRoute to update.
# @param string update_mask Optional. Comma-delimited list of fields to update (e.g. 'display_name,route_attributes').
# @return string The JSON UpdateSelectedRouteRequest object.
roadsselection_v1_selectedroute_update_request_json() {
  local selected_route="$1"
  local update_mask="${2:-}"

  jq -n -c \
    --argjson sr "$selected_route" \
    --arg um "$update_mask" \
    '{
      selectedRoute: $sr,
      updateMask: $um
    }' | jq -c 'if .updateMask == "" then del(.updateMask) else . end'
}

# Creates a BatchUpdateSelectedRoutesRequest JSON object.
#
# @param string requests_json Required. JSON array of UpdateSelectedRouteRequest objects (max 1000).
# @param string parent Optional. Top-level parent project.
# @param string update_mask Optional. Shared update mask for all requests in the batch.
# @return string The JSON BatchUpdateSelectedRoutesRequest object.
roadsselection_v1_selectedroute_batchupdate_request_json() {
  local requests="$1"
  local parent="${2:-}"
  local update_mask="${3:-}"

  jq -n -c \
    --arg p "$parent" \
    --argjson rs "$requests" \
    --arg um "$update_mask" \
    '{
      parent: $p,
      requests: $rs,
      updateMask: $um
    }' | jq -c '
      if .parent == "" then del(.parent) else . end |
      if .updateMask == "" then del(.updateMask) else . end
    '
}

# Creates a BatchDeleteSelectedRoutesRequest JSON object.
#
# @param string parent Required. Parent project (projects/{project}).
# @param string names_json Required. JSON array of resource names to delete (max 1000).
# @return string The JSON BatchDeleteSelectedRoutesRequest object.
roadsselection_v1_selectedroute_batchdelete_request_json() {
  local parent="$1"
  local names_json="$2"

  jq -n -c \
    --arg p "$parent" \
    --argjson nms "$names_json" \
    '{
      parent: $p,
      names: $nms
    }'
}

# -----------------------------------------------------------------------------
# Backward-compatibility aliases
# -----------------------------------------------------------------------------
roadsselection_v1_latlng_create_json() { roadsselection_v1_latlng_json "$@"; }
roadsselection_v1_dynamicroute_create_json() { roadsselection_v1_dynamicroute_json "$@"; }
roadsselection_v1_selectedroute_create_json() { roadsselection_v1_selectedroute_json "$@"; }

# Request JSON builder aliases (legacy names)
roadsselection_v1_create_selectedroute_request_json() { roadsselection_v1_selectedroute_create_request_json "$@"; }
roadsselection_v1_batchcreate_selectedroutes_request_json() { roadsselection_v1_selectedroute_batchcreate_request_json "$@"; }
roadsselection_v1_batch_create_selectedroutes_request_json() { roadsselection_v1_selectedroute_batchcreate_request_json "$@"; }
roadsselection_v1_update_selectedroute_request_json() { roadsselection_v1_selectedroute_update_request_json "$@"; }
roadsselection_v1_batchupdate_selectedroutes_request_json() { roadsselection_v1_selectedroute_batchupdate_request_json "$@"; }
roadsselection_v1_batch_update_selectedroutes_request_json() { roadsselection_v1_selectedroute_batchupdate_request_json "$@"; }
roadsselection_v1_batchdelete_selectedroutes_request_json() { roadsselection_v1_selectedroute_batchdelete_request_json "$@"; }
roadsselection_v1_batch_delete_selectedroutes_request_json() { roadsselection_v1_selectedroute_batchdelete_request_json "$@"; }

# Early format aliases
roadsselection_v1_create_selectedroute_request_create_json() { roadsselection_v1_selectedroute_create_request_json "$@"; }
roadsselection_v1_batch_create_selectedroutes_request_create_json() { roadsselection_v1_selectedroute_batchcreate_request_json "$@"; }
roadsselection_v1_update_selectedroute_request_create_json() { roadsselection_v1_selectedroute_update_request_json "$@"; }
roadsselection_v1_batch_update_selectedroutes_request_create_json() { roadsselection_v1_selectedroute_batchupdate_request_json "$@"; }
roadsselection_v1_batch_delete_selectedroutes_request_create_json() { roadsselection_v1_selectedroute_batchdelete_request_json "$@"; }
