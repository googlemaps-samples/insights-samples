# Table: historical_travel_time

## 1. Overview

This table provides accumulated, historical trip duration data for your selected routes. It is the primary dataset for long-term behavior analysis, strategic planning, and identifying seasonal traffic trends.

## 2. Core Definitions

- **Selected Route ID (`selected_route_id`)**: Unique identifier for the route, matching the Roads Selection API resource name.
- **Display Name (`display_name`)**: Human-readable label assigned to the route.
- **Record Time (`record_time`)**: The UTC timestamp when the routing calculation was performed (daily partition column).
- **Traffic-Aware Duration (`duration_in_seconds`)**: Estimated total travel time at `record_time` factoring in real-world traffic conditions. **Omitted (`NULL`) when `has_road_closure = true`** because the corridor is impassable.
- **Static Duration (`static_duration_in_seconds`)**: The "free-flow" baseline travel time calculated without live traffic.
- **Route Geometry (`route_geometry`)**: The polyline geometry of the route taken at `record_time` as a BigQuery `GEOGRAPHY`.
- **Road Segment IDs (`road_segment_ids`)**: Repeated array of Google Place IDs representing topological road segments traversed at `record_time`. Available for records on or after June 19, 2026 (`record_time >= '2026-06-19'`).
- **Road Closure (`has_road_closure`)**: Indicates whether there is a full road closure on the route. Consistent with Google Maps full road closure status. When `true`, `duration_in_seconds` is `NULL`.

## 3. Technical Behaviors & Facts

- **Aggregation**: Data is collected periodically and written in **hourly batches**.
- **Data Latency**: After a new route is created in the Roads Selection API, expect a wait of up to 1 hour for data to begin populating in this table.
- **Partitioning**: Partitioned by **day** based on the `record_time` column.
- **Expiration**: Each partition has a **10-year expiration policy**, supporting multi-year trend analysis.
- **Retention**: If a route is deleted from the Roads Selection API, no new data is written, but historical records remain until their partition expires.

## 4. Analytical Guidance

- **Cost Optimization**: Always include a filter on `record_time` (e.g., `WHERE DATE(record_time) = '2026-03-01'`) to ensure BigQuery can prune partitions and minimize scan costs.
- **Congestion Metrics**:
  - **TTI (Travel Time Index)**: `SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)`. Values > 1.0 indicate delay relative to free-flow.
- **Handling Road Closures**: When `has_road_closure = true`, `duration_in_seconds` is omitted (`NULL`) because the route is impassable. When aggregating travel times or computing KPIs, either filter them with `WHERE has_road_closure IS NOT TRUE` (or `WHERE COALESCE(has_road_closure, FALSE) = FALSE`), or handle closures explicitly using conditional logic (e.g. `IF(has_road_closure, ...)` to distinguish full closures from missing observations).
- **Route Deviation & Detour Detection**: Compare `historical_travel_time.road_segment_ids` with `routes_status.road_segment_ids` (available on/after June 19, 2026). When segments diverge (`has_deviated = true`), always inspect `has_road_closure`:
  - `has_road_closure = true`: Full road closure forced traffic off the corridor (`duration_in_seconds` is NULL).
  - `has_road_closure = false`: Dynamic traffic reroute bypassed congestion (`duration_in_seconds` is populated).
- **Clustering**: The table is typically clustered by `selected_route_id` to speed up route-specific lookups.

## 5. Usage Example: Calculating Monthly Average Delay

```sql
-- Calculate the average Travel Time Index (TTI) per route for a specific month
SELECT 
  selected_route_id,
  AVG(SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)) as avg_tti,
  COUNT(*) as data_points
FROM `historical_travel_time`
WHERE record_time >= '2026-03-01' AND record_time < '2026-04-01'
GROUP BY 1
HAVING data_points > 100
ORDER BY avg_tti DESC;
```

## 6. Usage Example: Route Geometry Over Time

```sql
-- Retrieve the geometry of a specific route to verify the path taken during a peak window
SELECT 
  selected_route_id,
  record_time,
  route_geometry
FROM `historical_travel_time`
WHERE selected_route_id = 'my-route-001'
  AND DATE(record_time) = '2026-03-15'
  AND EXTRACT(HOUR FROM record_time) = 8
ORDER BY record_time;
```

## 7. Usage Example: Detecting Route Deviations and Correlating with Road Closures

```sql
-- Detect dynamic detours and classify whether deviation was caused by road closure or congestion
SELECT 
  h.selected_route_id,
  h.record_time,
  s.display_name,
  s.dynamic_routing,
  h.duration_in_seconds,
  h.has_road_closure,
  TO_JSON_STRING(s.road_segment_ids) != TO_JSON_STRING(h.road_segment_ids) AS has_deviated,
  (
    SELECT COUNT(1) 
    FROM UNNEST(h.road_segment_ids) AS obs_seg 
    WHERE obs_seg NOT IN (SELECT base_seg FROM UNNEST(s.road_segment_ids) AS base_seg)
  ) AS detour_segment_count,
  CASE 
    WHEN TO_JSON_STRING(s.road_segment_ids) != TO_JSON_STRING(h.road_segment_ids) AND h.has_road_closure IS TRUE 
      THEN 'DEVIATION_FULL_ROAD_CLOSURE'
    WHEN TO_JSON_STRING(s.road_segment_ids) != TO_JSON_STRING(h.road_segment_ids) AND COALESCE(h.has_road_closure, FALSE) = FALSE 
      THEN 'DEVIATION_CONGESTION_REROUTE'
    ELSE 'NOMINAL_BASELINE'
  END AS deviation_cause
FROM `historical_travel_time` AS h
INNER JOIN `routes_status` AS s
  ON h.selected_route_id = s.selected_route_id
WHERE h.record_time >= '2026-06-19'
  AND h.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY h.record_time DESC, detour_segment_count DESC;
```
