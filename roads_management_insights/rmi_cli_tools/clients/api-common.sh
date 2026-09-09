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

# This script is for internal use by the generated API clients.
# It is not meant to be used directly.

# Cache the access token to avoid calling gcloud repeatedly.
_GAC_ACCESS_TOKEN=""

# _get_access_token ensures we only call gcloud once per script execution.
_get_access_token() {
  local project_id="${1:-}"
  local gcloud_args=()

  if [[ -n "${project_id}" ]]; then
    gcloud_args+=(--project="${project_id}")
  fi

  if [[ -z "${_GAC_ACCESS_TOKEN}" ]]; then
    _GAC_ACCESS_TOKEN=$(gcloud auth application-default print-access-token ${gcloud_args[@]+"${gcloud_args[@]}"} 2>/dev/null || gcloud auth print-access-token 2>/dev/null || echo "mock-token")
  fi
  echo "${_GAC_ACCESS_TOKEN}"
}

# _build_query_params safely constructs a URL query string.
#
# @param ... Key-value pairs (e.g., "pageSize=10" "filter=state=ACTIVE").
#            Only pairs with a non-empty value are included.
_build_query_params() {
    local params=()
    for arg in "$@"; do
        local key="${arg%%=*}"
        local value="${arg#*=}"
        if [[ -n "$value" ]]; then
            # URL-encode filter/spaces if needed
            params+=("${key}=${value}")
        fi
    done

    if ((${#params[@]} > 0)); then
        (
            IFS='&'
            echo "?${params[*]}"
        )
    else
        echo ""
    fi
}

# _call_api is a helper function to make authenticated API calls.
#
# @param string method The HTTP method (e.g., GET, POST, DELETE).
# @param string url The full URL for the API endpoint.
# @param string body Optional. The request body as a JSON string.
# @param string project_id Optional. Project ID for quota/billing.
# @param string additional_headers Optional. Additional headers.
_call_api() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  local project_id="${4:-}"
  local additional_headers="${5:-}"
  local access_token
  access_token=$(_get_access_token "${project_id}")

  local curl_args=("-sS" "-X" "${method}")
  curl_args+=("-H" "Authorization: Bearer ${access_token}")

  if [[ -n "${project_id}" ]]; then
    curl_args+=("-H" "X-Goog-User-Project: ${project_id}")
  fi

  if [[ -n "${additional_headers}" ]]; then
    IFS=$'\n' read -ra header_array <<< "${additional_headers}"
    for header in "${header_array[@]}"; do
      curl_args+=("-H" "${header}")
    done
  fi

  local temp_body_file=""
  if [[ -n "${body}" ]]; then
    curl_args+=("-H" "Content-Type: application/json")
    temp_body_file=$(mktemp)
    echo -n "${body}" > "${temp_body_file}"
    curl_args+=("-d" "@${temp_body_file}")
  fi

  curl "${curl_args[@]}" "${url}"
  if [[ -n "${temp_body_file}" ]]; then
    rm -f "${temp_body_file}"
  fi
}
