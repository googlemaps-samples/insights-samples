-- Job ID: rmisqlfactory_ds9_YYYYMMDDHHMMSS
-- Persona: data_scientist
-- Purpose: RMI BigQuery Analytical Query (ds9)

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

-- Data Scientist Query 9: Corridor Secular Trend Decomposition & Forward Projection (ML.TREND)
-- Business Question: What is the underlying directional growth trajectory of travel times on monitored corridors once daily/weekly cyclical noise is removed, and where is it heading?
-- Use Case: Strips out diurnal and day-of-week fluctuations using STL decomposition to expose secular congestion drift and project the smoothed trajectory into the future without training custom models.
-- Product Stage: GA (Uses ML.TREND)
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Secular Trend Extraction vs. Full Seasonal Forecasting
  - ARIMA_PLUS / AI.FORECAST (DS6, DS7): Models and predicts the full seasonal curve including morning/evening peak oscillations.
  - ML.TREND (DS9): Uses ARIMA_PLUS's in-database STL decomposition algorithm to isolate the pure, 
    smoothed directional trajectory (`trend`), projecting secular drift across future horizons.
  - Multi-Corridor Scaling: Automatically processes multiple time series simultaneously using `id_cols`.
*/

WITH daily_corridor_metrics AS (
  SELECT
    h.selected_route_id,
    DATE(h.record_time) AS record_date,
    -- Daily average travel duration in seconds
    AVG(h.duration_in_seconds) AS avg_duration_seconds
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
  record_date,
  time_series_type,
  ROUND(avg_duration_seconds, 1) AS actual_duration_sec,
  ROUND(trend, 1) AS trend_duration_sec,
  -- Deviation percentage of actual/forecasted data from the secular trend component
  ROUND(SAFE_DIVIDE(avg_duration_seconds - trend, trend) * 100, 2) AS pct_deviation_from_trend,
  status
FROM ML.TREND(
  TABLE daily_corridor_metrics,
  data_col => 'avg_duration_seconds',
  timestamp_col => 'record_date',
  id_cols => ['selected_route_id'],
  horizon => 7,                  -- Project the underlying trend 7 days into the future
  smoothing_window_size => 5     -- Centered moving average smoothing window
)
ORDER BY selected_route_id, record_date;
