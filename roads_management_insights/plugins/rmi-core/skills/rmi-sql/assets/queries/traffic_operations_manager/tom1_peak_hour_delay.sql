-- Job ID: rmisamplesql_tom1_YYYYMMDDHHMMSS
-- Persona: traffic_operations_manager
-- Purpose: RMI BigQuery Analytical Query (tom1)

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

-- Traffic Operations Manager Query 1: Peak Hour Delay Analysis
-- Business Question: What is the average travel time delay during the morning peak (7-9 AM) for the top 10 most congested routes, explicitly accounting for road closures?
-- Use Case: Identifies critical morning commute bottlenecks and closure incidents to inform operational decisions or public messaging.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  ANALYTICAL PATTERN: Temporal Filtering & Closure Safety
  This query uses EXTRACT(HOUR...) on a converted DATETIME to focus on local 
  peak windows. It joins routes_status on s.status = 'STATUS_RUNNING' and
  explicitly tracks has_road_closure rather than silently dropping closures
  with a naive duration_in_seconds IS NOT NULL filter.
*/

WITH peak_hour_data AS (
  SELECT
    h.selected_route_id,
    h.display_name,
    h.has_road_closure,
    -- delay_ratio > 1.0 indicates travel time is slower than free-flow (static)
    SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) AS delay_ratio
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  WHERE h.record_time BETWEEN '2026-07-01' AND '2026-07-30'
    -- STATUS_RUNNING ensures we only analyze routes that are currently being monitored
    AND s.status = 'STATUS_RUNNING'
    -- AM Peak Window: 7:00 AM to 8:59 AM Local Time
    AND EXTRACT(HOUR FROM DATETIME(h.record_time, 'America/New_York')) BETWEEN 7 AND 8
    -- Geometry Integrity: Only process continuous, healthy paths (ST_LineString)
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
    AND (h.static_duration_in_seconds > 0 OR h.has_road_closure IS TRUE)
)
SELECT
  display_name,
  -- Compute average delay ratio on passable periods
  ROUND(AVG(CASE WHEN COALESCE(has_road_closure, FALSE) IS FALSE THEN delay_ratio END), 3) AS avg_delay_ratio,
  COUNT(*) AS total_observations,
  -- Explicitly audit road closure incidents rather than silently dropping them
  COUNTIF(has_road_closure IS TRUE) AS road_closure_incidents,
  COUNTIF(COALESCE(has_road_closure, FALSE) IS FALSE AND delay_ratio IS NOT NULL) AS valid_delay_samples
FROM peak_hour_data
GROUP BY 1
-- Threshold: Filter for routes that are slower than free-flow or experienced road closures
HAVING avg_delay_ratio > 1.0 OR road_closure_incidents > 0
ORDER BY road_closure_incidents DESC, avg_delay_ratio DESC
LIMIT 10;
