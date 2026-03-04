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
-- Business Question: What is the average spatial complexity (vertex count) and metadata size (routeAttributes) of my actual records?
-- Product Stage: GA
-- Estimated Bytes Processed: ~450 MB (Full scan of geometry and attributes)

/*
  This query performs a deep audit of the data payload. 
  It is useful for understanding the impact of route precision and 
  custom attributes on storage and processing costs.
*/

-- Historical Spatial Complexity
SELECT
  'historical_travel_time' as table_name,
  COUNT(DISTINCT selected_route_id) as unique_routes,
  AVG(BYTE_LENGTH(ST_ASBINARY(route_geometry))) as avg_geom_bytes,
  AVG(ST_LENGTH(route_geometry) / 1000) as avg_route_length_km,
  AVG(ST_NUMPOINTS(route_geometry)) as avg_num_points,
  CAST(NULL AS FLOAT64) as avg_attr_bytes
FROM `boston_oct_2025_sample_data.historical_travel_time`
WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'

UNION ALL

-- Recent Spatial Complexity (Enriched)
SELECT
  'recent_roads_data' as table_name,
  COUNT(DISTINCT selected_route_id) as unique_routes,
  AVG(BYTE_LENGTH(ST_ASBINARY(route_geometry))) as avg_geom_bytes,
  AVG(ST_LENGTH(route_geometry) / 1000) as avg_route_length_km,
  AVG(ST_NUMPOINTS(route_geometry)) as avg_num_points,
  CAST(NULL AS FLOAT64) as avg_attr_bytes
FROM `boston_oct_2025_sample_data.recent_roads_data`
WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'

UNION ALL

-- Status Metadata Complexity
SELECT
  'routes_status' as table_name,
  COUNT(DISTINCT selected_route_id) as unique_routes,
  CAST(NULL AS FLOAT64) as avg_geom_bytes,
  CAST(NULL AS FLOAT64) as avg_route_length_km,
  CAST(NULL AS FLOAT64) as avg_num_points,
  AVG(BYTE_LENGTH(route_attributes)) as avg_attr_bytes
FROM `boston_oct_2025_sample_data.routes_status`;
