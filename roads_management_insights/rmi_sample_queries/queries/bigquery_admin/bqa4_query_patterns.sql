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

-- BigQuery Admin Query 4: Detect Repeated Query Patterns for Optimization
-- Business Question: What are the most frequent query patterns (joins, filters, JSON extractions) that could benefit from optimized downstream tables?
-- Use Case: Enables pro-active optimization. If many users are extracting the same JSON attribute or joining the same tables daily, the Admin can create a materialized view or flattened table to improve performance and reduce costs.
-- Product Stage: GA (Uses BigQuery INFORMATION_SCHEMA)
-- Estimated Bytes Processed: N/A (Metadata Query)

/*
  OPTIMIZATION PATTERN: Pattern Mining
  This query analyzes your recent job history to identify common access patterns.
  
  Note: Replace 'region-us' with your actual BigQuery region.
*/

WITH job_history AS (
  SELECT
    query,
    total_bytes_processed
  FROM `region-us`.INFORMATION_SCHEMA.JOBS
  WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND job_type = 'QUERY'
    AND statement_type = 'SELECT'
    -- Heuristic: Focus on RMI-related queries
    AND (
      query LIKE '%historical_travel_time%' 
      OR query LIKE '%recent_roads_data%' 
      OR query LIKE '%routes_status%'
    )
),
patterns AS (
  SELECT
    query,
    -- Regex: Identify specific JSON attributes being extracted from 'route_attributes'
    REGEXP_EXTRACT_ALL(query, r"JSON_EXTRACT_SCALAR\(route_attributes, '([^']+)'\)") as extracted_attributes,
    -- Regex: Detect if the query performs SRI flattening (expensive unnest)
    REGEXP_CONTAINS(query, r"UNNEST\(speed_reading_intervals\)") as uses_sri_unnest,
    -- Regex: Detect common join patterns
    REGEXP_CONTAINS(query, r"JOIN\s+`[^`]+historical_travel_time`") AND REGEXP_CONTAINS(query, r"JOIN\s+`[^`]+routes_status`") as joins_hist_and_status
  FROM job_history
)
SELECT
  'Frequent Attribute Extraction' as pattern_type,
  attr as detail,
  COUNT(*) as frequency
FROM patterns, UNNEST(extracted_attributes) as attr
GROUP BY 1, 2

UNION ALL

SELECT
  'Heavy SRI Processing' as pattern_type,
  'Uses UNNEST(speed_reading_intervals)' as detail,
  COUNT(*) as frequency
FROM patterns
WHERE uses_sri_unnest
GROUP BY 1, 2

UNION ALL

SELECT
  'Common Table Joins' as pattern_type,
  'Joins historical_travel_time and routes_status' as detail,
  COUNT(*) as frequency
FROM patterns
WHERE joins_hist_and_status
GROUP BY 1, 2

ORDER BY frequency DESC;
