#!/bin/bash
# strategy_match_and_split_by_road.sh (GA VERSION)
#
# RMI Route Setting Strategy: MATCH_AND_SPLIT_BY_ROAD (Basic)
#
# ORCHESTRATION LOGIC:
# 1. PATHFINDING: Calls Routes API v2 (ComputeRoutes) for a stable traffic-unaware baseline.
# 2. LEGACY SNAPPING: Calls Legacy Roads API v1 (snapToRoads) to align coordinates with the road network.
# 3. SEGMENTATION: Splits the path based on unique 'placeId' returned by the legacy API.
# 4. REGISTRATION: Creates individual SelectedRoute objects for each identified road section.

set -euo pipefail

# Configuration
PROJECT_ID="${GAC_PROJECT_ID:-your-project-id}"
SKILLS_DIR="$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")"
ROADS_SCRIPTS="${SKILLS_DIR}/api-roads/scripts"
ROUTES_SCRIPTS="${SKILLS_DIR}/api-routes/scripts"
VIZ_SCRIPTS="${SKILLS_DIR}/geospatial-viz/scripts"
VIZ_CLI="${VIZ_SCRIPTS}/viz_cli.sh"

usage() {
  echo "Usage: $0 <origin_lat,lng> <dest_lat,lng> <output_prefix>"
  exit 1
}

if [[ $# -lt 3 ]]; then usage; fi

ORIGIN="$1"; DEST="$2"; PREFIX="$3"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
CREATOR=$(gcloud config get-value account 2>/dev/null || echo "unknown")

# 1. Compute Base Route (Routes API v2 - GA)
echo "1/3 Computing Base Route..." >&2
source "${ROUTES_SCRIPTS}/routes_v2.sh"
source "${ROUTES_SCRIPTS}/routes_v2_helpers.sh"
olat="${ORIGIN%%,*}"; olng="${ORIGIN#*,}"; dlat="${DEST%%,*}"; dlng="${DEST#*,}"
payload=$(jq -n --arg lat "$olat" --arg lng "$olng" --arg dlat "$dlat" --arg dlng "$dlng" '{origin:{location:{latLng:{latitude:($lat|tonumber),longitude:($lng|tonumber)}}},destination:{location:{latLng:{latitude:($dlat|tonumber),longitude:($dlng|tonumber)}}},travelMode:"DRIVE",routingPreference:"TRAFFIC_UNAWARE",polylineQuality:"OVERVIEW",polylineEncoding:"GEO_JSON_LINESTRING"}')
route_geojson=$(routes_computeRoutes "$payload" "routes.polyline.geoJsonLinestring" "$PROJECT_ID" | jq -c '.routes[0].polyline.geoJsonLinestring')

# 2. Legacy Snapping (Roads API v1 - GA)
echo "2/3 Snapping path to legacy road network (snapToRoads)..." >&2
source "${ROADS_SCRIPTS}/roads_v1.sh"
# Convert GeoJSON to points param
points_param=$(echo "$route_geojson" | jq -r '.coordinates | map(.[1]|tostring + "," + (.[0]|tostring)) | join("|")')
snapped_resp=$(roads_v1_snapToRoads "$points_param" "true" "$PROJECT_ID")

# 3. Create SelectedRoute Objects (Split by unique placeId)
echo "3/3 Finalizing RMI Mapping..." >&2
# Simple implementation: Output SelectedRoutes for unique placeIds found
echo "$snapped_resp" | jq -c --arg prefix "$PREFIX" --arg creator "$CREATOR" --arg ts "$TIMESTAMP" \
  '.snappedPoints | group_by(.placeId)[] | {
    displayName: ($prefix + " Segment " + .[0].placeId),
    dynamicRoute: {
      origin: { latitude: .[0].location.latitude, longitude: .[0].location.longitude },
      destination: { latitude: .[-1].location.latitude, longitude: .[-1].location.longitude }
    },
    routeAttributes: {
      strategy: "MATCH_AND_SPLIT_BY_ROAD",
      version: "GA_LEGACY",
      placeId: .[0].placeId,
      creator: $creator,
      creationTimestamp: $ts,
      class: "selected_route"
    }
  }' > "${PREFIX}_selected_routes.jsonl"

echo "Pipeline complete. Output: ${PREFIX}_selected_routes.jsonl"
