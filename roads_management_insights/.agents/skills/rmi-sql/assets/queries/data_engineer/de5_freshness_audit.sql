-- Job ID: rmisqlfactory_de5_YYYYMMDDHHMMSS
-- Persona: data_engineer
-- Purpose: RMI BigQuery Analytical Query (de5)

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

-- Data Engineer Query 5: Data Freshness Audit
-- Business Question: Which active routes have stopped receiving updates, indicating potential data gaps?
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB
-- Metadata: Provides descriptions for the audit results.

/*
  AUDIT GOAL: Identify routes that are 'STATUS_RUNNING' but have no recent 
  records in historical_travel_time. This helps detect routes with 
  insufficient traffic or pipeline latency issues.
*/

CREATE OR REPLACE VIEW `your-project.your-dataset.route_freshness_audit`
(
  selected_route_id OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  last_updated OPTIONS(description="The UTC timestamp of the most recent telemetry record found in historical_travel_time."),
  hours_since_last_update OPTIONS(description="The age of the telemetry data in hours relative to the reference audit timestamp.")
)
OPTIONS(
  description="Operational audit view identifying active routes with missing or stale travel time telemetry data."
) AS
WITH freshness AS (
  SELECT
    selected_route_id,
    MAX(record_time) as last_updated
  FROM `LINKED_DATASET_NAME.historical_travel_time`
  -- Scans the full sample month to find the latest record for every route
  WHERE ST_GEOMETRYTYPE(route_geometry) = 'ST_LineString' AND record_time BETWEEN '2026-06-01' AND '2026-06-30'
  GROUP BY 1
)
SELECT
  s.selected_route_id,
  s.display_name,
  f.last_updated,
  -- Using '2026-06-30' as the reference 'Now' for this static sample dataset
  TIMESTAMP_DIFF(TIMESTAMP('2026-06-30'), f.last_updated, HOUR) AS hours_since_last_update
FROM `LINKED_DATASET_NAME.routes_status` s
LEFT JOIN freshness f USING(selected_route_id)
-- Focus on routes that SHOULD be providing data
WHERE s.status = 'STATUS_RUNNING'
ORDER BY hours_since_last_update DESC;
