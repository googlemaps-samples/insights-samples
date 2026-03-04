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

-- Data Scientist Query 6: Travel Time Forecasting (BigQuery ML ARIMA_PLUS)
-- Business Question: Can we predict next week's peak travel times based on the last 21 days of history?
-- Use Case: Demonstrates a complete predictive workflow: Training an ARIMA_PLUS model, evaluating its seasonal fit, and performing backtesting against actual results.
-- Product Stage: GA (Uses BigQuery ML)
-- Estimated Bytes Processed: ~150 MB

/*
  METHODOLOGY: TIME-SERIES BACKTESTING
  To build trust in a traffic model, we use 'Backtesting'. We split our 31-day 
  sample dataset into two parts:
  1. Training Set (Weeks 1-3): The model 'learns' the route's diurnal and weekly rhythm.
  2. Validation Set (Week 4): We withhold this data from the model, then ask the 
     model to 'forecast' it. Comparing the forecast to reality gives us an 
     empirical accuracy score.
*/

/*
  INTERPRETATION & VISUALIZATION GUIDE:
  
  1. REPORT INTERPRETATION:
     - 'absolute_error': Smaller is better. Measures the magnitude of the prediction 'miss'.
     - 'within_confidence_interval': This is your 'Anomaly Signal'. 
        - 'YES': Traffic is behaving normally/predictably.
        - 'NO': A significant event occurred (accident, weather, gridlock) that 
          exceeded statistical expectations. This is the trigger for operational alerts.
  
  2. RECOMMENDED VISUALIZATIONS:
     - Time-Series Line: Plot 'forecast_seconds' and 'actual_seconds' on the same Y-axis.
     - Confidence Band: Plot 'lower_bound' and 'upper_bound' as a shaded area. Dots 
       (actuals) falling outside this band are your truly actionable traffic incidents.
*/

-- STEP 1: Train the ARIMA_PLUS model using a 3-week window.
-- We use hourly aggregation (AVG) to regularize the input for the ARIMA algorithm.
CREATE OR REPLACE MODEL `your-project.your-dataset.travel_time_forecast_model`
OPTIONS(
  model_type='ARIMA_PLUS',
  time_series_timestamp_col='record_hour',
  time_series_data_col='duration_in_seconds',
  auto_arima=TRUE,          -- Automatically finds the best P, D, Q parameters.
  data_frequency='HOURLY',
  clean_spikes_and_dips=TRUE -- Prevents one-off accidents from skewing the long-term trend.
) AS
SELECT
  TIMESTAMP_TRUNC(record_time, HOUR) as record_hour,
  AVG(duration_in_seconds) as duration_in_seconds
FROM `boston_oct_2025_sample_data.historical_travel_time`
WHERE selected_route_id = 'route-4202493217'
  AND record_time BETWEEN '2025-10-01' AND '2025-10-21'
GROUP BY 1;

-- STEP 2: Evaluate the model's training metrics.
-- This returns AIC, Log Likelihood, and identified seasonal periods (e.g., DAILY).
-- A low AIC relative to other models indicates a better fit.
SELECT * FROM ML.EVALUATE(MODEL `your-project.your-dataset.travel_time_forecast_model`);

-- STEP 3: Compare Forecast vs. Actual for the 4th week (Backtesting).
-- We forecast a 168-hour 'horizon' (7 full days) to match the final week of October.
WITH forecast_data AS (
  SELECT
    forecast_timestamp,
    forecast_value as predicted_duration,
    prediction_interval_lower_bound as lower_bound,
    prediction_interval_upper_bound as upper_bound
  FROM ML.FORECAST(MODEL `your-project.your-dataset.travel_time_forecast_model`,
    STRUCT(168 AS horizon, 0.9 AS confidence_level))
),
actual_data AS (
  -- Aggregate actual withheld data to the same hourly grid for comparison.
  SELECT
    TIMESTAMP_TRUNC(record_time, HOUR) as record_hour,
    AVG(duration_in_seconds) as actual_duration
  FROM `boston_oct_2025_sample_data.historical_travel_time`
  WHERE selected_route_id = 'route-4202493217'
    AND record_time BETWEEN '2025-10-22' AND '2025-10-29'
  GROUP BY 1
)
SELECT
  f.forecast_timestamp,
  ROUND(f.predicted_duration, 1) as forecast_seconds,
  ROUND(a.actual_duration, 1) as actual_seconds,
  -- absolute_error: How many seconds off was the prediction?
  ROUND(ABS(f.predicted_duration - a.actual_duration), 1) as absolute_error,
  -- within_confidence_interval: Was reality within the 90% expected range?
  IF(a.actual_duration BETWEEN f.lower_bound AND f.upper_bound, 'YES', 'NO') as within_confidence_interval,
  -- Include bounds for visualization in tools like Looker Studio or Colab.
  ROUND(f.lower_bound, 1) as lower_bound,
  ROUND(f.upper_bound, 1) as upper_bound
FROM forecast_data f
LEFT JOIN actual_data a ON f.forecast_timestamp = a.record_hour
WHERE a.actual_duration IS NOT NULL
ORDER BY f.forecast_timestamp;
