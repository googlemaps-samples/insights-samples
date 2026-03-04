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

-- Traffic Operations Manager Query 5: Significant Event Detection
-- Business Question: Which routes experienced a travel time more than double their static baseline in the last 24 hours?
-- Use Case: Automates the detection of extreme traffic events (accidents, severe weather, gridlock) that require immediate operational intervention.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  ANALYTICAL PATTERN: Threshold-Based Alerting
  This query identifies major traffic incidents by flagging records where the 
  actual travel time is at least 2x the free-flow baseline (static_duration). 
  It applies quality filters to ensure alerts are only triggered for single, 
  continuous paths.
*/

SELECT
  h.display_name,
  h.selected_route_id,
  h.record_time,
  h.duration_in_seconds,
  h.static_duration_in_seconds,
  -- Delay ratio > 2.0 means travel time is 2x slower than ideal
  ROUND(SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds), 2) AS delay_ratio
FROM `boston_oct_2025_sample_data.historical_travel_time` AS h
JOIN `boston_oct_2025_sample_data.routes_status` AS s USING(selected_route_id)
-- Filter for the final day of the sample dataset
WHERE h.record_time BETWEEN '2025-10-30' AND '2025-11-01'
  -- Focus on active monitoring fleet
  AND s.status = 'STATUS_RUNNING'
  -- Filter for "Significant" events
  AND SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) > 2.0
  -- Quality filter: Exclude non-continuous geometries
  AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
ORDER BY delay_ratio DESC;
