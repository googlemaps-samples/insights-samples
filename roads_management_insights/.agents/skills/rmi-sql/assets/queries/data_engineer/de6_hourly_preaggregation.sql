-- Job ID: rmisqlfactory_de6_YYYYMMDDHHMMSS
-- Persona: data_engineer
-- Purpose: RMI BigQuery Analytical Query (de6 - Hourly Array Pre-Aggregation Pattern)

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

-- Data Engineer Query 6: 2-Stage Hourly Pre-Aggregation Pattern
-- Business Question: How do we transform high-frequency 2-minute SRI telemetry arrays (720 intervals/day) into lightweight hourly profiles without losing peak traffic congestion events?
-- Product Stage: GA
-- Estimated Bytes Processed: ~15 MB
-- Optimization Impact: Reduces ARRAY_AGG size from 720 elements to 24 per route/day (>95% response payload reduction).

WITH hourly_stage AS (
  SELECT 
    r.selected_route_id,
    s.display_name,
    EXTRACT(HOUR FROM r.record_time) AS hour_of_day,
    -- Pre-aggregate 2-minute interval records into the worst-case traffic state per hour
    CASE 
      WHEN LOGICAL_OR(sri.speed = 'TRAFFIC_JAM') THEN 'TRAFFIC_JAM'
      WHEN LOGICAL_OR(sri.speed = 'SLOW') THEN 'SLOW'
      ELSE 'NORMAL'
    END AS worst_hourly_speed
  FROM `LINKED_DATASET_NAME.recent_roads_data` r
  JOIN `LINKED_DATASET_NAME.routes_status` s USING(selected_route_id),
  UNNEST(speed_reading_intervals) AS sri
  -- PAYLOAD OPTIMIZATION NOTE:
  -- Stage 1 consolidates 2-minute interval records into hourly worst-case states via LOGICAL_OR.
  -- Stage 2 executes ARRAY_AGG, capping array length at exactly <= 24 elements per route/day,
  -- reducing downstream network transport and visualization client memory by over 95%.
  WHERE ST_GEOMETRYTYPE(r.route_geometry) = 'ST_LineString'
    AND r.record_time >= '2026-06-15 00:00:00' AND r.record_time < '2026-06-16 00:00:00'
  GROUP BY r.selected_route_id, s.display_name, hour_of_day
)
SELECT 
  selected_route_id,
  display_name,
  -- Stage 2: Aggregate the 24 hourly buckets into the final clean array
  ARRAY_AGG(STRUCT(hour_of_day, worst_hourly_speed) ORDER BY hour_of_day) AS hourly_congestion_profile,
  ARRAY_LENGTH(ARRAY_AGG(STRUCT(hour_of_day, worst_hourly_speed))) AS hourly_array_length
FROM hourly_stage
GROUP BY selected_route_id, display_name
ORDER BY selected_route_id
LIMIT 100;
