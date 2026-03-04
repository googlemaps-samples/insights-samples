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

-- Q6: Load Latest SelectedRoutes Snapshot to BigQuery
-- Business Question: How can I load a point-in-time snapshot of all SelectedRoutes from the API into a BigQuery table?
-- Product Stage: Preview (Uses BigQuery Remote Functions / External Query pattern)
-- Estimated Bytes Processed: N/A (External API Connection)

-- Note: This query provides a template for a periodic load job.
-- It assumes you have a Remote Function or External Connection configured to call the Roads Selection API.
-- Replace `your-project.your-dataset` and connection details with your actual configuration.

-- Step 1: Create a staging table for the snapshot
-- CREATE OR REPLACE TABLE `your-project.your-dataset.selected_routes_snapshot_staging` AS
SELECT
  CURRENT_TIMESTAMP() as snapshot_time,
  route.name as selected_route_id,
  route.displayName as display_name,
  route.state as status,
  route.validationError as validation_error,
  TO_JSON_STRING(route.routeAttributes) as route_attributes,
  TO_JSON_STRING(route.dynamicRoute) as dynamic_route_config
FROM (
  -- This represents a call to the Roads Selection API via a Remote Function
  -- In a real environment, you would use: SELECT * FROM EXTERNAL_QUERY("connection", "SELECT ...")
  -- Or call a specialized Remote Function that handles pagination and API keys.
  SELECT * FROM UNNEST([
    STRUCT(
      'projects/moritani-roads/selectedRoutes/route-123' as name,
      'Commuter Path A' as displayName,
      'STATUS_RUNNING' as state,
      'VALIDATION_ERROR_UNSPECIFIED' as validationError,
      STRUCT('priority' as tier, 'north' as region) as routeAttributes,
      STRUCT(STRUCT(42.36 as latitude, -71.06 as longitude) as origin) as dynamicRoute
    )
  ])
) as route;

-- Step 2: (Optional) Append to a historical tracking table
-- INSERT INTO `your-project.your-dataset.selected_routes_history`
-- SELECT * FROM `your-project.your-dataset.selected_routes_snapshot_staging`;
