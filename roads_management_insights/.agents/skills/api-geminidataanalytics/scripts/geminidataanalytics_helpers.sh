#!/bin/bash
set -euo pipefail
#
# Consolidated helper functions for creating JSON request bodies and parameters
# for the Google Cloud Gemini Data Analytics API (v1beta and v1alpha).
# It is meant to be sourced by other scripts.
#
# For more information, see official documentation:
# https://cloud.google.com/gemini/docs/conversational-analytics-api/overview

# --- Request Body Helper Functions ---

# Creates a UserMessage JSON object.
#
# @param string text Required. The user prompt or message text.
# @return string The JSON object.
create_user_message_json() {
  local text="$1"
  jq -n -c --arg text "${text}" '{text: $text}'
}

# Creates a Message JSON wrapping a UserMessage.
#
# @param string user_msg_json Required. The JSON output of create_user_message_json.
# @param string message_id Optional. Unique ID for this message.
# @return string The Message JSON object.
create_message_with_user_message_json() {
  local user_msg="$1"
  local msg_id="${2:-}"

  local json_output="{}"
  json_output=$(echo "${json_output}" | jq -c --argjson um "${user_msg}" '.userMessage = $um')

  if [[ -n "${msg_id}" ]]; then
    json_output=$(echo "${json_output}" | jq -c --arg mid "${msg_id}" '.messageId = $mid')
  fi

  echo "${json_output}"
}

# Creates a ConversationReference JSON object.
#
# @param string conversation_path Required. Resource path: "projects/*/locations/*/conversations/*"
# @return string The ConversationReference JSON object.
create_conversation_reference_json() {
  local path="$1"
  jq -n -c --arg p "${path}" '{conversation: $p}'
}

# Creates a ChatRequest JSON object.
#
# @param string messages_json_array Required. JSON array of messages.
# @param string conversation_ref_json Optional. JSON object or path for conversationReference.
# @param string thinking_mode Optional. Thinking mode enum: "FAST", "THINKING".
# @param string model Optional. Model enum (e.g. "LATEST_GA_MODEL").
# @return string The ChatRequest JSON payload.
create_chat_request_json() {
  local msgs="$1"
  local conv="${2:-}"
  local tm="${3:-}"
  local md="${4:-}"

  local conv_obj="null"
  if [[ -n "${conv}" && "${conv}" != "null" ]]; then
    if [[ "${conv}" == \{* ]]; then
      conv_obj="${conv}"
    else
      conv_obj=$(create_conversation_reference_json "${conv}")
    fi
  fi

  jq -n \
    --argjson msgs "${msgs}" \
    --argjson conv "${conv_obj}" \
    --arg tm "${tm}" \
    --arg md "${md}" \
    '{
      messages: $msgs,
      conversationReference: $conv,
      thinkingMode: (if $tm == "" then null else $tm end),
      model: (if $md == "" then null else $md end)
    }' | jq -c 'del(..|nulls)'
}

# Creates a BigQueryTableReference JSON object.
#
# @param string project_id Required. The GCP project ID.
# @param string dataset_id Required. The BigQuery dataset ID.
# @param string table_id Required. The BigQuery table ID.
# @return string The BigQueryTableReference JSON object.
create_bigquery_table_reference_json() {
  local proj="$1"
  local ds="$2"
  local tbl="$3"
  jq -n -c \
    --arg p "${proj}" \
    --arg d "${ds}" \
    --arg t "${tbl}" \
    '{projectId: $p, datasetId: $d, tableId: $t}'
}

# Creates a BigQueryPropertyGraphReference JSON object.
#
# @param string project_id Required. The GCP project ID.
# @param string dataset_id Required. The BigQuery dataset ID.
# @param string property_graph_id Required. The BigQuery Property Graph ID.
# @return string The BigQueryPropertyGraphReference JSON object.
create_bigquery_property_graph_reference_json() {
  local proj="$1"
  local ds="$2"
  local pg="$3"
  jq -n -c \
    --arg p "${proj}" \
    --arg d "${ds}" \
    --arg pg "${pg}" \
    '{projectId: $p, datasetId: $d, propertyGraphId: $pg}'
}

# Creates a BigtableReference JSON object.
#
# @param string project_id Required. The GCP project ID.
# @param string instance_id Required. The Bigtable instance ID.
# @param string table_id Required. The Bigtable table ID.
# @return string The BigtableReference JSON object.
create_bigtable_reference_json() {
  local proj="$1"
  local inst="$2"
  local tbl="$3"
  jq -n -c \
    --arg p "${proj}" \
    --arg i "${inst}" \
    --arg t "${tbl}" \
    '{projectId: $p, instanceId: $i, tableId: $t}'
}

# Creates a QueryDataRequest JSON object.
#
# @param string prompt Required. The natural language prompt.
# @param string bq_table_refs_json_array Required. JSON array of BigQueryTableReference objects.
# @return string The QueryDataRequest JSON payload.
create_query_data_request_json() {
  local prompt="$1"
  local bq_refs="${2:-[]}"
  jq -n -c \
    --arg p "${prompt}" \
    --argjson bq "${bq_refs}" \
    '{prompt: $p, context: {datasourceReferences: {bq: {tableReferences: $bq}}}}'
}

# Creates a DataAgent JSON object.
#
# @param string display_name Required. Human-readable name for the Data Agent.
# @param string description Optional. Description of the agent's responsibilities.
# @param string context_json Optional. Context JSON object specifying data sources.
# @return string The DataAgent JSON payload.
create_data_agent_json() {
  local display_name="$1"
  local description="${2:-}"
  local context="${3:-null}"

  jq -n -c \
    --arg dn "${display_name}" \
    --arg desc "${description}" \
    --argjson ctx "${context}" \
    '{
      displayName: $dn,
      description: (if $desc == "" then null else $desc end),
      context: $ctx
    }' | jq -c 'del(..|nulls)'
}

# --- Backward-Compatibility Aliases ---

geminidataanalytics_v1beta_bq_table_ref_json() {
  create_bigquery_table_reference_json "$@"
}

geminidataanalytics_v1beta_query_data_context_json() {
  local bq_tables="$1"
  jq -n -c --argjson bqt "$bq_tables" '{bigqueryTables: $bqt}'
}

geminidataanalytics_v1beta_query_data_request_json() {
  local prompt="$1"
  local context="${2:-null}"
  jq -n -c --arg p "$prompt" --argjson c "$context" '{prompt: $p, context: $c}'
}

geminidataanalytics_v1beta_chat_request_json() {
  local conv_ref="${1:-null}"
  local messages="$2"
  jq -n -c --argjson cr "$conv_ref" --argjson msg "$messages" \
    '{conversationReference: $cr, messages: $msg}' | jq -c 'del(..|nulls)'
}
