# RMI Table & Column Description Dictionary & Inheritance Standard

This document defines the canonical descriptions for foundational RMI tables, column metadata, and the standard rules for description inheritance in derived tables, views, and BigQuery ML models.

---

## 1. Description Inheritance Tenet

When creating derived tables, summary views, or materialized extracts in BigQuery from upstream RMI datasets:

1. **Always Supply Table/View Descriptions**: Every `CREATE TABLE`, `CREATE VIEW`, or `CREATE MODEL` statement must include an `OPTIONS(description = "...")` block providing clear business context, timeframe/scope, and lineage.
2. **Inherit Column Metadata for Core Fields**: If a column originates directly from an RMI source table (e.g. `selected_route_id`, `display_name`, `record_time`, `duration_in_seconds`, `static_duration_in_seconds`, `route_geometry`, `status`, `validation_error`, `has_road_closure`, `road_segment_ids`), its column-level description (`OPTIONS(description = "...")`) must inherit the canonical definitions defined below.
3. **Explicitly Document Derived & Transformed Fields**: Computed metrics (such as `delay_ratio`, `hours_since_last_update`, `route_length_meters`, `snapshot_time`, `cluster_id`) must have explicit, unambiguous descriptions documenting the formula or transformation logic.
4. **BigQuery ML Model Documentation**: BigQuery ML does NOT support `description` as a parameter inside the `OPTIONS(...)` block of `CREATE MODEL` (which only accepts ML hyperparameters). Models should be documented with SQL header comments or post-creation DDL: `ALTER MODEL <model_name> SET OPTIONS(description = "...")`.

---

## 2. Canonical Column Dictionary

### A. Route Identification & Lifecycle Metadata (from `routes_status`)

The `routes_status` table contains 12 authoritative fields describing route configuration and operational lifecycle status:

| Column Name | Data Type | Canonical Description |
| :--- | :--- | :--- |
| `selected_route_id` | `STRING` | Unique identifier for the SelectedRoute resource (`projects/{project}/selectedRoutes/{selected_route_id}`). Primary correlation key across all RMI telemetry and status tables. |
| `display_name` | `STRING` | User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards (max 128 characters). |
| `status` | `STRING` | The current operational lifecycle state of the route (`STATUS_RUNNING`, `STATUS_INVALID`, `STATUS_EXPIRED`). Active telemetry is only monitored for routes in `STATUS_RUNNING`. |
| `validation_error` | `STRING` | Detailed error code explaining why a route is in `STATUS_INVALID` (`VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION`, `VALIDATION_ERROR_LOW_ROAD_USAGE`). NULL for valid running routes. |
| `low_road_usage_start_time` | `TIMESTAMP` | The UTC timestamp when the route first transitioned to `STATUS_INVALID` due to low road usage during periodic re-validation. |
| `route_attributes` | `STRING` | JSON-formatted flat string of custom key-value metadata attributes (up to 25 key-value string pairs, e.g., tier, region, priority, route_length). |
| `dynamic_routing` | `BOOLEAN` | Indicates whether the route is configured for real-time dynamic rerouting (`true`) or fixed routing (`false`). |
| `origin` | `GEOGRAPHY` | Origin waypoint coordinate of the route as a GEOGRAPHY point. |
| `destination` | `GEOGRAPHY` | Destination waypoint coordinate of the route as a GEOGRAPHY point. |
| `intermediates` | `ARRAY<GEOGRAPHY>` | Repeated array of intermediate waypoint coordinates along the route. |
| `static_route_geometry` | `GEOGRAPHY` | Polyline geometry of the static route calculated without live traffic from the waypoints (EPSG:4326). |
| `road_segment_ids` | `ARRAY<STRING>` | Sequence of Place IDs in topological order representing connected road segments along the static route calculated without live traffic. |

### B. Historical Travel Time Telemetry (from `historical_travel_time`)

The `historical_travel_time` table stores long-term historical records across 8 fields:

| Column Name | Data Type | Canonical Description |
| :--- | :--- | :--- |
| `selected_route_id` | `STRING` | Unique identifier for the SelectedRoute resource (first clustering column). Correlates with `routes_status`. |
| `display_name` | `STRING` | User-provided descriptive name for the route. |
| `record_time` | `TIMESTAMP` | The UTC timestamp representing when the route data was computed. Daily partitioning column (`DAY(record_time)`). |
| `duration_in_seconds` | `FLOAT64` | The traffic-aware duration of the route in seconds under observed real-time traffic conditions at `record_time`. **Omitted (`NULL`) when `has_road_closure = true`** because the corridor is impassable. |
| `static_duration_in_seconds` | `FLOAT64` | The traffic-unaware (static) baseline duration in seconds under ideal free-flow conditions. Baseline for delay calculations. |
| `route_geometry` | `GEOGRAPHY` | The traffic-aware optimal polyline geometry of the route taken at `record_time` as a GEOGRAPHY object (WKT, EPSG:4326). |
| `road_segment_ids` | `ARRAY<STRING>` | Repeated array of Google Place IDs representing traversed road segments in topological order at `record_time` (populated for records on or after June 19, 2026). |
| `has_road_closure` | `BOOLEAN` | Indicates whether there is a full road closure on the route (consistent with Google Maps live closure status). When `true`, `duration_in_seconds` is `NULL`. |

### C. Real-Time Telemetry & SRI (from `recent_roads_data`)

The `recent_roads_data` table stores near real-time telemetry across 10 fields:

| Column Name | Data Type | Canonical Description |
| :--- | :--- | :--- |
| `selected_route_id` | `STRING` | Unique identifier for the SelectedRoute resource. Primary correlation key across all RMI datasets. |
| `display_name` | `STRING` | User-provided descriptive name for the route. |
| `record_time` | `TIMESTAMP` | The UTC timestamp representing when the route data was computed. Daily partitioning column (60-day sliding retention). |
| `duration_in_seconds` | `FLOAT64` | The traffic-aware duration in seconds. **Omitted (`NULL`) when `has_road_closure = true`**. |
| `static_duration_in_seconds` | `FLOAT64` | The traffic-unaware (static) baseline duration in seconds under ideal free-flow conditions. |
| `route_geometry` | `GEOGRAPHY` | The optimal polyline geometry of the route as a GEOGRAPHY object (EPSG:4326). |
| `speed_reading_intervals` | `ARRAY<STRUCT>` | **Legacy coordinate-based speed reading intervals**. May cease population on or after **January 13, 2027**. Use `speed_reading_offsets` instead. |
| `road_segment_ids` | `ARRAY<STRING>` | Sequence of Google Place IDs representing connected physical road segments traversed at `record_time`. |
| `speed_reading_offsets` | `ARRAY<STRUCT>` | **Modern offset-based speed reading intervals** demarcated by meter distance from route start (`start_offset INT64`, `end_offset INT64`, `speed STRING`). Available as of **October 8, 2026**. Omitted when `has_road_closure = true`. 4 traffic tiers: `NORMAL`, `SLOW`, `TRAFFIC_JAM`, `TRAFFIC_JAM_HEAVY`. |
| `has_road_closure` | `BOOLEAN` | Indicates whether there is an active full road closure on the route. When `true`, `duration_in_seconds` and `speed_reading_offsets` are `NULL`. |

### D. Common Derived & Transformed Columns

| Derived Column Name | Data Type | Recommended Inherited / Derived Description |
| :--- | :--- | :--- |
| `delay_ratio` | `FLOAT64` | Ratio of traffic-aware duration to static duration (`duration_in_seconds / static_duration_in_seconds`). Values > 1.0 indicate delay relative to free-flow. |
| `route_length_meters` | `FLOAT64` | Intended physical length of the route in meters, extracted and cast to FLOAT64 from custom `route_attributes.route_length`. |
| `region` | `STRING` | Geographical business region extracted from custom `route_attributes.region`. |
| `tier` | `STRING` | Service tier (e.g., priority, standard) extracted from custom `route_attributes.tier`. |
| `priority` | `STRING` | Operational monitoring priority level extracted from custom `route_attributes.priority`. |
| `snapshot_time` | `TIMESTAMP` | The UTC timestamp when the periodic status snapshot was captured. |
| `last_updated` | `TIMESTAMP` | The UTC timestamp of the most recent telemetry record found in `historical_travel_time`. |
| `hours_since_last_update` | `INT64` | Age of telemetry data in hours relative to the reference audit timestamp. |
| `cluster_id` | `INT64` | Centroid cluster identifier assigned by BQML K-Means clustering representing shared diurnal traffic profiles. |
| `predicted_duration` | `FLOAT64` | Predicted route travel duration in seconds generated by time-series forecasting models (ARIMA_PLUS or TimesFM). |
| `lower_bound` | `FLOAT64` | Lower bound of the prediction confidence interval in seconds. |
| `upper_bound` | `FLOAT64` | Upper bound of the prediction confidence interval in seconds. |
| `interval_length_meters` | `INT64` | Physical length of a speed reading interval in meters, computed via integer offset subtraction `(end_offset - start_offset)`. |
| `heavy_jam_km` | `FLOAT64` | Physical distance in kilometers in severe standstill gridlock (`TRAFFIC_JAM_HEAVY`). |

---

## 3. Implementation Patterns

### Pattern 1: Materialized Clustered Table with Inherited Descriptions

```sql
CREATE OR REPLACE TABLE `my_project.writable_dataset.corridor_travel_time`
(
  selected_route_id STRING OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  record_time TIMESTAMP OPTIONS(description="The UTC timestamp representing when the route data was computed. Daily partitioning column."),
  duration_in_seconds FLOAT64 OPTIONS(description="The traffic-aware duration of the route in seconds under observed real-time traffic conditions. NULL during road closures."),
  static_duration_in_seconds FLOAT64 OPTIONS(description="The traffic-unaware (static) duration of the route in seconds under ideal free-flow conditions."),
  route_geometry GEOGRAPHY OPTIONS(description="The traffic-aware optimal polyline geometry of the route as a GEOGRAPHY object (WKT, EPSG:4326)."),
  road_segment_ids ARRAY<STRING> OPTIONS(description="Repeated array of Google Place IDs representing traversed road segments at record_time."),
  has_road_closure BOOLEAN OPTIONS(description="Indicates whether there is a full road closure on the route (consistent with Google Maps live closure status).")
)
PARTITION BY DATE(record_time)
CLUSTER BY selected_route_id
OPTIONS (
  description="Materialized 7-day corridor extract of RMI historical travel time data inheriting canonical column descriptions across all 8 fields."
) AS
SELECT selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry, road_segment_ids, has_road_closure
FROM `LINKED_DATASET_NAME.historical_travel_time`
WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY);
```

### Pattern 2: Cleaned Transformation View

```sql
CREATE OR REPLACE VIEW `my_project.writable_dataset.routes_status_cleaned`
(
  selected_route_id OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  status OPTIONS(description="The current operational lifecycle state of the route (STATUS_RUNNING)."),
  validation_error OPTIONS(description="Detailed error code explaining why a route is in STATUS_INVALID (NULL for valid running routes)."),
  dynamic_routing OPTIONS(description="Indicates whether the route is dynamic (true) or fixed (false)."),
  static_route_geometry OPTIONS(description="Polyline geometry of the static route calculated without live traffic from the waypoints."),
  road_segment_ids OPTIONS(description="Sequence of Place IDs representing topological road segments along the static route."),
  route_length_meters OPTIONS(description="Intended physical route length in meters, cast to FLOAT64 from custom route_attributes.")
)
OPTIONS (
  description="Cleaned view of active SelectedRoutes enforcing STATUS_RUNNING and promoting custom attributes to typed columns."
) AS
SELECT selected_route_id, display_name, status, validation_error, dynamic_routing, static_route_geometry, road_segment_ids,
       SAFE_CAST(COALESCE(JSON_VALUE(route_attributes, '$.route_length_meters'), JSON_VALUE(route_attributes, '$.route_length')) AS FLOAT64) AS route_length_meters
FROM `LINKED_DATASET_NAME.routes_status`
WHERE status = 'STATUS_RUNNING';
```
