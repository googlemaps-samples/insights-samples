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

-- Traffic Operations Manager Query 3: Operational Health Check
-- Business Question: Which active routes are currently flagged with a 'LOW_ROAD_USAGE' validation error?
-- Use Case: Monitors the reliability of data collection. Low usage flags indicate that insights for these routes may be based on fewer probes, requiring a review of route priority or placement.
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB

/*
  ANALYTICAL PATTERN: Status Auditing
  This query inspects the management plane table (routes_status) to identify 
  active routes that have quality warnings. This is critical for maintaining 
  trust in downstream traffic analytics.
*/

SELECT
  display_name,
  selected_route_id,
  status,
  validation_error,
  -- 'low_road_usage_start_time' is specifically populated when probe density drops below threshold
  low_road_usage_start_time,
  -- Time elapsed since the error was first detected (relative to sample end date)
  DATETIME_DIFF(DATETIME('2025-11-01'), DATETIME(low_road_usage_start_time, 'UTC'), DAY) AS days_in_error_state
FROM `boston_oct_2025_sample_data.routes_status`
-- We only care about errors on routes that are supposed to be active (STATUS_RUNNING)
WHERE status = 'STATUS_RUNNING'
  -- Filter specifically for the Low Road Usage warning
  AND validation_error = 'VALIDATION_ERROR_LOW_ROAD_USAGE'
ORDER BY days_in_error_state DESC;
