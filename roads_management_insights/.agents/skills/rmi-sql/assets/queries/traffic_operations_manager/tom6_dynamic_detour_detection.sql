-- Job ID: rmisqlfactory_tom6_YYYYMMDDHHMMSS
-- Persona: traffic_operations_manager
-- Purpose: RMI BigQuery Analytical Query (tom6)

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

-- Traffic Operations Manager Query 6: Dynamic Detour and Path Variation Analysis
-- Business Question: Which routes experienced dynamic rerouting/detours, and what was the travel time impact between the primary path and detour variations?
-- Use Case: Identifies recurring dynamic route variations or incident diversions caused by congestion, road closures, or routing engine shifts.
-- Product Stage: GA
-- Estimated Bytes Processed: ~80 MB

/*
  ANALYTICAL PATTERN: Dynamic Path Variation & Detour Analysis
  
  IMPORTANT SCHEMA NOTE:
  The 'road_segment_ids' column (ARRAY<STRING> containing topological Place IDs)
  was added to 'historical_travel_time' on July 1, 2026.
  Telemetry records prior to this date have empty/NULL arrays for this column.
  Therefore, queries utilizing 'road_segment_ids' MUST filter for:
    record_time >= '2026-07-01' AND ARRAY_LENGTH(road_segment_ids) > 0
  
  WORKFLOW:
  1. Flattens road_segment_ids into a pipe-delimited string (fingerprint) to allow GROUP BY.
  2. Computes the frequency and average duration of each distinct physical path variant.
  3. Aggregates variations into an array sorted by frequency (Index 0 = Primary, Index 1+ = Detour).
  4. Computes the Detour Delay Multiplier to quantify the operational travel time penalty.
*/

WITH path_variants AS (
  SELECT
    h.selected_route_id,
    h.display_name,
    ARRAY_TO_STRING(h.road_segment_ids, '|') AS segment_ids,
    AVG(h.duration_in_seconds) AS avg_duration_in_seconds,
    COUNT(h.record_time) AS num_of_records
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  -- Schema Temporal Filter: road_segment_ids is only populated from 2026-07-01 onward
  WHERE h.record_time >= '2026-07-01'
    AND ARRAY_LENGTH(h.road_segment_ids) > 0
    AND s.status = 'STATUS_RUNNING'
    AND h.duration_in_seconds IS NOT NULL
    AND h.static_duration_in_seconds > 0
  GROUP BY 1, 2, 3
),
ranked_routes AS (
  SELECT
    selected_route_id,
    display_name,
    ARRAY_AGG(
      STRUCT(segment_ids, avg_duration_in_seconds, num_of_records)
      ORDER BY num_of_records DESC
    ) AS variations
  FROM path_variants
  GROUP BY 1, 2
)
SELECT
  selected_route_id,
  display_name,
  ARRAY_LENGTH(variations) AS total_path_variations,
  variations[OFFSET(0)].num_of_records AS primary_path_samples,
  ROUND(variations[OFFSET(0)].avg_duration_in_seconds, 1) AS primary_avg_duration_seconds,
  variations[OFFSET(1)].num_of_records AS detour_path_samples,
  ROUND(variations[OFFSET(1)].avg_duration_in_seconds, 1) AS detour_avg_duration_seconds,
  -- Detour Delay Multiplier: > 1.0 means the detour was slower than the standard path
  ROUND(SAFE_DIVIDE(variations[OFFSET(1)].avg_duration_in_seconds, variations[OFFSET(0)].avg_duration_in_seconds), 2) AS detour_delay_multiplier
FROM ranked_routes
WHERE ARRAY_LENGTH(variations) > 1
ORDER BY detour_delay_multiplier DESC;
