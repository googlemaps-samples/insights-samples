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

-- Urban Planner Query 1: Corridor Performance Trend
-- Business Question: What has been the week-over-week trend in the average delay ratio for a specific corridor?
-- Use Case: Enables long-term performance monitoring of critical transportation infrastructure, helping planners identify if congestion is worsening or improving over time.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Weekly Trend Aggregation
  This query truncates timestamps to the week level to smooth out day-to-day 
  fluctuations, focusing on the macro traffic behavior of a critical route.
*/

WITH weekly_trends AS (
  SELECT
    selected_route_id,
    -- Truncate to the start of the week for consistent aggregation
    TIMESTAMP_TRUNC(record_time, WEEK) AS week,
    -- Calculate average delay (Actual / Free-flow baseline)
    AVG(SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)) AS avg_delay_ratio
  FROM `boston_oct_2025_sample_data.historical_travel_time`
  -- Filter for a specific corridor of interest (e.g., Storrow Drive)
  WHERE selected_route_id = 'route-4202493217'
    AND record_time BETWEEN '2025-10-01' AND '2025-11-01'
  GROUP BY 1, 2
)
SELECT
  selected_route_id,
  -- Format for readable year-week reporting
  FORMAT_TIMESTAMP("%Y-%W", week) AS year_week,
  ROUND(avg_delay_ratio, 3) AS avg_delay_ratio
FROM weekly_trends
ORDER BY week;
