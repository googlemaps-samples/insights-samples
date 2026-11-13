-- Job ID: rmisamplesql_tom5_YYYYMMDDHHMMSS
-- Persona: traffic_operations_manager
-- Purpose: RMI BigQuery Analytical Query (tom5)

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

-- Traffic Operations Manager Query 5: Significant Event Detection (Closures & Severe Congestion)
-- Business Question: Which routes experienced a significant event (full road closure OR travel time more than double static baseline) in the last 24-72 hours?
-- Use Case: Automates the detection of extreme traffic events (accidents, road closures, severe gridlock) requiring immediate operational intervention.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  ANALYTICAL PATTERN: Threshold-Based Alerting with Road Closure Branch
  This query identifies major disruptions by flagging:
  1. Full road closures (has_road_closure = true, duration_in_seconds IS NULL).
  2. Severe congestion events where actual travel time is at least 2x the free-flow baseline.
*/

SELECT
  h.display_name,
  h.selected_route_id,
  h.record_time,
  h.has_road_closure,
  h.duration_in_seconds,
  h.static_duration_in_seconds,
  -- Classify the event type
  CASE
    WHEN h.has_road_closure IS TRUE THEN 'FULL_ROAD_CLOSURE'
    WHEN SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) > 2.0 THEN 'SEVERE_CONGESTION'
    ELSE 'NOMINAL'
  END AS event_type,
  -- Delay ratio > 2.0 means travel time is 2x slower than ideal (NULL for full closures)
  ROUND(SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds), 2) AS delay_ratio
FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
WHERE h.record_time BETWEEN '2026-07-27' AND '2026-07-30'
  AND s.status = 'STATUS_RUNNING'
  -- Trigger alert if road is completely closed OR travel time exceeds 2x baseline
  AND (h.has_road_closure IS TRUE OR SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) > 2.0)
  -- Quality filter: Exclude non-continuous geometries
  AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
  AND (h.static_duration_in_seconds > 0 OR h.has_road_closure IS TRUE)
ORDER BY h.has_road_closure DESC, delay_ratio DESC;
