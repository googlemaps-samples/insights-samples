---
name: rmi-data-realtime-bigquery
description: Use this skill for near real-time traffic analysis using the recent_roads_data table. This is a superset of the foundation data, enabling granular Speed Reading Interval (SRI) analysis and 60-day rolling performance audits.
---

# RMI Real-Time Data (BigQuery)

This skill provides comprehensive procedural and technical knowledge for working with the Road Management Insights (RMI) near real-time data layer. The `recent_roads_data` table operates as a superset of the foundation data, enabling granular Speed Reading Interval (SRI) analysis, segment-level delay audits, and rapid 60-day operational reviews.

---

## 1. Technical Table Schema (Source of Truth)

The core real-time table contains nested and repeated attributes. The exact columns, repeated structures, data types, physical constraints, string enums, and logical nullability rules are declared in the schema JSON definition file, which acts as the absolute source of truth. Refer directly to this definition for field-level intelligence:

*   **Table: `recent_roads_data`** — High-frequency travel times and segment-level speed intervals.
    *   *Schema Source of Truth:* [recent_roads_data.json](references/recent_roads_data.json)
    *   *Partitioning*: Partitioned by **`DAY`** on the `record_time` column. Sliding retention is hard-capped at **60 days**. Any partitions older than 60 days are automatically pruned/deleted.
    *   *Clustering*: Clustered on **`selected_route_id`** (first position) and `record_time` (second position).


---

## 2. Advanced Querying & SRI Unnesting

Because `speed_reading_intervals` is a repeated RECORD (array), you must flat-map the nested fields to analyze individual road segments.

### The LEFT JOIN UNNEST Safety Standard
*   **Critical Pattern**: Always use `LEFT JOIN UNNEST(speed_reading_intervals)` instead of a comma-join or `INNER JOIN UNNEST`. If a real-time observation does not record any congested segments, an inner unnest will silently discard the entire parent row, biasing your average speed and delay calculations.

```sql
SELECT 
  selected_route_id,
  record_time,
  sri.speed AS segment_speed_state
FROM 
  `my_project.rmi_realtime.recent_roads_data`
LEFT JOIN 
  UNNEST(speed_reading_intervals) AS sri;
```

### Segment Speed Index Mapping
*   **NORMAL**: Speed is running at or near the free-flow speed of the segment.
*   **SLOW**: Telemetry indicates a noticeable reduction in speed (congestion starting).
*   **TRAFFIC_JAM**: Heavy congestion where speeds are heavily degraded.

### Filtering by Road Segment IDs
*   **Topological Road Segments**: The `road_segment_ids` field is an `ARRAY<STRING>` containing the topological road segment Place IDs along the monitored route. This allows you to find which routes pass through a specific physical road segment, or to join with external segment-level catalogs.
*   **Querying Array Membership**: Use `EXISTS` with `UNNEST` to quickly filter routes that contain a specific road segment without flattening your dataset:
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

## 3. Troubleshooting & Common Pitfalls

| Symptom / Error | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **Parent records vanish from results** | Using `CROSS JOIN UNNEST` or `, UNNEST` when some records have empty SRI lists. | Replace with `LEFT JOIN UNNEST(speed_reading_intervals) AS sri`. |
| **`Cannot query table: 60-day limit exceeded`** | Accessing records older than the 60-day sliding retention window. | Always filter `record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 60 DAY)`. Defer older queries to the historical archive. |
| **High latency / scan costs** | Querying raw geometries without geographic filtering. | Filter using bounding boxes early: `ST_INTERSECTS(route_geometry, ST_GEOGFROMTEXT('POLYGON(...)'))`. |
| **Zero results returned for current hour** | Processing delay from ingestion pipeline. | Check telemetry latency: `SELECT MAX(record_time) FROM recent_roads_data`. Keep in mind data can have a 2-5 minute delay. |

---

## 4. References
* [Google Maps Platform - Roads Management Insights Overview](https://developers.google.com/maps/documentation/roads-management-insights/overview)
* [Google Maps Platform - RMI Guidelines & Governance](https://developers.google.com/maps/documentation/roads-management-insights/guidelines)
* [Google Maps Platform - RMI Real-Time Data](https://developers.google.com/maps/documentation/roads-management-insights/real-time-data)

---

## 5. Examples

### Example 1: Near Live Corridor Speed Ratio & State Analysis
Calculate current segment congestion metrics across active monitored routes for the last 15 minutes of live operations:
```sql
SELECT 
  selected_route_id,
  record_time,
  sri.speed AS segment_speed_state,
  -- Calculate georeferenced length of the congested segment in meters
  SUM(ST_LENGTH(coords)) AS segment_length_meters
FROM 
  `my_project.rmi_realtime.recent_roads_data`
LEFT JOIN 
  UNNEST(speed_reading_intervals) AS sri
LEFT JOIN 
  UNNEST(sri.interval_coordinates) AS coords
WHERE 
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)
GROUP BY 
  selected_route_id,
  record_time,
  segment_speed_state
ORDER BY 
  record_time DESC, 
  segment_length_meters DESC;
```

### Example 2: Corridors with the Most Frequent 'TRAFFIC_JAM' Segments
Identify which routes have experienced the highest proportion of severe congestion over the last 7 days of operations:
```sql
SELECT 
  selected_route_id,
  COUNT(1) AS total_intervals_logged,
  COUNTIF(sri.speed = 'TRAFFIC_JAM') AS jam_intervals,
  COUNTIF(sri.speed = 'SLOW') AS slow_intervals,
  -- Calculate % of route segments currently bottlenecked
  SAFE_DIVIDE(
    COUNTIF(sri.speed = 'TRAFFIC_JAM'), 
    COUNT(1)
  ) * 100 AS pct_time_jammed
FROM 
  `my_project.rmi_realtime.recent_roads_data`
LEFT JOIN 
  UNNEST(speed_reading_intervals) AS sri
WHERE 
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY 
  selected_route_id
HAVING 
  total_intervals_logged > 100
ORDER BY 
  pct_time_jammed DESC
LIMIT 10;
```

### Example 3: Unique Road Segment Coverage Across Monitored Routes
List the distinct road segments being monitored, along with the count of unique routes that traverse them:

> [!WARNING]
> **Historical Nulls / Empty Arrays**: Because `road_segment_ids` was introduced recently, older historical partitions will have empty or NULL arrays for this column.
> * If you use `CROSS JOIN UNNEST(road_segment_ids)`, any older records with empty arrays will be completely omitted from your query results.
> * To safely query historical trends across the schema transition boundary, use `LEFT JOIN UNNEST(road_segment_ids)` to prevent parent records from being discarded.

```sql
SELECT 
  seg_id,
  COUNT(DISTINCT selected_route_id) AS routes_traversing_count
FROM 
  `my_project.rmi_realtime.recent_roads_data`
CROSS JOIN 
  UNNEST(road_segment_ids) AS seg_id
WHERE 
  -- Restricting to a recent window ensures we only look at records containing the new field
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
GROUP BY 
  seg_id
ORDER BY 
  routes_traversing_count DESC;
```


