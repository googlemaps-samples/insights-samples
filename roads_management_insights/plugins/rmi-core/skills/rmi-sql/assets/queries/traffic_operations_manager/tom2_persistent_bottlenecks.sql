-- Job ID: rmisamplesql_tom2_YYYYMMDDHHMMSS
-- Persona: traffic_operations_manager
-- Purpose: RMI BigQuery Analytical Query (tom2)

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

-- Traffic Operations Manager Query 2: Persistent Bottlenecks (Segment-Level Offsets)
-- Business Question: Which routes and segments suffer from persistent traffic jams (TRAFFIC_JAM / TRAFFIC_JAM_HEAVY), and what is the physical distance (meters/km) in congestion?
-- Use Case: Locates recurring local bottlenecks within monitored corridors, quantifying both standstill gridlock and standard congestion mileage to guide operational intervention.
-- Product Stage: GA
-- Estimated Bytes Processed: ~120 MB (Optimized via speed_reading_offsets integer arithmetic)

/*
  ANALYTICAL PATTERN: SRI Unnesting with Modern Offsets
  RMI routes store segment-level traffic states in speed_reading_offsets.
  This query unpacks that array to audit the frequency and physical length
  of severe congestion (TRAFFIC_JAM and TRAFFIC_JAM_HEAVY) using pure integer arithmetic.
*/

WITH congested_offsets AS (
  SELECT
    r.selected_route_id,
    s.display_name,
    r.record_time,
    sro.speed,
    -- Compute physical interval length in meters via integer offset subtraction
    (sro.end_offset - sro.start_offset) AS interval_length_meters
  FROM `LINKED_DATASET_NAME.recent_roads_data` AS r
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  LEFT JOIN UNNEST(r.speed_reading_offsets) AS sro
  WHERE r.record_time BETWEEN '2026-07-01' AND '2026-07-30'
    AND s.status = 'STATUS_RUNNING'
    AND (r.has_road_closure IS FALSE OR r.has_road_closure IS NULL)
    AND ST_GEOMETRYTYPE(r.route_geometry) = 'ST_LineString'
    -- Focus exclusively on severe and standard traffic congestion tiers
    AND sro.speed IN ('TRAFFIC_JAM', 'TRAFFIC_JAM_HEAVY')
)
SELECT
  selected_route_id,
  display_name,
  -- Count total congestion interval occurrences
  COUNT(*) AS total_congested_intervals,
  -- Break out counts by congestion severity
  COUNTIF(speed = 'TRAFFIC_JAM_HEAVY') AS heavy_jam_occurrences,
  COUNTIF(speed = 'TRAFFIC_JAM') AS standard_jam_occurrences,
  -- Aggregate physical distance in congestion (km)
  ROUND(SUM(interval_length_meters) / 1000.0, 2) AS total_congested_km,
  ROUND(SUM(CASE WHEN speed = 'TRAFFIC_JAM_HEAVY' THEN interval_length_meters ELSE 0 END) / 1000.0, 2) AS heavy_jam_km,
  ROUND(AVG(interval_length_meters), 1) AS avg_congested_interval_meters
FROM congested_offsets
GROUP BY 1, 2
ORDER BY heavy_jam_km DESC, total_congested_km DESC
LIMIT 10;
