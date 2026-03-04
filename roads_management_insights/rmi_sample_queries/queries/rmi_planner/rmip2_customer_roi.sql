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

-- RMI Seller Query 2: Customer ROI (Value at Risk)
-- Business Question: How much total time is lost to congestion across different customer service tiers?
-- Use Case: Translates raw traffic data into "Business Value" by quantifying the potential time savings for priority routes, justifying the monitoring cost and providing a clear ROI for the customer.
-- Product Stage: GA
-- Estimated Bytes Processed: < 1 MB (Standard SQL on RMI Tables)

SELECT
  JSON_EXTRACT_SCALAR(route_attributes, '$.tier') as service_tier,
  -- Aggregate total lost time (Actual - Free-flow) converted to hours
  ROUND(SUM(duration_in_seconds - static_duration_in_seconds) / 3600, 1) as total_delay_hours,
  COUNT(DISTINCT h.selected_route_id) as monitored_routes,
  -- Average performance multiplier
  ROUND(AVG(SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)), 2) as avg_delay_index
FROM `boston_oct_2025_sample_data.historical_travel_time` h
JOIN `boston_oct_2025_sample_data.routes_status` s ON h.selected_route_id = s.selected_route_id
WHERE h.record_time BETWEEN '2025-10-01' AND '2025-11-01'
  -- Filter for records where actual was slower than free-flow
  AND (duration_in_seconds - static_duration_in_seconds) > 0
GROUP BY 1
HAVING service_tier IS NOT NULL
ORDER BY total_delay_hours DESC;
