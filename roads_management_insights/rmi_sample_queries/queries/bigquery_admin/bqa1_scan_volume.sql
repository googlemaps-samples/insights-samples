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

-- BigQuery Admin Query 1: Scan Volume Monitoring by User
-- Business Question: Which users or service accounts are generating the highest scan volume against RMI tables this month?
-- Use Case: Enables cost governance by identifying 'heavy' consumers of the RMI dataset. Administrators can use this data to justify budget reallocations or suggest query optimizations to specific teams.
-- Product Stage: GA (Uses BigQuery INFORMATION_SCHEMA)
-- Estimated Bytes Processed: N/A (Metadata Query)

/*
  AUDIT PATTERN: Job Metadata Analysis
  This query scans the system-managed JOBS view. It calculates total data scanned 
  (billed bytes) for any query that mentions core RMI table names.
  
  Note: Replace 'region-us' with the specific region where your dataset resides.
*/

SELECT
  user_email,
  -- Convert bytes to GB for readable billing analysis
  SUM(total_bytes_billed) / POW(1024, 3) AS total_gb_billed,
  COUNT(*) AS job_count,
  -- Average scan size helps distinguish between 'many small queries' vs 'one massive scan'
  AVG(total_bytes_billed) / POW(1024, 3) AS avg_gb_per_job
FROM `region-us`.INFORMATION_SCHEMA.JOBS
WHERE creation_time BETWEEN TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), MONTH) AND CURRENT_TIMESTAMP()
  AND job_type = 'QUERY'
  -- Heuristic filter: Look for queries mentioning RMI core tables
  AND (
    query LIKE '%historical_travel_time%' 
    OR query LIKE '%recent_roads_data%' 
    OR query LIKE '%routes_status%'
  )
GROUP BY 1
ORDER BY total_gb_billed DESC
LIMIT 10;
