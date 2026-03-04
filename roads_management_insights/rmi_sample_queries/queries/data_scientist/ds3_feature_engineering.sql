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

-- Data Scientist Query 3: Predictive Feature Engineering (Regularized Time-Series)
-- Business Question: How can I prepare a high-quality, gap-aware feature set for training a predictive traffic model?
-- Use Case: Demonstrates how to regularize a time-series using a timestamp grid. This ensures that window functions (LAG, AVG) accurately reflect chronological time even when records are missing due to quality filtering or detours.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB

/*
  HANDLING MISSING DATA (DETOURS/GAPS):
  By joining the RMI data with a generated 'time_grid', we identify missing records. 
  Downstream models can then decide how to handle these nulls (e.g., interpolation, 
  imputation, or masking), preventing window functions from 'collapsing' time gaps.
*/

WITH quality_filtered_base AS (
  SELECT
    -- Truncating to hour to match the RMI collection interval
    TIMESTAMP_TRUNC(h.record_time, HOUR) as record_hour,
    h.duration_in_seconds,
    ST_LENGTH(h.route_geometry) as actual_length,
    CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64) as intended_length
  FROM `boston_oct_2025_sample_data.historical_travel_time` h
  JOIN `boston_oct_2025_sample_data.routes_status` s USING(selected_route_id)
  WHERE h.selected_route_id = 'route-4202493217'
    AND h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
    -- Quality filter: Only process single, continuous paths
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
),
hourly_averages AS (
  -- Aggregate to a single record per hour before regularizing
  SELECT 
    record_hour,
    AVG(duration_in_seconds) as avg_duration,
    COUNT(*) as samples_in_hour
  FROM quality_filtered_base
  WHERE SAFE_DIVIDE(ABS(actual_length - intended_length), intended_length) < 0.05
  GROUP BY 1
),
time_grid AS (
  -- Generate a continuous hourly grid for the study period
  SELECT hour
  FROM UNNEST(GENERATE_TIMESTAMP_ARRAY('2025-10-01', '2025-10-31', INTERVAL 1 HOUR)) as hour
),
regularized_series AS (
  SELECT
    g.hour,
    a.avg_duration as duration_in_seconds,
    COALESCE(a.samples_in_hour, 0) as samples_in_hour,
    IF(a.avg_duration IS NULL, TRUE, FALSE) as is_missing_data
  FROM time_grid g
  LEFT JOIN hourly_averages a ON g.hour = a.record_hour
)
SELECT
  hour,
  ROUND(duration_in_seconds, 2) as duration_in_seconds,
  samples_in_hour,
  is_missing_data,
  -- Lagged features now accurately represent -1hr and -2hr regardless of data availability
  ROUND(LAG(duration_in_seconds, 1) OVER (ORDER BY hour), 2) AS lag_1hr_duration,
  ROUND(LAG(duration_in_seconds, 2) OVER (ORDER BY hour), 2) AS lag_2hr_duration,
  -- Rolling average (3-hour window)
  ROUND(AVG(duration_in_seconds) OVER (
    ORDER BY hour 
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
  ), 2) AS rolling_avg_3hr
FROM regularized_series
ORDER BY hour DESC;
