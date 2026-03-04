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

-- Data Engineer Query 1: Create Materialized Subset
-- Business Question: Generate a query to create a 7-day materialized view of historical_travel_time for a specific corridor.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB
-- Metadata: Uses ALTER statements to apply technical descriptions to all columns and the view itself.

-- NOTE: The source dataset (e.g., `boston_oct_2025_sample_data`) is a read-only subscription from Analytics Hub.
-- This materialized view MUST be created in a separate, writable dataset within your project.
-- Replace `your-project.your-dataset` with your target location.

CREATE MATERIALIZED VIEW IF NOT EXISTS `your-project.your-dataset.storrow_drive_view`
CLUSTER BY selected_route_id AS
SELECT
  selected_route_id,
  display_name,
  record_time,
  duration_in_seconds,
  static_duration_in_seconds,
  route_geometry
FROM `boston_oct_2025_sample_data.historical_travel_time`
WHERE record_time >= TIMESTAMP_SUB(TIMESTAMP('2025-10-31'), INTERVAL 7 DAY)
  AND display_name LIKE '%Storrow-Drive%';

-- Applying view-level metadata
ALTER MATERIALIZED VIEW `your-project.your-dataset.storrow_drive_view`
SET OPTIONS (
  description="A 7-day rolling subset of RMI historical travel time data specifically for the Storrow Drive corridor."
);

-- Applying column-level metadata descriptions
ALTER COLUMN selected_route_id SET OPTIONS(description="Unique identifier for the SelectedRoute resource.")
ON `your-project.your-dataset.storrow_drive_view`;

ALTER COLUMN display_name SET OPTIONS(description="User-provided descriptive name for the route.")
ON `your-project.your-dataset.storrow_drive_view`;

ALTER COLUMN record_time SET OPTIONS(description="The UTC timestamp representing when the route data was computed.")
ON `your-project.your-dataset.storrow_drive_view`;

ALTER COLUMN duration_in_seconds SET OPTIONS(description="The traffic-aware duration of the route in seconds.")
ON `your-project.your-dataset.storrow_drive_view`;

ALTER COLUMN static_duration_in_seconds SET OPTIONS(description="The traffic-unaware (static) duration of the route in seconds.")
ON `your-project.your-dataset.storrow_drive_view`;

ALTER COLUMN route_geometry SET OPTIONS(description="The traffic-aware polyline geometry of the route as a GEOGRAPHY object.")
ON `your-project.your-dataset.storrow_drive_view`;
