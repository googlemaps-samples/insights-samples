#!/bin/bash
# strategy_simple_origin_destination.sh
#
# RMI Route Setting Strategy: SIMPLE_ORIGIN_DESTINATION
#
# ORCHESTRATION LOGIC:
# 1. BASELINE METRICS: Calls Routes API v2 (ComputeRoutes) to capture current travel duration and distance.
#    Note: Uses TRAFFIC_AWARE_OPTIMAL to get current context for metadata enrichment.
# 2. REGISTRATION: Constructs a dynamic SelectedRoute JSON object (origin/destination only).
#    This allows the RMI engine to monitor path and travel time variations over time.

set -euo pipefail

# Configuration
PROJECT_ID="${GAC_PROJECT_ID:-your-project-id}"
SKILLS_DIR="$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")"
ROUTES_SCRIPTS="${SKILLS_DIR}/api-routes/scripts"

usage() {
  echo "Usage: $0 <origin_lat,lng> <dest_lat,lng> <output_prefix>"
  exit 1
}

if [[ $# -lt 3 ]]; then usage; fi

ORIGIN="$1"; DEST="$2"; PREFIX="$3"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
CREATOR=$(gcloud config get-value account 2>/dev/null || echo "unknown")

# 1. Compute Baseline Route (Routes API v2)
echo "1/2 Computing Baseline Route via Routes API v2..." >&2
source "${ROUTES_SCRIPTS}/routes_v2.sh"
source "${ROUTES_SCRIPTS}/routes_v2_helpers.sh"
olat="${ORIGIN%%,*}"; olng="${ORIGIN#*,}"; dlat="${DEST%%,*}"; dlng="${DEST#*,}"
payload=$(jq -n --argjson olat "$olat" --argjson olng "$olng" --arg dlat "$dlat" --arg dlng "$dlng" '{origin:{location:{latLng:{latitude:($olat|tonumber),longitude:($olng|tonumber)}}},destination:{location:{latLng:{latitude:($dlat|tonumber),longitude:($dlng|tonumber)}}},travelMode:"DRIVE",routingPreference:"TRAFFIC_AWARE_OPTIMAL"}')
route_json=$(routes_computeRoutes "$payload" "routes.duration,routes.distanceMeters" "$PROJECT_ID")
dist=$(echo "$route_json" | jq -r '.routes[0].distanceMeters')
dur=$(echo "$route_json" | jq -r '.routes[0].duration')

# 2. Construct SelectedRoute for Registration
echo "2/2 Constructing Dynamic SelectedRoute..." >&2
jq -n \
  --arg olat "$olat" --arg olng "$olng" \
  --arg dlat "$dlat" --arg dlng "$dlng" \
  --arg dist "$dist" --arg dur "$dur" \
  --arg prefix "$PREFIX" \
  --arg ts "$TIMESTAMP" \
  --arg creator "$CREATOR" \
  '{
    displayName: ($prefix + " Dynamic Route"),
    dynamicRoute: {
      origin: { latitude: ($olat|tonumber), longitude: ($olng|tonumber) },
      destination: { latitude: ($dlat|tonumber), longitude: ($dlng|tonumber) }
    },
    routeAttributes: {
      strategy: "SIMPLE_ORIGIN_DESTINATION",
      useragent: "rmi-routesetting-skill",
      creator: $creator,
      creationTimestamp: $ts,
      sourceOrigin: ($olat + "," + $olng),
      sourceDestination: ($dlat + "," + $dlng),
      baseDistanceMeters: $dist,
      baseDuration: $dur,
      monitoringType: "DYNAMIC_PATH",
      purpose: "Traffic variation analysis"
    }
  }' > "${PREFIX}_selected_route.json"

echo "Pipeline complete. Output: ${PREFIX}_selected_route.json"
