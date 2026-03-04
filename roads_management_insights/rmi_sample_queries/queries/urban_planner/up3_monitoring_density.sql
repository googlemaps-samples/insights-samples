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

-- Urban Planner Query 3: Traffic Monitoring Density
-- Business Question: Which geographic areas show the highest concentration of RMI route monitoring?
-- Use Case: Helps planners identify "blind spots" in their monitoring network or confirm that critical urban zones are sufficiently covered by RMI probes.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Spatial Grid Aggregation
  This query maps the RMI monitoring footprint by calculating route centroids 
  and grouping them into a ~1.1km grid (3 decimal places). This provides a 
  coarse-grained view of network density without high computational overhead.
*/

WITH route_centroids AS (
  SELECT 
    selected_route_id,
    -- Use the centroid to represent the general location of the route polyline
    ST_CENTROID(route_geometry) as centroid
  FROM `boston_oct_2025_sample_data.historical_travel_time`
  WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
)
SELECT
  -- Grid the coordinates to a precision of ~1.1km
  ROUND(ST_Y(centroid), 3) AS lat_grid,
  ROUND(ST_X(centroid), 3) AS lon_grid,
  -- Count unique route definitions in this grid cell
  COUNT(DISTINCT selected_route_id) AS unique_routes_monitored,
  -- Count total traffic samples captured in this grid cell
  COUNT(*) AS total_samples_collected
FROM route_centroids
GROUP BY 1, 2
ORDER BY unique_routes_monitored DESC
LIMIT 20;
