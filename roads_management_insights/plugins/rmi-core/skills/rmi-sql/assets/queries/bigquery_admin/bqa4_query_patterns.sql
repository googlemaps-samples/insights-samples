-- Job ID: rmisamplesql_bqa4_YYYYMMDDHHMMSS
-- Persona: bigquery_admin
-- Purpose: RMI BigQuery Analytical Query (bqa4)

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

-- BigQuery Admin Query 4: Detect Repeated Query Patterns & SRI Migration Audit
-- Business Question: What are the most frequent query patterns, and what percentage of queries have migrated to speed_reading_offsets ahead of the Jan 13, 2027 sunset?
-- Use Case: Enables pro-active optimization, identifying hot attribute extractions, frequent joins, and tracking the retirement of deprecated speed_reading_intervals.
-- Product Stage: GA (Uses BigQuery INFORMATION_SCHEMA)
-- Estimated Bytes Processed: N/A (Metadata Query)

/*
  OPTIMIZATION PATTERN: Pattern Mining & Deprecation Tracking
  This query analyzes recent job history to identify common access patterns
  and measures workload readiness for the January 13, 2027 sunset of speed_reading_intervals.
  
  Note: Replace 'region-us' with your actual BigQuery region.
*/

WITH job_history AS (
  SELECT
    query,
    total_bytes_processed
  FROM `region-us`.INFORMATION_SCHEMA.JOBS
  -- Fast interactive audit default (7 days). Expand to INTERVAL 30 DAY for monthly governance reviews.
  WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
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
    REGEXP_EXTRACT_ALL(query, r"(?:JSON_EXTRACT_SCALAR|JSON_VALUE)\(route_attributes, '([^']+)'\)") AS extracted_attributes,
    -- Regex: Detect modern offset unnest
    REGEXP_CONTAINS(query, r"UNNEST\(speed_reading_offsets\)") AS uses_modern_offsets,
    -- Regex: Detect deprecated interval unnest (sunsetting Jan 13, 2027)
    REGEXP_CONTAINS(query, r"UNNEST\(speed_reading_intervals\)") AS uses_legacy_intervals,
    -- Regex: Detect common join patterns
    REGEXP_CONTAINS(query, r"JOIN\s+`[^`]+historical_travel_time`") AND REGEXP_CONTAINS(query, r"JOIN\s+`[^`]+routes_status`") AS joins_hist_and_status
  FROM job_history
)
SELECT
  'Frequent Attribute Extraction' AS pattern_type,
  attr AS detail,
  COUNT(*) AS frequency
FROM patterns, UNNEST(extracted_attributes) AS attr
GROUP BY 1, 2

UNION ALL

SELECT
  'SRI Offsets Adoption (Modern)' AS pattern_type,
  'Uses UNNEST(speed_reading_offsets)' AS detail,
  COUNT(*) AS frequency
FROM patterns
WHERE uses_modern_offsets
GROUP BY 1, 2

UNION ALL

SELECT
  'Legacy SRI Processing (Sunset Jan 13, 2027)' AS pattern_type,
  'Uses deprecated UNNEST(speed_reading_intervals)' AS detail,
  COUNT(*) AS frequency
FROM patterns
WHERE uses_legacy_intervals
GROUP BY 1, 2

UNION ALL

SELECT
  'SRI Migration Progress' AS pattern_type,
  'Migration Percentage to Modern Offsets (%)' AS detail,
  CAST(ROUND(SAFE_DIVIDE(COUNTIF(uses_modern_offsets), COUNTIF(uses_modern_offsets) + COUNTIF(uses_legacy_intervals)) * 100) AS INT64) AS frequency
FROM patterns
WHERE uses_modern_offsets OR uses_legacy_intervals

UNION ALL

SELECT
  'Common Table Joins' AS pattern_type,
  'Joins historical_travel_time and routes_status' AS detail,
  COUNT(*) AS frequency
FROM patterns
WHERE joins_hist_and_status
GROUP BY 1, 2

ORDER BY frequency DESC;
