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

-- RMI Seller Query 1: Usage Growth Projection
-- Business Question: Based on current data, what is the rate of record creation, and how will it scale?
-- Use Case: Helps sales teams estimate BigQuery storage and compute growth as a customer increases their monitoring footprint from a small pilot to an enterprise-wide fleet.
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB (Standard SQL on RMI Tables)

WITH daily_stats AS (
  SELECT
    DATE(record_time) as log_date,
    selected_route_id,
    COUNT(*) as records_per_day
  FROM `boston_oct_2025_sample_data.historical_travel_time`
  WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
  GROUP BY 1, 2
),
avg_usage AS (
  SELECT
    AVG(records_per_day) as avg_daily_records_per_route
  FROM daily_stats
)
SELECT
  ROUND(avg_daily_records_per_route, 2) as avg_records_per_route_per_day,
  -- Parameter: Target fleet size (e.g., 5,000 routes)
  5000 as target_route_count,
  ROUND(avg_daily_records_per_route * 5000, 0) as estimated_total_daily_records,
  -- Extrapolate to monthly volume in millions of records
  ROUND(avg_daily_records_per_route * 5000 * 30 / 1000000, 2) as estimated_monthly_millions
FROM avg_usage;
