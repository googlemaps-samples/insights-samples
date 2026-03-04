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

-- RMI Seller Query 3: Road Segment Estimation
-- Business Question: How many physical road segments exist in our target study area, categorized by class?
-- Use Case: Helps sales and solution architects estimate the "Total Addressable Monitoring" footprint for a city, aiding in pricing and coverage strategy.
-- Product Stage: GA
-- Estimated Bytes Processed: ~1 MB (Uses BigQuery Public Dataset: Overture Maps)

/*
  EXTERNAL DEPENDENCY: 
  RMI monitoring is based on user-defined routes. To understand the underlying 
  physical scale of an area, this query joins with the Overture Maps public 
  dataset to provide a baseline count of all physical road segments.
*/

WITH target_boundary AS (
  SELECT geometry
  FROM `bigquery-public-data.overture_maps.division_area`
  WHERE names.primary = 'Boston' 
    AND country = 'US' 
    AND region = 'US-MA'
    AND class = 'land'
)
SELECT
  -- Group by physical road classification (e.g., motorway, primary, local)
  class as road_class,
  subtype,
  COUNT(*) as segment_count,
  ROUND(SUM(ST_LENGTH(s.geometry)) / 1000, 2) as total_length_km
FROM `bigquery-public-data.overture_maps.segment` s
JOIN target_boundary b ON ST_INTERSECTS(s.geometry, b.geometry)
WHERE s.subtype = 'road'
GROUP BY 1, 2
ORDER BY segment_count DESC;
