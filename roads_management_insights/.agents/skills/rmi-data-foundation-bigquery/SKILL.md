---
name: rmi-data-foundation-bigquery
description: Use this skill for querying and analyzing the foundational RMI (Roads Management Insights) BigQuery datasets, specifically route status (routes_status) and long-term/historical traffic duration metrics (historical_travel_time). Activate when querying RMI historical datasets, managing route registration definitions, or reviewing base schema designs.
---

# RMI Foundation Data (BigQuery)

This skill provides comprehensive procedural and technical knowledge for working with the Roads Management Insights (RMI) base data contract. The foundation data is structured to deliver long-term traffic-aware travel times, historical routing geometries, and active route registration statuses.

---

## 1. Technical Table Schemas (Source of Truth)

All RMI foundation analysis relies on two primary tables. The exact columns, data types, physical constraints, string enums, and logical nullability rules are declared in their respective schema JSON definition files, which act as the absolute source of truth. Refer directly to these definitions for field-level intelligence:

*   **Table A: `routes_status`** — Static definitions, real-time lifecycle states, and custom administrative grouping metadata for all selected routes.
    *   *Schema Source of Truth:* [routes_status.json](references/tables/routes_status.json)
*   **Table B: `historical_travel_time`** — Long-term historical records of traffic-aware and static duration observations computed periodically.
    *   *Schema Source of Truth:* [historical_travel_time.json](references/tables/historical_travel_time.json)
    *   *Partitioning*: Partitioned by **`DAY`** on the `record_time` column. Default partitions hold up to 10 years of history.
    *   *Clustering*: Clustered on the **`selected_route_id`** column (first position) and `record_time` (second position).

> [!IMPORTANT]
> **Road Segment IDs (`road_segment_ids`) Support & Historical Constraint**: 
> *   The `road_segment_ids` field (an array of place IDs representing topological road segments) is available in **both** `recent_roads_data` (real-time) and `historical_travel_time` (historical).
> *   **Temporal Constraint**: This field was added on **June 19, 2026** and is populated **only** for records generated on or after this date (`record_time >= '2026-06-19'`). Historical partitions prior to June 19, 2026 will have empty or null arrays for `road_segment_ids`.
> *   **Query Safety Rule**: When querying or unnesting `road_segment_ids` in `historical_travel_time`, **always use `LEFT JOIN UNNEST(road_segment_ids)`** (or filter `WHERE record_time >= '2026-06-19' AND ARRAY_LENGTH(road_segment_ids) > 0`). Using a standard `CROSS JOIN UNNEST` or implicit comma join will silently filter out and exclude all older records where `road_segment_ids` is empty, leading to incomplete/corrupted historical analysis.

---

## 2. Query Optimization & Mapping Standards

### Partition Pruning & Cost Control
The `historical_travel_time` table grows indefinitely as hourly snapshots accumulate. To prevent exorbitant query costs, **never perform full table scans**.
*   **Mandatory Rule**: Always include a direct filter on the partition column `record_time` (e.g., `WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)`).
*   **Clustering Benefit**: Always filter on `selected_route_id` early in your queries. Because the table is clustered on this ID, BigQuery will bypass blocks that do not contain matching route data.

### Parsing Route Attributes (JSON Strings)
Since `route_attributes` is stored as a serialized JSON string in `routes_status`, you must use BigQuery’s JSON extraction functions to filter or group by administrative metadata:
```sql
SELECT 
  selected_route_id,
  JSON_EXTRACT_SCALAR(route_attributes, '$.region') AS region,
  JSON_EXTRACT_SCALAR(route_attributes, '$.tier') AS tier
FROM 
  `my_project.rmi_foundation.routes_status`
WHERE 
  JSON_EXTRACT_SCALAR(route_attributes, '$.region') = 'North-West';
```

### Mapping Key Performance Indices (KPIs)
When analyzing traffic-aware speeds and corridor efficiency, translate technical attributes to standard transportation metrics:
*   **Travel Time Index (TTI)**: Represents the ratio of travel time in peak traffic to ideal travel time.
    $$\text{TTI} = \frac{\text{duration\_in\_seconds}}{\text{static\_duration\_in\_seconds}}$$
    *BigQuery Implementation*: `SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)`
*   **Congestion Delay**: Total seconds wasted due to traffic:
    `duration_in_seconds - static_duration_in_seconds` (Clamped to a minimum of 0 using `GREATEST(0, ...)`).

---

## 3. Troubleshooting & Common Pitfalls

| Symptom / Error | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **High Query Scan Cost** | Omitting partition filter on `record_time`. | Append `WHERE record_time BETWEEN start_ts AND end_ts`. Verify with a query Dry Run first. |
| **`ST_LENGTH` returns weird/huge numbers** | Evaluating geometry in degrees instead of meters. | `ST_LENGTH(geography)` returns length in meters by default. Do not use coordinate-based Euclidean math. |
| **Empty join results with `routes_status`** | Using `display_name` as the join condition. | Never join on `display_name`. **Always** join on `selected_route_id`. |
| **`NULL` values for custom attributes** | Using `JSON_EXTRACT` instead of `JSON_EXTRACT_SCALAR`. | `JSON_EXTRACT` retains enclosing double-quotes. Use `JSON_EXTRACT_SCALAR` to retrieve clean string literals. |
| **Routing path gaps or loops** | `route_geometry` contains multi-geometries or invalid paths. | Filter with `WHERE ST_GEOMETRYTYPE(route_geometry) = 'ST_LineString'` to ensure simple, connected paths. |

---

## 4. References
* [Google Maps Platform - Roads Management Insights Overview](https://developers.google.com/maps/documentation/roads-management-insights/overview)
* [Google Maps Platform - RMI Guidelines & Governance](https://developers.google.com/maps/documentation/roads-management-insights/guidelines)
* [Google Maps Platform - RMI Accumulated Data](https://developers.google.com/maps/documentation/roads-management-insights/accumulated-data)

---

## 5. Examples

### Example 1: Calculating Daily Congestion Profiles
Retrieve hourly travel time indices grouped by hour of the day for a specific route over the past 30 days:
```sql
SELECT 
  selected_route_id,
  EXTRACT(HOUR FROM record_time) AS hour_of_day,
  AVG(duration_in_seconds) AS avg_duration,
  AVG(static_duration_in_seconds) AS free_flow_duration,
  -- Calculate Travel Time Index (TTI)
  SAFE_DIVIDE(AVG(duration_in_seconds), AVG(static_duration_in_seconds)) AS travel_time_index,
  COUNT(1) AS observation_count
FROM 
  `my_project.rmi_foundation.historical_travel_time`
WHERE 
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND selected_route_id = "route-boston-logan-93"
GROUP BY 
  selected_route_id, 
  hour_of_day
ORDER BY 
  hour_of_day ASC;
```

### Example 2: Corridors with Severe Peak Bottlenecks
Find the top 10 registered priority routes experiencing the highest peak delay ratios during the morning commute (7:00 AM - 9:00 AM):
```sql
WITH route_metadata AS (
  SELECT 
    selected_route_id,
    display_name,
    JSON_EXTRACT_SCALAR(route_attributes, '$.tier') AS priority_tier
  FROM 
    `my_project.rmi_foundation.routes_status`
  WHERE 
    status = 'STATUS_RUNNING'
)
SELECT 
  t.selected_route_id,
  m.display_name,
  m.priority_tier,
  AVG(t.duration_in_seconds) AS peak_duration,
  AVG(t.static_duration_in_seconds) AS free_flow_duration,
  AVG(SAFE_DIVIDE(t.duration_in_seconds, t.static_duration_in_seconds)) AS peak_tti,
  AVG(GREATEST(0, t.duration_in_seconds - t.static_duration_in_seconds)) AS avg_delay_seconds
FROM 
  `my_project.rmi_foundation.historical_travel_time` AS t
INNER JOIN 
  route_metadata AS m ON t.selected_route_id = m.selected_route_id
WHERE 
  t.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  -- Standardize to morning commute (UTC-adjusted or local timezone extracts)
  AND EXTRACT(HOUR FROM t.record_time) BETWEEN 7 AND 9
GROUP BY 
  t.selected_route_id,
  m.display_name,
  m.priority_tier
HAVING 
  peak_tti > 1.25 -- Only show corridors with > 25% traffic delay
ORDER BY 
  peak_tti DESC
LIMIT 10;
```

### Example 3: Safe Segment-level Analysis across Historical Records
This query demonstrates how to count occurrences of specific road segment IDs across historical route snapshots. Using `LEFT JOIN UNNEST` ensures that older partitions where `road_segment_ids` is not yet populated are **not** silently discarded from other calculations or aggregates.

```sql
SELECT 
  t.selected_route_id,
  t.record_time,
  segment_id,
  -- Check if segment_id is null (i.e. older records without the segment array)
  IF(segment_id IS NULL, 'No Segment Data (Legacy Partition)', segment_id) as segment_status,
  t.duration_in_seconds,
  t.static_duration_in_seconds
FROM 
  `my_project.rmi_foundation.historical_travel_time` AS t
-- Safe unnesting prevents deleting historical records with empty segment arrays
LEFT JOIN 
  UNNEST(t.road_segment_ids) AS segment_id
WHERE 
  t.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
  AND t.selected_route_id = "route-boston-logan-93"
ORDER BY 
  t.record_time DESC;
```

