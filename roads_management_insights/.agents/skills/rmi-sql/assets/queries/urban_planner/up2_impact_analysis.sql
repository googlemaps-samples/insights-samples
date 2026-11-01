-- Job ID: rmisamplesql_up2_YYYYMMDDHHMMSS
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

-- Urban Planner Query 2: Before-and-After Impact Analysis (with Closure Auditing)
-- Business Question: Has the average travel time on routes passing through a recent construction zone improved since the project's completion date, accounting for full road closures?
-- Use Case: Provides empirical evidence of infrastructure project success, validating whether road improvements reduced congestion and eliminated closure disruptions.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  ANALYTICAL PATTERN: Spatial & Milestone Join with Road Closure Defense
  This query uses a DECLARE statement for the study area geometry to ensure 
  BigQuery treats the polygon as a constant, enabling efficient spatial 
  indexing during the ST_INTERSECTS join. It joins routes_status on STATUS_RUNNING
  and accounts for has_road_closure so closures are not silently dropped.
*/

-- Study Area: Downtown Boston Intersection
DECLARE study_area GEOGRAPHY DEFAULT ST_GEOGFROMTEXT('POLYGON((-71.06 42.35, -71.05 42.35, -71.05 42.34, -71.06 42.34, -71.06 42.35))');
-- Project Milestone: Date when construction was completed
DECLARE completion_date DATE DEFAULT '2026-07-15';

WITH impact_data AS (
  SELECT
    h.selected_route_id,
    h.record_time,
    h.has_road_closure,
    -- Split records into 'Before' and 'After' buckets
    DATE(h.record_time) >= completion_date AS is_after_completion,
    SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds) AS delay_ratio
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  WHERE ST_INTERSECTS(h.route_geometry, study_area)
    AND s.status = 'STATUS_RUNNING'
    AND h.record_time BETWEEN '2026-07-01' AND '2026-07-30'
    AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
    AND (h.static_duration_in_seconds > 0 OR h.has_road_closure IS TRUE)
)
SELECT
  is_after_completion,
  -- Average delay ratio during passable periods
  ROUND(AVG(CASE WHEN COALESCE(has_road_closure, FALSE) IS FALSE THEN delay_ratio END), 3) AS avg_delay_ratio,
  -- Track closure incidents explicitly to evaluate project impact on road availability
  COUNTIF(has_road_closure IS TRUE) AS closure_incidents,
  COUNTIF(COALESCE(has_road_closure, FALSE) IS FALSE AND delay_ratio IS NOT NULL) AS valid_observations,
  COUNT(*) AS total_samples
FROM impact_data
GROUP BY 1
ORDER BY 1;
