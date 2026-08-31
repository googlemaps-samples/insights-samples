-- Job ID: rmisqlfactory_de1_YYYYMMDDHHMMSS
-- Persona: data_engineer
-- Purpose: RMI BigQuery Analytical Query (de1)

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

-- Data Engineer Query 1: Create Materialized Corridor Subset Table
-- Business Question: Generate a query to create a clustered materialized table of historical_travel_time for a specific corridor.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB
-- Metadata: Creates a clustered table with column-level descriptions to store a materialized extract from linked datasets.

-- ARCHITECTURAL NOTE: Analytics Hub shared datasets are read-only linked datasets.
-- BigQuery explicitly forbids 'CREATE MATERIALIZED VIEW' directly against linked tables.
-- Instead, we use 'CREATE OR REPLACE TABLE ... CLUSTER BY selected_route_id' with column-level
-- OPTIONS descriptions to materialize query outputs in a writable dataset, providing fast
-- downstream lookups without hitting linked table materialized view restrictions.
-- Replace `your-project.your-dataset` with your target location.

CREATE OR REPLACE TABLE `your-project.your-dataset.massachusetts_avenue_corridor`
(
  selected_route_id STRING OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  record_time TIMESTAMP OPTIONS(description="The UTC timestamp representing when the route data was computed. Daily partitioning column for pruning scans."),
  duration_in_seconds FLOAT64 OPTIONS(description="The traffic-aware duration of the route in seconds under observed real-time traffic conditions."),
  static_duration_in_seconds FLOAT64 OPTIONS(description="The traffic-unaware (static) duration of the route in seconds under ideal free-flow conditions."),
  route_geometry GEOGRAPHY OPTIONS(description="The traffic-aware optimal polyline geometry of the route as a GEOGRAPHY object (WKT, EPSG:4326).")
)
PARTITION BY DATE(record_time)
CLUSTER BY selected_route_id
OPTIONS (
  description="A 7-day materialized extract of RMI historical travel time data specifically for the Massachusetts Avenue corridor, inheriting canonical column descriptions."
) AS
SELECT
  selected_route_id,
  display_name,
  record_time,
  duration_in_seconds,
  static_duration_in_seconds,
  route_geometry
FROM `LINKED_DATASET_NAME.historical_travel_time`
WHERE record_time >= TIMESTAMP_SUB(TIMESTAMP('2026-07-29'), INTERVAL 7 DAY)
  AND display_name LIKE '%Massachusetts Avenue%'
  AND duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds > 0;
