#!/bin/bash
set -euo pipefail
#
# This script provides a comprehensive client for the Google Cloud Gemini Data Analytics API v1 (GA).
# It is not meant to be used directly, but rather to be sourced by other scripts.
#
# Discovery Doc Revision: 20260815 (GA v1)
# Base URL: https://geminidataanalytics.googleapis.com/v1
#
# For more information, see official documentation:
# https://cloud.google.com/gemini/docs/conversational-analytics-api/overview

# Source the internal helper scripts
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/geminidataanalytics_helpers.sh"

# --- Gemini Data Analytics API v1 (GA) ---

GEMINIDATAANALYTICS_V1_BASE_URL="https://geminidataanalytics.googleapis.com/v1"

# =============================================================================
# 1. Chat & Conversational Analytics (GA v1)
# =============================================================================

# Answers data questions by generating a conversational response stream.
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string request_body Required. ChatRequest JSON payload.
# @param string project_id Optional. Project ID for billing / quota header.
# @see https://cloud.google.com/gemini/docs/conversational-analytics-api/reference/rest/v1/projects.locations/chat
geminidataanalytics_v1_chat() {
  local parent="$1"
  local request_body="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}:chat"
  _call_api "POST" "${url}" "${request_body}" "${project_id}"
}

# =============================================================================
# 2. Managed Conversations CRUD (GA v1)
# =============================================================================

# Creates a new managed conversation session.
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string conversation_json Required. Conversation JSON payload.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_conversations_create() {
  local parent="$1"
  local conversation_json="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}/conversations"
  _call_api "POST" "${url}" "${conversation_json}" "${project_id}"
}

# Retrieves details of a managed conversation.
#
# @param string name Required. Conversation resource path: "projects/*/locations/*/conversations/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_conversations_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Lists managed conversations in a project location.
#
# @param string parent Required. Location resource path.
# @param string page_size Optional. Number of conversations to return.
# @param string page_token Optional. Continuation token.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_conversations_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}/conversations${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Deletes a managed conversation.
#
# @param string name Required. Conversation resource path.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_conversations_delete() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${project_id}"
}

# Lists messages in a conversation.
#
# @param string parent Required. Conversation resource path.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_conversations_messages_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}/messages${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# =============================================================================
# 3. Data Agents Management (GA v1)
# =============================================================================

# Creates a DataAgent asynchronously.
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string agent_json Required. DataAgent JSON payload.
# @param string data_agent_id Optional. Custom ID for the agent.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_create() {
  local parent="$1"
  local agent_json="$2"
  local data_agent_id="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "dataAgentId=${data_agent_id}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}/dataAgents${query_params}"
  _call_api "POST" "${url}" "${agent_json}" "${project_id}"
}

# Creates a DataAgent synchronously.
#
# @param string parent Required. Location resource path.
# @param string agent_json Required. DataAgent JSON payload.
# @param string data_agent_id Optional. Custom ID for the agent.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_createSync() {
  local parent="$1"
  local agent_json="$2"
  local data_agent_id="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "dataAgentId=${data_agent_id}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}/dataAgents:createSync${query_params}"
  _call_api "POST" "${url}" "${agent_json}" "${project_id}"
}

# Retrieves details of a DataAgent.
#
# @param string name Required. Resource path: "projects/*/locations/*/dataAgents/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Lists DataAgents in a location.
#
# @param string parent Required. Location resource path.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}/dataAgents${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Lists accessible DataAgents.
#
# @param string parent Required. Location resource path.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_listAccessible() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${parent}/dataAgents:listAccessible${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Updates a DataAgent with field mask (asynchronous).
#
# @param string name Required. Resource path: "projects/*/locations/*/dataAgents/*".
# @param string agent_json Required. Updated DataAgent JSON payload.
# @param string update_mask Optional. Comma-separated field mask.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_patch() {
  local name="$1"
  local agent_json="$2"
  local update_mask="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "updateMask=${update_mask}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}${query_params}"
  _call_api "PATCH" "${url}" "${agent_json}" "${project_id}"
}

# Updates a DataAgent synchronously.
#
# @param string name Required. Resource path.
# @param string agent_json Required. Updated DataAgent JSON payload.
# @param string update_mask Optional. Field mask.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_updateSync() {
  local name="$1"
  local agent_json="$2"
  local update_mask="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "updateMask=${update_mask}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}:updateSync${query_params}"
  _call_api "PATCH" "${url}" "${agent_json}" "${project_id}"
}

# Deletes a DataAgent (asynchronous).
#
# @param string name Required. Resource path.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_delete() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${project_id}"
}

# Deletes a DataAgent synchronously.
#
# @param string name Required. Resource path.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_deleteSync() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}:deleteSync"
  _call_api "DELETE" "${url}" "" "${project_id}"
}

# Gets IAM policy for a DataAgent.
#
# @param string resource Required. Resource path: "projects/*/locations/*/dataAgents/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_getIamPolicy() {
  local resource="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${resource}:getIamPolicy"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Sets IAM policy for a DataAgent.
#
# @param string resource Required. Resource path.
# @param string policy_json Required. SetIamPolicyRequest JSON payload.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_dataAgents_setIamPolicy() {
  local resource="$1"
  local policy_json="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${resource}:setIamPolicy"
  _call_api "POST" "${url}" "${policy_json}" "${project_id}"
}

# =============================================================================
# 4. Long-Running Operations (LRO) (GA v1)
# =============================================================================

# Retrieves status of an operation.
#
# @param string name Required. Operation resource path: "projects/*/locations/*/operations/*".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_operations_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Lists operations.
#
# @param string name Required. Resource path: "projects/*/locations/*".
# @param string filter Optional.
# @param string page_size Optional.
# @param string page_token Optional.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_operations_list() {
  local name="$1"
  local filter="${2:-}"
  local page_size="${3:-}"
  local page_token="${4:-}"
  local project_id="${5:-}"

  local query_params
  query_params=$(_build_query_params "filter=${filter}" "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}/operations${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Cancels an active operation.
#
# @param string name Required. Operation path.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_operations_cancel() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}:cancel"
  _call_api "POST" "${url}" "{}" "${project_id}"
}

# Deletes an operation.
#
# @param string name Required. Operation path.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_operations_delete() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${project_id}"
}

# =============================================================================
# 5. Agent-to-Agent (A2A) Messaging (GA v1)
# =============================================================================

# Gets the agent card for an A2A tenant.
#
# @param string tenant Required. Tenant resource path: "projects/*/locations/agents" or "projects/*/locations/dataAgents".
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_a2a_getCard() {
  local tenant="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/a2a/${tenant}/v1/card"
  _call_api "GET" "${url}" "" "${project_id}"
}

# Sends an A2A message to an agent.
#
# @param string tenant Required. Tenant resource path.
# @param string message_json Required. Message payload.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_a2a_message_send() {
  local tenant="$1"
  local message_json="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/a2a/${tenant}/v1/message:send"
  _call_api "POST" "${url}" "${message_json}" "${project_id}"
}

# Streams an A2A message to an agent.
#
# @param string tenant Required. Tenant resource path.
# @param string message_json Required. Message payload.
# @param string project_id Optional. Project ID for billing.
geminidataanalytics_v1_a2a_message_stream() {
  local tenant="$1"
  local message_json="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1_BASE_URL}/a2a/${tenant}/v1/message:stream"
  _call_api "POST" "${url}" "${message_json}" "${project_id}"
}
