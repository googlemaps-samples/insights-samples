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


# Source the internal helper script
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/analyticshub_v1_helpers.sh"

# --- Analytics Hub API v1 ---

# Base URL for the Analytics Hub API
ANALYTICSHub_V1_BASE_URL="https://analyticshub.googleapis.com/v1"

# --- Organizations.Locations.DataExchanges ---

# Lists all data exchanges from projects in a given organization and location.
#
# @param string organization_id Required. The organization ID. e.g. `myorg`.
# @param string location Required. The location ID. e.g. `us`.
# @param string page_size Optional. The maximum number of results to return in a single response page.
# @param string page_token Optional. Page token, returned by a previous call, to request the next page of results.
# @param string project_id Optional. The project ID for auth and billing.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/organizations.locations.dataExchanges/list
analyticshub_organizations_locations_dataExchanges_list() {
  local org_id="$1"
  local location="$2"
  local page_size="${3:-}"
  local page_token="${4:-}"
  local project_id="${5:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")
  
  local url="${ANALYTICSHub_V1_BASE_URL}/organizations/${org_id}/locations/${location}/dataExchanges${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# --- Projects.Locations.DataExchanges ---

# Creates a new data exchange.
#
# @param string project_id Required. The project ID. e.g. `myproject`.
# @param string location Required. The location ID. e.g. `us`.
# @param string data_exchange_id Required. The ID of the data exchange.
# @param string request_body Required. The request body as a JSON string (DataExchange).
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges/create
analyticshub_projects_locations_dataExchanges_create() {
  local pid="$1"
  local location="$2"
  local data_exchange_id="$3"
  local request_body="$4"

  local query_params
  query_params=$(_build_query_params "dataExchangeId=${data_exchange_id}")

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges${query_params}"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Deletes an existing data exchange.
#
# @param string project_id Required. The project ID.
# @param string location Required. The location ID.
# @param string data_exchange_id Required. The ID of the data exchange to delete.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges/delete
analyticshub_projects_locations_dataExchanges_delete() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}"
  _call_api "DELETE" "${url}" "" "${pid}"
}

# Gets the details of a data exchange.
#
# @param string project_id Required. The project ID.
# @param string location Required. The location ID.
# @param string data_exchange_id Required. The ID of the data exchange.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges/get
analyticshub_projects_locations_dataExchanges_get() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Lists all data exchanges in a given project and location.
#
# @param string project_id Required. The project ID.
# @param string location Required. The location ID.
# @param string page_size Optional.
# @param string page_token Optional.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges/list
analyticshub_projects_locations_dataExchanges_list() {
  local pid="$1"
  local location="$2"
  local page_size="${3:-}"
  local page_token="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges${query_params}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Gets the IAM policy for a data exchange.
#
# @param string project_id Required. The project ID.
# @param string location Required. The location ID.
# @param string data_exchange_id Required. The ID of the data exchange.
# @param string request_body Optional. JSON string for GetIamPolicyRequest.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges/getIamPolicy
analyticshub_projects_locations_dataExchanges_getIamPolicy() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local request_body="${4:-{}}"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}:getIamPolicy"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Tests permissions against a data exchange.
#
# @param string project_id Required. The project ID.
# @param string location Required. The location ID.
# @param string data_exchange_id Required. The ID of the data exchange.
# @param string request_body Required. JSON string for TestIamPermissionsRequest (e.g. {"permissions":[...]}).
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges/testIamPermissions
analyticshub_projects_locations_dataExchanges_testIamPermissions() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local request_body="$4"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}:testIamPermissions"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# --- Projects.Locations.DataExchanges.Listings ---

# Creates a new listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required. The ID of the listing to create.
# @param string request_body Required. The request body as a JSON string (Listing).
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/create
analyticshub_projects_locations_dataExchanges_listings_create() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local listing_id="$4"
  local request_body="$5"
  
  local query_params
  query_params=$(_build_query_params "listingId=${listing_id}")

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings${query_params}"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Deletes a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param boolean delete_commercial Optional.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/delete
analyticshub_projects_locations_dataExchanges_listings_delete() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local listing_id="$4"
  local delete_commercial="${5:-}"

  local query_params
  query_params=$(_build_query_params "deleteCommercial=${delete_commercial}")

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings/${listing_id}${query_params}"
  _call_api "DELETE" "${url}" "" "${pid}"
}

# Updates an existing listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param string request_body Required. The request body as a JSON string (Listing).
# @param string update_mask Required. Field mask specifying the fields to update (e.g. displayName,description,primaryContact).
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/patch
analyticshub_projects_locations_dataExchanges_listings_patch() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local listing_id="$4"
  local request_body="$5"
  local update_mask="$6"

  local query_params
  query_params=$(_build_query_params "updateMask=${update_mask}")

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings/${listing_id}${query_params}"
  _call_api "PATCH" "${url}" "${request_body}" "${pid}"
}

# Gets the details of a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/get
analyticshub_projects_locations_dataExchanges_listings_get() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local listing_id="$4"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings/${listing_id}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Lists all listings in a given project and location.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string page_size Optional.
# @param string page_token Optional.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/list
analyticshub_projects_locations_dataExchanges_listings_list() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local page_size="${4:-}"
  local page_token="${5:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings${query_params}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Subscribes to a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param string request_body Required. (SubscribeListingRequest)
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/subscribe
analyticshub_projects_locations_dataExchanges_listings_subscribe() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local listing_id="$4"
  local request_body="$5"

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings/${listing_id}:subscribe"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Gets the IAM policy for a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param string request_body Optional. JSON string for GetIamPolicyRequest.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/getIamPolicy
analyticshub_projects_locations_dataExchanges_listings_getIamPolicy() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local listing_id="$4"
  local request_body="${5:-{}}"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings/${listing_id}:getIamPolicy"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Tests permissions against a listing.
#
# @param string project_id Required.
# @param string location Required.
# @param string data_exchange_id Required.
# @param string listing_id Required.
# @param string request_body Required. JSON string for TestIamPermissionsRequest (e.g. {"permissions":[...]}).
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.dataExchanges.listings/testIamPermissions
analyticshub_projects_locations_dataExchanges_listings_testIamPermissions() {
  local pid="$1"
  local location="$2"
  local dxid="$3"
  local listing_id="$4"
  local request_body="$5"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/dataExchanges/${dxid}/listings/${listing_id}:testIamPermissions"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# --- Projects.Locations.Subscriptions ---

# Deletes a subscription.
#
# @param string project_id Required.
# @param string location Required.
# @param string subscription_id Required.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.subscriptions/delete
analyticshub_projects_locations_subscriptions_delete() {
  local pid="$1"
  local location="$2"
  local subid="$3"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/subscriptions/${subid}"
  _call_api "DELETE" "${url}" "" "${pid}"
}

# Gets the details of a Subscription.
#
# @param string project_id Required.
# @param string location Required.
# @param string subscription_id Required.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.subscriptions/get
analyticshub_projects_locations_subscriptions_get() {
  local pid="$1"
  local location="$2"
  local subid="$3"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/subscriptions/${subid}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Lists all subscriptions in a given project and location.
#
# @param string project_id Required.
# @param string location Required.
# @param string filter Optional.
# @param string page_size Optional.
# @param string page_token Optional.
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.subscriptions/list
analyticshub_projects_locations_subscriptions_list() {
  local pid="$1"
  local location="$2"
  local filter="${3:-}"
  local page_size="${4:-}"
  local page_token="${5:-}"

  local query_params
  query_params=$(_build_query_params "filter=${filter}" "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/subscriptions${query_params}"
  _call_api "GET" "${url}" "" "${pid}"
}

# Refreshes a Subscription to a Data Exchange.
#
# @param string project_id Required.
# @param string location Required.
# @param string subscription_id Required.
# @param string request_body Required. (RefreshSubscriptionRequest)
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.subscriptions/refresh
analyticshub_projects_locations_subscriptions_refresh() {
  local pid="$1"
  local location="$2"
  local subid="$3"
  local request_body="$4"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/subscriptions/${subid}:refresh"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}

# Revokes a given subscription.
#
# @param string project_id Required.
# @param string location Required.
# @param string subscription_id Required.
# @param string request_body Required. (RevokeSubscriptionRequest)
# @see https://cloud.google.com/bigquery/docs/reference/rest/v1/projects.locations.subscriptions/revoke
analyticshub_projects_locations_subscriptions_revoke() {
  local pid="$1"
  local location="$2"
  local subid="$3"
  local request_body="$4"
  local url="${ANALYTICSHub_V1_BASE_URL}/projects/${pid}/locations/${location}/subscriptions/${subid}:revoke"
  _call_api "POST" "${url}" "${request_body}" "${pid}"
}
