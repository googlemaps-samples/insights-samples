# RMI Table & Column Description Dictionary & Inheritance Standard

This document defines the canonical descriptions for foundational RMI tables, column metadata, and the standard rules for description inheritance in derived tables, views, and BigQuery ML models.

---

## 1. Description Inheritance Tenet

When creating derived tables, summary views, or materialized extracts in BigQuery from upstream RMI datasets:
1. **Always Supply Table/View Descriptions**: Every `CREATE TABLE`, `CREATE VIEW`, or `CREATE MODEL` statement must include an `OPTIONS(description = "...")` block providing clear business context, timeframe/scope, and lineage.
2. **Inherit Column Metadata for Core Fields**: If a column originates directly from an RMI source table (e.g. `selected_route_id`, `display_name`, `record_time`, `duration_in_seconds`, `static_duration_in_seconds`, `route_geometry`, `status`, `validation_error`), its column-level description (`OPTIONS(description = "...")`) must inherit the canonical definitions defined below.
3. **Explicitly Document Derived & Transformed Fields**: Computed metrics (such as `delay_ratio`, `hours_since_last_update`, `route_length_meters`, `snapshot_time`, `cluster_id`) must have explicit, unambiguous descriptions documenting the formula or transformation logic.
4. **BigQuery ML Model Documentation**: BigQuery ML does NOT support `description` as a parameter inside the `OPTIONS(...)` block of `CREATE MODEL` (which only accepts ML hyperparameters). Models should be documented with SQL header comments or post-creation DDL: `ALTER MODEL <model_name> SET OPTIONS(description = "...")`.

---

## 2. Canonical Column Dictionary

### A. Route Identification & Lifecycle Metadata (from `routes_status`)

| Column Name | Data Type | Canonical Description |
| :--- | :--- | :--- |
| `selected_route_id` | `STRING` | Unique identifier for the SelectedRoute resource. Primary correlation key across all RMI telemetry and status tables. |
| `display_name` | `STRING` | User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards. |
| `status` | `STRING` | The current operational lifecycle state of the route (`STATUS_SCHEDULING`, `STATUS_RUNNING`, `STATUS_DELETING`, `STATUS_VALIDATING`, `STATUS_INVALID`). |
| `validation_error` | `STRING` | Detailed error code explaining why a route is in `STATUS_INVALID` (`VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION`, `VALIDATION_ERROR_LOW_ROAD_USAGE`). NULL for valid routes. |
| `low_road_usage_start_time` | `TIMESTAMP` | The UTC timestamp when the route first transitioned to `STATUS_INVALID` due to low road usage during periodic re-validation. |
| `route_attributes` | `STRING` | JSON-formatted flat string of custom key-value metadata attributes (e.g., region, tier, priority, route_length). |

### B. Historical Travel Time Telemetry (from `historical_travel_time`)

| Column Name | Data Type | Canonical Description |
| :--- | :--- | :--- |
| `record_time` | `TIMESTAMP` | The UTC timestamp representing when the route data was computed. Daily partitioning column for pruning scans. |
| `duration_in_seconds` | `FLOAT64` | The traffic-aware duration of the route in seconds under observed real-time traffic conditions at `record_time`. |
| `static_duration_in_seconds` | `FLOAT64` | The traffic-unaware (static) duration of the route in seconds under ideal free-flow conditions. Baseline for delay calculations. |
| `route_geometry` | `GEOGRAPHY` | The traffic-aware optimal polyline geometry of the route as a GEOGRAPHY object (WKT, EPSG:4326). |

### C. Real-Time Telemetry & SRI (from `recent_roads_data`)

| Column Name | Data Type | Canonical Description |
| :--- | :--- | :--- |
| `speed_reading_intervals` | `ARRAY<STRUCT>` | Array of speed reading interval records along the route segments, indicating localized congestion and speeds (`NORMAL`, `SLOW`, `TRAFFIC_JAM`). |
| `interval_coordinates` | `ARRAY<GEOGRAPHY>` | Array of geospatial point coordinates defining the sub-segment geometry within a speed reading interval. |
| `speed` | `STRING` | The traffic speed classification for the interval (`NORMAL`, `SLOW`, `TRAFFIC_JAM`). |

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

---

## 3. Implementation Patterns

### Pattern 1: Materialized Clustered Table with Inherited Descriptions
```sql
CREATE OR REPLACE TABLE `my_project.writable_dataset.corridor_travel_time`
(
  selected_route_id STRING OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  record_time TIMESTAMP OPTIONS(description="The UTC timestamp representing when the route data was computed. Daily partitioning column."),
  duration_in_seconds FLOAT64 OPTIONS(description="The traffic-aware duration of the route in seconds under observed real-time traffic conditions."),
  static_duration_in_seconds FLOAT64 OPTIONS(description="The traffic-unaware (static) duration of the route in seconds under ideal free-flow conditions."),
  route_geometry GEOGRAPHY OPTIONS(description="The traffic-aware optimal polyline geometry of the route as a GEOGRAPHY object (WKT, EPSG:4326).")
)
PARTITION BY DATE(record_time)
CLUSTER BY selected_route_id
OPTIONS (
  description="Materialized 7-day corridor extract of RMI historical travel time data inheriting canonical column descriptions."
) AS
SELECT selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry
FROM `LINKED_DATASET_NAME.historical_travel_time`
WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY);
```

### Pattern 2: Cleaned Transformation View
```sql
CREATE OR REPLACE VIEW `my_project.writable_dataset.routes_status_cleaned`
(
  selected_route_id OPTIONS(description="Unique identifier for the SelectedRoute resource. Primary correlation key across RMI telemetry datasets."),
  display_name OPTIONS(description="User-provided descriptive name for the route. Intended for human readability in reports and UI dashboards."),
  status OPTIONS(description="The current operational lifecycle state of the route (e.g., STATUS_RUNNING)."),
  validation_error OPTIONS(description="Detailed error code explaining why a route is in STATUS_INVALID (NULL for valid routes)."),
  route_length_meters OPTIONS(description="Intended physical route length in meters, cast to FLOAT64 from custom route_attributes.")
)
OPTIONS (
  description="Cleaned view of SelectedRoutes excluding invalid routes and promoting custom attributes to typed columns."
) AS
SELECT selected_route_id, display_name, status, validation_error,
       SAFE_CAST(COALESCE(JSON_VALUE(route_attributes, '$.route_length_meters'), JSON_VALUE(route_attributes, '$.route_length')) AS FLOAT64) AS route_length_meters
FROM `LINKED_DATASET_NAME.routes_status`
WHERE status != 'STATUS_INVALID';
```
