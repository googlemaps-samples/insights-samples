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

-- Data Scientist Query 7: Zero-Shot Multi-Route Forecasting (TimesFM)
-- Business Question: Can we immediately forecast next-day traffic for multiple routes without waiting to train individual models?
-- Use Case: Demonstrates 'Zero-Shot' forecasting using Google's Time Series Foundation Model (TimesFM). Unlike ARIMA, this model uses pre-trained patterns to predict future travel times for an entire cluster of routes simultaneously, even with limited local history.
-- Product Stage: GA (Uses AI.FORECAST with TimesFM)
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL ADVANTAGE: Foundation Models vs. Traditional Models
  - ARIMA_PLUS (DS6): Requires 'Training' (Learning) on specific route history first.
  - TimesFM (DS7): Uses 'Zero-Shot' inference via AI.FORECAST. It applies global 
    patterns to your data immediately. Ideal for 'Cold Start' (new routes) or 
    scaling to thousands of routes without per-route training overhead.
*/

-- STEP 1: Prepare a 'Context' window of history for multiple routes.
-- Foundation models like TimesFM perform best with 3-7 days of chronological context.
WITH route_context AS (
  SELECT
    selected_route_id,
    TIMESTAMP_TRUNC(record_time, HOUR) as record_hour,
    AVG(duration_in_seconds) as duration_in_seconds
  FROM `boston_oct_2025_sample_data.historical_travel_time`
  -- We pick a 7-day context window for 3 specific routes
  WHERE selected_route_id IN ('route-4202493217', 'route-3850158153', 'route-381361371')
    AND record_time BETWEEN '2025-10-14' AND '2025-10-21'
  GROUP BY 1, 2
)
-- STEP 2: Use AI.FORECAST to generate predictions.
-- Note: TimesFM is a managed foundation model; no CREATE MODEL is required.
SELECT
  *
FROM AI.FORECAST(
  TABLE route_context,
  data_col => 'duration_in_seconds',
  timestamp_col => 'record_hour',
  model => 'TimesFM 2.0',          -- Specify the foundation model version
  id_cols => ['selected_route_id'], -- Forecast each route independently
  horizon => 24,                   -- Forecast 24 hours ahead
  confidence_level => 0.9          -- Generate 90% confidence intervals
)
ORDER BY selected_route_id, forecast_timestamp;
