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

-- BigQuery Admin Query 3: Identify Derived Tables and Views
-- Business Question: What tables or views in my project are derived from the core RMI dataset?
-- Use Case: Critical for lineage auditing and change management. Identifies 'shadow' analytical assets that may need to be updated or retired if the core RMI schema changes.
-- Product Stage: GA (Uses BigQuery INFORMATION_SCHEMA)
-- Estimated Bytes Processed: N/A (Metadata Query)

/*
  LINEAGE PATTERN: Metadata Dependency Mapping
  This query scans the project metadata to find any VIEW definition that 
  references RMI core tables, as well as any clones or snapshots 
  targeting 'rmi' or 'road' named resources.
*/

-- Replace `your-project.your-dataset` with the location of your analytical workspace.

SELECT
  table_schema AS dataset_id,
  table_name AS resource_name,
  'VIEW' AS type,
  -- view_definition allows the admin to see the exact transformation logic
  view_definition as lineage_detail
FROM `your-project.your-dataset.INFORMATION_SCHEMA.VIEWS`
WHERE (
    view_definition LIKE '%historical_travel_time%' 
    OR view_definition LIKE '%recent_roads_data%' 
    OR view_definition LIKE '%routes_status%'
  )

UNION ALL

-- Also identify Clones and Snapshots (cost-effective analytical patterns)
SELECT
  table_schema AS dataset_id,
  table_name AS resource_name,
  table_type AS type,
  'N/A (Check Table Metadata for Base Table Lineage)' AS lineage_detail
FROM `your-project.your-dataset.INFORMATION_SCHEMA.TABLES`
WHERE (table_name LIKE '%rmi%' OR table_name LIKE '%road%')
  AND table_type IN ('BASE TABLE', 'CLONE', 'SNAPSHOT')
  -- Exclude the raw source tables themselves
  AND table_name NOT IN ('historical_travel_time', 'recent_roads_data', 'routes_status')

ORDER BY dataset_id, resource_name;
