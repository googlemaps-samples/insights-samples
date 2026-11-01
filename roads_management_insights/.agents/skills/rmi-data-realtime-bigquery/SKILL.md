---
name: rmi-data-realtime-bigquery
description: Use this skill for near real-time traffic analysis using the recent_roads_data table. This is a superset of the foundation data, enabling granular Speed Reading Interval (SRI) analysis, offset-based traffic density, road closure auditing, and 60-day rolling performance audits.
---

# RMI Real-Time Data (BigQuery)

This skill provides comprehensive procedural and technical knowledge for working with the Roads Management Insights (RMI) near real-time data layer. The `recent_roads_data` table operates as a superset of the foundation data, enabling granular Speed Reading Interval (SRI) analysis, offset-based corridor congestion profiling, full road closure detection, and rapid 60-day operational reviews.

---

## 1. Technical Table Schema (Source of Truth)

The core real-time table contains nested and repeated attributes. The exact columns, repeated structures, data types, physical constraints, string enums, and logical nullability rules are declared in the schema JSON definition file, which acts as the absolute source of truth. Refer directly to this definition for field-level intelligence:

* **Table: `recent_roads_data`** — High-frequency travel times, offset-based speed intervals, road closures, and topological road segments.
  * *Schema Source of Truth:* [recent_roads_data.json](references/recent_roads_data.json)
  * *Fields (10 total)*:
    1. `selected_route_id` (`STRING`): Unique identifier for the SelectedRoute resource (`projects/{project}/selectedRoutes/{selected_route_id}`). Correlates with `historical_travel_time` and `routes_status`.
    2. `display_name` (`STRING`): User-provided descriptive route name for UI reporting (max 128 characters).
    3. `record_time` (`TIMESTAMP`): The UTC timestamp when the route data was computed. Partitioning column (`DAY(record_time)`).
    4. `duration_in_seconds` (`FLOAT`): Traffic-aware travel duration in seconds. **Omitted (`NULL`) when `has_road_closure = true`** because the corridor is impassable.
    5. `static_duration_in_seconds` (`FLOAT`): Traffic-unaware (static) baseline duration in seconds under ideal or free-flow conditions.
    6. `route_geometry` (`GEOGRAPHY`): Optimal polyline geometry at `record_time` (WGS84, EPSG:4326).
    7. `speed_reading_intervals` (`REPEATED RECORD`): **Legacy coordinate-based speed reading intervals**. May stop being populated on or after **January 13, 2027**. Use `speed_reading_offsets` instead.
    8. `road_segment_ids` (`REPEATED STRING`): Sequence of Place IDs in topological order representing connected road segments (populated for records on or after June 18/19, 2026).
    9. `speed_reading_offsets` (`REPEATED RECORD`): **Offset-based speed reading intervals** demarcated by meter distance from route start (`start_offset`, `end_offset`, `speed`). Available as of **October 8, 2026**. Omitted when `has_road_closure = true`.
    10. `has_road_closure` (`BOOLEAN`): Indicates whether there is a full road closure on the route (consistent with Google Maps live closure status). When `true`, `duration_in_seconds` and `speed_reading_offsets` are omitted (`NULL`). A `NULL` value indicates that road closure information is undetermined.

### Partitioning, Retention & Ingestion Cadence Facts

* *Partitioning*: Partitioned by **`DAY`** on the `record_time` column. Sliding retention is hard-capped at **60 days**. Any partitions older than 60 days are automatically pruned and deleted.
  * *Time Travel vs. Retention Limit*: BigQuery Time Travel is strictly limited to 7 days (168 hours) from current time. It **cannot** be used to access data beyond the 60-day partition expiration (e.g. attempting to query 65 days back via `FOR SYSTEM_TIME AS OF` fails with an invalid snapshot time error). To preserve historical data beyond 60 days, configure BigQuery Table Snapshots or export partitions to an archive table/bucket.
* *Ingestion Cadence (Hourly Batch)*: While observation data reflects high-frequency calculations (recomputed every 2 minutes for subscribed routes), the table is populated via **scheduled hourly batch writes** with up to 1 hour of ingestion delay. Workloads requiring sub-minute real-time alerting must ingest directly from Google Cloud Pub/Sub streaming topics.
* *Clustering*: In Google's shared Analytics Hub provider dataset, tables are unclustered (`clustering: null`). When copying or materializing extracts into a customer-managed warehouse, clustering on **`selected_route_id`** (first position) and `record_time` (second position) is strongly recommended.

---

## 2. Speed Reading Intervals (SRI): Offsets vs. Legacy Coordinates

A Speed Reading Interval (SRI) represents a contiguous stretch of a route where traffic falls into a single speed category. Together, intervals cover the entire route contiguously from origin to destination.

### The Modern Standard: Offset-Based Intervals (`speed_reading_offsets`)

Introduced on **October 8, 2026**, offset-based intervals replace heavy coordinate arrays with lightweight meter offsets:

* **`start_offset` (`INTEGER`)**: Distance in meters from the route start (inclusive).
* **`end_offset` (`INTEGER`)**: Distance in meters from the route start (exclusive; equals `start_offset` of the subsequent interval).
* **`speed` (`STRING`)**: Speed classification aligned 1:1 with Google Maps traffic layer colors:
  * **`NORMAL`** (Green): Traffic is flowing smoothly; no slowdown detected.
  * **`SLOW`** (Yellow): Slowdown detected, but no congestion formed.
  * **`TRAFFIC_JAM`** (Red): Traffic jam detected.
  * **`TRAFFIC_JAM_HEAVY`** (Dark Red, available as of October 8, 2026): Severe traffic jam / gridlock detected.

> [!TIP]
> **Pure Integer Distance Calculations**: With `speed_reading_offsets`, the length of each speed interval in meters is computed via pure integer subtraction: `(end_offset - start_offset)`. This eliminates expensive geospatial functions (`ST_LENGTH`, `ST_MAKELINE`), speeding up BigQuery aggregations by 10x–50x and reducing query scan overhead.

### Coexistence Window & Deprecation Horizon

| Attribute | Modern Offsets (`speed_reading_offsets`) | Legacy Coordinates (`speed_reading_intervals`) |
| :--- | :--- | :--- |
| **Availability** | Available as of **October 8, 2026** | Phasing out. May cease population on or after **January 13, 2027** |
| **Geometry Format** | Meter offsets (`start_offset`, `end_offset`) | Coordinate array (`interval_coordinates`) |
| **Speed Categories** | 4 tiers: `NORMAL`, `SLOW`, `TRAFFIC_JAM`, **`TRAFFIC_JAM_HEAVY`** | 3 tiers: `NORMAL`, `SLOW`, `TRAFFIC_JAM` (heavy jams grouped into `TRAFFIC_JAM`) |
| **Road Closures** | Omitted (`NULL`) when `has_road_closure = true` | May be empty when route is closed |

### The LEFT JOIN UNNEST Safety Standard

* **Critical Pattern**: Always use `LEFT JOIN UNNEST(speed_reading_offsets)` (or `LEFT JOIN UNNEST(speed_reading_intervals)`) instead of a comma-join or `INNER JOIN UNNEST`.
* If a route observation has no recorded congestion, or if the route has an active full road closure (`has_road_closure = true`), the interval array will be empty or omitted. An inner unnest will silently discard the entire parent row, biasing your travel duration and route count metrics.

```sql
SELECT 
  selected_route_id,
  record_time,
  sro.speed AS speed_category,
  (sro.end_offset - sro.start_offset) AS interval_length_meters
FROM 
  `my_project.rmi_realtime.recent_roads_data`
LEFT JOIN 
  UNNEST(speed_reading_offsets) AS sro;
```

---

## 3. Road Closures & Impassable Corridor Handling (`has_road_closure`)

The `has_road_closure` boolean column reports full road closure status consistent with Google Maps:

* **`has_road_closure = true`**: The corridor is fully closed and impassable.
  * **`duration_in_seconds` is omitted (`NULL`)** because a route travel duration cannot be calculated.
  * **`speed_reading_offsets` is omitted (`NULL`)**.
* **`has_road_closure = false`**: The corridor is open and passable.
* **`has_road_closure IS NULL`**: Road closure information is undetermined.

> [!WARNING]
> **Safe Query Standard for Duration Metrics**:
> Because `duration_in_seconds` is `NULL` during full road closures, naive arithmetic such as `duration_in_seconds - static_duration_in_seconds` will return `NULL`.
> When analyzing normal flow performance, explicitly filter:
> `WHERE (has_road_closure IS FALSE OR has_road_closure IS NULL) AND duration_in_seconds IS NOT NULL`.
> To audit closure incidents, query `WHERE has_road_closure = TRUE`.

---

## 4. Topological Road Segments (`road_segment_ids`)

* **Topological Order**: `road_segment_ids` is an `ARRAY<STRING>` containing the Google Maps Place IDs of the connected physical road segments along the route in topological order.
* **Querying Array Membership**: Use `EXISTS` with `UNNEST` to quickly filter routes traversing a specific road segment without duplicating parent rows:

```sql
SELECT 
  selected_route_id,
  record_time,
  duration_in_seconds
FROM 
  `my_project.rmi_realtime.recent_roads_data`
WHERE 
  EXISTS(SELECT 1 FROM UNNEST(road_segment_ids) AS seg_id WHERE seg_id = 'place_id_of_road_segment')
  AND record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY);
```

---

## 5. Combining `recent_roads_data` with `routes_status` (from `rmi-data-foundation-bigquery`)

While `recent_roads_data` provides high-frequency rolling telemetry (live duration, `speed_reading_offsets`, and `has_road_closure`), it contains minimal static route metadata. In enterprise production deployments, **`recent_roads_data` should almost always be combined with the `routes_status` table** (covered in detail by [rmi-data-foundation-bigquery](../rmi-data-foundation-bigquery/SKILL.md)).

### Why Join with `routes_status`?

The two tables correlate directly on **`selected_route_id`** as the primary join key:

```sql
FROM `my_project.roads_insights.recent_roads_data` AS r
INNER JOIN `my_project.roads_insights.routes_status` AS s
  ON r.selected_route_id = s.selected_route_id
```

Joining with `routes_status` unlocks essential operational capabilities:

1. **Active Route Lifecycle Filtering (`status = 'STATUS_RUNNING'`)**:
   - `recent_roads_data` accumulates raw calculation snapshots, which may include routes that have failed validation (`STATUS_INVALID`) or expired (`STATUS_EXPIRED`).
   - Filtering on `s.status = 'STATUS_RUNNING'` guarantees that dashboards, alerting engines, and KPIs only evaluate healthy, actively monitored corridors.
2. **Operational Metadata & Hierarchy via `route_attributes`**:
   - `recent_roads_data` only provides `selected_route_id` and `display_name`.
   - `routes_status.route_attributes` contains serialized JSON metadata tags attached during route registration (e.g., `{"corridor_type": "arterial", "region": "metro_west", "priority": "high", "concessionaire": "state_dot"}`).
   - Extracting attributes via `JSON_VALUE(s.route_attributes, '$.key')` enables grouping real-time congestion and gridlock by administrative district, priority tier, or functional road class.
3. **Route Dynamism Awareness (`dynamic_routing`)**:
   - `routes_status.dynamic_routing` (`BOOLEAN`) indicates whether the route allows dynamic live-traffic detour rerouting (`true`) or enforces fixed geometry (`false`).
   - Real-time operators use this flag to distinguish between fixed transit corridors and dynamic bypass routes when evaluating travel duration fluctuations and heavy jams.
4. **Spatial Anchor Geometry Filtering (`origin`, `destination`, `intermediates`)**:
   - `routes_status` stores the exact physical coordinates of route endpoints. Joining with `routes_status` enables spatial boundary filtering (e.g. `ST_DWITHIN(s.origin, ST_GEOGPOINT(...), 5000)`).
5. **Static Free-Flow vs. Live Geometry Divergence**:
   - Comparing `r.route_geometry` with `s.static_route_geometry` allows GIS teams to detect active detours and temporary lane shifts.

---

## 6. Troubleshooting & Common Pitfalls

| Symptom / Error | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **Parent records vanish from query results** | Using `CROSS JOIN UNNEST` or `, UNNEST` when records have empty SRI lists or when `has_road_closure = true`. | Replace with `LEFT JOIN UNNEST(speed_reading_offsets) AS sro`. |
| **`duration_in_seconds` is unexpectedly NULL** | An active full road closure exists on the corridor (`has_road_closure = true`). | Inspect `has_road_closure`. Treat NULL durations as closed/impassable corridors rather than data loss. |
| **`speed_reading_offsets` is empty (`[]`)** | Querying records computed prior to October 8, 2026. | For historical partitions before Oct 8, 2026, fallback to `speed_reading_intervals`. For modern partitions, use `speed_reading_offsets`. |
| **`TRAFFIC_JAM_HEAVY` never appears in results** | Querying legacy `speed_reading_intervals.speed` instead of `speed_reading_offsets.speed`. | Migrate queries to `speed_reading_offsets`. Legacy field groups dark red into `TRAFFIC_JAM`. |
| **`Cannot query table: 60-day limit exceeded`** | Accessing records older than the 60-day sliding retention window. | Always filter `record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 60 DAY)`. Defer older queries to the historical archive (`historical_travel_time`). |
| **`Invalid snapshot time` on `FOR SYSTEM_TIME AS OF`** | Attempting BigQuery Time Travel beyond 7 days (e.g. 60+ days back). Platform limit is strictly 168 hours (7 days). | Do not use Time Travel for historical access past 7 days. Use BigQuery Table Snapshots or historical archive tables instead. |
| **Queries scan full table despite filtering by route ID** | Provider Analytics Hub table has `clustering: null`. | Predicates on `selected_route_id` do not prune storage in the linked table. Always include a `record_time` partition filter, and materialize clustered extracts for analytical dashboards. |
| **Zero results returned for current 15 minutes** | Telemetry recomputed every 2 minutes is batched hourly into BigQuery. | Expect up to 1-hour delay in BigQuery tables. For real-time sub-minute streaming, consume directly from the RMI Pub/Sub topic. |

---

## 7. References

* [Google Maps Platform - Roads Management Insights Overview](https://developers.google.com/maps/documentation/roads-management-insights/overview)
* [Google Maps Platform - RMI Accumulated Road Data in BigQuery](https://developers.google.com/maps/documentation/roads-management-insights/accumulated-data#recent_roads_data_table)
* [Google Maps Platform - RMI Concepts: Speed Reading Intervals](https://developers.google.com/maps/documentation/roads-management-insights/rmi-concepts#speed-reading-intervals)
* [Google Maps Platform - RMI Real-Time Road Data in Pub/Sub](https://developers.google.com/maps/documentation/roads-management-insights/real-time-data)

---

## 8. Production SQL Examples

### Example 1: Near Live Corridor Speed Profile & Congestion Length (Modern Offsets)

Calculate current segment congestion metrics across active monitored routes using the modern `speed_reading_offsets` field:

```sql
SELECT 
  selected_route_id,
  record_time,
  sro.speed AS speed_category,
  -- Instantaneous length calculation via integer subtraction (no spatial ST_LENGTH required)
  SUM(sro.end_offset - sro.start_offset) AS total_meters_in_category
FROM 
  `my_project.rmi_realtime.recent_roads_data`
LEFT JOIN 
  UNNEST(speed_reading_offsets) AS sro
WHERE 
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND (has_road_closure IS FALSE OR has_road_closure IS NULL)
GROUP BY 
  selected_route_id,
  record_time,
  speed_category
ORDER BY 
  record_time DESC, 
  total_meters_in_category DESC;
```

### Example 2: Corridors Experiencing Severe Gridlock (`TRAFFIC_JAM_HEAVY`)

Identify which corridors have suffered the highest proportion of severe standstill congestion over the last 7 days of operations:

```sql
SELECT 
  selected_route_id,
  COUNT(DISTINCT record_time) AS total_observations,
  -- Count occurrences of severe gridlock vs standard congestion
  COUNTIF(sro.speed = 'TRAFFIC_JAM_HEAVY') AS heavy_jam_intervals,
  COUNTIF(sro.speed = 'TRAFFIC_JAM') AS standard_jam_intervals,
  COUNTIF(sro.speed = 'SLOW') AS slow_intervals,
  -- Total meters subjected to heavy gridlock across all observations
  SUM(IF(sro.speed = 'TRAFFIC_JAM_HEAVY', sro.end_offset - sro.start_offset, 0)) AS total_heavy_jam_meters
FROM 
  `my_project.rmi_realtime.recent_roads_data`
LEFT JOIN 
  UNNEST(speed_reading_offsets) AS sro
WHERE 
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND (has_road_closure IS FALSE OR has_road_closure IS NULL)
GROUP BY 
  selected_route_id
HAVING 
  heavy_jam_intervals > 0
ORDER BY 
  total_heavy_jam_meters DESC
LIMIT 20;
```

### Example 3: Full Road Closure Incident Auditing (`has_road_closure`)

Detect corridors that have experienced active full road closures over the past 24 hours:

```sql
SELECT 
  selected_route_id,
  display_name,
  MIN(record_time) AS closure_first_detected,
  MAX(record_time) AS closure_last_detected,
  COUNT(1) AS closed_observation_count,
  static_duration_in_seconds AS free_flow_baseline_seconds
FROM 
  `my_project.rmi_realtime.recent_roads_data`
WHERE 
  has_road_closure = TRUE
  AND record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 
  selected_route_id,
  display_name,
  static_duration_in_seconds
ORDER BY 
  closure_last_detected DESC;
```

### Example 4: Topological Road Segment Coverage Across Monitored Routes

List the distinct road segments being monitored and the count of unique routes traversing them:

```sql
SELECT 
  seg_id,
  COUNT(DISTINCT selected_route_id) AS routes_traversing_count
FROM 
  `my_project.rmi_realtime.recent_roads_data`
CROSS JOIN 
  UNNEST(road_segment_ids) AS seg_id
WHERE 
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
GROUP BY 
  seg_id
ORDER BY 
  routes_traversing_count DESC;
```

### Example 5: Backward-Compatible SRI Unnesting (Legacy Schema Reference)

For querying historical partitions recorded prior to October 8, 2026, or maintaining existing queries before the January 13, 2027 deprecation date:

```sql
-- LEGACY PATTERN: Uses ST_LENGTH on coordinate geometries
SELECT 
  selected_route_id,
  record_time,
  sri.speed AS segment_speed_state,
  SUM(ST_LENGTH(coords)) AS segment_length_meters
FROM 
  `my_project.rmi_realtime.recent_roads_data`
LEFT JOIN 
  UNNEST(speed_reading_intervals) AS sri
LEFT JOIN 
  UNNEST(sri.interval_coordinates) AS coords
WHERE 
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 
  selected_route_id,
  record_time,
  segment_speed_state;
```

### Example 6: Active Route Filtering & Corridor Attribute Aggregation (Joining with `routes_status`)

Join `recent_roads_data` with `routes_status` (from `rmi-data-foundation-bigquery`) to filter for currently active routes (`status = 'STATUS_RUNNING'`), extract operational metadata tags (`route_attributes`), and aggregate congestion metrics:

```sql
SELECT 
  r.selected_route_id,
  r.display_name,
  -- Extract enterprise metadata tags from routes_status
  JSON_VALUE(s.route_attributes, '$.corridor_tier') AS corridor_tier,
  JSON_VALUE(s.route_attributes, '$.jurisdiction') AS jurisdiction,
  s.dynamic_routing,
  r.record_time,
  r.duration_in_seconds,
  r.has_road_closure,
  -- Sum total distance affected by severe gridlock (TRAFFIC_JAM_HEAVY)
  SUM(IF(sro.speed = 'TRAFFIC_JAM_HEAVY', sro.end_offset - sro.start_offset, 0)) AS heavy_jam_meters
FROM 
  `my_project.rmi_realtime.recent_roads_data` AS r
INNER JOIN 
  `my_project.roads_insights.routes_status` AS s
  ON r.selected_route_id = s.selected_route_id
LEFT JOIN 
  UNNEST(r.speed_reading_offsets) AS sro
WHERE 
  -- 1. Filter for actively running routes (exclude STATUS_INVALID or STATUS_EXPIRED)
  s.status = 'STATUS_RUNNING'
  -- 2. Partition filter on recent_roads_data
  AND r.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY 
  r.selected_route_id,
  r.display_name,
  corridor_tier,
  jurisdiction,
  s.dynamic_routing,
  r.record_time,
  r.duration_in_seconds,
  r.has_road_closure
ORDER BY 
  heavy_jam_meters DESC;
```
