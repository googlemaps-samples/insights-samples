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
# Google API Client - Internal Utilities
#
# This script provides shared internal helper functions for authentication,
# request building, and API execution. It is intended to be sourced by
# specific service client scripts.
###############################################################################

# =============================================================================
# INTERNAL: Authentication & API Utilities
# =============================================================================

# Cache the access token to avoid calling gcloud repeatedly.
_API_CLIENT_ACCESS_TOKEN=""

# _get_access_token ensures we only call gcloud once per script execution.
_get_access_token() {
  local project_id="${1:-""}"
  local gcloud_args=()

  if [[ -n "${project_id}" ]]; then
    gcloud_args+=("--project"="${project_id}")
  fi

  if [[ -z "${_API_CLIENT_ACCESS_TOKEN}" ]]; then
    if ! command -v gcloud &> /dev/null; then
        echo "Error: gcloud CLI is not installed or not in PATH." >&2
        return 1
    fi
    _API_CLIENT_ACCESS_TOKEN=$(gcloud auth application-default print-access-token "${gcloud_args[@]}" 2>/dev/null)
  fi
  echo "${_API_CLIENT_ACCESS_TOKEN}"
}
# _build_query_params safely constructs a URL query string.
#
# @param ... Key-value pairs (e.g., "pageSize=10" "pageToken=abc").
#            Only pairs with a non-empty value are included.
_build_query_params() {
  local params=()
  for arg in "$@"; do
    local key="${arg%%=*}"
    local value="${arg#*=}"
    if [[ -n "$value" ]]; then
      # Note: For production use, value should be URL-encoded.
      params+=("${key}=${value}")
    fi
  done

  if ((${#params[@]} > 0)); then
    (
      # Join the array with '&'
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
# @param string project_id Optional. Project ID for quota and billing.
# @param string additional_headers Optional. A newline-separated string of additional headers.
_call_api() {
  local method="$1"
  local url="$2"
  local body="${3:-""}"
  local project_id="${4:-""}"
  local additional_headers="${5:-""}"
  local access_token

  # Log the API call to stderr (captured by logs)
  echo "[API CALL] $method $url" >&2
  if [[ -n "${body}" ]]; then
      echo "[API BODY] ${body}" >&2
  fi

  access_token=$(_get_access_token "${project_id}")

  if [[ -z "${access_token}" ]]; then
    echo "Error: Not authenticated. Please run 'gcloud auth application-default login'." >&2
    return 1
  fi

  local curl_args=("--silent" "--show-error" "--request" "${method}")
  curl_args+=("--header" "Authorization: Bearer ${access_token}")

  # Add the quota project header if a project_id was provided.
  if [[ -n "${project_id}" ]]; then
    curl_args+=("--header" "X-Goog-User-Project: ${project_id}")
  fi

  # Parse and add additional headers
  if [[ -n "${additional_headers}" ]]; then
    local OLD_IFS="$IFS"
    IFS=$'\n'
    for header in ${additional_headers}; do
      curl_args+=("--header" "${header}")
    done
    IFS="$OLD_IFS"
  fi

  if [[ -n "${body}" ]]; then
    curl_args+=("--header" "Content-Type: application/json")
    curl_args+=("--data" "${body}")
  fi

  curl "${curl_args[@]}" "${url}"
}


###############################################################################
# Analytics Hub API (v1) - JSON Helpers
#
# This script provides helper functions to construct JSON request bodies
# for the Analytics Hub API v1.
###############################################################################

# Creates a JSON object for a DataExchange.
# @param string display_name Required.
# @param string description Optional.
# @param string primary_contact Optional.
# @param string documentation Optional.
create_data_exchange() {
    local display_name="$1"
    local description="${2:-null}"
    local primary_contact="${3:-null}"
    local documentation="${4:-null}"

    jq -c --null-input \
       --arg dn "$display_name" \
       --arg desc "$description" \
       --arg pc "$primary_contact" \
       --arg doc "$documentation" \
       '{displayName: $dn, description: $desc, primaryContact: $pc, documentation: $doc} | del(..|select(. == "null"))'
}

# Creates a JSON object for a BigQueryDatasetSource.
# @param string dataset_resource Required. Format: projects/{project}/datasets/{dataset}
create_bigquery_dataset_source() {
    jq -c --null-input --arg ds "$1" '{dataset: $ds}'
}

# Creates a JSON object for a Listing.
# @param string display_name Required.
# @param string bigquery_dataset_source_json Required. JSON object.
# @param string description Optional.
# @param string primary_contact Optional.
# @param string documentation Optional.
create_listing() {
    local display_name="$1"
    local bq_source="$2"
    local description="${3:-null}"
    local primary_contact="${4:-null}"
    local documentation="${5:-null}"

    jq -c --null-input \
       --arg dn "$display_name" \
       --argjson bqs "$bq_source" \
       --arg desc "$description" \
       --arg pc "$primary_contact" \
       --arg doc "$documentation" \
       '{displayName: $dn, bigQueryDataset: $bqs, description: $desc, primaryContact: $pc, documentation: $doc} | del(..|select(. == "null"))'
}

# Creates a JSON object for DestinationDatasetReference.
# @param string project_id Required.
# @param string dataset_id Required.
create_destination_dataset_reference() {
    jq -c --null-input --arg pid "$1" --arg did "$2" \
        '{projectId: $pid, datasetId: $did}'
}

# Creates a JSON object for DestinationDataset.
# @param string dataset_reference_json Required.
# @param string location Required.
# @param string description Optional.
# @param string friendly_name Optional.
create_destination_dataset() {
    local ref="$1"
    local loc="$2"
    local desc="${3:-null}"
    local fname="${4:-null}"

    jq -c --null-input \
       --argjson ref "$ref" \
       --arg loc "$loc" \
       --arg desc "$desc" \
       --arg fname "$fname" \
       '{datasetReference: $ref, location: $loc, description: $desc, friendlyName: $fname} | del(..|select(. == "null"))'
}

# Creates a JSON object for SubscribeListingRequest.
# @param string destination_dataset_json Required.
create_subscribe_listing_request() {
    jq -c --null-input --argjson dd "$1" \
        '{destinationDataset: $dd}'
}

# Creates a JSON object for SetIamPolicyRequest.
# @param string policy_json Required.
# @param string update_mask Optional.
create_set_iam_policy_request() {
    local policy="$1"
    local mask="${2:-null}"
    jq -c --null-input --argjson p "$policy" --arg m "$mask" \
        '{policy: $p, updateMask: $m} | del(..|select(. == "null"))'
}

# Creates a JSON object for RefreshSubscriptionRequest.
create_refresh_subscription_request() {
    echo "{}"
}

# Creates a JSON object for RevokeSubscriptionRequest.
create_revoke_subscription_request() {
    echo "{}"
}

# Creates a JSON object for SubscribeDataExchangeRequest.
# @param string destination_dataset_json Required.
create_subscribe_data_exchange_request() {
    jq -c --null-input --argjson dd "$1" \
        '{destinationDataset: $dd}'
}

# Creates a JSON object for TestIamPermissionsRequest.
# @param string permissions_array_json Required. e.g. ["bigquery.datasets.get"]
create_test_iam_permissions_request() {
    jq -c --null-input --argjson p "$1" \
        '{permissions: $p}'
}


###############################################################################
# Analytics Hub API (v1) Client
#
# This script provides a client for the Analytics Hub API v1.
#
# Discovery Doc Revision: 20260125
###############################################################################

# Resolve the directory of this script to locate internal helpers.
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Base URL for the Analytics Hub API
ANALYTICSHUB_V1_BASE_URL="https://analyticshub.googleapis.com/v1"

# --- Data Exchanges ---

# Lists all data exchanges in a given project and location.
#
# @param string project_id Required.
# @param string location Required.
# @param integer page_size Optional.
# @param string page_token Optional.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_list() {
  local project_id="$1"
  local location="$2"
  local page_size="${3:-""}"
  local page_token="${4:-""}"
  local billing_project_id="${5:-$project_id}"

  local parent="projects/${project_id}/locations/${location}"
  local query_args=()
  if [[ -n "${page_size}" ]]; then query_args+=("pageSize=${page_size}"); fi
  if [[ -n "${page_token}" ]]; then query_args+=("pageToken=${page_token}"); fi
  
  local query_params
  query_params=$(_build_query_params "${query_args[@]}")

  local url="${ANALYTICSHUB_V1_BASE_URL}/${parent}/dataExchanges${query_params}"
  _call_api "GET" "${url}" "" "${billing_project_id}"
}

# Creates a new data exchange.
#
# @param string project_id Required.
# @param string location Required.
# @param string request_body Required. DataExchange JSON.
# @param string data_exchange_id Required. The ID of the data exchange.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_create() {
  local project_id="$1"
  local location="$2"
  local request_body="$3"
  local data_exchange_id="$4"
  local billing_project_id="${5:-$project_id}"

  local parent="projects/${project_id}/locations/${location}"
  local query_params
  query_params=$(_build_query_params "dataExchangeId=${data_exchange_id}")

  local url="${ANALYTICSHUB_V1_BASE_URL}/${parent}/dataExchanges${query_params}"
  _call_api "POST" "${url}" "${request_body}" "${billing_project_id}"
}

# Gets the details of a data exchange.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_get() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local billing_project_id="${4:-$project_id}"

  local name="projects/${project_id}/locations/${location}/dataExchanges/${data_exchange_id}"
  local url="${ANALYTICSHUB_V1_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${billing_project_id}"
}

# Deletes an existing data exchange.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_delete() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local billing_project_id="${4:-$project_id}"

  local name="projects/${project_id}/locations/${location}/dataExchanges/${data_exchange_id}"
  local url="${ANALYTICSHUB_V1_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${billing_project_id}"
}

# --- Listings ---

# Lists all listings in a given project and location.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param integer page_size Optional.
# @param string page_token Optional.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_listings_list() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local page_size="${4:-""}"
  local page_token="${5:-""}"
  local billing_project_id="${6:-$project_id}"

  local parent="projects/${project_id}/locations/${location}/dataExchanges/${data_exchange_id}"
  local query_args=()
  if [[ -n "${page_size}" ]]; then query_args+=("pageSize=${page_size}"); fi
  if [[ -n "${page_token}" ]]; then query_args+=("pageToken=${page_token}"); fi
  
  local query_params
  query_params=$(_build_query_params "${query_args[@]}")

  local url="${ANALYTICSHUB_V1_BASE_URL}/${parent}/listings${query_params}"
  _call_api "GET" "${url}" "" "${billing_project_id}"
}

# Creates a new listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string request_body Required. Listing JSON.
# @param string listing_id Required. The ID of the listing.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_listings_create() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local request_body="$4"
  local listing_id="$5"
  local billing_project_id="${6:-$project_id}"

  local parent="projects/${project_id}/locations/${location}/dataExchanges/${data_exchange_id}"
  local query_params
  query_params=$(_build_query_params "listingId=${listing_id}")

  local url="${ANALYTICSHUB_V1_BASE_URL}/${parent}/listings${query_params}"
  _call_api "POST" "${url}" "${request_body}" "${billing_project_id}"
}

# Gets the details of a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_listings_get() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local listing_id="$4"
  local billing_project_id="${5:-$project_id}"

  local name="projects/${project_id}/locations/${location}/dataExchanges/${data_exchange_id}/listings/${listing_id}"
  local url="${ANALYTICSHUB_V1_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${billing_project_id}"
}

# Deletes a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_listings_delete() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local listing_id="$4"
  local billing_project_id="${5:-$project_id}"

  local name="projects/${project_id}/locations/${location}/dataExchanges/${data_exchange_id}/listings/${listing_id}"
  local url="${ANALYTICSHUB_V1_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${billing_project_id}"
}

# Subscribes to a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param string request_body Required. SubscribeListingRequest JSON.
# @param string billing_project_id Optional. Defaults to project_id.
analyticshub_v1_projects_locations_dataExchanges_listings_subscribe() {
  local project_id="$1"
  local location="$2"
  local data_exchange_id="$3"
  local listing_id="$4"
  local request_body="$5"
  local billing_project_id="${6:-$project_id}"

  local name="projects/${project_id}/locations/${location}/dataExchanges/${data_exchange_id}/listings/${listing_id}"
  local url="${ANALYTICSHUB_V1_BASE_URL}/${name}:subscribe"
  _call_api "POST" "${url}" "${request_body}" "${billing_project_id}"
}
