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

-- Traffic Operations Manager Query 1: Peak Hour Delay Analysis
-- Business Question: What is the average travel time delay during the morning peak (7-9 AM) for the top 10 most congested routes?
-- Use Case: Identifies critical morning commute bottlenecks to inform operational decisions or public messaging.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  ANALYTICAL PATTERN: Temporal Filtering
  This query uses EXTRACT(HOUR...) on a converted DATETIME to focus on local 
  Boston peak windows. It filters for active routes and applies a quality 
  check to ensure the geometry is a single ST_LineString.
*/

WITH peak_hour_data AS (
  SELECT
    h.selected_route_id,
    h.display_name,
    -- delay_ratio > 1.0 indicates travel time is slower than free-flow (static)
    SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) AS delay_ratio
  FROM `boston_oct_2025_sample_data.historical_travel_time` AS h
  JOIN `boston_oct_2025_sample_data.routes_status` AS s USING (selected_route_id)
  WHERE h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
    -- STATUS_RUNNING ensures we only analyze routes that are currently being monitored
    AND s.status = 'STATUS_RUNNING'
    -- AM Peak Window: 7:00 AM to 8:59 AM Local Time
    AND EXTRACT(HOUR FROM DATETIME(h.record_time, 'America/New_York')) BETWEEN 7 AND 8
    -- Geometry Integrity: Only process continuous, healthy paths
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
)
SELECT
  display_name,
  ROUND(AVG(delay_ratio), 3) AS avg_delay_ratio,
  COUNT(*) AS sample_count
FROM peak_hour_data
GROUP BY 1
-- Threshold: Filter for routes that are at least marginally slower than free-flow
HAVING avg_delay_ratio > 1.0
ORDER BY avg_delay_ratio DESC
LIMIT 10;
