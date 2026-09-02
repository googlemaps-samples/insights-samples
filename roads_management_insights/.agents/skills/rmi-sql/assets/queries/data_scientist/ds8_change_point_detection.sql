-- Job ID: rmisqlfactory_ds8_YYYYMMDDHHMMSS
-- Persona: data_scientist
-- Purpose: RMI BigQuery Analytical Query (ds8)

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

-- Data Scientist Query 8: Corridor Structural Shift Detection (ML.DETECT_CHANGE_POINTS)
-- Business Question: When did the baseline travel time on key monitored corridors undergo significant step-changes or regime shifts?
-- Use Case: Uncovers sustained structural breaks (e.g., road construction phases, signal timing overhauls, or permanent bottleneck emergence) across multiple corridors without managing custom ML models.
-- Product Stage: GA (Uses ML.DETECT_CHANGE_POINTS)
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Change Point Detection vs. Point Anomalies
  - IQR / ML.DETECT_ANOMALIES (DS1): Detects transient 1-2 hour outliers (e.g., accidents or severe thunderstorms).
  - ML.DETECT_CHANGE_POINTS (DS8): Detects prolonged, structural level shifts in mean/variance 
    over multi-day or multi-week windows.
  - Zero Model Overhead: Operates directly on table expressions without requiring a CREATE MODEL pipeline.
  - Multi-Corridor Scaling: Automatically processes multiple time series simultaneously using `id_cols`.
*/

WITH daily_corridor_metrics AS (
  SELECT
    h.selected_route_id,
    DATE(h.record_time) AS record_date,
    -- Daily average travel duration in seconds
    AVG(h.duration_in_seconds) AS avg_duration_seconds,
    -- Daily average delay ratio relative to free-flow baseline
    AVG(SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds)) AS avg_delay_ratio
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING(selected_route_id)
  WHERE h.record_time BETWEEN '2026-07-01' AND '2026-07-30'
    -- Quality filter: Exclude non-continuous geometries
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
    AND h.duration_in_seconds IS NOT NULL
    AND h.static_duration_in_seconds > 0
    AND s.status = 'STATUS_RUNNING'
  GROUP BY 1, 2
)

SELECT
  selected_route_id,
  begin_timestamp,
  end_timestamp,
  ROUND(metrics.avg, 2) AS shift_avg_duration_sec,
  ROUND(metrics.min, 2) AS shift_min_duration_sec,
  ROUND(metrics.max, 2) AS shift_max_duration_sec,
  ROUND(metrics.stddev, 2) AS shift_stddev,
  metrics.count AS data_points_in_window,
  status
FROM ML.DETECT_CHANGE_POINTS(
  TABLE daily_corridor_metrics,
  data_col => 'avg_duration_seconds',
  timestamp_col => 'record_date',
  id_cols => ['selected_route_id']
)
ORDER BY selected_route_id, begin_timestamp;
