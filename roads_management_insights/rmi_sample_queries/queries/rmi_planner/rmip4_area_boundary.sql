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

-- RMI Seller Query 4: Create Reusable Area Boundary
-- Business Question: How can I create a reusable, open-source administrative boundary for my target study area?
-- Use Case: Establishes a "Master Boundary" for a city or region using public data. This view can then be joined with RMI tables to automate geofencing and localized reporting.
-- Product Stage: GA
-- Estimated Bytes Processed: ~1 MB (Uses BigQuery Public Dataset: Overture Maps)

/*
  NOTE: This query creates a persistent view of a target city's official boundary.
  The source dataset (e.g., `boston_oct_2025_sample_data`) is read-only.
  This view MUST be created in a separate, writable dataset within your project.
  Replace `your-project.your-dataset` with your target location.
*/

CREATE OR REPLACE VIEW `your-project.your-dataset.target_area_boundary` 
(
  division_id OPTIONS(description="Stable identifier for the administrative division."),
  area_name OPTIONS(description="The primary display name (e.g. Boston)."),
  region OPTIONS(description="The ISO state/province code (e.g. US-MA)."),
  country OPTIONS(description="The ISO country code."),
  geometry OPTIONS(description="The physical land boundary of the division as a GEOGRAPHY polygon.")
)
OPTIONS(
  description="A reusable administrative boundary for geofencing RMI analytical assets."
)
AS
SELECT 
  id AS division_id,
  names.primary AS area_name,
  region,
  country,
  geometry
FROM `bigquery-public-data.overture_maps.division_area`
WHERE names.primary = 'Boston' 
  AND country = 'US' 
  AND region = 'US-MA'
  AND class = 'land';
