-- Job ID: rmisamplesql_bqa6_YYYYMMDDHHMMSS
-- Persona: bigquery_admin
-- Purpose: RMI BigQuery Analytical Query (bqa6)

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

-- Q6: Data Characteristics and Complexity Audit
-- Business Question: What is the average spatial complexity (vertex count, length, binary size) and metadata size (routeAttributes) across telemetry and static status tables?
-- Product Stage: GA
-- Estimated Bytes Processed: ~450 MB (Full scan of geometry and attributes)

/*
  This query performs a deep audit of the data payload across all 3 primary tables.
  In routes_status, spatial metrics are computed directly from static_route_geometry.
*/

-- Historical Spatial Complexity
SELECT
  'historical_travel_time' as table_name,
  COUNT(DISTINCT selected_route_id) as unique_routes,
  AVG(BYTE_LENGTH(ST_ASBINARY(route_geometry))) as avg_geom_bytes,
  AVG(ST_LENGTH(route_geometry) / 1000) as avg_route_length_km,
  AVG(ST_NUMPOINTS(route_geometry)) as avg_num_points,
  SAFE_CAST(NULL AS FLOAT64) as avg_attr_bytes
FROM `LINKED_DATASET_NAME.historical_travel_time`
WHERE ST_GEOMETRYTYPE(route_geometry) = 'ST_LineString' AND record_time BETWEEN '2026-07-01' AND '2026-07-30'

UNION ALL

-- Recent Spatial Complexity (Enriched)
SELECT
  'recent_roads_data' as table_name,
  COUNT(DISTINCT selected_route_id) as unique_routes,
  AVG(BYTE_LENGTH(ST_ASBINARY(route_geometry))) as avg_geom_bytes,
  AVG(ST_LENGTH(route_geometry) / 1000) as avg_route_length_km,
  AVG(ST_NUMPOINTS(route_geometry)) as avg_num_points,
  SAFE_CAST(NULL AS FLOAT64) as avg_attr_bytes
FROM `LINKED_DATASET_NAME.recent_roads_data`
WHERE record_time BETWEEN '2026-07-01' AND '2026-07-30'

UNION ALL

-- Status Metadata & Static Route Complexity
SELECT
  'routes_status' as table_name,
  COUNT(DISTINCT selected_route_id) as unique_routes,
  AVG(BYTE_LENGTH(ST_ASBINARY(static_route_geometry))) as avg_geom_bytes,
  AVG(ST_LENGTH(static_route_geometry) / 1000) as avg_route_length_km,
  AVG(ST_NUMPOINTS(static_route_geometry)) as avg_num_points,
  AVG(BYTE_LENGTH(route_attributes)) as avg_attr_bytes
FROM `LINKED_DATASET_NAME.routes_status`
WHERE ST_GEOMETRYTYPE(static_route_geometry) = 'ST_LineString';
