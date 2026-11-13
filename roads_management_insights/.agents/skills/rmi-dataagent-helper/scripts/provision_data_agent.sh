#!/bin/bash
#
# RMI BigQuery Data Agent Multi-Persona Provisioner
# Sourced by operational scripts or run directly via CLI to configure and interact
# with RMI persona-tailored Data Agents.
#
# Dependencies: api-geminidataanalytics (GA v1 client)
#
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SKILL_DIR="${SCRIPT_DIR}/.."
ASSETS_DIR="${SKILL_DIR}/assets"
API_GEMINI_DIR="${SKILL_DIR}/../api-geminidataanalytics/scripts"

# Source the canonical GA client and helpers from api-geminidataanalytics
if [[ -f "${API_GEMINI_DIR}/geminidataanalytics_v1.sh" ]]; then
  # shellcheck source=/dev/null
  source "${API_GEMINI_DIR}/geminidataanalytics_v1.sh"
elif [[ -f "${HOME}/agentic-skills-dev/src/api-geminidataanalytics/scripts/geminidataanalytics_v1.sh" ]]; then
  # shellcheck source=/dev/null
  source "${HOME}/agentic-skills-dev/src/api-geminidataanalytics/scripts/geminidataanalytics_v1.sh"
fi

# Map a persona key or alias to its asset JSON template
_get_persona_template_file() {
  local persona_key="$1"
  case "${persona_key,,}" in
    tom|traffic_ops|traffic_operations_manager)
      echo "${ASSETS_DIR}/traffic_ops_agent_expert.json"
      ;;
    up|urban_planner)
      echo "${ASSETS_DIR}/urban_planner_agent_expert.json"
      ;;
    bqa|bigquery_admin|finops)
      echo "${ASSETS_DIR}/bigquery_admin_agent_expert.json"
      ;;
    de|data_engineer|etl)
      echo "${ASSETS_DIR}/data_engineer_agent_expert.json"
      ;;
    ds|data_scientist|ml)
      echo "${ASSETS_DIR}/data_scientist_agent_expert.json"
      ;;
    rmip|rmi_planner|planner)
      echo "${ASSETS_DIR}/rmi_planner_agent_expert.json"
      ;;
    *)
      echo ""
      ;;
  esac
}

# =============================================================================
# Multi-Persona Provisioning Core Function
# =============================================================================

# Sets up a persona-tailored BigQuery Data Agent.
#
# @param string persona_key Required. One of: tom, up, bqa, de, ds, rmip.
# @param string parent_location Required. Location resource path: "projects/*/locations/*".
# @param string project_id Required. GCP project ID.
# @param string dataset_id Required. BigQuery dataset ID (e.g. "src_boston_ga").
# @param string agent_id Optional. Custom agent ID (defaults to "rmi-<persona>-agent").
setup_persona_agent() {
  local persona_key="$1"
  local parent_location="$2"
  local project_id="$3"
  local dataset_id="$4"
  local agent_id="${5:-}"

  local asset_path
  asset_path=$(_get_persona_template_file "${persona_key}")
  if [[ -z "${asset_path}" || ! -f "${asset_path}" ]]; then
    echo "❌ Error: Unknown persona '${persona_key}' or asset template missing at '${asset_path}'." >&2
    echo "   Available personas: tom (Traffic Ops), up (Urban Planner), bqa (BigQuery Admin), de (Data Engineer), ds (Data Scientist), rmip (RMI Planner)." >&2
    return 1
  fi

  if [[ -z "${agent_id}" ]]; then
    agent_id="rmi-${persona_key,,}-agent"
  fi

  # Hydrate datasource table references with target project and dataset
  local payload
  payload=$(jq --arg p "${project_id}" --arg d "${dataset_id}" '
    .dataAnalyticsAgent.stagingContext.datasourceReferences.bq.tableReferences = [
      .dataAnalyticsAgent.stagingContext.datasourceReferences.bq.tableReferences[] |
      { projectId: $p, datasetId: $d, tableId: .tableId }
    ]
  ' "${asset_path}")

  echo "📦 Provisioning RMI [${persona_key^^}] Data Agent '${agent_id}' in ${parent_location}..."
  geminidataanalytics_v1_dataAgents_createSync "${parent_location}" "${payload}" "${agent_id}" "${project_id}"
}

# =============================================================================
# Persona Convenience Wrappers
# =============================================================================

provision_rmi_traffic_ops_agent() {
  setup_persona_agent "tom" "$1" "$2" "$3" "${4:-rmi-traffic-ops-agent}"
}

provision_rmi_urban_planner_agent() {
  setup_persona_agent "up" "$1" "$2" "$3" "${4:-rmi-urban-planner-agent}"
}

provision_rmi_bigquery_admin_agent() {
  setup_persona_agent "bqa" "$1" "$2" "$3" "${4:-rmi-bigquery-admin-agent}"
}

provision_rmi_data_engineer_agent() {
  setup_persona_agent "de" "$1" "$2" "$3" "${4:-rmi-data-engineer-agent}"
}

provision_rmi_data_scientist_agent() {
  setup_persona_agent "ds" "$1" "$2" "$3" "${4:-rmi-data-scientist-agent}"
}

provision_rmi_planner_agent() {
  setup_persona_agent "rmip" "$1" "$2" "$3" "${4:-rmi-planner-agent}"
}

# =============================================================================
# Conversational Querying Helper
# =============================================================================

# Sends a natural language traffic query to a provisioned RMI Data Agent.
#
# @param string parent_location Required. Location resource path: "projects/*/locations/*".
# @param string agent_resource_name Required. Resource path: "projects/*/locations/*/dataAgents/*".
# @param string user_query Required. Conversational user question.
# @param string project_id Optional. Quota / billing project ID.
chat_with_rmi_agent() {
  local parent_location="$1"
  local agent_resource_name="$2"
  local user_query="$3"
  local project_id="${4:-}"

  local umsg
  umsg=$(create_user_message_json "${user_query}")
  local msg
  msg=$(create_message_with_user_message_json "${umsg}")
  local msgs_array
  msgs_array=$(jq -n --argjson m "${msg}" '[$m]')

  local chat_payload
  chat_payload=$(jq -n \
    --arg agent "${agent_resource_name}" \
    --argjson msgs "${msgs_array}" \
    '{
      dataAgentContext: {
        dataAgent: $agent,
        contextVersion: "STAGING"
      },
      messages: $msgs,
      thinkingMode: "THINKING"
    }')

  geminidataanalytics_v1_chat "${parent_location}" "${chat_payload}" "${project_id}"
}

# =============================================================================
# CLI Entrypoint
# =============================================================================

_print_usage() {
  cat <<EOF
Usage:
  bash scripts/provision_data_agent.sh --persona <tom|up|bqa|de|ds|rmip> --location <projects/*/locations/*> --project <project_id> --dataset <dataset_id> [--agent-id <custom_id>]

Available Personas:
  - tom   : Traffic Operations Manager (Real-time incident response, SRIs, detours)
  - up    : Urban Planner (Longitudinal infrastructure ROI, TTI/PTI, emissions)
  - bqa   : BigQuery Admin (Cost attribution, slot contention, zero-cost audits)
  - de    : Data Engineer (Spatial integrity, SRI flattening, hourly rollups)
  - ds    : Data Scientist (Statistical Z-scores, ARIMA_PLUS forecasting, buffer index)
  - rmip  : RMI Planner (TAM network coverage, tier SLAs, compute growth forecasting)

Examples:
  bash scripts/provision_data_agent.sh --persona tom --location projects/my-p/locations/us-central1 --project my-p --dataset src_boston_ga
  bash scripts/provision_data_agent.sh --persona up --location projects/my-p/locations/us-central1 --project my-p --dataset src_boston_ga --agent-id custom-urban-planner
EOF
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  PERSONA=""
  LOCATION=""
  PROJECT=""
  DATASET=""
  AGENT_ID=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --persona|-p)
        PERSONA="$2"
        shift 2
        ;;
      --location|-l)
        LOCATION="$2"
        shift 2
        ;;
      --project)
        PROJECT="$2"
        shift 2
        ;;
      --dataset|-d)
        DATASET="$2"
        shift 2
        ;;
      --agent-id|-a)
        AGENT_ID="$2"
        shift 2
        ;;
      --help|-h)
        _print_usage
        exit 0
        ;;
      *)
        echo "❌ Unknown option: $1" >&2
        _print_usage
        exit 1
        ;;
    esac
  done

  if [[ -z "${PERSONA}" || -z "${LOCATION}" || -z "${PROJECT}" || -z "${DATASET}" ]]; then
    echo "❌ Missing required arguments." >&2
    _print_usage
    exit 1
  fi

  setup_persona_agent "${PERSONA}" "${LOCATION}" "${PROJECT}" "${DATASET}" "${AGENT_ID}"
fi
