#!/bin/bash
set -euo pipefail

# ==============================================================================
# list_sample_datasets.sh
# Retrieves and formats all available RMI sample datasets published on Analytics Hub.
# Leverages the api-analyticshub client.
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

# 4. Format and display tabular overview
echo ""
echo "========================================================================================================="
echo "                    ROADS MANAGEMENT INSIGHTS (RMI) SAMPLE DATASETS CATALOG                             "
echo "========================================================================================================="
echo "Exchange URL: https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/${PROJECT_ID}/locations/${LOCATION}/dataExchanges/${EXCHANGE_ID}"
echo ""

python3 -c '
import sys
import json

raw_input = sys.stdin.read()
try:
    data = json.loads(raw_input)
except Exception as e:
    print("Error parsing API response: {}".format(e))
    sys.exit(1)

listings = data.get("listings", [])
if not listings:
    print("No active listings found in exchange.")
    sys.exit(0)

print("{} sample dataset(s) available:\n".format(len(listings)))
header_fmt = "{:<3} | {:<20} | {:<32} | {:<42} | {:<8}"
header = header_fmt.format("#", "Listing ID", "Display Name", "BigQuery Source Dataset", "State")
print(header)
print("-" * len(header))

for idx, l in enumerate(listings, 1):
    lid = l.get("name", "").split("/")[-1]
    name = l.get("displayName", "N/A")
    ds = l.get("bigqueryDataset", {}).get("dataset", "N/A")
    state = l.get("state", "UNKNOWN")
    print(header_fmt.format(idx, lid, name, ds, state))

print("\n" + "=" * 115)
print("Detailed Listing Metadata & Route Setting Criteria:")
print("=" * 115)

for idx, l in enumerate(listings, 1):
    lid = l.get("name", "").split("/")[-1]
    name = l.get("displayName", "N/A")
    ds = l.get("bigqueryDataset", {}).get("dataset", "N/A")
    desc = l.get("description", "").strip()
    contact = l.get("primaryContact", "N/A")
    req_access = l.get("requestAccess", "N/A")
    doc = l.get("documentation", "")
    
    rs_text = "N/A"
    if "## Route setting" in doc:
        start = doc.find("## Route setting")
        end = doc.find("## Key Data Points", start)
        if end != -1:
            raw_rs = doc[start:end].replace("## Route setting", "").strip()
            lines = [line.strip() for line in raw_rs.splitlines() if line.strip()]
            rs_text = " ".join(lines)
        else:
            rs_text = doc[start:start+200].strip()

    print("\n[{}] {} ({})".format(idx, name, lid))
    print("    • BigQuery Source: {}".format(ds))
    print("    • Description:     {}".format(desc))
    print("    • Contact / Access: {} / {}".format(contact, req_access))
    print("    • Route Criteria:  {}".format(rs_text))
' <<< "${RAW_RESPONSE}"
