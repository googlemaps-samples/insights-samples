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
# Derived directly from roads_selection_v1_20261104.json (roads:selection_v1, revision 20261104).
#

# Source shared common utilities when present alongside this helper script.
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/api-common.sh" ]]; then
  # shellcheck source=/dev/null
  source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
fi

# Validates a SelectedRoute request locally before API execution.
#
# @param string selected_route_id Optional. The ID to check (4-63 chars, [a-zA-Z0-9_-]*; empty/omitted auto-generates UUID).
# @param string selected_route_json Optional. The SelectedRoute JSON to check.
# @return 0 if valid, 1 if invalid (prints errors to stderr).
roadsselection_v1_selectedroute_validate() {
  local route_id="${1:-}"
  local route_json="${2:-}"

  # 1. Check ID for valid characters: [a-zA-Z0-9_-]*, 4-63 characters if provided
  if [[ -n "$route_id" ]]; then
    if [[ ${#route_id} -lt 4 || ${#route_id} -gt 63 ]]; then
      echo "CRITICAL VALIDATION ERROR: selectedRouteId '$route_id' length (${#route_id}) must be between 4 and 63 characters." >&2
      return 1
    fi
    if [[ ! "$route_id" =~ ^[a-zA-Z0-9_-]+$ ]]; then
      echo "CRITICAL VALIDATION ERROR: selectedRouteId '$route_id' contains invalid characters. Valid characters are 'a-z', 'A-Z', '0-9', '-', or '_'." >&2
      return 1
    fi
  fi

  # 2. Check Top-Level Schema Allowlist, Display Name, DynamicRoute, dynamicRouting & Route Attributes
  if [[ -n "$route_json" ]]; then
    if ! echo "$route_json" | jq -e 'type == "object"' >/dev/null 2>&1; then
      echo "CRITICAL VALIDATION ERROR: SelectedRoute payload must be a valid JSON object." >&2
      return 1
    fi

    local unknown_keys
    unknown_keys=$(echo "$route_json" | jq -r '
      keys[] | select(IN(
        "name", "selectedRouteId", "selected_route_id",
        "displayName", "display_name",
        "dynamicRoute", "dynamic_route",
        "dynamicRouting", "dynamic_routing",
        "routeAttributes", "route_attributes",
        "state", "validationError", "validation_error", "validationErrors", "validation_errors",
        "createTime", "create_time", "updateTime", "update_time"
      ) | not)
    ' 2>/dev/null || echo "")
    if [[ -n "$unknown_keys" ]]; then
      echo "CRITICAL VALIDATION ERROR: SelectedRoute contains unsupported top-level field(s): $(echo "$unknown_keys" | tr '\n' ' '). Fields like 'priority' belong inside 'routeAttributes'/'route_attributes', and 'geometry' must be omitted." >&2
      return 1
    fi

    local dyn_routing_type
    dyn_routing_type=$(echo "$route_json" | jq -r '
      if has("dynamicRouting") then (.dynamicRouting | type)
      elif has("dynamic_routing") then (.dynamic_routing | type)
      else "absent" end
    ' 2>/dev/null || echo "absent")
    if [[ "$dyn_routing_type" != "absent" && "$dyn_routing_type" != "boolean" ]]; then
      echo "CRITICAL VALIDATION ERROR: dynamicRouting / dynamic_routing must be a JSON boolean (true or false), got '$dyn_routing_type'." >&2
      return 1
    fi

    # Check displayName length <= 100 Unicode code points (jq string `length` counts Unicode code points)
    local dname_len
    dname_len=$(echo "$route_json" | jq -r '((.displayName // .display_name) // "") | tostring | length' 2>/dev/null || echo "0")
    if [[ "$dname_len" -gt 100 ]]; then
      echo "CRITICAL VALIDATION ERROR: displayName length ($dname_len Unicode code points) exceeds 100 characters limit." >&2
      return 1
    fi

    # 3. Check Intermediates Limit (Max 25) and LatLng bounds
    local count
    count=$(echo "$route_json" | jq '((.dynamicRoute // .dynamic_route).intermediates // []) | length' 2>/dev/null || echo "0")
    if [[ "$count" -gt 25 ]]; then
      echo "CRITICAL VALIDATION ERROR: SelectedRoute contains $count intermediate waypoints. The limit is 25. Please simplify the route before submission." >&2
      return 1
    fi

    local coord_err
    coord_err=$(echo "$route_json" | jq -r '
      (.dynamicRoute // .dynamic_route) as $dr |
      if $dr == null then empty
      else
        [
          (if $dr.origin != null then [{label: "origin", pt: $dr.origin}] else [] end),
          (if $dr.destination != null then [{label: "destination", pt: $dr.destination}] else [] end),
          ([($dr.intermediates // []) | to_entries[] | {label: "intermediates[\(.key)]", pt: .value}])
        ] | add | .[] |
        if (.pt.latitude == null or (.pt.latitude | type) != "number" or .pt.latitude < -90 or .pt.latitude > 90) then
          "\(.label) latitude must be between -90 and 90"
        elif (.pt.longitude == null or (.pt.longitude | type) != "number" or .pt.longitude < -180 or .pt.longitude > 180) then
          "\(.label) longitude must be between -180 and 180"
        else empty end
      end
    ' 2>/dev/null | head -n 1 || echo "")
    if [[ -n "$coord_err" ]]; then
      echo "CRITICAL VALIDATION ERROR: $coord_err." >&2
      return 1
    fi

    # 4. Check Route Attributes (Max 25, non-empty string keys and values 1-100 Unicode code points, keys cannot start with 'goog')
    local attr_err
    attr_err=$(echo "$route_json" | jq -r '
      (.routeAttributes // .route_attributes // {}) as $attrs |
      if ($attrs | type) != "object" then
        "routeAttributes must be a JSON object"
      elif ($attrs | length) > 25 then
        "routeAttributes count (\($attrs | length)) exceeds maximum limit of 25"
      else
        ($attrs | to_entries[] |
          if (.key | length) < 1 or (.key | length) > 100 then
            "routeAttributes key '\''\(.key)'\'' length (\(.key | length)) must be between 1 and 100 characters"
          elif (.key | startswith("goog")) then
            "routeAttributes key '\''\(.key)'\'' starts with '\''goog'\'', which is prohibited"
          elif (.value | type) != "string" then
            "routeAttributes value for key '\''\(.key)'\'' must be a string, got \(.value | type)"
          elif (.value | length) < 1 or (.value | length) > 100 then
            "routeAttributes value for key '\''\(.key)'\'' must be a non-empty string between 1 and 100 characters (got length \(.value | length))"
          else empty end
        )
      end
    ' 2>/dev/null | head -n 1 || echo "")
    if [[ -n "$attr_err" ]]; then
      echo "CRITICAL VALIDATION ERROR: ${attr_err}." >&2
      return 1
    fi
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
# @param string display_name Optional. Display name for the route (max 100 Unicode code points).
# @param string dynamic_route_json Required. JSON object representing a DynamicRoute.
# @param string route_attributes_json Optional. JSON object for custom attributes (max 25 pairs).
# @param string name Optional. Resource name for update/patch operations.
# @param string dynamic_routing Optional. Boolean string ('true' or 'false') for top-level dynamicRouting.
# @return string The JSON SelectedRoute object.
roadsselection_v1_selectedroute_json() {
  local display_name="${1:-}"
  local dynamic_route="${2:-null}"
  local route_attrs="${3:-}"
  local name="${4:-}"
  local dynamic_routing="${5:-}"
  if [[ -z "${route_attrs}" ]]; then
    route_attrs="{}"
  fi
  local dyn_routing_json="null"
  if [[ "${dynamic_routing}" == "true" || "${dynamic_routing}" == "false" ]]; then
    dyn_routing_json="${dynamic_routing}"
  fi

  jq -n -c \
    --arg dn "$display_name" \
    --argjson dr "$dynamic_route" \
    --argjson ra "$route_attrs" \
    --arg nm "$name" \
    --argjson dynr "$dyn_routing_json" \
    '{
      displayName: $dn,
      dynamicRoute: $dr,
      dynamicRouting: $dynr,
      routeAttributes: $ra,
      name: $nm
    }' | jq -c '
      if .displayName == "" then del(.displayName) else . end |
      if .dynamicRoute == null then del(.dynamicRoute) else . end |
      if .dynamicRouting == null then del(.dynamicRouting) else . end |
      if .name == "" then del(.name) else . end
    '
}

# Creates a CreateSelectedRouteRequest JSON object.
#
# @param string parent Optional. The parent project (projects/{project}); may be empty in BatchCreate if matching URL parent.
# @param string selected_route_json Required. JSON object representing a SelectedRoute.
# @param string selected_route_id Optional. Client-specified ID for the route (4-63 chars: a-z, A-Z, 0-9, '-', '_').
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
    }' | jq -c '
      if .parent == "" then del(.parent) else . end |
      if .selectedRouteId == "" then del(.selectedRouteId) else . end
    '
}

# Creates a BatchCreateSelectedRoutesRequest JSON object.
# Note: Top-level `parent` is bound via URL path (`selection/v1/{+parent}/selectedRoutes:batchCreate`)
# and is not part of the BatchCreateSelectedRoutesRequest JSON body schema in Discovery 20261104.
# An optional 2nd argument (`parent`) is accepted and ignored for backward compatibility.
#
# @param string requests_json Required. JSON array of CreateSelectedRouteRequest objects (max 1000).
# @param string legacy_parent Optional. Ignored (kept for backward compatibility).
# @return string The JSON BatchCreateSelectedRoutesRequest object.
roadsselection_v1_selectedroute_batchcreate_request_json() {
  local requests="$1"

  jq -n -c \
    --argjson rs "$requests" \
    '{
      requests: $rs
    }'
}

# Creates an UpdateSelectedRouteRequest JSON object.
#
# @param string selected_route_json Required. JSON object representing the SelectedRoute to update.
# @param string update_mask Optional. Comma-delimited list of fields to update (e.g. 'display_name,route_attributes,dynamic_routing,dynamic_route').
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
# Note: Top-level `parent` is bound via URL path (`selection/v1/{+parent}/selectedRoutes:batchUpdate`)
# and is not part of the BatchUpdateSelectedRoutesRequest JSON body schema in Discovery 20261104.
# Supports both `(requests_json, [update_mask])` and legacy 3-arg `(requests_json, parent, [update_mask])`.
#
# @param string requests_json Required. JSON array of UpdateSelectedRouteRequest objects (max 1000).
# @param string update_mask_or_legacy_parent Optional. Shared update mask (or legacy 'projects/...' parent).
# @param string legacy_update_mask Optional. Shared update mask when called with legacy 3-arg signature.
# @return string The JSON BatchUpdateSelectedRoutesRequest object.
roadsselection_v1_selectedroute_batchupdate_request_json() {
  local requests="$1"
  local update_mask=""

  if [[ $# -ge 3 ]]; then
    update_mask="${3:-}"
  elif [[ $# -eq 2 ]]; then
    if [[ "${2:-}" != projects/* ]]; then
      update_mask="${2:-}"
    fi
  fi

  jq -n -c \
    --argjson rs "$requests" \
    --arg um "$update_mask" \
    '{
      requests: $rs,
      updateMask: $um
    }' | jq -c 'if .updateMask == "" then del(.updateMask) else . end'
}

# Creates a BatchDeleteSelectedRoutesRequest JSON object.
# Note: Top-level `parent` is bound via URL path (`selection/v1/{+parent}/selectedRoutes:batchDelete`)
# and is not part of the BatchDeleteSelectedRoutesRequest JSON body schema in Discovery 20261104.
# Supports both `(names_json)` and legacy 2-arg `(parent, names_json)`.
#
# @param string names_json_or_legacy_parent Required. JSON array of resource names to delete (or legacy parent when 2 args passed).
# @param string legacy_names_json Optional. JSON array of resource names when called with legacy 2-arg signature.
# @return string The JSON BatchDeleteSelectedRoutesRequest object.
roadsselection_v1_selectedroute_batchdelete_request_json() {
  local names_json
  if [[ $# -ge 2 ]]; then
    names_json="$2"
  else
    names_json="$1"
  fi

  jq -n -c \
    --argjson nms "$names_json" \
    '{
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
