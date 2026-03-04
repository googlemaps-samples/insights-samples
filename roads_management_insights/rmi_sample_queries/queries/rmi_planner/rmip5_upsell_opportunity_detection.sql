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

-- Q5: Identifying High-Value Infrastructure Opportunities
-- Business Question: Which customers are monitoring routes that traverse critical road infrastructure (like Controlled Access highways)?
-- Use Case: This query pinpoint accounts that are currently tracking travel-time metrics for abstract corridors but lack visibility into the underlying physical road network. By identifying intersections with high-priority road segments, we can demonstrate the value of upgrading to deeper segment-level analytics and road-class performance benchmarks.
-- Product Stage: Preview
-- Estimated Bytes Processed: ~5 MB

-- Note: This query performs a spatial join between user-defined SelectedRoutes and the physical Google Road Network dataset.
...
ORDER BY highway_segment_intersections DESC;

WITH highway_segments AS (
  SELECT
    place_id,
    geometry
  FROM `your-preview-project.preview_dataset.google_road_network`
  WHERE priority = 'ROAD_PRIORITY_CONTROLLED_ACCESS'
),
route_geometries AS (
  SELECT
    selected_route_id,
    -- Extracting owner/customer from route_attributes for targeting
    JSON_EXTRACT_SCALAR(route_attributes, '$.customer_id') AS customer_id,
    ST_GEOGFROMTEXT(geometry) AS route_geom
  FROM `boston_oct_2025_sample_data.routes_status`
  WHERE status = 'RUNNING'
)
SELECT
  r.customer_id,
  r.selected_route_id,
  COUNT(h.place_id) AS highway_segment_intersections
FROM route_geometries r
JOIN highway_segments h ON ST_INTERSECTS(r.route_geom, h.geometry)
GROUP BY 1, 2
HAVING highway_segment_intersections > 0
ORDER BY highway_segment_intersections DESC;
