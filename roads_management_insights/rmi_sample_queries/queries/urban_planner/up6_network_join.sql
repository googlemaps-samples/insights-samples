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

-- Urban Planner Query 6: Major Highway Performance (Network-Join)
-- Business Question: Which routes are using major freeways, and what is their specific delay?
-- Use Case: Demonstrates the power of joining abstract RMI corridors with physical road network data. By identifying routes that traverse high-priority segments (e.g., Controlled Access highways), planners can attribute systemic delays to specific infrastructure classes.
-- Product Stage: Preview
-- Estimated Bytes Processed: ~160 MB

/*
  ANALYTICAL PATTERN: Network Spatial Join
  This query performs a spatial join between the user-defined SelectedRoute 
  abstract corridors and a physical road network dataset. It aggregates 
  delay across all road segments that intersect with high-priority infrastructure.
*/

WITH highway_segments AS (
  SELECT 
    name as road_id,
    -- Extract the primary preferred display name from the physical segment
    (SELECT text FROM UNNEST(display_names) WHERE is_preferred LIMIT 1) as road_name,
    geometry as coordinates
  FROM `moritani-roads.boston_sample_supplemental.roads_enriched_20260301`
  -- Filter for the most critical infrastructure priority class
  WHERE priority = 'ROAD_PRIORITY_CONTROLLED_ACCESS'
),
rmi_highway_join AS (
  SELECT 
    h.selected_route_id,
    h.display_name as route_name,
    hs.road_name,
    -- Calculate delay ratio for the intersecting records
    SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) as delay_ratio
  FROM `boston_oct_2025_sample_data.historical_travel_time` h
  JOIN highway_segments hs ON ST_INTERSECTS(h.route_geometry, hs.coordinates)
  WHERE h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
)
SELECT 
  route_name,
  -- Aggregating all distinct physical highways traversed by this abstract route
  ARRAY_TO_STRING(ARRAY_AGG(DISTINCT road_name), ', ') as highways_traversed,
  ROUND(AVG(delay_ratio), 2) as avg_delay_ratio
FROM rmi_highway_join
GROUP BY 1
ORDER BY avg_delay_ratio DESC;
