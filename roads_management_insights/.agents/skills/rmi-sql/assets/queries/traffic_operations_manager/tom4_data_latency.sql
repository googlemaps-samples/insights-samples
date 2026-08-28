-- Job ID: rmisqlfactory_tom4_YYYYMMDDHHMMSS
-- Persona: traffic_operations_manager
-- Purpose: RMI BigQuery Analytical Query (tom4)

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

-- Traffic Operations Manager Query 4: Data Collection Latency
-- Business Question: Are there any active routes that have stopped sending data near the end of the snapshot period?
-- Use Case: Detects localized data gaps or "silent" routes in real-time, enabling operators to investigate issues before they impact reporting.
-- Product Stage: GA
-- Estimated Bytes Processed: ~151 MB (Requires JOIN with routes_status)

/*
  ANALYTICAL PATTERN: Freshness Monitoring
  By comparing the max record_time per route against the overall dataset 
  end-time, we can identify routes that have 'gone silent'.
*/

WITH last_data_arrival AS (
  SELECT
    selected_route_id,
    -- Get the latest record timestamp for every route in the dataset
    MAX(record_time) AS last_arrival
  FROM `LINKED_DATASET_NAME.historical_travel_time`
  -- Focused partition scan for the full sample month
  WHERE ST_GEOMETRYTYPE(route_geometry) = 'ST_LineString' AND record_time BETWEEN '2026-07-01' AND '2026-07-30'
  GROUP BY 1
)
SELECT
  s.selected_route_id,
  s.display_name,
  l.last_arrival,
  -- Measured relative to the end of the sample period
  TIMESTAMP_DIFF(TIMESTAMP('2026-07-30 00:00:00'), l.last_arrival, MINUTE) as minutes_of_silence
FROM `LINKED_DATASET_NAME.routes_status` s
LEFT JOIN last_data_arrival l USING (selected_route_id)
-- Focus on routes that are supposed to be producing data
WHERE s.status = 'STATUS_RUNNING'
  -- Threshold: Highlight routes that haven't sent a record in the last few hours of the dataset
  AND l.last_arrival < TIMESTAMP('2026-07-29 21:55:00')
ORDER BY minutes_of_silence DESC;
