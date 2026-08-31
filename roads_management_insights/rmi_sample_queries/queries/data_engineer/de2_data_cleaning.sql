-- Job ID: rmisqlfactory_de2_YYYYMMDDHHMMSS
-- Persona: data_engineer
-- Purpose: RMI BigQuery Analytical Query (de2)

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

-- Data Engineer Query 2: Data Cleaning Transformation
-- Business Question: Write a query that produces a "cleaned" version of the routes_status table, correctly casting the route_length.
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB
-- Metadata: Provides descriptions for transformed fields and the view itself.

/*
  PRE-REQUISITE: This query utilizes the custom routeAttribute 'route_length' 
  (intended physical length in meters), which has been pre-configured for 
  all routes in this sample dataset.
*/

CREATE OR REPLACE VIEW `your-project.your-dataset.routes_status_cleaned`
(
  selected_route_id OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  status OPTIONS(description="The current operational lifecycle state of the route (e.g., STATUS_RUNNING, STATUS_VALIDATING)."),
  validation_error OPTIONS(description="Detailed error code explaining why a route is in STATUS_INVALID (NULL for valid running routes)."),
  route_length_meters OPTIONS(description="The pre-computed intended route length in meters, cast to FLOAT64 from custom route_attributes.route_length.")
)
OPTIONS(
  description="A cleaned view of SelectedRoutes status, excluding invalid routes and promoting custom route_attributes to typed columns with inherited RMI metadata."
)
AS
SELECT
  selected_route_id,
  display_name,
  status,
  validation_error,
  SAFE_CAST(COALESCE(JSON_VALUE(route_attributes, '$.route_length_meters'), JSON_VALUE(route_attributes, '$.route_length')) AS FLOAT64) AS route_length_meters
FROM `LINKED_DATASET_NAME.routes_status`
WHERE status != 'STATUS_INVALID';
