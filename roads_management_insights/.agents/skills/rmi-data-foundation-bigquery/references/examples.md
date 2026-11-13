# Historical Roads Data Query Examples

This reference provides common SQL patterns for analyzing the `historical_travel_time` dataset.

## 1. Daily Average Travel Time per Route

Calculates the average traffic-aware duration for each route over the last 30 days.

```sql
SELECT
  selected_route_id,
  display_name,
  DATE(record_time) as record_date,
  AVG(duration_in_seconds) as avg_duration_seconds
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY
  1, 2, 3
ORDER BY
  3 DESC, 4 DESC;
```

## 2. Peak Hour vs. Free Flow Delay

Calculates the delay percentage during peak hours compared to static (free-flow) duration.

```sql
SELECT
  selected_route_id,
  display_name,
  EXTRACT(HOUR FROM record_time) as hour_of_day,
  AVG(duration_in_seconds) as avg_actual,
  AVG(static_duration_in_seconds) as avg_static,
  (AVG(duration_in_seconds) - AVG(static_duration_in_seconds)) / NULLIF(AVG(static_duration_in_seconds), 0) * 100 as delay_percentage
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY
  1, 2, 3
HAVING
  hour_of_day BETWEEN 7 AND 9 OR hour_of_day BETWEEN 16 AND 18
ORDER BY
  delay_percentage DESC;
```

## 3. Route Reliability (95th Percentile Travel Time)

Measures the variance in travel time to assess reliability.

```sql
SELECT
  selected_route_id,
  display_name,
  PERCENTILE_CONT(duration_in_seconds, 0.95) OVER(PARTITION BY selected_route_id) as p95_duration,
  AVG(duration_in_seconds) OVER(PARTITION BY selected_route_id) as avg_duration
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY);
```

## 4. Corridor Performance Audit

Aggregates data for multiple routes that form a corridor.

```sql
SELECT
  DATE(record_time) as day,
  SUM(duration_in_seconds) as corridor_total_duration,
  SUM(static_duration_in_seconds) as corridor_free_flow_duration
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  display_name LIKE '%Main St%'
  AND record_time >= '2025-10-01'
GROUP BY
  1
ORDER BY
  1;
```

## 5. Route Deviation Detection & Road Closure Correlation

Compares baseline road segment sequences in `routes_status` with observed segment sequences in `historical_travel_time` (post June 19, 2026). Detects dynamic detours and correlates deviation root cause with `has_road_closure` (full road closure vs. dynamic congestion rerouting).

```sql
SELECT 
  h.selected_route_id,
  h.record_time,
  s.display_name,
  s.dynamic_routing,
  h.duration_in_seconds,
  h.has_road_closure,
  -- Detect route deviation between static baseline and observed path
  TO_JSON_STRING(s.road_segment_ids) != TO_JSON_STRING(h.road_segment_ids) AS has_deviated,
  -- Count newly introduced detour segments
  (
    SELECT COUNT(1) 
    FROM UNNEST(h.road_segment_ids) AS obs_seg 
    WHERE obs_seg NOT IN (SELECT base_seg FROM UNNEST(s.road_segment_ids) AS base_seg)
  ) AS detour_segment_count,
  -- Categorize deviation root cause
  CASE 
    WHEN TO_JSON_STRING(s.road_segment_ids) != TO_JSON_STRING(h.road_segment_ids) AND h.has_road_closure IS TRUE 
      THEN 'DEVIATION_FULL_ROAD_CLOSURE'
    WHEN TO_JSON_STRING(s.road_segment_ids) != TO_JSON_STRING(h.road_segment_ids) AND COALESCE(h.has_road_closure, FALSE) = FALSE 
      THEN 'DEVIATION_CONGESTION_REROUTE'
    ELSE 'NOMINAL_BASELINE'
  END AS deviation_cause
FROM 
  `my_project.rmi_foundation.historical_travel_time` AS h
INNER JOIN 
  `my_project.rmi_foundation.routes_status` AS s
  ON h.selected_route_id = s.selected_route_id
WHERE 
  -- Temporal cutoff rule: road_segment_ids available from June 19, 2026 onwards
  h.record_time >= '2026-06-19'
  AND h.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY 
  h.record_time DESC,
  detour_segment_count DESC;
```

## 6. Multi-Criteria Route Discovery and Spatial Extraction (routes_status)

Extracts routes directly from `routes_status` using spatial bounding polygons, display name prefixes, JSON attributes, and traversed road segment Place IDs, superseding repetitive Roads Selection REST API calls.

```sql
SELECT 
  selected_route_id,
  display_name,
  dynamic_routing,
  JSON_EXTRACT_SCALAR(route_attributes, '$.priority') AS priority,
  JSON_EXTRACT_SCALAR(route_attributes, '$.corridor_type') AS corridor_type,
  ST_LENGTH(static_route_geometry) AS corridor_length_meters,
  ARRAY_LENGTH(road_segment_ids) AS traversed_segment_count,
  static_route_geometry
FROM 
  `my_project.rmi_foundation.routes_status`
WHERE 
  status = 'STATUS_RUNNING'
  -- 1. Route dynamism: Filter for fixed baseline corridors
  AND dynamic_routing = FALSE
  -- 2. Name prefix filtering
  AND display_name LIKE 'Route-%'
  -- 3. JSON attribute filtering
  AND JSON_EXTRACT_SCALAR(route_attributes, '$.priority') = 'tier-1'
  -- 4. Spatial boundary filter: Intersects metropolitan bounding polygon
  AND ST_INTERSECTS(
    static_route_geometry,
    ST_GEOGFROMTEXT('POLYGON((-71.12 42.32, -71.02 42.32, -71.02 42.40, -71.12 42.40, -71.12 42.32))')
  )
  -- 5. Traversed road segment lookup: Corridor traverses target highway segment
  AND EXISTS (
    SELECT 1 
    FROM UNNEST(road_segment_ids) AS segment_id 
    WHERE segment_id = 'ChIJ25e1g4hw44kR5UfM8pY61-E'
  )
ORDER BY 
  corridor_length_meters DESC;
```
