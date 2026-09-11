-- Job ID: rmisqlfactory_ds10_YYYYMMDDHHMMSS
-- Persona: data_scientist
-- Purpose: RMI BigQuery Analytical Query (ds10)

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

-- Data Scientist Query 10: Corridor Seasonality Decomposition & Diurnal Wave Extraction (ML.SEASONALITY)
-- Business Question: What are the exact additive diurnal (hour-of-day) and day-of-week (weekday vs. weekend) recurring congestion penalties across monitored corridors?
-- Use Case: Isolates recurring cyclic traffic patterns using in-database STL seasonality decomposition to calibrate time-of-day signal timing plans and optimize logistics dispatch schedules without managing custom models.
-- Product Stage: GA (Uses ML.SEASONALITY)
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Seasonality Component Decomposition
  - ML.TREND (DS9): Isolates the non-cyclical, secular directional trajectory (`trend`).
  - ML.SEASONALITY (DS10): Decomposes the time series into additive cyclical periodicities:
    - `daily`: Diurnal hour-of-day peak/off-peak penalty or relief (seconds).
    - `weekly`: Day-of-week weekend vs. weekday traffic swing (seconds).
  - Multi-Corridor Scaling: Simultaneously decomposes hundreds of corridors using `id_cols`.
*/

WITH hourly_corridor_metrics AS (
  SELECT
    h.selected_route_id,
    TIMESTAMP_TRUNC(h.record_time, HOUR) AS record_hour,
    -- Hourly average travel duration in seconds
    AVG(h.duration_in_seconds) AS avg_duration_seconds
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING(selected_route_id)
  WHERE h.record_time BETWEEN '2026-07-01' AND '2026-07-21'
    -- Quality filter: Exclude non-continuous geometries
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
    AND h.duration_in_seconds IS NOT NULL
    AND h.static_duration_in_seconds > 0
    AND s.status = 'STATUS_RUNNING'
  GROUP BY 1, 2
)

SELECT
  selected_route_id,
  record_hour,
  time_series_type,
  ROUND(avg_duration_seconds, 1) AS actual_duration_sec,
  -- Hour-of-day diurnal seasonal penalty (+) or relief (-) in seconds
  ROUND(daily, 1) AS daily_seasonal_effect_sec,
  -- Day-of-week seasonal penalty (+) or relief (-) in seconds
  ROUND(weekly, 1) AS weekly_seasonal_effect_sec,
  status
FROM ML.SEASONALITY(
  TABLE hourly_corridor_metrics,
  data_col => 'avg_duration_seconds',
  timestamp_col => 'record_hour',
  id_cols => ['selected_route_id'],
  seasonalities => ['DAILY', 'WEEKLY'],
  horizon => 24                   -- Project recurring seasonal cycles 24 hours forward
)
ORDER BY selected_route_id, record_hour;
