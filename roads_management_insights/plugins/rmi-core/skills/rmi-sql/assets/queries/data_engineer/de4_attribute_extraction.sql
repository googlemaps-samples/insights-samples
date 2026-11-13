-- Job ID: rmisamplesql_de4_YYYYMMDDHHMMSS
-- Persona: data_engineer
-- Purpose: RMI BigQuery Analytical Query (de4)

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

-- Data Engineer Query 4: Attribute Extraction
-- Business Question: Write a query that pivots JSON route_attributes into distinct columns, supporting up to 25 custom metadata pairs.
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB
-- Metadata: Enriches pivoted columns with business definitions.

CREATE OR REPLACE VIEW `your-project.your-dataset.routes_enriched_attributes`
(
  selected_route_id OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  static_route_geometry OPTIONS(description="Polyline geometry of the static route calculated without live traffic from waypoints."),
  region OPTIONS(description="The geographical business region extracted from custom route_attributes.region."),
  tier OPTIONS(description="The service tier (e.g. priority, standard) extracted from custom route_attributes.tier."),
  priority OPTIONS(description="The operational monitoring priority level extracted from custom route_attributes.priority."),
  route_length_meters OPTIONS(description="The intended physical length of the route in meters, cast to FLOAT64 from custom route_attributes.route_length.")
)
OPTIONS(
  description="A denormalized view of SelectedRoute metadata, promoting custom JSON route_attributes (up to 25 key-value pairs) into typed top-level columns with inherited RMI definitions."
) AS
SELECT
  selected_route_id,
  static_route_geometry,
  JSON_VALUE(route_attributes, '$.region') as region,
  COALESCE(JSON_VALUE(route_attributes, '$.tier'), JSON_VALUE(route_attributes, '$.priority'), 'STANDARD_TIER') as tier,
  JSON_VALUE(route_attributes, '$.priority') as priority,
  -- route_attributes supports up to 25 key-value string pairs. Casting to FLOAT64 for numerical analysis.
  SAFE_CAST(COALESCE(JSON_VALUE(route_attributes, '$.route_length_meters'), JSON_VALUE(route_attributes, '$.route_length')) AS FLOAT64) as route_length_meters
FROM `LINKED_DATASET_NAME.routes_status`
WHERE status = 'STATUS_RUNNING'
  -- Geometry integrity: in routes_status, the static polyline column is static_route_geometry
  AND ST_GEOMETRYTYPE(static_route_geometry) = 'ST_LineString';
