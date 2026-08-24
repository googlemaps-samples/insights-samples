#!/bin/bash
# strategy_match_and_split_by_road.sh (GA VERSION)
#
# RMI Route Setting Strategy: MATCH_AND_SPLIT_BY_ROAD
# Uses Roads API v1 (snapToRoads) to divide the route into Google road segments (placeId clusters).
# Places intermediate waypoints at the middle vertex of each traversed road segment (avoiding redundant
# waypoints on the same segment), with adaptive decimation to 25 waypoints if segment count > 25.
#
# Pure bash + jq implementation: Zero Node.js or Python runtime dependencies.

set -euo pipefail

# Configuration
PROJECT_ID="${GAC_PROJECT_ID:-your-project-id}"
SKILLS_DIR="$(dirname "$(dirname "$(dirname "${BASH_SOURCE[0]}")")")"
ROADS_SCRIPTS="${SKILLS_DIR}/api-roads-v1/scripts"
ROUTES_SCRIPTS="${SKILLS_DIR}/api-routes/scripts"

usage() {
  echo "Usage: $0 <origin_lat,lng> <dest_lat,lng> <output_prefix>"
  echo "Example: $0 '40.7573,-73.9859' '40.7682,-73.8635' 'manhattan_lga_segments'"
  exit 1
}

if [[ $# -lt 3 ]]; then usage; fi

ORIGIN="$1"; DEST="$2"; PREFIX="$3"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
CREATOR=$(gcloud config get-value account 2>/dev/null || echo "unknown")

# 1. Compute Base Route (Routes API v2 - GA)
echo "1/3 Computing Base Route via Routes API v2 (HIGH_QUALITY polyline)..." >&2
source "${ROUTES_SCRIPTS}/routes_v2.sh"
source "${ROUTES_SCRIPTS}/routes_v2_helpers.sh"

olat="${ORIGIN%%,*}"; olng="${ORIGIN#*,}"; dlat="${DEST%%,*}"; dlng="${DEST#*,}"
payload=$(jq -n --arg olat "$olat" --arg olng "$olng" --arg dlat "$dlat" --arg dlng "$dlng" \
  '{origin:{location:{latLng:{latitude:($olat|tonumber),longitude:($olng|tonumber)}}},destination:{location:{latLng:{latitude:($dlat|tonumber),longitude:($dlng|tonumber)}}},travelMode:"DRIVE",routingPreference:"TRAFFIC_UNAWARE",polylineQuality:"HIGH_QUALITY",polylineEncoding:"GEO_JSON_LINESTRING"}')
route_json=$(routes_computeRoutes "$payload" "routes.duration,routes.distanceMeters,routes.polyline.geoJsonLinestring" "$PROJECT_ID")
dist=$(echo "$route_json" | jq -r '.routes[0].distanceMeters // "0"')
dur=$(echo "$route_json" | jq -r '.routes[0].duration // "0s"')
route_geojson=$(echo "$route_json" | jq -c '.routes[0].polyline.geoJsonLinestring')

# 2. Road Snapping & Segment Clustering (Roads API v1 - GA)
echo "2/3 Snapping coordinates via Roads API v1 (snapToRoads)..." >&2
source "${ROADS_SCRIPTS}/roads_v1.sh"
points_param=$(echo "$route_geojson" | jq -r '.coordinates | map(.[1]|tostring + "," + (.[0]|tostring)) | join("|")')
snapped_resp=$(roads_v1_snapToRoads "$points_param" "true" "$PROJECT_ID")

# 3. Extract Road Segment Midpoint Vertices & Assemble SelectedRoute
echo "3/3 Extracting segment middle vertices and constructing SelectedRoute..." >&2
processed=$(echo "$snapped_resp" | jq -c '
  # Group contiguous points by unique placeId
  (reduce .snappedPoints[] as $pt (
    [];
    if length == 0 or .[-1].placeId != $pt.placeId then
      . + [{ placeId: $pt.placeId, points: [$pt.location] }]
    else
      .[-1].points += [$pt.location]
    end
  )) as $segments |

  ($segments | length) as $total_segs |

  # Extract midpoint vertex for each internal segment
  (if $total_segs <= 2 then
    []
  else
    $segments[1:-1] | map(.points[(.points | length / 2 | floor)])
  end) as $midpoints |

  ($midpoints | length) as $M |

  # Cap at 25 waypoints only if segment count exceeds quota
  (if $M <= 25 then
    $midpoints
  else
    [range(1; 26) | $midpoints[((. * ($M - 1) / 26) | floor)]]
  end) as $intermediates |

  {
    total_segments: $total_segs,
    intermediates: $intermediates
  }
')

intermediates=$(echo "$processed" | jq -c '.intermediates')
total_segments=$(echo "$processed" | jq -r '.total_segments')

jq -n \
  --arg olat "$olat" --arg olng "$olng" \
  --arg dlat "$dlat" --arg dlng "$dlng" \
  --argjson ints "$intermediates" \
  --arg dist "$dist" --arg dur "$dur" \
  --arg prefix "$PREFIX" \
  --arg ts "$TIMESTAMP" \
  --arg creator "$CREATOR" \
  --arg total_segs "$total_segments" \
  '{
    displayName: ($prefix + " Road-Segment Guided Route"),
    dynamicRoute: {
      origin: { latitude: ($olat|tonumber), longitude: ($olng|tonumber) },
      destination: { latitude: ($dlat|tonumber), longitude: ($dlng|tonumber) },
      intermediates: $ints
    },
    routeAttributes: {
      strategy: "MATCH_AND_SPLIT_BY_ROAD",
      creator: $creator,
      create_time: $ts,
      origin: ($olat + "," + $olng),
      destination: ($dlat + "," + $dlng),
      route_length_meters: ($dist | tostring),
      base_duration: ($dur | tostring),
      total_road_segments: ($total_segs | tostring),
      intermediate_count: ($ints | length | tostring),
      logic: "road segment middle vertices"
    }
  }' > "${PREFIX}_selected_route.json"

echo "Pipeline complete. Output: ${PREFIX}_selected_route.json"
