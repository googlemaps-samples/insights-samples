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

-- Data Scientist Query 1: Outlier Detection (Interquartile Range)
-- Business Question: Which travel time records for a specific route are statistical outliers?
-- Use Case: Automatically flags anomalous data points that could indicate extreme traffic events or potential data collection issues.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  QUALITY FILTERS:
  1. continuous_path: Excludes records where the geometry is not a single ST_LineString.
  2. length_integrity: Excludes records where actual physical length deviates by > 5% 
     from the intended 'route_length' attribute.
*/

WITH quality_filtered_history AS (
  SELECT
    h.selected_route_id,
    h.record_time,
    h.duration_in_seconds,
    ST_LENGTH(h.route_geometry) as actual_length,
    CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64) as intended_length
  FROM `boston_oct_2025_sample_data.historical_travel_time` h
  JOIN `boston_oct_2025_sample_data.routes_status` s USING(selected_route_id)
  WHERE h.selected_route_id = 'route-4202493217'
    AND h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
    -- Quality filter: Only process single, continuous paths
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
    -- Quality filter: Length deviation check (< 5%)
    AND SAFE_DIVIDE(ABS(ST_LENGTH(h.route_geometry) - CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64)), CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64)) < 0.05
),
stats AS (
  SELECT
    APPROX_QUANTILES(duration_in_seconds, 100)[OFFSET(25)] AS q1,
    APPROX_QUANTILES(duration_in_seconds, 100)[OFFSET(75)] AS q3
  FROM quality_filtered_history
),
outlier_thresholds AS (
  SELECT
    q1,
    q3,
    (q3 - q1) AS iqr,
    q1 - (1.5 * (q3 - q1)) AS lower_bound,
    q3 + (1.5 * (q3 - q1)) AS upper_bound
  FROM stats
)
SELECT
  h.record_time,
  h.duration_in_seconds,
  t.lower_bound,
  t.upper_bound,
  CASE 
    WHEN h.duration_in_seconds > t.upper_bound THEN 'High_Outlier'
    WHEN h.duration_in_seconds < t.lower_bound THEN 'Low_Outlier'
  END as outlier_type
FROM quality_filtered_history h, outlier_thresholds t
-- Filter for records outside the calculated IQR bounds
WHERE (h.duration_in_seconds > t.upper_bound OR h.duration_in_seconds < t.lower_bound)
ORDER BY h.record_time DESC;
