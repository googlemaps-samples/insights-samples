#!/bin/bash
set -euo pipefail

# ==============================================================================
# list_sample_datasets.sh
# Retrieves and formats all available RMI sample datasets published on Analytics Hub.
# Pure POSIX Bash + JQ implementation (Zero Python runtime dependency).
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${SKILL_ROOT}/.." && pwd)"

# Configuration defaults with environment fallbacks
PROJECT_ID="${PROJECT_ID:-1024202510105}"
LOCATION="${LOCATION:-us}"
EXCHANGE_ID="${EXCHANGE_ID:-rmi_sampledata_v2_ga_prod}"
OUTPUT_FORMAT="${1:---table}"

# 1. Resolve api-analyticshub skill directory
AH_SKILL_DIR="${ANALYTICSHUB_SKILL_DIR:-}"

if [[ -z "${AH_SKILL_DIR}" ]]; then
  if [[ -f "${WORKSPACE_ROOT}/api-analyticshub/scripts/analyticshub_v1.sh" ]]; then
    AH_SKILL_DIR="${WORKSPACE_ROOT}/api-analyticshub"
  elif [[ -f "${SKILL_ROOT}/../api-analyticshub/scripts/analyticshub_v1.sh" ]]; then
    AH_SKILL_DIR="${SKILL_ROOT}/../api-analyticshub"
  elif [[ -f "${HOME}/.gemini/skills/api-analyticshub/scripts/analyticshub_v1.sh" ]]; then
    AH_SKILL_DIR="${HOME}/.gemini/skills/api-analyticshub"
  elif [[ -f "${HOME}/.antigravity/skills/api-analyticshub/scripts/analyticshub_v1.sh" ]]; then
    AH_SKILL_DIR="${HOME}/.antigravity/skills/api-analyticshub"
  else
    echo "❌ Error: api-analyticshub skill client not found. Please set ANALYTICSHUB_SKILL_DIR." >&2
    exit 1
  fi
fi

# 2. Source Analytics Hub API client functions
# shellcheck source=/dev/null
source "${AH_SKILL_DIR}/scripts/analyticshub_v1.sh"
# shellcheck source=/dev/null
source "${AH_SKILL_DIR}/scripts/list_all_pages.sh"

echo "🔍 Querying Analytics Hub Data Exchange: projects/${PROJECT_ID}/locations/${LOCATION}/dataExchanges/${EXCHANGE_ID}..." >&2

# 3. Retrieve listings payload
RAW_RESPONSE=$(analyticshub_projects_locations_dataExchanges_listings_list "${PROJECT_ID}" "${LOCATION}" "${EXCHANGE_ID}")

if [[ "${OUTPUT_FORMAT}" == "--json" || "${OUTPUT_FORMAT}" == "-j" ]]; then
  echo "${RAW_RESPONSE}"
  exit 0
fi

# 4. Check if listings exist
count=$(echo "${RAW_RESPONSE}" | jq '.listings // [] | length')
if [[ "${count}" -eq 0 ]]; then
  echo "No active listings found in exchange."
  exit 0
fi

# 5. Format and display tabular overview (Pure Bash + JQ)
echo ""
echo "========================================================================================================="
echo "                    ROADS MANAGEMENT INSIGHTS (RMI) SAMPLE DATASETS CATALOG                             "
echo "========================================================================================================="
echo "Exchange URL: https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/${PROJECT_ID}/locations/${LOCATION}/dataExchanges/${EXCHANGE_ID}"
echo ""
echo "${count} sample dataset(s) available on Analytics Hub:"
echo ""

printf "%-3s | %-20s | %-32s | %-8s\n" "#" "Listing ID" "Display Name" "State"
printf -- "----+----------------------+----------------------------------+---------\n"

idx=1
while IFS=$'\t' read -r lid name state desc contact req_access rs_text; do
  printf "%-3s | %-20s | %-32s | %-8s\n" "${idx}" "${lid}" "${name}" "${state}"
  idx=$((idx + 1))
done < <(echo "${RAW_RESPONSE}" | jq -r '
  .listings[] |
  [
    (.name | split("/")[-1]),
    .displayName,
    .state,
    (.description // "N/A"),
    (.primaryContact // "N/A"),
    (.requestAccess // "N/A"),
    (if ((.documentation // "") | test("## Route setting")) then
      ((.documentation | capture("## Route setting(?<rs>[\\s\\S]*?)(?:## Key Data Points|$)").rs // "N/A")
      | gsub("\\n+"; " ") | gsub("\\s+"; " ") | sub("^\\s*"; ""))
    else "N/A" end)
  ] | @tsv
')

echo ""
echo "========================================================================================================="
echo "Detailed Listing Metadata & Route Setting Criteria:"
echo "========================================================================================================="

idx=1
while IFS=$'\t' read -r lid name state desc contact req_access rs_text; do
  echo ""
  echo "[${idx}] ${name} (${lid})"
  echo "    • Description:     ${desc}"
  echo "    • Contact / Access: ${contact} / ${req_access}"
  echo "    • Route Criteria:  ${rs_text}"
  idx=$((idx + 1))
done < <(echo "${RAW_RESPONSE}" | jq -r '
  .listings[] |
  [
    (.name | split("/")[-1]),
    .displayName,
    .state,
    (.description // "N/A"),
    (.primaryContact // "N/A"),
    (.requestAccess // "N/A"),
    (if ((.documentation // "") | test("## Route setting")) then
      ((.documentation | capture("## Route setting(?<rs>[\\s\\S]*?)(?:## Key Data Points|$)").rs // "N/A")
      | gsub("\\n+"; " ") | gsub("\\s+"; " ") | sub("^\\s*"; ""))
    else "N/A" end)
  ] | @tsv
')
