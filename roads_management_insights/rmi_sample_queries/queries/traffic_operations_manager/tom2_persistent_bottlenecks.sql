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

-- Traffic Operations Manager Query 2: Persistent Bottlenecks (Segment-Level)
-- Business Question: Which road segments (SRIs) have been in a 'TRAFFIC_JAM' state most frequently?
-- Use Case: Locates recurring local bottlenecks within routes, enabling targeted infrastructure investigation or signal timing adjustments.
-- Product Stage: GA
-- Estimated Bytes Processed: ~250 MB (Requires UNNEST of speed_reading_intervals)

/*
  ANALYTICAL PATTERN: SRI Unnesting
  RMI routes store segment-level traffic states (SRI) in a nested array. 
  This query 'explodes' that array using UNNEST to audit the frequency of 
  severe congestion across the entire network.
*/

WITH exploded_sris AS (
  SELECT
    selected_route_id,
    display_name,
    -- 'speed' represents the RMI traffic state for that specific interval
    sri.speed
  FROM `boston_oct_2025_sample_data.recent_roads_data`,
  UNNEST(speed_reading_intervals) AS sri
  WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
)
SELECT
  selected_route_id,
  display_name,
  -- We count every occurrence of an interval being in a 'TRAFFIC_JAM'
  COUNT(*) AS traffic_jam_count
FROM exploded_sris
-- Filter exclusively for the most severe RMI congestion state
WHERE speed = 'TRAFFIC_JAM'
GROUP BY 1, 2
ORDER BY traffic_jam_count DESC
LIMIT 10;
