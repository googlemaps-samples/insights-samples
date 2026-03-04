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

-- BigQuery Admin Query 5: Identify Queries with Inefficient Partition Pruning
-- Business Question: Are there queries performing full table scans on 'historical_travel_time' instead of using the 'record_time' partition filter?
-- Use Case: Detects 'expensive' behavior. Since RMI datasets are partitioned by day on 'record_time', any query that doesn't include a temporal filter will scan the entire history, significantly increasing costs.
-- Product Stage: GA (Uses BigQuery INFORMATION_SCHEMA)
-- Estimated Bytes Processed: N/A (Metadata Query)

/*
  AUDIT PATTERN: Pruning Heuristics
  This query identifies large scans on the historical table. 
  It calculates if the 'total_bytes_processed' for a job is disproportionately 
  large compared to the typical size of a single daily partition.
  
  Note: Replace 'region-us' with your actual BigQuery region.
*/

SELECT
  job_id,
  user_email,
  query,
  -- Convert bytes to GB for readable performance auditing
  total_bytes_processed / POW(1024, 3) AS gb_processed,
  creation_time
FROM `region-us`.INFORMATION_SCHEMA.JOBS
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND job_type = 'QUERY'
  AND statement_type = 'SELECT'
  AND query LIKE '%historical_travel_time%'
  -- Heuristic: Trigger audit if scan volume exceeds 100 GB (adjustable baseline)
  -- This suggests the user might have missed a partition pruning filter (record_time)
  AND total_bytes_processed > 100 * POW(1024, 3) 
ORDER BY gb_processed DESC
LIMIT 10;
