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

-- Data Scientist Query 4: Route Integrity Audit (Time-Windowed)
-- Business Question: When and for how long did specific routes experience extreme geometry deviations?
-- Use Case: Identifies persistent "integrity incidents" rather than transient noise. By grouping consecutive failed records into windows, engineers can correlate failures with specific infrastructure changes, GPS outages, or registration updates.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  DEFINITION: Route Integrity
  In RMI, 'Route Integrity' measures the spatial consistency between a route's 
  registered definition and its actual data collection performance.
  
  - The Baseline: 'intended_length' (meters) provided as a custom attribute during registration.
  - The Signal: 'actual_length' (meters) calculated from the captured ST_LineString.
  - High Integrity: A ratio near 1.0 (actual length matches intended definition).
  - Low Integrity: Significant deviations (> 10%) indicate detours, missing road 
    segments, or incorrect metadata registration.
*/

/*
  ANALYTICAL PATTERN: Islands and Gaps
  This query groups consecutive records that exceed a 10% length deviation threshold 
  into discrete failure windows.
*/

WITH base_comparison AS (
  SELECT
    h.selected_route_id,
    h.display_name,
    h.record_time,
    ST_LENGTH(h.route_geometry) AS actual_length,
    CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64) AS intended_length
  FROM `boston_oct_2025_sample_data.historical_travel_time` h
  JOIN `boston_oct_2025_sample_data.routes_status` s USING (selected_route_id)
  WHERE s.status = 'STATUS_RUNNING'
    AND h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
    -- Quality filter: Exclude non-continuous geometries
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
),
outlier_flagging AS (
  SELECT
    *,
    -- Flag if deviation exceeds 10% (actual / intended)
    IF(intended_length IS NOT NULL AND (SAFE_DIVIDE(actual_length, intended_length) > 1.1 OR SAFE_DIVIDE(actual_length, intended_length) < 0.9), 1, 0) as is_outlier
  FROM base_comparison
),
streak_identification AS (
  SELECT
    *,
    -- A new streak starts if this is an outlier and the previous record (by time) wasn't
    IF(is_outlier = 1 AND LAG(is_outlier) OVER (PARTITION BY selected_route_id ORDER BY record_time) = 0, 1, 
       IF(is_outlier = 1 AND LAG(is_outlier) OVER (PARTITION BY selected_route_id ORDER BY record_time) IS NULL, 1, 0)) as is_streak_start
  FROM outlier_flagging
),
streak_grouping AS (
  SELECT
    *,
    -- Cumulative sum of starts creates a unique ID for each failure window
    SUM(is_streak_start) OVER (PARTITION BY selected_route_id ORDER BY record_time) as streak_id
  FROM streak_identification
  WHERE is_outlier = 1
)
SELECT
  selected_route_id,
  display_name,
  MIN(record_time) as failure_start,
  MAX(record_time) as failure_end,
  COUNT(*) as consecutive_records,
  -- Average ratio across the window: Severity of the discrepancy
  ROUND(AVG(SAFE_DIVIDE(actual_length, intended_length)), 2) as avg_deviation_ratio,
  -- Identify if the deviation is an over-count (likely detour) or under-count (missing segments)
  IF(AVG(actual_length) > AVG(intended_length), 'OVER_COUNT', 'UNDER_COUNT') as failure_type
FROM streak_grouping
GROUP BY selected_route_id, display_name, streak_id
-- Focus on persistent issues
HAVING consecutive_records >= 1
ORDER BY failure_start DESC, avg_deviation_ratio DESC
LIMIT 50;
