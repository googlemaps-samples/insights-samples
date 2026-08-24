#!/bin/bash
set -euo pipefail
#
# This script provides a client for the Google Cloud Gemini Data Analytics API v1alpha.
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

# --- Gemini Data Analytics API v1alpha ---

GEMINIDATAANALYTICS_V1ALPHA_BASE_URL="https://geminidataanalytics.googleapis.com/v1alpha"

# =============================================================================
# 1. Chat & Conversational Analytics
# =============================================================================

# Answers data questions in v1alpha.
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string request_body Required. ChatRequest JSON payload.
# @param string project_id Optional. Project ID for billing / quota header.
geminidataanalytics_v1alpha_chat() {
  local parent="$1"
  local request_body="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${parent}:chat"
  _call_api "POST" "${url}" "${request_body}" "${project_id}"
}

# Translates natural language queries into executable structured queries in v1alpha.
#
# @param string parent Required. Location resource path: "projects/*/locations/*".
# @param string request_body Required. QueryDataRequest JSON payload.
# @param string project_id Optional. Project ID for billing / quota header.
geminidataanalytics_v1alpha_queryData() {
  local parent="$1"
  local request_body="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${parent}:queryData"
  _call_api "POST" "${url}" "${request_body}" "${project_id}"
}

# =============================================================================
# 2. Managed Conversations CRUD
# =============================================================================

geminidataanalytics_v1alpha_conversations_create() {
  local parent="$1"
  local conversation_json="$2"
  local project_id="${3:-}"

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${parent}/conversations"
  _call_api "POST" "${url}" "${conversation_json}" "${project_id}"
}

geminidataanalytics_v1alpha_conversations_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

geminidataanalytics_v1alpha_conversations_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${parent}/conversations${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

geminidataanalytics_v1alpha_conversations_delete() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${project_id}"
}

# =============================================================================
# 3. Data Agents Management
# =============================================================================

geminidataanalytics_v1alpha_dataAgents_create() {
  local parent="$1"
  local agent_json="$2"
  local data_agent_id="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "dataAgentId=${data_agent_id}")

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${parent}/dataAgents${query_params}"
  _call_api "POST" "${url}" "${agent_json}" "${project_id}"
}

geminidataanalytics_v1alpha_dataAgents_get() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${name}"
  _call_api "GET" "${url}" "" "${project_id}"
}

geminidataanalytics_v1alpha_dataAgents_list() {
  local parent="$1"
  local page_size="${2:-}"
  local page_token="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "pageSize=${page_size}" "pageToken=${page_token}")

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${parent}/dataAgents${query_params}"
  _call_api "GET" "${url}" "" "${project_id}"
}

geminidataanalytics_v1alpha_dataAgents_patch() {
  local name="$1"
  local agent_json="$2"
  local update_mask="${3:-}"
  local project_id="${4:-}"

  local query_params
  query_params=$(_build_query_params "updateMask=${update_mask}")

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${name}${query_params}"
  _call_api "PATCH" "${url}" "${agent_json}" "${project_id}"
}

geminidataanalytics_v1alpha_dataAgents_delete() {
  local name="$1"
  local project_id="${2:-}"

  local url="${GEMINIDATAANALYTICS_V1ALPHA_BASE_URL}/${name}"
  _call_api "DELETE" "${url}" "" "${project_id}"
}
