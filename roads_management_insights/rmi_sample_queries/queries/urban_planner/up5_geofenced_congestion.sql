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
-- Business Question: Within a specific downtown polygon, which routes are currently seeing travel times more than 50% above their static baseline?
-- Use Case: Enables targeted traffic management and demand-response strategies within high-density zones or during special events.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Spatial Geofencing
  This query uses a DECLARE statement for the downtown polygon to ensure 
  BigQuery treats the study area as a constant, enabling efficient spatial 
  indexing during the ST_INTERSECTS join. It identifies routes that are 
  physically impacted by a specific urban zone.
*/

-- Study Area: Downtown Boston Geofence
DECLARE downtown_zone GEOGRAPHY DEFAULT ST_GEOGFROMTEXT('POLYGON((-71.066 42.358, -71.052 42.358, -71.052 42.348, -71.066 42.348, -71.066 42.358))');

WITH intersecting_routes AS (
  SELECT
    h.selected_route_id,
    h.display_name,
    SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) AS delay_ratio
  FROM `boston_oct_2025_sample_data.historical_travel_time` h
  WHERE ST_INTERSECTS(h.route_geometry, downtown_zone)
    AND h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
    -- Quality filter: Exclude non-continuous geometries
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
)
SELECT
  selected_route_id,
  display_name,
  ROUND(AVG(delay_ratio), 3) AS avg_delay_ratio,
  COUNT(*) as sample_count
FROM intersecting_routes
GROUP BY 1, 2
-- Threshold: Filter for routes that are at least 1.5x slower than free-flow
HAVING avg_delay_ratio > 1.5
ORDER BY avg_delay_ratio DESC;
