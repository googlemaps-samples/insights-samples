-- Job ID: rmisamplesql_de3_YYYYMMDDHHMMSS
-- Persona: data_engineer
-- Purpose: RMI BigQuery Analytical Query (de3)

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

-- Data Engineer Query 3: SRI Flattening with Modern Offsets
-- Business Question: Transform the latest 30 minutes of nested SRI offset data into a flattened format with spatial progress metrics and quality filters using native integer arithmetic.
-- Product Stage: GA
-- Estimated Bytes Processed: ~8 MB (Optimized via Scripting, Static Partition Pruning, and speed_reading_offsets)

/*
  BIGQUERY OPTIMIZATION PATTERN: Native Integer Offsets vs. Windowing
  
  Modern RMI datasets provide speed_reading_offsets (start_offset, end_offset, speed).
  This eliminates complex ST_MAKELINE spatial polyline assembly and window function sums:
  
  1. Static Pruning: Resolves 'latest_timestamp' to prune partitions ahead of the main SELECT.
  2. Native Offsets: Computes interval lengths directly via (end_offset - start_offset).
  3. Progress Ratios: Derives start_position_ratio and end_position_ratio directly from 
     start_offset and end_offset without LAG() or rolling SUM() window calculations.
  4. Multi-Tier Congestion: Accurately classifies SLOW, TRAFFIC_JAM, and TRAFFIC_JAM_HEAVY.
*/

-- Step 1: Define the static anchor date to narrow down partitions
DECLARE anchor_date DATE DEFAULT '2026-07-29';

-- Step 2: Find the exact latest timestamp and define the 30-minute window
DECLARE latest_timestamp TIMESTAMP;
SET latest_timestamp = (
  SELECT MAX(record_time)
  FROM `LINKED_DATASET_NAME.recent_roads_data`
  WHERE record_time >= TIMESTAMP(anchor_date)
);

-- Step 3: Execute flattening logic using native integer offsets
WITH base_intervals AS (
  SELECT
    r.selected_route_id,
    r.record_time,
    segment_offset AS interval_index,
    sro.speed AS interval_speed_state,
    sro.start_offset,
    sro.end_offset,
    -- Physical interval length in meters via integer subtraction
    (sro.end_offset - sro.start_offset) AS interval_length_meters,
    ST_LENGTH(r.route_geometry) AS actual_route_length_meters,
    SAFE_CAST(COALESCE(JSON_VALUE(s.route_attributes, '$.route_length_meters'), JSON_VALUE(s.route_attributes, '$.route_length')) AS FLOAT64) AS intended_route_length_meters
  FROM `LINKED_DATASET_NAME.recent_roads_data` AS r
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  LEFT JOIN UNNEST(r.speed_reading_offsets) AS sro WITH OFFSET AS segment_offset
  WHERE r.record_time >= TIMESTAMP(anchor_date)
    AND r.record_time > TIMESTAMP_SUB(latest_timestamp, INTERVAL 30 MINUTE)
    AND s.status = 'STATUS_RUNNING'
    AND (r.has_road_closure IS FALSE OR r.has_road_closure IS NULL)
    AND ST_GEOMETRYTYPE(r.route_geometry) = 'ST_LineString'
),
quality_filtered_intervals AS (
  SELECT
    *,
    -- Deviation between intended and actual geometry length
    SAFE_DIVIDE(ABS(actual_route_length_meters - intended_route_length_meters), intended_route_length_meters) AS length_deviation_ratio
  FROM base_intervals
  -- Filter for high-integrity geometries (< 5% length deviation)
  WHERE SAFE_DIVIDE(ABS(actual_route_length_meters - intended_route_length_meters), intended_route_length_meters) < 0.05
)
SELECT
  selected_route_id,
  record_time,
  interval_index,
  interval_speed_state,
  start_offset,
  end_offset,
  interval_length_meters,
  -- Rounded relative positions (0.000 to 1.000) within the trip computed directly from offsets
  ROUND(SAFE_DIVIDE(start_offset, actual_route_length_meters), 3) AS start_position_ratio,
  ROUND(SAFE_DIVIDE(end_offset, actual_route_length_meters), 3) AS end_position_ratio,
  length_deviation_ratio
FROM quality_filtered_intervals
-- Filter for congested intervals (including TRAFFIC_JAM_HEAVY) and exclude short GPS noise
WHERE interval_speed_state IN ('SLOW', 'TRAFFIC_JAM', 'TRAFFIC_JAM_HEAVY')
  AND interval_length_meters >= 5
ORDER BY selected_route_id, record_time, interval_index;
