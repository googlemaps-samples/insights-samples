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

-- Data Scientist Query 2: Route Similarity Clustering (Feature-Based)
-- Business Question: Which routes exhibit similar traffic patterns based on their average peak-hour delay ratios?
-- Use Case: Grouping routes by behavioral similarity allows planners to apply similar mitigation strategies to entire clusters of road segments rather than analyzing each route individually.
-- Product Stage: GA
-- Estimated Bytes Processed: ~150 MB

/*
  INTERPRETATION GUIDE:
  Routes assigned to the same 'cluster_id' share a similar diurnal traffic profile 
  (the relationship between AM, Midday, and PM delays).
  
  Example Interpretation:
  - Cluster 1: Commuter Heavy (High AM/PM delay, low Midday).
  - Cluster 2: Consistently Efficient (Delay ratio near 1.0 all day).
  - Cluster 3: Midday Bottleneck (High Midday delay, typical AM/PM).
*/

-- Step 1: Create the K-Means model.
-- NOTE: The source dataset (e.g., `boston_oct_2025_sample_data`) is a read-only subscription.
-- This model MUST be created in a separate, writable dataset within your project.
-- Replace `your-project.your-dataset` with your target location.

CREATE OR REPLACE MODEL `your-project.your-dataset.route_clusters`
OPTIONS(model_type='kmeans', num_clusters=5) AS
SELECT
  -- K-Means works with numerical features. We will use the delay ratios as features.
  COALESCE(AVG(CASE WHEN EXTRACT(HOUR FROM DATETIME(record_time, 'America/New_York')) BETWEEN 7 AND 9 THEN SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) END), 1.0) AS avg_am_delay,
  COALESCE(AVG(CASE WHEN EXTRACT(HOUR FROM DATETIME(record_time, 'America/New_York')) BETWEEN 12 AND 14 THEN SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) END), 1.0) AS avg_midday_delay,
  COALESCE(AVG(CASE WHEN EXTRACT(HOUR FROM DATETIME(record_time, 'America/New_York')) BETWEEN 16 AND 18 THEN SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) END), 1.0) AS avg_pm_delay
FROM `boston_oct_2025_sample_data.historical_travel_time`
WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
GROUP BY selected_route_id;

-- Step 2: Predict the cluster for each route using the trained model.
WITH route_features AS (
  SELECT
    selected_route_id,
    display_name,
    COALESCE(AVG(CASE WHEN EXTRACT(HOUR FROM DATETIME(record_time, 'America/New_York')) BETWEEN 7 AND 9 THEN SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) END), 1.0) AS avg_am_delay,
    COALESCE(AVG(CASE WHEN EXTRACT(HOUR FROM DATETIME(record_time, 'America/New_York')) BETWEEN 12 AND 14 THEN SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) END), 1.0) AS avg_midday_delay,
    COALESCE(AVG(CASE WHEN EXTRACT(HOUR FROM DATETIME(record_time, 'America/New_York')) BETWEEN 16 AND 18 THEN SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds) END), 1.0) AS avg_pm_delay
  FROM `boston_oct_2025_sample_data.historical_travel_time`
  WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
  GROUP BY 1, 2
)
SELECT
  selected_route_id,
  display_name,
  CENTROID_ID AS cluster_id,
  ROUND(avg_am_delay, 2) as am_ratio,
  ROUND(avg_midday_delay, 2) as midday_ratio,
  ROUND(avg_pm_delay, 2) as pm_ratio
FROM ML.PREDICT(MODEL `your-project.your-dataset.route_clusters`,
  (SELECT * FROM route_features)
)
ORDER BY cluster_id, selected_route_id;
