-- Job ID: rmisamplesql_de2_YYYYMMDDHHMMSS
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
-- Business Question: Write a query that produces a "cleaned" active version of the routes_status table, correctly casting route_length and exposing modern routing geometry and segment columns.
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
  status OPTIONS(description="The current operational lifecycle state of the route (STATUS_RUNNING)."),
  validation_error OPTIONS(description="Detailed error code explaining why a route is in STATUS_INVALID (NULL for valid running routes)."),
  dynamic_routing OPTIONS(description="Indicates whether the route is dynamic (true) or fixed (false)."),
  static_route_geometry OPTIONS(description="Polyline geometry of the static route calculated without live traffic from waypoints."),
  road_segment_ids OPTIONS(description="Sequence of Place IDs representing topological road segments along the static route."),
  route_length_meters OPTIONS(description="The pre-computed intended route length in meters, cast to FLOAT64 from custom route_attributes.route_length.")
)
OPTIONS(
  description="A cleaned view of active SelectedRoutes status, ensuring STATUS_RUNNING and exposing typed geometry and topological metadata."
)
AS
SELECT
  selected_route_id,
  display_name,
  status,
  validation_error,
  dynamic_routing,
  static_route_geometry,
  road_segment_ids,
  SAFE_CAST(COALESCE(JSON_VALUE(route_attributes, '$.route_length_meters'), JSON_VALUE(route_attributes, '$.route_length')) AS FLOAT64) AS route_length_meters
FROM `LINKED_DATASET_NAME.routes_status`
WHERE status = 'STATUS_RUNNING';
