-- Job ID: rmisamplesql_ds3_YYYYMMDDHHMMSS
-- Persona: data_scientist
-- Purpose: RMI BigQuery Analytical Query (ds3)

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

-- Data Scientist Query 3: Predictive Feature Engineering (Regularized Time-Series with Closure Discrimination)
-- Business Question: How can I prepare a high-quality, gap-aware feature set for training a predictive traffic model, distinguishing physical road closures from telemetry pipeline dropouts?
-- Use Case: Regularizes a time-series using a timestamp grid and labels missing values with explicit root causes (physical closure vs pipeline dropout) to prevent distorted ML imputation.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB

/*
  HANDLING MISSING DATA (CLOSURES VS. DROPOUTS):
  When joining RMI telemetry with a generated 'time_grid', null observations are categorized:
  1. ROAD_CLOSURE: has_road_closure = true (duration is NULL because corridor is impassable).
  2. PIPELINE_DROPOUT: Grid timestamp has zero telemetry observations.
  3. QUALITY_FILTERED: Observation failed geometric deviation or line-string filters.
*/

WITH quality_filtered_base AS (
  SELECT
    TIMESTAMP_TRUNC(h.record_time, HOUR) as record_hour,
    h.duration_in_seconds,
    h.has_road_closure,
    ST_LENGTH(h.route_geometry) as actual_length,
    SAFE_CAST(COALESCE(JSON_VALUE(s.route_attributes, '$.route_length_meters'), JSON_VALUE(s.route_attributes, '$.route_length')) AS FLOAT64) as intended_length
  FROM `LINKED_DATASET_NAME.historical_travel_time` h
  JOIN `LINKED_DATASET_NAME.routes_status` s USING(selected_route_id)
  WHERE h.selected_route_id = 'boston-v2--2rwshKeDrs'
    AND s.status = 'STATUS_RUNNING'
    AND h.record_time BETWEEN '2026-07-01' AND '2026-07-30'
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
),
hourly_averages AS (
  SELECT 
    record_hour,
    -- Compute average duration only over passable observations
    AVG(CASE WHEN COALESCE(has_road_closure, FALSE) IS FALSE THEN duration_in_seconds END) as avg_duration,
    COUNT(*) as samples_in_hour,
    LOGICAL_OR(has_road_closure IS TRUE) as had_road_closure
  FROM quality_filtered_base
  WHERE SAFE_DIVIDE(ABS(actual_length - intended_length), intended_length) < 0.05
     OR has_road_closure IS TRUE
  GROUP BY 1
),
time_grid AS (
  -- Generate a continuous hourly grid for the study period
  SELECT hour
  FROM UNNEST(GENERATE_TIMESTAMP_ARRAY('2026-07-01', '2026-07-29', INTERVAL 1 HOUR)) as hour
),
regularized_series AS (
  SELECT
    g.hour,
    a.avg_duration as duration_in_seconds,
    COALESCE(a.samples_in_hour, 0) as samples_in_hour,
    COALESCE(a.had_road_closure, FALSE) as is_road_closure,
    -- Distinguish physical road closures from upstream pipeline dropouts
    CASE
      WHEN a.had_road_closure IS TRUE THEN 'ROAD_CLOSURE'
      WHEN a.record_hour IS NULL THEN 'PIPELINE_DROPOUT'
      WHEN a.avg_duration IS NULL THEN 'QUALITY_FILTERED'
      ELSE 'OBSERVED'
    END as observation_status
  FROM time_grid g
  LEFT JOIN hourly_averages a ON g.hour = a.record_hour
)
SELECT
  hour,
  ROUND(duration_in_seconds, 2) as duration_in_seconds,
  samples_in_hour,
  observation_status,
  is_road_closure,
  -- Lagged features represent chronological -1hr and -2hr windows
  ROUND(LAG(duration_in_seconds, 1) OVER (ORDER BY hour), 2) AS lag_1hr_duration,
  ROUND(LAG(duration_in_seconds, 2) OVER (ORDER BY hour), 2) AS lag_2hr_duration,
  -- Rolling average (3-hour window)
  ROUND(AVG(duration_in_seconds) OVER (
    ORDER BY hour 
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
  ), 2) AS rolling_avg_3hr
FROM regularized_series
ORDER BY hour DESC;
