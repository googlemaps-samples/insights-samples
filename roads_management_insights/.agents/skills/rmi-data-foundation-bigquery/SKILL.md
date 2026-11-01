---
name: rmi-data-foundation-bigquery
description: Use this skill for querying and analyzing the foundational RMI (Roads Management Insights) BigQuery datasets, specifically route status (routes_status) and long-term/historical traffic duration metrics (historical_travel_time). Activate when querying RMI historical datasets, managing route registration definitions, or reviewing base schema designs.
---

# RMI Foundation Data (BigQuery)

This skill provides comprehensive procedural and technical knowledge for working with the Roads Management Insights (RMI) base data contract. The foundation data is structured to deliver long-term traffic-aware travel times, historical routing geometries, and active route registration statuses.

---

## 1. Technical Table Schemas (Source of Truth)

All RMI foundation analysis relies on two primary tables. The exact columns, data types, physical constraints, string enums, and logical nullability rules are declared in their respective schema JSON definition files, which act as the absolute source of truth. Refer directly to these definitions for field-level intelligence:

* **Table A: `routes_status`** — Static definitions, real-time lifecycle states, and custom administrative grouping metadata for all selected routes.
  * *Schema Source of Truth:* [routes_status.json](references/tables/routes_status.json)
  * *Fields (12 total)*:
    * `selected_route_id` (`STRING`): Unique identifier for the selected route.
    * `display_name` (`STRING`): Human-readable route label.
    * `status` (`STRING`): Operational lifecycle state (`STATUS_RUNNING`, `STATUS_INVALID`, `STATUS_EXPIRED`).
    * `validation_error` (`STRING`): Descriptive error message if route configuration fails validation.
    * `low_road_usage_start_time` (`TIMESTAMP`): Timestamp when low road usage / probe shortage was first detected.
    * `route_attributes` (`STRING`): Custom serialized JSON string containing user-defined metadata (e.g., tier, region, corridor type).
    * `dynamic_routing` (`BOOLEAN`): Indicates whether the route is dynamic (`true`) or fixed (`false`).
    * `origin` (`GEOGRAPHY`): Origin waypoint coordinate of the route.
    * `destination` (`GEOGRAPHY`): Destination waypoint coordinate of the route.
    * `intermediates` (`REPEATED GEOGRAPHY`): Repeated array of intermediate waypoint coordinates.
    * `static_route_geometry` (`GEOGRAPHY`): Polyline geometry of the static route calculated without live traffic from the waypoints.
    * `road_segment_ids` (`REPEATED STRING`): Sequence of Place IDs representing topological road segments along the static route calculated without live traffic. For fixed routes (`dynamic_routing: false`), Place IDs automatically update to reflect Google road network changes; for dynamic routes (`dynamic_routing: true`), they are not updated.
* **Table B: `historical_travel_time`** — Long-term historical records of traffic-aware and static duration observations computed periodically.
  * *Schema Source of Truth:* [historical_travel_time.json](references/tables/historical_travel_time.json)
  * *Fields (8 total)*:
    * `selected_route_id` (`STRING`): Unique identifier for the route (first clustering column).
    * `display_name` (`STRING`): Human-readable route label.
    * `record_time` (`TIMESTAMP`): UTC timestamp when the routing calculation was performed (daily partition column).
    * `duration_in_seconds` (`FLOAT`): Traffic-aware travel duration in seconds. **Omitted (`NULL`) when `has_road_closure = true`** because the corridor is impassable.
    * `static_duration_in_seconds` (`FLOAT`): Free-flow baseline travel duration without live traffic.
    * `route_geometry` (`GEOGRAPHY`): Polyline geometry of the route taken at `record_time`.
    * `road_segment_ids` (`REPEATED STRING`): Repeated array of Google Place IDs representing traversed road segments at `record_time`. Available for records on or after June 19, 2026 (`record_time >= '2026-06-19'`).
    * `has_road_closure` (`BOOLEAN`): Indicates whether there is a full road closure on the route (consistent with Google Maps full road closure status).
  * *Partitioning*: Partitioned by **`DAY`** on the `record_time` column. Default partitions hold up to 10 years of history.
  * *Clustering*: Clustered on the **`selected_route_id`** column (first position) and `record_time` (second position).

> [!IMPORTANT]
> **Road Segment IDs (`road_segment_ids`) Support & Historical Constraint**:
>
> * The `road_segment_ids` field (an array of place IDs representing topological road segments) is available in **both** `recent_roads_data` (real-time) and `historical_travel_time` (historical).
> * **Temporal Constraint**: This field was added on **June 19, 2026** and is populated **only** for records generated on or after this date (`record_time >= '2026-06-19'`). Historical partitions prior to June 19, 2026 will have empty or null arrays for `road_segment_ids`.
> * **Query Safety Rule**: When querying or unnesting `road_segment_ids` in `historical_travel_time`, **always use `LEFT JOIN UNNEST(road_segment_ids)`** (or filter `WHERE record_time >= '2026-06-19' AND ARRAY_LENGTH(road_segment_ids) > 0`). Using a standard `CROSS JOIN UNNEST` or implicit comma join will silently filter out and exclude all older records where `road_segment_ids` is empty, leading to incomplete/corrupted historical analysis.

---

## 2. Query Optimization & Mapping Standards

### Partition Pruning & Cost Control

The `historical_travel_time` table grows indefinitely as hourly snapshots accumulate. To prevent exorbitant query costs, **never perform full table scans**.

* **Mandatory Rule**: Always include a direct filter on the partition column `record_time` (e.g., `WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)`).
* **Clustering Benefit**: Always filter on `selected_route_id` early in your queries. Because the table is clustered on this ID, BigQuery will bypass blocks that do not contain matching route data.

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

### Efficient Route Discovery vs. Roads Selection API

Historically, discovering registered routes or extracting specific corridors required calling the Roads Selection REST API (`selectedRoutes.list`), which imposed REST API quota limits, pagination latency, and rate throttling. Because `routes_status` has been expanded to include full routing definitions (`origin`, `destination`, `intermediates`, `static_route_geometry`, `road_segment_ids`, `dynamic_routing`, and `route_attributes`), **`routes_status` in BigQuery now serves as the authoritative, ultra-efficient route extraction and discovery engine**.

Querying `routes_status` directly in BigQuery is vastly preferred over calling the Roads Selection API:

* **Zero REST API Quota & Latency**: Eliminates repetitive REST API requests, client-side pagination overhead, and rate limits when querying thousands of monitored corridors.
* **Native BigQuery GIS Spatial Indexing**: Enables high-performance geospatial operations (`ST_INTERSECTS`, `ST_DWITHIN`, `ST_CONTAINS`, `ST_LENGTH`) directly on `static_route_geometry`, `origin`, and `destination` using BigQuery's spatial indexing.
* **Instant Multi-Criteria Slicing**: Combines route ID or display name prefixes (`display_name LIKE 'corridor-boston-%'`), custom JSON attributes (`JSON_EXTRACT_SCALAR(route_attributes, '$.corridor_type') = 'arterial'`), route dynamism (`dynamic_routing = FALSE`), and traversed road segment Place IDs (`EXISTS (SELECT 1 FROM UNNEST(road_segment_ids) AS seg WHERE seg = 'ChIJ...')`) in a single query.
* **Direct Analytical Joins**: Extracted route sets can be directly joined with `historical_travel_time` or `recent_roads_data` without intermediate client-side buffering.

### Detecting Route Deviations and Detours by Comparing Road Segment Sequences (routes_status vs historical_travel_time)

Because `routes_status.road_segment_ids` records the static baseline sequence of Google Place IDs and `historical_travel_time.road_segment_ids` captures the actual traffic-aware sequence observed at each `record_time` (starting from the June 19, 2026 cutoff), comparing the two arrays reveals whether a dynamic route has detoured or deviated around incidents or heavy congestion:

* **Nominal Route (`has_deviated = FALSE`)**: The observed segment sequence matches the static baseline identically.
* **Route Deviation (`has_deviated = TRUE`)**: Real-time traffic rerouted vehicles onto alternative streets, resulting in mismatched Place ID sequences or extra detour segments (`detour_segment_count > 0`).
* **Root-Cause Correlation with `has_road_closure`**: Whenever a deviation is detected (`has_deviated = TRUE`), **always correlate with `historical_travel_time.has_road_closure`**:
  * **`has_road_closure IS TRUE`** (`DEVIATION_FULL_ROAD_CLOSURE`): The deviation was triggered by a full, impassable road closure on the corridor. In this state, `duration_in_seconds` is omitted (`NULL`) per the RMI nullability contract.
  * **`COALESCE(has_road_closure, FALSE) = FALSE`** (`DEVIATION_CONGESTION_REROUTE`): The deviation was triggered by dynamic routing avoiding peak congestion or minor delays (`dynamic_routing = TRUE`), and `duration_in_seconds` is populated with the alternative path duration.

### Mapping Key Performance Indices (KPIs)

When analyzing traffic-aware speeds and corridor efficiency, translate technical attributes to standard transportation metrics:

* **Travel Time Index (TTI)**: Represents the ratio of travel time in peak traffic to ideal travel time:
    `SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)`
* **Congestion Delay**: Total seconds wasted due to traffic:
    `duration_in_seconds - static_duration_in_seconds` (Clamped to a minimum of 0 using `GREATEST(0, ...)`).

> [!NOTE]
> **Road Closures and Duration Nullability**: `duration_in_seconds` is omitted (`NULL`) when `has_road_closure = true` because the route is impassable. When aggregating travel times, computing average delays, or calculating TTI, filter out closed routes using `WHERE has_road_closure IS NOT TRUE` (or `WHERE COALESCE(has_road_closure, FALSE) = FALSE`), or explicitly account for closures in conditional KPI calculations.

---

## 3. Troubleshooting & Common Pitfalls

| Symptom / Error | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **High Query Scan Cost** | Omitting partition filter on `record_time`. | Append `WHERE record_time BETWEEN start_ts AND end_ts`. Verify with a query Dry Run first. |
| **`ST_LENGTH` returns weird/huge numbers** | Evaluating geometry in degrees instead of meters. | `ST_LENGTH(geography)` returns length in meters by default. Do not use coordinate-based Euclidean math. |
| **Empty join results with `routes_status`** | Using `display_name` as the join condition. | Never join on `display_name`. **Always** join on `selected_route_id`. |
| **`NULL` values for custom attributes** | Using `JSON_EXTRACT` instead of `JSON_EXTRACT_SCALAR`. | `JSON_EXTRACT` retains enclosing double-quotes. Use `JSON_EXTRACT_SCALAR` to retrieve clean string literals. |
| **Routing path gaps or loops** | `route_geometry` contains multi-geometries or invalid paths. | Filter with `WHERE ST_GEOMETRYTYPE(route_geometry) = 'ST_LineString'` to ensure simple, connected paths. |
| **`duration_in_seconds` is NULL unexpectedly** | A full road closure is active on the route (`has_road_closure = true`). | Check `has_road_closure`. Filter with `WHERE has_road_closure IS NOT TRUE` or handle closures explicitly in KPIs. |

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

### Example 4: Multi-Criteria Route Discovery and Spatial Extraction

Extract active, fixed arterial routes intersecting a target metropolitan bounding polygon, matching a display name prefix, having a specific priority tag in `route_attributes`, and traversing a specific road segment Place ID:

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
  -- 4. Spatial boundary filter: Corridor intersects metropolitan bounding polygon
  AND ST_INTERSECTS(
    static_route_geometry,
    ST_GEOGFROMTEXT('POLYGON((-71.12 42.32, -71.02 42.32, -71.02 42.40, -71.12 42.40, -71.12 42.32))')
  )
  -- 5. Traversed road segment lookup: Corridor traverses target highway segment Place ID
  AND EXISTS (
    SELECT 1 
    FROM UNNEST(road_segment_ids) AS segment_id 
    WHERE segment_id = 'ChIJ25e1g4hw44kR5UfM8pY61-E'
  )
ORDER BY 
  corridor_length_meters DESC;
```

### Example 5: Detecting Route Deviations and Detours with Road Closure Correlation

Compare static baseline Place IDs in `routes_status` against observed Place IDs in `historical_travel_time`, calculate detour segment counts, and classify the deviation root cause using `has_road_closure`:

```sql
SELECT 
  h.selected_route_id,
  h.record_time,
  s.display_name,
  s.dynamic_routing,
  h.duration_in_seconds,
  h.has_road_closure,
  -- Compare baseline vs actual observed road segment sequences
  TO_JSON_STRING(s.road_segment_ids) != TO_JSON_STRING(h.road_segment_ids) AS has_deviated,
  (
    SELECT COUNT(1) 
    FROM UNNEST(h.road_segment_ids) AS obs_seg 
    WHERE obs_seg NOT IN (SELECT base_seg FROM UNNEST(s.road_segment_ids) AS base_seg)
  ) AS detour_segment_count,
  -- Correlate route deviation with road closure state
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
  -- Temporal constraint: road_segment_ids populated on/after June 19, 2026
  h.record_time >= '2026-06-19'
  AND h.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY 
  h.record_time DESC, 
  detour_segment_count DESC;
```
