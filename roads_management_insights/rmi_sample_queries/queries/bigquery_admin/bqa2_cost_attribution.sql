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

-- BigQuery Admin Query 2: Cost Attribution Audit (Missing Prefixes)
-- Business Question: Identify any BigQuery jobs missing the mandatory 'rmisqlfactory_' prefix in their job IDs.
-- Use Case: Ensures compliance with project governance standards. Consistent job ID prefixing is required for accurate cost attribution and auditing of RMI-related analysis.
-- Product Stage: GA (Uses BigQuery INFORMATION_SCHEMA)
-- Estimated Bytes Processed: N/A (Metadata Query)

/*
  NOTE: 'rmisqlfactory_' is the mandatory job ID prefix for this workspace.
  This allows administrators to filter billing logs and correlate spend 
  with specific personas or tools.
  
  SCOPE NOTE: Replace 'JOBS' with 'JOBS_BY_ORGANIZATION' if you have the 
  necessary permissions to audit spend across multiple projects.
*/

SELECT
  job_id,
  user_email,
  creation_time,
  total_bytes_billed,
  -- Provide the query text to help identify the source of the non-compliant job
  query
FROM `region-us`.INFORMATION_SCHEMA.JOBS
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND job_type = 'QUERY'
  -- Filter for jobs that missed the mandatory prefix
  AND NOT STARTS_WITH(job_id, 'rmisqlfactory_')
  -- Only audit jobs that were targeting RMI core tables
  AND (
    query LIKE '%historical_travel_time%' 
    OR query LIKE '%recent_roads_data%' 
    OR query LIKE '%routes_status%'
  )
ORDER BY creation_time DESC;
