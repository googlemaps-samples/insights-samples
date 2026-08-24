#!/bin/bash
set -euo pipefail
#
# This script provides a comprehensive client for the Google Cloud Gemini Data Analytics API v1beta.
# It is not meant to be used directly, but rather to be sourced by other scripts.
#
# Discovery Doc Revision: 20260815
# Base URL: https://geminidataanalytics.googleapis.com
#
# For more information, see official documentation:
# https://cloud.google.com/gemini/docs/conversational-analytics-api/overview

# Source the internal helper script
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/geminidataanalytics_helpers.sh"

# --- Gemini Data Analytics API v1beta ---

GEMINIDATAANALYTICS_V1BETA_BASE_URL="https://geminidataanalytics.googleapis.com/v1beta"

# =============================================================================
# 1. Chat & Conversational Analytics
# =============================================================================

# Answers data questions by generating a conversational response stream.
#
# @param string parent Required. Location resource path: "projects/*/locations/*" (or project ID if legacy).
# @param string request_body Required. ChatRequest JSON payload.
# @param string project_id Optional. Project ID for billing / quota header.
# @see https://cloud.google.com/gemini/docs/conversational-analytics-api/reference/rest/v1beta/projects.locations/chat
geminidataanalytics_v1beta_chat() {
  local parent="$1"
  local request_body="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}:chat"
  _call_api "POST" "${url}" "${request_body}" "${project_id}"
}

# =============================================================================
# 2. Query Translation (queryData)
# =============================================================================

# Translates natural language queries into executable structured queries (e.g. SQL).
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string request_body Required. QueryDataRequest JSON payload.
# @param string project_id Optional. Project ID for billing / quota header.
# @see https://cloud.google.com/gemini/docs/conversational-analytics-api/reference/rest/v1beta/projects.locations/queryData
geminidataanalytics_v1beta_queryData() {
  local parent="$1"
  local request_body="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}:queryData"
  _call_api "POST" "${url}" "${request_body}" "${project_id}"
}

# =============================================================================
# 3. Managed Conversations CRUD
# =============================================================================

# Creates a new managed conversation.
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string conversation_json Required. Conversation JSON payload.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_conversations_create() {
  local parent="$1"
  local conversation_json="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}/conversations"
  _call_api "POST" "${url}" "${conversation_json}" "${project_id}"
}

# Retrieves details of a managed conversation.
#
# @param string name Required. Conversation resource path: "projects/*/locations/*/conversations/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_conversations_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Lists managed conversations.
#
# @param string parent Required. Location resource path.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_conversations_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}/conversations${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Deletes a managed conversation.
#
# @param string name Required. Conversation resource path.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_conversations_delete() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${project_id}"
}

# Lists messages in a conversation.
#
# @param string parent Required. Conversation resource path.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_conversations_messages_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}/messages${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# =============================================================================
# 4. Data Agents Management
# =============================================================================

# Creates a DataAgent.
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string agent_json Required. DataAgent JSON payload.
# @param string data_agent_id Optional. Custom ID for the agent.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_dataAgents_create() {
  local parent="$1"
  local agent_json="$2"
  local data_agent_id="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "dataAgentId=${data_agent_id}")

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}/dataAgents${query_params}"
  _call_api "POST" "${url}" "${agent_json}" "${project_id}"
}

# Retrieves details of a DataAgent.
#
# @param string name Required. Resource path: "projects/*/locations/*/dataAgents/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_dataAgents_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Lists DataAgents.
#
# @param string parent Required. Location resource path.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_dataAgents_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}/dataAgents${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Updates a DataAgent with field mask.
#
# @param string name Required. Resource path: "projects/*/locations/*/dataAgents/*".
# @param string agent_json Required. Updated DataAgent JSON payload.
# @param string update_mask Optional. Comma-separated field mask (e.g. "displayName,description").
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_dataAgents_patch() {
  local name="$1"
  local agent_json="$2"
  local update_mask="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "updateMask=${update_mask}")

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${name}${query_params}"
  _call_api "PATCH" "${url}" "${agent_json}" "${project_id}"
}

# Deletes a DataAgent.
#
# @param string name Required. Resource path.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_dataAgents_delete() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${project_id}"
}

# Lists accessible DataAgents.
#
# @param string parent Required. Location resource path.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_dataAgents_listAccessible() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${parent}/dataAgents:listAccessible${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# =============================================================================
# 5. Agent-to-Agent (A2A) Messaging
# =============================================================================

# Gets the agent card for an A2A tenant.
#
# @param string tenant Required. Tenant resource path: "projects/*/locations/*/dataAgents/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_a2a_getCard() {
  local tenant="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/a2a/${tenant}/v1/card"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Sends an A2A message.
#
# @param string tenant Required. Tenant resource path.
# @param string request_body Required. Message JSON payload.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_a2a_message_send() {
  local tenant="$1"
  local request_body="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/a2a/${tenant}/v1/message:send"
  _call_api "POST" "${url}" "${request_body}" "${project_id}"
}

# =============================================================================
# 6. Operations Management
# =============================================================================

# Gets the status of an asynchronous operation.
#
# @param string name Required. Operation resource path: "projects/*/locations/*/operations/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_operations_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Lists operations.
#
# @param string name Required. Parent resource path.
# @param string filter Optional.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1beta_operations_list() {
  local name="$1"
  local filter="${2:-}"
  local page_size="${3:-}"
  local page_token="${4:-}"
  local project_id="${5:-}"

  local query_params
  query_params=$(_build_query_params "filter=${filter}" "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1BETA_BASE_URL}/${name}/operations${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# =============================================================================
# 7. Backward-Compatibility Aliases
# =============================================================================

geminidataanalytics_projects_locations_chat() {
  local pid="$1"
  local location="${2:-}"
  local request_body="${3:-}"

  if [[ "$pid" == projects/* ]]; then
    geminidataanalytics_v1beta_chat "$pid" "$location" "$request_body"
  else
    local parent="projects/${pid}/locations/${location}"
    geminidataanalytics_v1beta_chat "$parent" "$request_body" "$pid"
  fi
}

geminidataanalytics_projects_locations_query_data() {
  local pid="$1"
  local location="${2:-}"
  local request_body="${3:-}"

  if [[ "$pid" == projects/* ]]; then
    geminidataanalytics_v1beta_queryData "$pid" "$location" "$request_body"
  else
    local parent="projects/${pid}/locations/${location}"
    geminidataanalytics_v1beta_queryData "$parent" "$request_body" "$pid"
  fi
}

geminidataanalytics_projects_locations_conversations_create() {
  local pid="$1"
  local location="${2:-}"
  local request_body="${3:-}"

  if [[ "$pid" == projects/* ]]; then
    geminidataanalytics_v1beta_conversations_create "$pid" "$location" "$request_body"
  else
    local parent="projects/${pid}/locations/${location}"
    geminidataanalytics_v1beta_conversations_create "$parent" "$request_body" "$pid"
  fi
}

geminidataanalytics_projects_locations_conversations_list() {
  local pid="$1"
  local location="${2:-}"

  if [[ "$pid" == projects/* ]]; then
    geminidataanalytics_v1beta_conversations_list "$pid" "" "" "$location"
  else
    local parent="projects/${pid}/locations/${location}"
    geminidataanalytics_v1beta_conversations_list "$parent" "" "" "$pid"
  fi
}
