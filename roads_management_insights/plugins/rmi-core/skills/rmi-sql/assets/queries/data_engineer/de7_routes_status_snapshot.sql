-- Job ID: rmisamplesql_de7_YYYYMMDDHHMMSS
-- Persona: data_engineer
-- Purpose: RMI BigQuery Analytical Query (de7)

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

-- Q7: Automate Daily Snapshot of Routes Status (Scheduled Query)
-- Business Question: How can I automate the historical tracking of my SelectedRoutes' status changes and routing configurations across all 12 metadata columns?
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB
-- Metadata: Inherits column descriptions from routes_status and adds snapshot metadata.

/*
  AUTOMATION EXAMPLE: 
  To schedule this snapshot daily at 2 AM UTC using the bq CLI, run:
  
  bq mk \
    --transfer_config \
    --project_id="your-project-id" \
    --data_source=scheduled_query \
    --display_name="Daily RMI Routes Status Snapshot" \
    --target_dataset="your_dataset" \
    --schedule="every 24 hours" \
    --params='{
      "query":"INSERT INTO `your-project.your-dataset.routes_status_history` SELECT CURRENT_TIMESTAMP() as snapshot_time, * FROM `LINKED_DATASET_NAME.routes_status`"
    }'
*/

-- STEP 1: Initialize the partitioned history table with all 12 inherited metadata columns
CREATE TABLE IF NOT EXISTS `your-project.your-dataset.routes_status_history` (
  snapshot_time TIMESTAMP OPTIONS(description="The UTC timestamp when this daily snapshot was captured."),
  selected_route_id STRING OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  status STRING OPTIONS(description="Current operational lifecycle state of the route at snapshot time (e.g., STATUS_RUNNING, STATUS_INVALID)."),
  validation_error STRING OPTIONS(description="Detailed error code explaining why the route is in STATUS_INVALID at snapshot time (NULL for valid running routes)."),
  low_road_usage_start_time TIMESTAMP OPTIONS(description="The UTC timestamp when low road usage was first detected during periodic re-validation."),
  route_attributes STRING OPTIONS(description="JSON-formatted flat string of custom key-value metadata attributes (up to 25 key-value pairs)."),
  dynamic_routing BOOLEAN OPTIONS(description="Indicates whether the route is configured for dynamic traffic rerouting (true) or fixed routing (false)."),
  origin GEOGRAPHY OPTIONS(description="Origin waypoint coordinate of the route as a GEOGRAPHY point."),
  destination GEOGRAPHY OPTIONS(description="Destination waypoint coordinate of the route as a GEOGRAPHY point."),
  intermediates ARRAY<GEOGRAPHY> OPTIONS(description="Repeated array of intermediate waypoint coordinates along the route."),
  static_route_geometry GEOGRAPHY OPTIONS(description="Polyline geometry of the static route calculated without live traffic from waypoints."),
  road_segment_ids ARRAY<STRING> OPTIONS(description="Sequence of Place IDs representing topological road segments along the static route.")
)
PARTITION BY DATE(snapshot_time)
CLUSTER BY selected_route_id
OPTIONS (
  description="Daily historical snapshots of SelectedRoutes status, routing geometry, and metadata across all 12 canonical routes_status columns."
);

-- STEP 2: The Periodic Append Logic (Manually executable version)
-- This statement appends the current state of all routes into the history table.
INSERT INTO `your-project.your-dataset.routes_status_history`
SELECT
  CURRENT_TIMESTAMP() as snapshot_time,
  selected_route_id,
  display_name,
  status,
  validation_error,
  low_road_usage_start_time,
  route_attributes,
  dynamic_routing,
  origin,
  destination,
  intermediates,
  static_route_geometry,
  road_segment_ids
FROM `LINKED_DATASET_NAME.routes_status`;
