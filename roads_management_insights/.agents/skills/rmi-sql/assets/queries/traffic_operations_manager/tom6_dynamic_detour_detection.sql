-- Job ID: rmisamplesql_tom6_YYYYMMDDHHMMSS
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
-- Business Question: Which dynamic routes experienced rerouting/detours away from their baseline static sequence, and what was the travel time impact between baseline and detour variants?
-- Use Case: Identifies dynamic route variations and incident diversions on dynamic_routing = true corridors by comparing observed segment sequences against routes_status.road_segment_ids.
-- Product Stage: GA
-- Estimated Bytes Processed: ~80 MB

/*
  ANALYTICAL PATTERN: Dynamic Detour Verification via road_segment_ids
  
  Leverages:
  1. s.dynamic_routing = true: Focuses on corridors configured for dynamic rerouting.
  2. s.road_segment_ids: Authoritative static baseline Place ID sequence from routes_status.
  3. h.road_segment_ids: Actual observed traffic-aware Place ID sequence (available since 2026-07-01).
  4. Detour Delay Multiplier: Compares detour average duration against baseline path duration.
*/

WITH path_variants AS (
  SELECT
    h.selected_route_id,
    h.display_name,
    s.dynamic_routing,
    ARRAY_TO_STRING(s.road_segment_ids, '|') AS baseline_segment_ids,
    ARRAY_TO_STRING(h.road_segment_ids, '|') AS observed_segment_ids,
    -- Check if observed path matches registered static baseline
    (ARRAY_TO_STRING(h.road_segment_ids, '|') = ARRAY_TO_STRING(s.road_segment_ids, '|')) AS is_baseline_path,
    AVG(h.duration_in_seconds) AS avg_duration_in_seconds,
    COUNT(h.record_time) AS num_of_records
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  -- Schema Temporal Filter: road_segment_ids is only populated from 2026-07-01 onward
  WHERE h.record_time >= '2026-07-01'
    AND ARRAY_LENGTH(h.road_segment_ids) > 0
    AND ARRAY_LENGTH(s.road_segment_ids) > 0
    AND s.status = 'STATUS_RUNNING'
    -- Focus strictly on routes configured for dynamic traffic rerouting
    AND s.dynamic_routing IS TRUE
    AND (h.has_road_closure IS FALSE OR h.has_road_closure IS NULL)
    AND h.duration_in_seconds IS NOT NULL
    AND h.static_duration_in_seconds > 0
  GROUP BY 1, 2, 3, 4, 5, 6
),
ranked_routes AS (
  SELECT
    selected_route_id,
    display_name,
    dynamic_routing,
    baseline_segment_ids,
    ARRAY_AGG(
      STRUCT(observed_segment_ids, is_baseline_path, avg_duration_in_seconds, num_of_records)
      ORDER BY is_baseline_path DESC, num_of_records DESC
    ) AS variations
  FROM path_variants
  GROUP BY 1, 2, 3, 4
)
SELECT
  selected_route_id,
  display_name,
  ARRAY_LENGTH(variations) AS total_path_variations,
  variations[OFFSET(0)].num_of_records AS baseline_path_samples,
  ROUND(variations[OFFSET(0)].avg_duration_in_seconds, 1) AS baseline_avg_duration_seconds,
  variations[OFFSET(1)].num_of_records AS detour_path_samples,
  ROUND(variations[OFFSET(1)].avg_duration_in_seconds, 1) AS detour_avg_duration_seconds,
  -- Detour Delay Multiplier: > 1.0 means the detour was slower than the baseline path
  ROUND(SAFE_DIVIDE(variations[OFFSET(1)].avg_duration_in_seconds, variations[OFFSET(0)].avg_duration_in_seconds), 2) AS detour_delay_multiplier
FROM ranked_routes
WHERE ARRAY_LENGTH(variations) > 1
ORDER BY detour_delay_multiplier DESC;
