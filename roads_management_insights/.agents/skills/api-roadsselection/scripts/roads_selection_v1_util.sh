#!/bin/bash
set -euo pipefail
#
# Utility functions for the Roads Selection API v1.
# Builds on top of the service and helper scripts to provide higher-level workflows.

# Source the service and helper scripts
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/roads_selection_v1.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/roads_selection_v1_helpers.sh"

# --- Utility Functions ---

# Replaces an existing SelectedRoute by deleting it and creating a new one.
# This is the standard way to "update" a route as the API lacks a native update call.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string selected_route_id Required. The ID of the route to replace.
# @param string new_selected_route_json Required. The JSON SelectedRoute object.
roads_selection_v1_util_replace_route() {
  local pid="$1"
  local rid="$2"
  local json="$3"

  echo "Replacing SelectedRoute '${rid}' in project '${pid}'..."

  # 1. Delete the existing route (ignore error if it doesn't exist)
  roads_selection_projects_selectedRoutes_delete "${pid}" "${rid}" > /dev/null 2>&1 || true

  # 2. Create the new version
  roads_selection_projects_selectedRoutes_create "${pid}" "${json}" "${rid}"
}

# Waits for a SelectedRoute to reach a specific state.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string selected_route_id Required. The ID of the route.
# @param string target_state Required. The state to wait for (e.g., STATE_RUNNING).
# @param integer timeout_seconds Optional. How long to wait before failing (default: 60).
roads_selection_v1_util_wait_for_route_state() {
  local project_id="$1"
  local route_id="$2"
  local target_state="$3"
  local timeout="${4:-60}"
  local start_time
  start_time=$(date +%s)

  echo "Waiting for route '${route_id}' to reach state '${target_state}' (timeout: ${timeout}s)..."

  while true; do
    local response
    response=$(roads_selection_projects_selectedRoutes_get "${project_id}" "${route_id}")
    local current_state
    current_state=$(echo "${response}" | jq -r '.state')

    if [[ "${current_state}" == "${target_state}" ]]; then
      echo "Target state reached: ${current_state}"
      return 0
    fi

    if [[ "${current_state}" == "STATE_INVALID" ]]; then
      local error
      error=$(echo "${response}" | jq -r '.validationError // "No validation error provided"')
      echo "Error: Route reached STATE_INVALID. Validation error: ${error}" >&2
      return 1
    fi

    local current_time
    current_time=$(date +%s)
    local elapsed=$((current_time - start_time))

    if ((elapsed >= timeout)); then
      echo "Error: Timeout waiting for state ${target_state} (current: ${current_state})" >&2
      return 1
    fi

    sleep 2
  done
}

# Lists all SelectedRoutes for a project, automatically handling pagination.
#
# @param string project_id Required. The Google Cloud project ID.
# @return string A JSON array of all SelectedRoute objects.
roads_selection_v1_util_list_all_routes() {
  local project_id="$1"
  local page_token=""
  local tmp_all
  tmp_all=$(mktemp)
  echo "[]" > "$tmp_all"

  while true; do
    local response
    local tmp_chunk
    tmp_chunk=$(mktemp)
    
    # Using a large page size to minimize requests (max 5000)
    roads_selection_projects_selectedRoutes_list "${project_id}" 5000 "${page_token}" > "$tmp_chunk"
    
    # Extract routes from chunk and append to all_routes file
    local tmp_merged
    tmp_all_new=$(mktemp)
    jq -c -s '.[0] + (.[1].selectedRoutes // [])' "$tmp_all" "$tmp_chunk" > "$tmp_all_new"
    mv "$tmp_all_new" "$tmp_all"

    page_token=$(jq -r '.nextPageToken // empty' "$tmp_chunk")
    rm "$tmp_chunk"

    if [[ -z "${page_token}" ]]; then
      break
    fi
  done

  cat "$tmp_all"
  rm "$tmp_all"
}

# Deletes all SelectedRoutes in a specific project by iterating over the list.
# Automatically handles pagination.
#
# @param string project_id Required. The Google Cloud project ID.
roads_selection_v1_util_delete_all_routes() {
  local project_id="$1"
  echo "Fetching all SelectedRoutes for project: ${project_id}..."

  local all_routes
  all_routes=$(roads_selection_v1_util_list_all_routes "${project_id}")
  
  local route_names
  route_names=$(echo "${all_routes}" | jq -r '.[].name // empty')

  if [[ -z "${route_names}" ]]; then
    echo "No routes found to delete."
    return 0
  fi

  for name in ${route_names}; do
    local route_id="${name##*/}"
    echo "Deleting route: ${route_id}..."
    roads_selection_projects_selectedRoutes_delete "${project_id}" "${route_id}" > /dev/null
  done
  echo "All routes deleted."
}

# Deletes a list of SelectedRoutes by iterating over the provided IDs.
#
# @param string project_id Required. The Google Cloud project ID.
# @param ... route_ids Required. List of route IDs to delete.
roads_selection_v1_util_delete_batch() {
  local project_id="$1"
  shift
  local route_ids=("$@")

  for rid in "${route_ids[@]}"; do
    echo "Deleting route: ${rid}..."
    roads_selection_projects_selectedRoutes_delete "${project_id}" "${rid}" > /dev/null
  done
}

# Converts a SelectedRoute JSON object into a GeoJSON FeatureCollection.
# The resulting GeoJSON contains:
# 1. A LineString feature representing the path (origin -> intermediates -> destination).
# 2. Point features for each waypoint (origin, intermediates, destination) with metadata.
#
# @param string selected_route_json Required. The JSON SelectedRoute object.
# @return string The GeoJSON FeatureCollection.
roads_selection_v1_util_to_geojson() {
  local json="$1"

  # Extract components using jq
  echo "${json}" | jq -c '
    .name as $name |
    .displayName as $displayName |
    .state as $state |
    .dynamicRoute as $dr |
    
    # Extract points in order: origin, intermediates[], destination
    ([$dr.origin] + ($dr.intermediates // []) + [$dr.destination]) as $points |
    
    # Create LineString coordinates [[lng, lat], ...]
    ($points | map([.longitude, .latitude])) as $lineCoords |
    
    # Build FeatureCollection
    {
      type: "FeatureCollection",
      features: (
        # 1. The LineString
        [{
          type: "Feature",
          geometry: {
            type: "LineString",
            coordinates: $lineCoords
          },
          properties: {
            name: $name,
            displayName: $displayName,
            state: $state,
            type: "route_line"
          }
        }] +
        # 2. The Points
        ($points | to_entries | map({
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [.value.longitude, .value.latitude]
          },
          properties: {
            name: $name,
            displayName: $displayName,
            point_type: (
              if .key == 0 then "origin"
              elif .key == ($points | length - 1) then "destination"
              else "intermediate"
              end
            ),
            index: .key
          }
        }))
      )
    }
  '
}

# Filters a list of route request objects against the live project state to return only unregistered routes.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string requests_json_array Required. A JSON array of CreateSelectedRouteRequest objects.
# @return string A JSON array containing only unregistered requests.
roads_selection_v1_util_diff_unregistered_routes() {
  local project_id="$1"
  local requests="$2"

  local registered_json
  registered_json=$(roads_selection_v1_util_list_all_routes "${project_id}")

  local temp_req
  temp_req=$(mktemp)
  echo -n "${requests}" > "${temp_req}"

  jq -c --argjson reg "${registered_json}" '
    ($reg | map(.name | split("/") | last) | map(gsub("_"; "-"))) as $reg_ids |
    map(select((.selectedRouteId | gsub("_"; "-")) as $id | ($reg_ids | contains([$id]) | not)))
  ' "${temp_req}"

  rm -f "${temp_req}"
}

# Robustly executes batchCreate by automatically excluding invalid routes, applying exponential backoff,
# pacing delays, and dynamic batch bisection to isolate failures without dropping to 1-by-1.
#
# @param string project_id Required. The Google Cloud project ID.
# @param string requests_json_array Required. A JSON array of CreateSelectedRouteRequest objects.
# @param string output_failures_file Optional. Path to store identified failures (JSONL).
# @return string The successful SelectedRoutes response (JSON).
roads_selection_v1_util_batch_create_robust() {
  local project_id="$1"
  local requests="$2"
  local failure_log="${3:-/dev/null}"

  local current_requests="${requests}"
  local final_response="{ \"selectedRoutes\": [] }"
  local pace_delay="${ROADS_PACE_DELAY:-0.5}"

  local count
  count=$(echo "${current_requests}" | jq 'length')

  if [[ "${count}" -eq 0 ]]; then
    echo "${final_response}"
    return 0
  fi

  # Apply pacing delay if configured
  if [[ -n "${pace_delay}" && "${pace_delay}" != "0" && "${pace_delay}" != "0.0" ]]; then
    sleep "${pace_delay}"
  fi

  echo "Attempting to register batch of ${count} routes..." >&2
  local request_body
  local temp_requests_file
  temp_requests_file=$(mktemp)
  echo -n "${current_requests}" > "${temp_requests_file}"
  request_body=$(jq -c '{ requests: . }' "${temp_requests_file}")
  rm -f "${temp_requests_file}"

  # Attempt execution with exponential backoff for transient server errors (500, 502, 503, 429)
  local response=""
  local max_retries=3
  local attempt=0
  local backoff=2

  while [[ ${attempt} -le ${max_retries} ]]; do
    response=$(roads_selection_projects_selectedRoutes_batchCreate "${project_id}" "${request_body}")

    # Check for success
    if ! echo "${response}" | jq -e '.error' > /dev/null 2>&1; then
      echo "  [SUCCESS] Batch accepted (${count} routes)." >&2
      echo "${response}"
      return 0
    fi

    local http_code
    http_code=$(echo "${response}" | jq -r '.error.code // 500')
    if [[ "${http_code}" == "429" || "${http_code}" == "500" || "${http_code}" == "502" || "${http_code}" == "503" ]]; then
      attempt=$((attempt + 1))
      if [[ ${attempt} -le ${max_retries} ]]; then
        echo "  [TRANSIENT ERROR ${http_code}] Retrying batch in ${backoff}s (attempt ${attempt}/${max_retries})..." >&2
        sleep "${backoff}"
        backoff=$((backoff * 2))
        continue
      fi
    fi
    break
  done

  # Process non-transient error or exhausted retries
  local status
  status=$(echo "${response}" | jq -r '.error.status // "UNKNOWN"')
  local error_msg
  error_msg=$(echo "${response}" | jq -r '.error.message // "Batch creation failed"')

  # Strategy A: Try extracting failing indices from fieldViolations
  local failing_indices
  failing_indices=$(echo "${response}" | jq -r '
    .error.details[]? | 
    select(."@type" | endswith("BadRequest")) | 
    .fieldViolations[]? | 
    .field | 
    capture("requests\\[(?<idx>[0-9]+)\\]") | 
    .idx
  ' 2>/dev/null | sort -un || true)

  if [[ -n "${failing_indices}" ]]; then
    echo "  [ERROR ${status}] Parsing field violation indices..." >&2
    local new_requests="[]"
    local idx_list=" $(echo "${failing_indices}" | xargs) "

    for (( i=0; i<count; i++ )); do
      if [[ "${idx_list}" =~ " $i " ]]; then
        local failing_route
        failing_route=$(echo "${current_requests}" | jq -c ".[$i]")
        local route_id
        route_id=$(echo "${failing_route}" | jq -r '.selectedRouteId // .selected_route_id // "unknown"')
        local desc
        desc=$(echo "${response}" | jq -r "
          .error.details[]? | 
          select(.\"@type\" | endswith(\"BadRequest\")) | 
          .fieldViolations[]? | 
          select(.field | contains(\"requests[$i]\")) | 
          .description
        " 2>/dev/null | head -n 1)
        
        [[ -z "${desc}" || "${desc}" == "null" ]] && desc="${error_msg}"
        echo "  - EXCLUDING: ${route_id} (Reason: ${desc})" >&2
        echo "{\"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"selectedRouteId\": \"${route_id}\", \"error\": \"${desc}\", \"request\": ${failing_route}}" >> "${failure_log}"
      else
        new_requests=$(echo "${new_requests}" | jq -c ". += [$(echo "${current_requests}" | jq -c ".[$i]")]")
      fi
    done

    # Retry valid subset
    local sub_res
    sub_res=$(roads_selection_v1_util_batch_create_robust "${project_id}" "${new_requests}" "${failure_log}")
    echo "${sub_res}"
    return 0
  fi

  # Strategy B: Dynamic Batch Bisection when no index details are available
  if [[ ${count} -gt 1 ]]; then
    local mid=$(( count / 2 ))
    echo "  [RECOVERY ${status}] No specific index parsed. Bisecting batch of ${count} into halves (${mid} and $((count - mid)))..." >&2
    
    local half1
    local half2
    half1=$(echo "${current_requests}" | jq -c ".[0:${mid}]")
    half2=$(echo "${current_requests}" | jq -c ".[${mid}:${count}]")

    local res1
    local res2
    res1=$(roads_selection_v1_util_batch_create_robust "${project_id}" "${half1}" "${failure_log}")
    res2=$(roads_selection_v1_util_batch_create_robust "${project_id}" "${half2}" "${failure_log}")

    local tmp1
    local tmp2
    tmp1=$(mktemp)
    tmp2=$(mktemp)
    echo -n "${res1}" > "${tmp1}"
    echo -n "${res2}" > "${tmp2}"
    final_response=$(jq -c -s '.[0].selectedRoutes += (.[1].selectedRoutes // []) | .[0]' "${tmp1}" "${tmp2}" 2>/dev/null || echo "${res1}")
    rm -f "${tmp1}" "${tmp2}"

    echo "${final_response}"
    return 0
  fi

  # Strategy C: Single route failed
  local single_route
  single_route=$(echo "${current_requests}" | jq -c '.[0]')
  local single_id
  single_route_id=$(echo "${single_route}" | jq -r '.selectedRouteId // .selected_route_id // "unknown"')
  echo "  [PERMANENT FAILURE] Route ${single_route_id} failed: ${error_msg}" >&2
  echo "{\"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"selectedRouteId\": \"${single_route_id}\", \"error\": \"${error_msg}\", \"request\": ${single_route}}" >> "${failure_log}"

  echo "${final_response}"
  return 0
}

