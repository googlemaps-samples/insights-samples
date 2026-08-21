-- Job ID: rmisqlfactory_up2_YYYYMMDDHHMMSS
-- Persona: urban_planner
-- Purpose: RMI BigQuery Analytical Query (up2)

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

-- Urban Planner Query 2: Before-and-After Impact Analysis
-- Business Question: Has the average travel time on routes passing through a recent construction zone improved since the project's completion date?
-- Use Case: Provides empirical evidence of infrastructure project success, validating whether road improvements (like new lanes or signals) actually reduced congestion.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Spatial & Milestone Join
  This query uses a DECLARE statement for the study area geometry to ensure 
  BigQuery treats the polygon as a constant, enabling efficient spatial 
  indexing during the ST_INTERSECTS join. It then segments the data based 
  on a chronological project milestone.
*/

-- Study Area: Downtown Boston Intersection
DECLARE study_area GEOGRAPHY DEFAULT ST_GEOGFROMTEXT('POLYGON((-71.06 42.35, -71.05 42.35, -71.05 42.34, -71.06 42.34, -71.06 42.35))');
-- Project Milestone: Date when construction was completed
DECLARE completion_date DATE DEFAULT '2026-06-15';

WITH impact_data AS (
  SELECT
    -- Split records into 'Before' and 'After' buckets
    DATE(record_time) >= completion_date AS is_after_completion,
    SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) AS delay_ratio
  FROM `LINKED_DATASET_NAME.historical_travel_time`
  -- S2 SPATIAL INDEXING NOTE:
  -- BigQuery leverages native S2 cell indexing for ST_INTERSECTS, performing
  -- sub-second bounding box pruning across millions of polyline records.
  WHERE ST_INTERSECTS(route_geometry, study_area)
    AND record_time BETWEEN '2026-06-01' AND '2026-06-30'
    AND duration_in_seconds IS NOT NULL
    AND static_duration_in_seconds > 0
)
SELECT
  is_after_completion,
  ROUND(AVG(delay_ratio), 3) AS avg_delay_ratio,
  COUNT(*) as sample_count
FROM impact_data
GROUP BY 1
ORDER BY 1;
