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

-- Data Scientist Query 5: Persistent Unreliability Audit (Time-Windowed)
-- Business Question: When and for how long did specific routes experience persistent travel time spikes?
-- Use Case: Identifies chronic congestion incidents rather than transient variance. By grouping consecutive "slow" records into windows, operators can distinguish between random noise and actionable infrastructure failures or major events.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  DEFINITION: Route Reliability vs. Route Integrity
  - Route Integrity (DS4): Measures spatial consistency (Actual Geometry vs. Registered Definition).
  - Route Reliability (DS5): Measures temporal performance (Actual Travel Time vs. Free-flow Baseline).
  
  High Reliability means a route's travel time is stable and near its ideal baseline. 
  Low Reliability (this query) indicates persistent periods of 'excess delay' 
  where actual travel times significantly exceed free-flow estimates.
*/

/*
  ANALYTICAL PATTERN: Reliability Gaps (Islands and Gaps)
  1. Calculate a historical baseline per route.
  2. Flag records where travel time exceeds a 'significant delay' threshold (e.g., 1.5x baseline).
  3. Group consecutive flags into discrete failure windows (streaks).
*/

WITH quality_filtered_history AS (
  -- Standard quality filtering to ensure we analyze healthy geometries
  SELECT
    h.selected_route_id,
    h.display_name,
    h.record_time,
    h.duration_in_seconds,
    h.static_duration_in_seconds
  FROM `boston_oct_2025_sample_data.historical_travel_time` h
  JOIN `boston_oct_2025_sample_data.routes_status` s USING(selected_route_id)
  WHERE h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
    AND SAFE_DIVIDE(ABS(ST_LENGTH(h.route_geometry) - CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64)), CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64)) < 0.05
),
incident_flagging AS (
  SELECT
    *,
    -- Threshold: Travel time is more than 50% above the static (free-flow) baseline
    IF(SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) > 1.5, 1, 0) as is_incident
  FROM quality_filtered_history
),
streak_identification AS (
  SELECT
    *,
    -- Identify the start of a new consecutive incident window
    IF(is_incident = 1 AND LAG(is_incident) OVER (PARTITION BY selected_route_id ORDER BY record_time) = 0, 1, 
       IF(is_incident = 1 AND LAG(is_incident) OVER (PARTITION BY selected_route_id ORDER BY record_time) IS NULL, 1, 0)) as is_streak_start
  FROM incident_flagging
),
streak_grouping AS (
  SELECT
    *,
    -- Cumulative sum of starts creates a unique ID for each incident window
    SUM(is_streak_start) OVER (PARTITION BY selected_route_id ORDER BY record_time) as streak_id
  FROM streak_identification
  WHERE is_incident = 1
)
SELECT
  selected_route_id,
  display_name,
  MIN(record_time) as incident_start,
  MAX(record_time) as incident_end,
  -- Total consecutive records in this incident window
  COUNT(*) as consecutive_samples,
  -- Average severity of the delay during this window
  ROUND(AVG(SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)), 2) as avg_delay_ratio
FROM streak_grouping
GROUP BY selected_route_id, display_name, streak_id
-- Focus on persistent unreliability (lasting at least 3 samples)
HAVING consecutive_samples >= 3
ORDER BY avg_delay_ratio DESC, incident_start DESC
LIMIT 50;
