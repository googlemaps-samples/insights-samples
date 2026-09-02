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
# Utility workflows for the Roads Selection API v1.
# Implements atomic PATCH/update, batch deletion, batch updates, and automated pagination.
#

# Source service and helper scripts
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/roadsselection_v1.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/roadsselection_v1_helpers.sh"

# Updates an existing SelectedRoute using native PATCH method.
#
# @param string name Required. Resource name (projects/{project}/selectedRoutes/{id}).
# @param string updated_route_json Required. JSON SelectedRoute object.
# @param string update_mask Optional. Comma-separated field mask (e.g. 'display_name,route_attributes').
roadsselection_v1_selectedroute_patch_util() {
  local name="$1"
  local json="$2"
  local mask="${3:-display_name,route_attributes,dynamic_route}"

  echo "Updating SelectedRoute '${name}' with updateMask '${mask}'..."
  roadsselection_v1_selectedroute_patch "${name}" "${json}" "${mask}"
}

# Batch deletes routes by list of IDs or names (up to 1,000 routes).
#
# @param string project_id Required. The Google Cloud project ID.
# @param array names Required. List of route resource names.
roadsselection_v1_selectedroute_batch_delete_by_names() {
  local project_id="$1"
  shift
  local names=("$@")

  if [[ ${#names[@]} -eq 0 ]]; then
    echo "No route names provided for batch deletion."
    return 0
  fi

  echo "Submitting batch delete for ${#names[@]} routes in project '${project_id}'..."
  local names_json
  names_json=$(printf '%s\n' "${names[@]}" | jq -R . | jq -s .)
  local req_json
  req_json=$(roadsselection_v1_selectedroute_batchdelete_request_json "projects/${project_id}" "${names_json}")
  roadsselection_v1_selectedroute_batchdelete "${project_id}" "${req_json}"
}

# Waits for a SelectedRoute to reach a specific state.
#
# @param string name Required. Resource name (projects/{project}/selectedRoutes/{id}).
# @param string target_state Required. The state to wait for (e.g. STATE_RUNNING).
# @param integer timeout_seconds Optional. Default 60.
roadsselection_v1_selectedroute_wait_for_state() {
  local name="$1"
  local target_state="$2"
  local timeout="${3:-60}"
  local start_time
  start_time=$(date +%s)

  echo "Waiting for route '${name}' to reach state '${target_state}' (timeout: ${timeout}s)..."

  while true; do
    local response
    response=$(roadsselection_v1_selectedroute_get "${name}")
    local current_state
    current_state=$(echo "${response}" | jq -r '.state // "STATE_UNSPECIFIED"')

    if [[ "${current_state}" == "${target_state}" ]]; then
      echo "Target state reached: ${current_state}"
      return 0
    fi

    if [[ "${current_state}" == "STATE_INVALID" ]]; then
      local error
      error=$(echo "${response}" | jq -r '.validationError // "No validation error provided"')
      echo "Error: Route reached failure state 'STATE_INVALID'. Validation error: ${error}" >&2
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

# Lists all SelectedRoutes for a project, handling pagination automatically.
#
# @param string project_id Required. The Google Cloud project ID.
# @return string A JSON array of all SelectedRoute objects.
roadsselection_v1_selectedroute_list_all() {
  local project_id="$1"
  local page_token=""
  local tmp_all
  tmp_all=$(mktemp)
  echo "[]" > "$tmp_all"

  while true; do
    local response
    local tmp_chunk
    tmp_chunk=$(mktemp)

    roadsselection_v1_selectedroute_list "${project_id}" 5000 "${page_token}" > "$tmp_chunk"

    local routes
    routes=$(jq -c '.selectedRoutes // []' "$tmp_chunk")

    local updated
    updated=$(jq -s '.[0] + .[1]' "$tmp_all" <(echo "$routes"))
    echo "$updated" > "$tmp_all"

    page_token=$(jq -r '.nextPageToken // empty' "$tmp_chunk")
    rm -f "$tmp_chunk"

    if [[ -z "$page_token" ]]; then
      break
    fi
  done

  cat "$tmp_all"
  rm -f "$tmp_all"
}

