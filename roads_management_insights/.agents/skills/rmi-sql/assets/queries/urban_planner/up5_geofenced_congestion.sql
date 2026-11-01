-- Job ID: rmisamplesql_up5_YYYYMMDDHHMMSS
-- Persona: urban_planner
-- Purpose: RMI BigQuery Analytical Query (up5)

-- Copyright 2026 Google LLC
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     https://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Urban Planner Query 5: Geofenced Congestion
-- Business Question: Within a specific downtown polygon, which routes are currently seeing travel times more than 50% above their static baseline, and how many closure incidents occurred?
-- Use Case: Enables targeted traffic management and demand-response strategies within high-density zones or during special events.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Spatial Geofencing with Closure Awareness
  This query uses a DECLARE statement for the downtown polygon to ensure 
  BigQuery treats the study area as a constant, enabling efficient spatial 
  indexing during the ST_INTERSECTS join. It joins routes_status on s.status = 'STATUS_RUNNING'
  and tracks road closures rather than dropping them.
*/

-- Study Area: Downtown Boston Geofence
DECLARE downtown_zone GEOGRAPHY DEFAULT ST_GEOGFROMTEXT('POLYGON((-71.066 42.358, -71.052 42.358, -71.052 42.348, -71.066 42.348, -71.066 42.358))');

WITH intersecting_routes AS (
  SELECT
    h.selected_route_id,
    h.display_name,
    h.has_road_closure,
    SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) AS delay_ratio
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  -- S2 SPATIAL INDEXING NOTE:
  -- BigQuery leverages native S2 cell spatial indexing for ST_INTERSECTS, performing
  -- sub-second bounding box pruning across millions of polyline records.
  WHERE ST_INTERSECTS(h.route_geometry, downtown_zone)
    AND s.status = 'STATUS_RUNNING'
    AND h.record_time BETWEEN '2026-07-01' AND '2026-07-30'
    -- Quality filter: Exclude non-continuous geometries
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
    AND (h.static_duration_in_seconds > 0 OR h.has_road_closure IS TRUE)
)
SELECT
  selected_route_id,
  display_name,
  ROUND(AVG(CASE WHEN COALESCE(has_road_closure, FALSE) IS FALSE THEN delay_ratio END), 3) AS avg_delay_ratio,
  COUNTIF(has_road_closure IS TRUE) AS closure_count,
  COUNT(*) as sample_count
FROM intersecting_routes
GROUP BY 1, 2
-- Threshold: Filter for routes that are at least 1.5x slower than free-flow or experienced closures
HAVING avg_delay_ratio > 1.5 OR closure_count > 0
ORDER BY closure_count DESC, avg_delay_ratio DESC;
