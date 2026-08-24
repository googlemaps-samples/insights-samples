#!/bin/bash
# strategy_single_route_uniform_intermediates.sh
#
# RMI Route Setting Strategy: SINGLE_ROUTE_UNIFORM_INTERMEDIATES
# Registers an entire corridor as one SelectedRoute with up to 25 authentic existing intermediate waypoints.
#
# Pure bash + jq implementation: Zero Node.js or Python runtime dependencies.

set -euo pipefail

# Configuration
PROJECT_ID="${GAC_PROJECT_ID:-your-project-id}"
SKILLS_DIR="$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")"
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

# 1. Compute Route (Routes API v2 - GA)
echo "1/3 Computing Route via Routes API v2 (HIGH_QUALITY polyline)..." >&2
source "${ROUTES_SCRIPTS}/routes_v2.sh"
source "${ROUTES_SCRIPTS}/routes_v2_helpers.sh"

olat="${ORIGIN%%,*}"
olng="${ORIGIN#*,}"
dlat="${DEST%%,*}"
dlng="${DEST#*,}"

payload=$(jq -n --arg olat "$olat" --arg olng "$olng" --arg dlat "$dlat" --arg dlng "$dlng" \
  '{origin:{location:{latLng:{latitude:($olat|tonumber),longitude:($olng|tonumber)}}},destination:{location:{latLng:{latitude:($dlat|tonumber),longitude:($dlng|tonumber)}}},travelMode:"DRIVE",routingPreference:"TRAFFIC_UNAWARE",polylineQuality:"HIGH_QUALITY",polylineEncoding:"GEO_JSON_LINESTRING"}')
route_json=$(routes_computeRoutes "$payload" "routes.duration,routes.distanceMeters,routes.polyline.geoJsonLinestring" "$PROJECT_ID")

# 2. Select Authentic Existing Intermediates (Pure JQ - Zero Synthetic Points)
echo "2/3 Selecting Authentic Existing Intermediates via pure JQ..." >&2
intermediates=$(echo "$route_json" | jq -c '
  .routes[0] |
  ((.distanceMeters // 0) | tonumber) as $L |
  (.polyline.geoJsonLinestring.coordinates // []) as $coords |
  ($coords | length) as $M |
  if $M <= 2 or $L < 200 then
    []
  else
    ([25, ($L / 200 | floor)] | min) as $N |
    if ($M - 2) <= $N then
      $coords[1:-1] | map({ latitude: .[1], longitude: .[0] })
    else
      [range(1; $N + 1) | ($coords[((. * ($M - 1) / ($N + 1)) | floor)])] |
      map({ latitude: .[1], longitude: .[0] })
    end
  end
')

# 3. Create SelectedRoute Object
echo "3/3 Constructing SelectedRoute JSON..." >&2
dist=$(echo "$route_json" | jq -r '.routes[0].distanceMeters // "0"')
dur=$(echo "$route_json" | jq -r '.routes[0].duration // "0s"')

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
      creator: $creator,
      create_time: $ts,
      origin: ($olat + "," + $olng),
      destination: ($dlat + "," + $dlng),
      route_length_meters: ($dist | tostring),
      base_duration: ($dur | tostring),
      intermediate_count: ($ints | length | tostring),
      logic: "sample route vertices"
    }
  }' > "${PREFIX}_selected_route.json"

echo "Pipeline complete. Output: ${PREFIX}_selected_route.json"
