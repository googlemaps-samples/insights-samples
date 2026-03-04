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
-- Business Question: Write a query that pivots the JSON route_attributes into distinct columns.
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB
-- Metadata: Enriches pivoted columns with business definitions.

CREATE OR REPLACE VIEW `your-project.your-dataset.routes_enriched_attributes`
(
  selected_route_id OPTIONS(description="Unique identifier for the SelectedRoute resource."),
  region OPTIONS(description="The geographical business region extracted from routeAttributes."),
  tier OPTIONS(description="The service tier (e.g. priority, standard) extracted from routeAttributes."),
  priority OPTIONS(description="The operational priority level assigned during registration."),
  route_length_meters OPTIONS(description="The intended physical length of the route in meters, cast to FLOAT64 from routeAttributes.")
)
OPTIONS(
  description="A denormalized view of SelectedRoute metadata, promoting custom JSON attributes into typed top-level columns."
)
AS
SELECT
  selected_route_id,
  JSON_EXTRACT_SCALAR(route_attributes, '$.region') as region,
  JSON_EXTRACT_SCALAR(route_attributes, '$.tier') as tier,
  JSON_EXTRACT_SCALAR(route_attributes, '$.priority') as priority,
  -- route_attributes values are always strings. Casting to FLOAT64 for numerical analysis.
  CAST(JSON_EXTRACT_SCALAR(route_attributes, '$.route_length') AS FLOAT64) as route_length_meters
FROM `boston_oct_2025_sample_data.routes_status`
-- Example: Filtering by priority attribute
-- WHERE JSON_EXTRACT_SCALAR(route_attributes, '$.priority') = 'high';
