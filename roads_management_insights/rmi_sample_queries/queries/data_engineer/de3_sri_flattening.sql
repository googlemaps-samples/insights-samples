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

-- Data Engineer Query 3: SRI Flattening (Scripted Version)
-- Business Question: Create an optimized script to transform the latest 30 minutes of nested SRI data into a flattened format with spatial progress metrics and quality filters.
-- Product Stage: GA
-- Estimated Bytes Processed: ~10 MB (Optimized via Scripting and Static Partition Pruning)

/*
  BIGQUERY OPTIMIZATION PATTERN: Static vs. Dynamic Partition Pruning
  
  This query uses BigQuery Scripting (DECLARE/SET) to force "Static Pruning".
  
  1. Static Pruning (This Pattern): By resolving 'target_time' into a variable BEFORE 
     the main SELECT, BigQuery treats it as a constant. This allows the optimizer 
     to immediately discard irrelevant partitions.
     
  2. Geometry Integrity Check: To ensure high-quality analysis, this query:
     a) Calculates 'length_deviation_ratio' against pre-computed attributes.
     b) Excludes 'MultiLineString' geometries to ensure we only process single, 
        continuous paths (ST_LineString).
        
  3. Noise Reduction: Final results exclude 'NORMAL' speed states and filter out 
     extremely short intervals (< 5 meters) that often represent GPS noise.
*/

-- Step 1: Define the static anchor date to narrow down partitions
DECLARE anchor_date DATE DEFAULT '2025-10-31';

-- Step 2: Find the exact latest timestamp and define the 30-minute window
DECLARE latest_timestamp TIMESTAMP;
SET latest_timestamp = (
  SELECT MAX(record_time)
  FROM `boston_oct_2025_sample_data.recent_roads_data`
  WHERE record_time >= TIMESTAMP(anchor_date)
);

-- Step 3: Execute the flattening logic for the latest 30-minute window
WITH base_intervals AS (
  SELECT
    r.selected_route_id,
    r.record_time,
    segment_offset as interval_index,
    sri.speed as interval_speed_state,
    -- Reconstruct the interval polyline from the array of interval points
    ST_MAKELINE(sri.interval_coordinates) as interval_geometry,
    -- Core metrics for integrity check
    ST_LENGTH(r.route_geometry) as actual_route_length_meters,
    CAST(JSON_VALUE(s.route_attributes, '$.route_length') AS FLOAT64) as intended_route_length_meters
  FROM `boston_oct_2025_sample_data.recent_roads_data` r
  JOIN `boston_oct_2025_sample_data.routes_status` s USING(selected_route_id),
  UNNEST(speed_reading_intervals) AS sri WITH OFFSET AS segment_offset
  WHERE r.record_time >= TIMESTAMP(anchor_date)
    -- Capture only records from the last 30 minutes
    AND r.record_time > TIMESTAMP_SUB(latest_timestamp, INTERVAL 30 MINUTE)
    -- Quality filter: Only process single, continuous paths
    AND ST_GEOMETRYTYPE(r.route_geometry) = 'ST_LineString'
),
quality_filtered_intervals AS (
  SELECT
    *,
    -- Deviation between intended and actual geometry length
    SAFE_DIVIDE(ABS(actual_route_length_meters - intended_route_length_meters), intended_route_length_meters) as length_deviation_ratio
  FROM base_intervals
  -- Filter for high-integrity geometries (e.g., < 5% deviation)
  WHERE SAFE_DIVIDE(ABS(actual_route_length_meters - intended_route_length_meters), intended_route_length_meters) < 0.05
),
metrics_calculation AS (
  SELECT
    *,
    ST_LENGTH(interval_geometry) as interval_length_meters,
    -- Roll-up sum of interval lengths to find cumulative distance from origin
    SUM(ST_LENGTH(interval_geometry)) OVER (
      PARTITION BY selected_route_id, record_time 
      ORDER BY interval_index
    ) as cumulative_length_meters,
    -- Count total intervals in the route for context
    COUNT(*) OVER (
      PARTITION BY selected_route_id, record_time
    ) as total_intervals
  FROM quality_filtered_intervals
),
position_ratios AS (
  SELECT
    *,
    -- The end of the previous interval is the start of the current interval
    COALESCE(LAG(cumulative_length_meters) OVER (
      PARTITION BY selected_route_id, record_time 
      ORDER BY interval_index
    ), 0.0) as start_length_meters
  FROM metrics_calculation
)
SELECT
  selected_route_id,
  record_time,
  interval_index,
  total_intervals,
  interval_speed_state,
  interval_length_meters,
  -- Rounded relative positions (0.000 to 1.000) within the trip
  ROUND(SAFE_DIVIDE(start_length_meters, actual_route_length_meters), 3) as start_position_ratio,
  ROUND(SAFE_DIVIDE(cumulative_length_meters, actual_route_length_meters), 3) as end_position_ratio,
  length_deviation_ratio,
  interval_geometry
FROM position_ratios
-- Filter for congested intervals and exclude noise (short intervals)
WHERE interval_speed_state != 'NORMAL'
  AND interval_length_meters >= 5
ORDER BY selected_route_id, record_time, interval_index;
