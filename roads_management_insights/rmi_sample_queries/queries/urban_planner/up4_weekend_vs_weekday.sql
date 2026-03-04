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

-- Urban Planner Query 4: Weekend vs. Weekday Trends
-- Business Question: How does average travel time in the afternoon (2-5 PM) differ between weekdays and weekends?
-- Use Case: Informs urban policy decisions like congestion pricing or off-peak transit scheduling by highlighting when road demand is most elastic.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Day-Type Segmentation
  This query uses EXTRACT(DAYOFWEEK...) to categorize records into binary 
  'Weekday' or 'Weekend' buckets. It combines this with a peak-window filter 
  to provide a clean comparison of temporal demand shifts.
*/

WITH afternoon_stats AS (
  SELECT
    -- Day segmentation: 1 = Sunday, 7 = Saturday
    CASE 
      WHEN EXTRACT(DAYOFWEEK FROM DATETIME(record_time, 'America/New_York')) IN (1, 7) THEN 'Weekend'
      ELSE 'Weekday'
    END AS day_type,
    duration_in_seconds,
    static_duration_in_seconds
  FROM `boston_oct_2025_sample_data.historical_travel_time`
  WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
    -- Afternoon period: 2 PM to 5 PM Local Time (Boston)
    AND EXTRACT(HOUR FROM DATETIME(record_time, 'America/New_York')) BETWEEN 14 AND 17
)
SELECT
  day_type,
  -- Calculate Average Delay Index (Actual / Ideal)
  ROUND(AVG(SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)), 3) AS avg_delay_ratio,
  ROUND(AVG(duration_in_seconds), 2) AS avg_duration_seconds,
  COUNT(*) as sample_count
FROM afternoon_stats
GROUP BY 1
ORDER BY avg_delay_ratio DESC;
