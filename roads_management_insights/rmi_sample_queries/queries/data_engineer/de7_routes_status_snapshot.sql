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
-- Business Question: How can I automate the historical tracking of my SelectedRoutes' status changes?
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
      "query":"INSERT INTO `your-project.your-dataset.routes_status_history` SELECT CURRENT_TIMESTAMP() as snapshot_time, * FROM `boston_oct_2025_sample_data.routes_status`"
    }'
*/

-- STEP 1: Initialize the partitioned history table with enriched metadata
CREATE TABLE IF NOT EXISTS `your-project.your-dataset.routes_status_history` (
  snapshot_time TIMESTAMP OPTIONS(description="The UTC timestamp when this snapshot was captured."),
  selected_route_id STRING OPTIONS(description="Unique identifier for the SelectedRoute resource."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route."),
  status STRING OPTIONS(description="Current operational state (e.g., STATUS_RUNNING, STATUS_INVALID)."),
  validation_error STRING OPTIONS(description="Detailed reason if the route failed validation."),
  low_road_usage_start_time TIMESTAMP OPTIONS(description="Timestamp when low road usage was first detected."),
  route_attributes STRING OPTIONS(description="JSON string of custom business metadata.")
)
PARTITION BY DATE(snapshot_time)
CLUSTER BY selected_route_id;

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
  route_attributes
FROM `boston_oct_2025_sample_data.routes_status`;
