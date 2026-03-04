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

-- Q0: Metadata Inventory and Partition Overview
-- Business Question: How can I quickly check the row count and storage size of all RMI tables using zero-cost metadata queries?
-- Product Stage: GA
-- Estimated Bytes Processed: N/A (Metadata Query)

/*
  This query utilizes INFORMATION_SCHEMA.PARTITIONS to provide a high-level 
  overview of table scale and data accumulation trends. 
  It processes 0 bytes because it scans system metadata rather than table data.
*/

SELECT
  table_name,
  CASE 
    WHEN partition_id IS NULL OR partition_id = '__UNPARTITIONED__' THEN 'UNPARTITIONED' 
    ELSE partition_id 
  END as partition_id,
  total_rows,
  ROUND(total_logical_bytes / POW(1024, 2), 2) as size_mb,
  last_modified_time
FROM `boston_oct_2025_sample_data.INFORMATION_SCHEMA.PARTITIONS`
WHERE table_name IN ('historical_travel_time', 'recent_roads_data', 'routes_status')
  AND partition_id != '__NULL__'
ORDER BY table_name, partition_id DESC;
