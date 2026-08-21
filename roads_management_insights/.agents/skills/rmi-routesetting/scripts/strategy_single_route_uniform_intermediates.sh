#!/bin/bash
# strategy_single_route_uniform_intermediates.sh
#
# RMI Route Setting Strategy: SINGLE_ROUTE_UNIFORM_INTERMEDIATES
# Registers an entire route as one SelectedRoute, with 25 equally spaced intermediates along the polyline.

set -euo pipefail

# Configuration
PROJECT_ID="${GAC_PROJECT_ID:-moritani-roads}"
SKILLS_DIR="$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")"
ROADS_SCRIPTS="${SKILLS_DIR}/api-roadnetwork-preview/scripts"
ROUTES_SCRIPTS="${SKILLS_DIR}/api-routes/scripts"

usage() {
  echo "Usage: $0 <origin_lat,lng> <dest_lat,lng> <output_prefix>"
  echo "Example: $0 '1.2761,103.8000' '1.2837,103.8591' 'mbs_uniform'"
  exit 1
}

if [[ $# -lt 3 ]]; then usage; fi

ORIGIN="$1"
DEST="$2"
PREFIX="$3"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
CREATOR=$(gcloud config get-value account 2>/dev/null || echo "unknown")

# 1. Compute Route
echo "1/4 Computing Route..." >&2
source "${ROUTES_SCRIPTS}/routes_v2.sh"
source "${ROUTES_SCRIPTS}/routes_v2_helpers.sh"

olat="${ORIGIN%%,*}"
olng="${ORIGIN#*,}"
dlat="${DEST%%,*}"
dlng="${DEST#*,}"

payload=$(jq -n --argjson olat "$olat" --argjson olng "$olng" --arg dlat "$dlat" --arg dlng "$dlng" '{origin:{location:{latLng:{latitude:($olat|tonumber),longitude:($olng|tonumber)}}},destination:{location:{latLng:{latitude:($dlat|tonumber),longitude:($dlng|tonumber)}}},travelMode:"DRIVE",routingPreference:"TRAFFIC_UNAWARE",polylineQuality:"OVERVIEW",polylineEncoding:"GEO_JSON_LINESTRING"}')
route_json=$(routes_computeRoutes "$payload" "routes.duration,routes.distanceMeters,routes.polyline.geoJsonLinestring" "$PROJECT_ID")

# 2. Generate Intermediates using the 'along' logic
echo "2/4 Generating Uniform Intermediates..." >&2
intermediates=$(echo "$route_json" | jq -c '.routes[0].polyline.geoJsonLinestring' | node "${ROADS_SCRIPTS}/route_to_intermediates.cjs")

# 3. Create SelectedRoute Object
echo "3/4 Constructing SelectedRoute with context..." >&2
dist=$(echo "$route_json" | jq -r '.routes[0].distanceMeters')
dur=$(echo "$route_json" | jq -r '.routes[0].duration')

jq -n \
  --arg olat "$olat" --arg olng "$olng" \
  --arg dlat "$dlat" --arg dlng "$dlng" \
  --argjson ints "$intermediates" \
  --arg dist "$dist" --arg dur "$dur" \
  --arg prefix "$PREFIX" \
  --arg ts "$TIMESTAMP" \
  --arg creator "$CREATOR" \
  '{
    displayName: ($prefix + " Uniform Route"),
    dynamicRoute: {
      origin: { latitude: ($olat|tonumber), longitude: ($olng|tonumber) },
      destination: { latitude: ($dlat|tonumber), longitude: ($dlng|tonumber) },
      intermediates: $ints
    },
    routeAttributes: {
      strategy: "SINGLE_ROUTE_UNIFORM_INTERMEDIATES",
      useragent: "rmi-routesetting-skill",
      creator: $creator,
      creationTimestamp: $ts,
      sourceOrigin: ($olat + "," + $olng),
      sourceDestination: ($dlat + "," + $dlng),
      totalDistanceMeters: $dist,
      totalDuration: $dur,
      intermediateCount: ($ints | length | tostring),
      samplingLogic: "turf_along_step"
    }
  }' > "${PREFIX}_selected_route.json"

echo "4/4 Pipeline complete. Output: ${PREFIX}_selected_route.json"
