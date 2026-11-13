-- Job ID: rmisamplesql_rmip2_YYYYMMDDHHMMSS
-- Persona: rmi_planner
-- Purpose: RMI BigQuery Analytical Query (rmip2)

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

-- RMI Seller Query 2: Customer ROI (Value at Risk with Closure Defense)
-- Business Question: How much total time is lost to congestion and road closures across different customer service tiers?
-- Use Case: Translates raw traffic data into "Business Value" by quantifying potential time savings and closure disruptions for priority routes, justifying monitoring ROI.
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB (Standard SQL on RMI Tables)

SELECT
  COALESCE(JSON_VALUE(s.route_attributes, '$.tier'), JSON_VALUE(s.route_attributes, '$.priority'), 'STANDARD_TIER') as service_tier,
  -- Aggregate total lost time (Actual - Free-flow) converted to hours during passable periods
  ROUND(SUM(CASE WHEN COALESCE(h.has_road_closure, FALSE) IS FALSE AND (h.duration_in_seconds - h.static_duration_in_seconds) > 0 THEN (h.duration_in_seconds - h.static_duration_in_seconds) ELSE 0 END) / 3600, 1) as total_delay_hours,
  COUNT(DISTINCT h.selected_route_id) as monitored_routes,
  -- Track full road closure events impacting customer SLAs
  COUNTIF(h.has_road_closure IS TRUE) as road_closure_incidents,
  -- Average performance multiplier during passable operations
  ROUND(AVG(CASE WHEN COALESCE(h.has_road_closure, FALSE) IS FALSE THEN SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) END), 2) as avg_delay_index
FROM `LINKED_DATASET_NAME.historical_travel_time` h
JOIN `LINKED_DATASET_NAME.routes_status` s ON h.selected_route_id = s.selected_route_id
WHERE ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
  AND h.record_time BETWEEN '2026-07-01' AND '2026-07-30'
  AND s.status = 'STATUS_RUNNING'
  AND (h.static_duration_in_seconds > 0 OR h.has_road_closure IS TRUE)
GROUP BY 1
HAVING service_tier IS NOT NULL
ORDER BY total_delay_hours DESC;
