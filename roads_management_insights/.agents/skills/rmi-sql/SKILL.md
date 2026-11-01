---
name: rmi-sql
description: Use this skill for RMI-specific SQL design, including SRI analysis, route metadata parsing, bottleneck detection, and complex traffic metrics. This is the expert guide for writing high-quality queries against RMI BigQuery datasets.
dependencies:
  - rmi-data-foundation-bigquery
  - rmi-data-realtime-bigquery
  - bigquery-practices
  - bigquery-geospatial
  - rmi-sampledatasets
---

# RMI SQL Reference & Query Logic

This skill provides expert-level procedural knowledge for applying BigQuery capabilities to RMI-specific data structures, modern schema evolutions, and business use cases.

## 1. RMI-Specific Analytical Patterns

### Path & Bottleneck Analysis

- **Segment-Level Congestion & Offsets (`speed_reading_offsets`)**:
  - Unnesting `speed_reading_offsets` from `recent_roads_data`. Available as of **October 8, 2026**, offset-based intervals replace legacy coordinate arrays with lightweight meter offsets (`start_offset`, `end_offset`, `speed`).
  - **Pure Integer Distance Calculations**: The physical length of each speed interval in meters is computed via pure integer subtraction: `(sro.end_offset - sro.start_offset)`. This eliminates expensive geospatial functions (`ST_LENGTH`, `ST_MAKELINE`), speeding up BigQuery aggregations by 10x–50x and reducing query scan overhead.
  - **The 4 Traffic Tiers**:
    - `NORMAL` (Green): Smooth flow; no slowdown detected.
    - `SLOW` (Yellow): Slowdown detected, but free-flowing.
    - `TRAFFIC_JAM` (Red): Traffic congestion and queueing detected.
    - `TRAFFIC_JAM_HEAVY` (Dark Red, available as of Oct 8, 2026): Severe standstill gridlock.
  - **LEFT JOIN UNNEST Safety Standard**: Always use `LEFT JOIN UNNEST(speed_reading_offsets) AS sro` instead of comma or `INNER JOIN UNNEST`. When an observation has no congestion or has an active road closure, the array is empty or omitted; an inner unnest silently discards the entire route observation.
  - **Legacy Coordinate Deprecation**: Coordinate-based `speed_reading_intervals` (with `interval_coordinates` and `ST_MAKELINE`) is phasing out and may cease population on or after **January 13, 2027**. All production queries should adopt `speed_reading_offsets`.

- **Road Closures & Impassable Corridor Invariant (`has_road_closure`)**:
  - `has_road_closure = true` indicates a full road closure consistent with Google Maps live closure status.
  - **Duration Nullability Invariant**: When `has_road_closure = true`, `duration_in_seconds` is omitted (`NULL`) and `speed_reading_offsets` is omitted (`NULL`) because a route travel duration cannot be computed for an impassable corridor.
  - **Safe Aggregation Patterns**:
    - Filtering strictly with `duration_in_seconds IS NOT NULL` silently drops real physical road closures!
    - When evaluating passable travel time, explicitly filter:
      `WHERE (has_road_closure IS FALSE OR has_road_closure IS NULL) AND duration_in_seconds IS NOT NULL`.
    - When auditing operational reliability or downtime, capture both modes conditionally:
      ```sql
      AVG(CASE WHEN COALESCE(has_road_closure, FALSE) IS FALSE THEN duration_in_seconds END) AS avg_duration_seconds,
      COUNTIF(has_road_closure IS TRUE) AS road_closure_incidents
      ```

- **Mandatory `routes_status` Companion Join (`s.status = 'STATUS_RUNNING'`)**:
  - Standard practice requires joining `routes_status s USING (selected_route_id)` when querying `historical_travel_time` or `recent_roads_data`.
  - Always enforce `WHERE s.status = 'STATUS_RUNNING'` to filter out invalid (`STATUS_INVALID`), validating, or deleted route telemetry.

- **Dynamic Routing Flag (`s.dynamic_routing`)**:
  - `dynamic_routing = true`: Route is configured for real-time dynamic rerouting around congestion and incidents. Its observed path (`historical_travel_time.road_segment_ids` or `route_geometry`) will diverge dynamically from the static baseline (`routes_status.road_segment_ids` / `static_route_geometry`).
  - `dynamic_routing = false`: Route is fixed to a static road segment sequence.
  - **Integrity Audits**: When auditing route integrity (comparing actual polyline length vs intended length), always filter `WHERE s.dynamic_routing = FALSE` to prevent flagging intentional congestion diversions as integrity failures.
  - **Detour Audits**: When detecting incident diversions, filter `WHERE s.dynamic_routing = TRUE` and compare `h.road_segment_ids` against baseline `s.road_segment_ids`.

- **Path Integrity**: Always filter for `ST_LineString` on traffic-aware polyline datasets. **Apply this filter as early as possible (e.g., in the first CTE)** to optimize performance. *Note: Static road network tables typically don't require this check.*

- **Route Deviation Audit**: Filter for routes where the actual physical length (`ST_LENGTH(route_geometry)`) deviates significantly from the intended `route_length` (stored in `route_attributes`). Apply a tolerance ratio (e.g., `0.9` to `1.1`) in early CTEs to exclude unreliable records:

    ```sql
    WHERE SAFE_DIVIDE(ST_LENGTH(route_geometry), SAFE_CAST(COALESCE(JSON_VALUE(route_attributes, '$.route_length_meters'), JSON_VALUE(route_attributes, '$.route_length')) AS FLOAT64)) BETWEEN 0.9 AND 1.1
    ```

- **Dynamic Path Variation & Detour Detection (`road_segment_ids`)**:
  - *Fingerprinting Path Variants*: Use `ARRAY_TO_STRING(road_segment_ids, '|')` to convert the segment Place ID sequence into a string fingerprint that can be grouped (`GROUP BY 1, 2, 3`).
  - *July 1, 2026 Temporal Schema Threshold*: The `road_segment_ids` column was added on **July 1, 2026**. Telemetry records prior to this date contain empty/NULL arrays. All queries using `road_segment_ids` MUST enforce:

    ```sql
    WHERE record_time >= '2026-07-01' AND ARRAY_LENGTH(road_segment_ids) > 0
    ```

  - *Detour Delay Multiplier*: Aggregate variants into an array sorted by sample count (`ARRAY_AGG(STRUCT(...) ORDER BY num_of_records DESC)`). Index `0` is the dominant baseline path; subsequent indices are detour variants. Compute `SAFE_DIVIDE(variations[OFFSET(1)].avg_duration_in_seconds, variations[OFFSET(0)].avg_duration_in_seconds)` to isolate high-penalty congestion diversions.

### Reliability & Performance Metrics

- **Local Time Conversion**: `record_time` is stored in UTC. For intuitive reporting, always convert to the local timezone using `DATETIME(record_time, "America/New_York")` (or appropriate zone).
- **Duration Ratio**: Calculate traffic impact using `SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)`.
- **JSON Attributes**: Parse custom RMI metadata (up to 25 key-value string pairs) using `JSON_VALUE(route_attributes, '$.key')`.

### Telemetry Payload Unpacking & Geometry Reconstruction (Legacy Intervals)

When querying raw streaming tables or reconstructing geometry from legacy coordinate intervals (prior to the Jan 13, 2027 sunset), use `ST_MAKELINE`:

- **Interval Coordinates Reconstruction**: `interval_coordinates` is an array of `ST_Point`. Reconstruct sub-segment geometry using `ST_MAKELINE(interval_coordinates)`.
- **Dynamic Geometry Assembly**: Dynamic geometries represented as nested arrays of points inside a parent array must be built using a two-level unnest-aggregation process:
  1. Map each nested position to `ST_GEOGPOINT`.
  2. Assemble coordinate arrays into a continuous path using `ST_MAKELINE`.
  3. Aggregate lines across the parent array using `ST_UNION_AGG`.

  *Example*:

  ```sql
  (
    SELECT ST_UNION_AGG(
      ST_MAKELINE(
        ARRAY(
          SELECT ST_GEOGPOINT(
            CAST(JSON_VALUE(pos, "$.longitude") AS FLOAT64),
            CAST(JSON_VALUE(pos, "$.latitude") AS FLOAT64)
          )
          FROM UNNEST(JSON_EXTRACT_ARRAY(stretch, "$.positions")) AS pos
        )
      )
    )
    FROM UNNEST(JSON_EXTRACT_ARRAY(data, "$.stretches")) AS stretch
  ) AS stretches_geometry
  ```

## 2. RMI Query Standards

- **Project Portability**: Omit the project ID prefix from table names (e.g., use `` `dataset.table` ``). Queries should rely on the default project associated with the BigQuery job to ensure portability across environments.
- **Job ID Convention**: All RMI queries MUST follow the `rmisamplesql_<queryid>_<timestamp>` format.
- **Mandatory Joins**: Standard practice joins `routes_status` with `historical_travel_time` or `recent_roads_data` via `selected_route_id`.

## 3. Query Execution Guardrails & CLI Driver Standards

### Safe Parsing Guardrails

- **Null & Malformed Protection**: Never use raw `CAST(...)` or `PARSE_TIMESTAMP(...)` on unstructured JSON fields or user routeAttributes. Always use `SAFE_CAST(...)` and `SAFE.PARSE_TIMESTAMP(...)` to prevent execution crashes on dirty/null inputs.

### CLI Driver & `bq query` Input Pipe

- **Comment Header Flag Recursion Avoidance**: Queries with SQL comment headers starting with `--` (such as `-- Job ID: rmisamplesql_...`) trigger flag parsing recursion in the `bq` CLI if passed as raw positional arguments. Always pipe SQL query strings via standard input (`input=query` in Python `subprocess.run`) or pass temporary file handles (`bq query ... < query.sql`).

### Job Labeling vs Multi-Statement Sessions

- **Submission-Time Job Labels**: Single SQL query files should not execute `SET @@query_label = "..."` (which requires multi-statement session contexts). Instead, attach metadata labels at job submission time:
  - **CLI**: `bq query --label=persona:urban_planner --label=usecase:corridor_trend`
  - **Python SDK**: `job_config.labels = {"persona": "urban_planner", "usecase": "corridor_trend"}`

### Parallel Dry-Run Validation (`scripts/dry_run_all_queries.py`)

- **Fast Zero-Cost Syntax Verification**: Execute `bq query --dry_run` with `ThreadPoolExecutor(max_workers=10)` to validate SQL syntax, schema resolution, and byte scan estimates across query libraries in parallel without executing database scans or incurring costs.

## 4. Geospatial Optimization & Derived Tables

### Hourly Array Aggregation Optimization

When transforming raw high-resolution spatial tables (e.g. 2-minute sampling frequency, giving 720 records per day) into geospatially-clustered derived tables, using `ARRAY_AGG` directly on unnested records causes massive nested array inflation. This bloats network transport size and impacts client-side rendering.

- **The Optimization:** Perform a two-stage aggregation. In the first stage (intermediate CTE), group by `selected_route_id, EXTRACT(HOUR FROM record_time) AS hour_of_day` and use logical aggregations to capture the worst-case speed state across modern `speed_reading_offsets` inside each hour (evaluating `TRAFFIC_JAM_HEAVY` first):

  ```sql
  CASE 
    WHEN LOGICAL_OR(sro.speed = 'TRAFFIC_JAM_HEAVY') THEN 'TRAFFIC_JAM_HEAVY'
    WHEN LOGICAL_OR(sro.speed = 'TRAFFIC_JAM') THEN 'TRAFFIC_JAM'
    WHEN LOGICAL_OR(sro.speed = 'SLOW') THEN 'SLOW'
    ELSE 'NORMAL'
  END AS worst_hourly_speed
  ```

- In the second stage, aggregate the consolidated hourly records into the final nested array `ARRAY_AGG(STRUCT(hour_of_day, worst_hourly_speed) ORDER BY hour_of_day)`. This guarantees at most 24 elements per road segment, shrinking database size and payload by over 95%.

```sql
WITH hourly_stage AS (
  SELECT 
    r.selected_route_id,
    s.display_name,
    EXTRACT(HOUR FROM r.record_time) AS hour_of_day,
    -- Pre-aggregate interval records into the worst-case traffic state per hour
    CASE 
      WHEN LOGICAL_OR(sro.speed = 'TRAFFIC_JAM_HEAVY') THEN 'TRAFFIC_JAM_HEAVY'
      WHEN LOGICAL_OR(sro.speed = 'TRAFFIC_JAM') THEN 'TRAFFIC_JAM'
      WHEN LOGICAL_OR(sro.speed = 'SLOW') THEN 'SLOW'
      ELSE 'NORMAL'
    END AS worst_hourly_speed
  FROM `LINKED_DATASET_NAME.recent_roads_data` AS r
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  LEFT JOIN UNNEST(r.speed_reading_offsets) AS sro
  WHERE ST_GEOMETRYTYPE(r.route_geometry) = 'ST_LineString'
    AND s.status = 'STATUS_RUNNING'
    AND (r.has_road_closure IS FALSE OR r.has_road_closure IS NULL)
    AND r.record_time >= '2026-07-15 00:00:00' AND r.record_time < '2026-07-16 00:00:00'
  GROUP BY r.selected_route_id, s.display_name, hour_of_day
)
SELECT 
  selected_route_id,
  display_name,
  ARRAY_AGG(STRUCT(hour_of_day, worst_hourly_speed) ORDER BY hour_of_day) AS hourly_congestion_profile
FROM hourly_stage
GROUP BY selected_route_id, display_name;
```

### Preventing Geography Grouping & Mixing

- BigQuery does not allow `GROUP BY` on complex `GEOGRAPHY` objects directly.
- **Group by WKT Text:** Always group on `ST_ASTEXT(coords)` to ensure mathematically distinct geometries are isolated and not blended.
- **Deterministic Reconstruction:** In the SELECT list, use `ST_GEOGFROMTEXT(geometry_wkt)` of the grouped WKT string. This is deterministic and guarantees zero risk of mixing or blending distinct geometries, which can happen with non-deterministic aggregations like `ANY_VALUE`.

## 5. Modern High-Value Analytical Query Patterns

### Pattern 1: Severe Standstill Congestion & Heavy Jam Mileage (`recent_roads_data`)

Leverages modern integer meter arithmetic `(end_offset - start_offset)` over `speed_reading_offsets` to audit kilometers of gridlock (`TRAFFIC_JAM_HEAVY`) without expensive GIS spatial operations:

```sql
-- Job ID: rmisamplesql_heavy_congestion_mileage_YYYYMMDDHHMMSS
-- Purpose: Calculate physical kilometers in TRAFFIC_JAM_HEAVY vs standard TRAFFIC_JAM
SELECT
  r.selected_route_id,
  s.display_name,
  DATE(r.record_time) AS record_date,
  -- Calculate physical distance (km) in severe gridlock vs standard congestion via integer subtraction
  ROUND(SUM(CASE WHEN sro.speed = 'TRAFFIC_JAM_HEAVY' THEN (sro.end_offset - sro.start_offset) ELSE 0 END) / 1000.0, 2) AS heavy_jam_km,
  ROUND(SUM(CASE WHEN sro.speed = 'TRAFFIC_JAM' THEN (sro.end_offset - sro.start_offset) ELSE 0 END) / 1000.0, 2) AS standard_jam_km,
  ROUND(SUM(CASE WHEN sro.speed IN ('TRAFFIC_JAM', 'TRAFFIC_JAM_HEAVY') THEN (sro.end_offset - sro.start_offset) ELSE 0 END) / 1000.0, 2) AS total_congested_km,
  COUNT(DISTINCT r.record_time) AS total_observations
FROM `LINKED_DATASET_NAME.recent_roads_data` AS r
JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
LEFT JOIN UNNEST(r.speed_reading_offsets) AS sro
WHERE r.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND s.status = 'STATUS_RUNNING'
  AND (r.has_road_closure IS FALSE OR r.has_road_closure IS NULL)
  AND ST_GEOMETRYTYPE(r.route_geometry) = 'ST_LineString'
GROUP BY 1, 2, 3
HAVING heavy_jam_km > 0.5
ORDER BY heavy_jam_km DESC;
```

### Pattern 2: Full Road Closure Incident Log & Downtime Audit (`recent_roads_data` & `historical_travel_time`)

Audits full corridor downtime where `has_road_closure = true` and `duration_in_seconds IS NULL`, isolating severe disruption windows and calculating affected hours:

```sql
-- Job ID: rmisamplesql_road_closure_audit_YYYYMMDDHHMMSS
-- Purpose: Audit corridor downtime and closure incidents where duration_in_seconds IS NULL
SELECT
  h.selected_route_id,
  s.display_name,
  DATE(h.record_time) AS incident_date,
  MIN(h.record_time) AS closure_first_detected,
  MAX(h.record_time) AS closure_last_detected,
  -- Each observation represents an observation interval
  COUNTIF(h.has_road_closure IS TRUE) AS closure_observation_count,
  -- Average duration is computed strictly on open/passable periods
  ROUND(AVG(CASE WHEN COALESCE(h.has_road_closure, FALSE) IS FALSE THEN h.duration_in_seconds END), 1) AS avg_open_duration_seconds,
  -- Free-flow static baseline
  ANY_VALUE(h.static_duration_in_seconds) AS static_duration_seconds
FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
WHERE h.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND s.status = 'STATUS_RUNNING'
GROUP BY 1, 2, 3
HAVING closure_observation_count > 0
ORDER BY closure_observation_count DESC, closure_first_detected DESC;
```

### Pattern 3: Dynamic Detour Verification (`h.road_segment_ids` vs `s.road_segment_ids`)

Compares observed Place ID sequences in `historical_travel_time.road_segment_ids` against registered static baseline `routes_status.road_segment_ids` on routes where `s.dynamic_routing = true`:

```sql
-- Job ID: rmisamplesql_dynamic_detour_verification_YYYYMMDDHHMMSS
-- Purpose: Compare observed Place ID sequence against registered static baseline on dynamic routes
WITH route_divergences AS (
  SELECT
    h.selected_route_id,
    s.display_name,
    h.record_time,
    h.duration_in_seconds,
    h.static_duration_in_seconds,
    ARRAY_TO_STRING(s.road_segment_ids, '|') AS baseline_segments,
    ARRAY_TO_STRING(h.road_segment_ids, '|') AS observed_segments,
    (ARRAY_TO_STRING(h.road_segment_ids, '|') != ARRAY_TO_STRING(s.road_segment_ids, '|')) AS is_detour,
    h.has_road_closure
  FROM `LINKED_DATASET_NAME.historical_travel_time` AS h
  JOIN `LINKED_DATASET_NAME.routes_status` AS s USING (selected_route_id)
  WHERE h.record_time >= '2026-07-01'
    AND s.status = 'STATUS_RUNNING'
    AND s.dynamic_routing IS TRUE
    AND ARRAY_LENGTH(h.road_segment_ids) > 0
    AND ARRAY_LENGTH(s.road_segment_ids) > 0
)
SELECT
  selected_route_id,
  display_name,
  COUNT(*) AS total_runs,
  COUNTIF(is_detour) AS detour_count,
  ROUND(COUNTIF(is_detour) / COUNT(*), 3) AS detour_frequency,
  ROUND(AVG(CASE WHEN NOT is_detour THEN duration_in_seconds END), 1) AS baseline_avg_duration,
  ROUND(AVG(CASE WHEN is_detour AND COALESCE(has_road_closure, FALSE) IS FALSE THEN duration_in_seconds END), 1) AS detour_avg_duration,
  ROUND(SAFE_DIVIDE(
    AVG(CASE WHEN is_detour AND COALESCE(has_road_closure, FALSE) IS FALSE THEN duration_in_seconds END),
    AVG(CASE WHEN NOT is_detour THEN duration_in_seconds END)
  ), 2) AS detour_delay_multiplier,
  COUNTIF(has_road_closure IS TRUE) AS closure_count
FROM route_divergences
GROUP BY 1, 2
HAVING detour_count > 0
ORDER BY detour_frequency DESC;
```

### Pattern 4: Multi-Attribute Operational Slicing (Expanded 25 Attribute Pairs)

Extracts custom tags from the expanded 25 `route_attributes` pairs (e.g., `corridor`, `tier`, `jurisdiction`, `functional_class`) to compute fleetwide delay and impact metrics:

```sql
-- Job ID: rmisamplesql_multi_attribute_slicing_YYYYMMDDHHMMSS
-- Purpose: Slice route metrics using expanded 25 route_attributes pairs
SELECT
  JSON_VALUE(s.route_attributes, '$.corridor') AS corridor_name,
  COALESCE(JSON_VALUE(s.route_attributes, '$.tier'), 'STANDARD') AS tier,
  JSON_VALUE(s.route_attributes, '$.jurisdiction') AS jurisdiction,
  JSON_VALUE(s.route_attributes, '$.functional_class') AS functional_class,
  COUNT(DISTINCT s.selected_route_id) AS monitored_routes,
  ROUND(AVG(SAFE_DIVIDE(h.duration_in_seconds, h.static_duration_in_seconds)), 2) AS avg_delay_index,
  ROUND(SUM(CASE WHEN (h.duration_in_seconds - h.static_duration_in_seconds) > 0 THEN (h.duration_in_seconds - h.static_duration_in_seconds) ELSE 0 END) / 3600.0, 1) AS total_lost_hours,
  COUNTIF(h.has_road_closure IS TRUE) AS total_closure_incidents
FROM `LINKED_DATASET_NAME.routes_status` AS s
JOIN `LINKED_DATASET_NAME.historical_travel_time` AS h USING (selected_route_id)
WHERE s.status = 'STATUS_RUNNING'
  AND h.record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  AND ST_GEOMETRYTYPE(h.route_geometry) = 'ST_LineString'
GROUP BY 1, 2, 3, 4
HAVING corridor_name IS NOT NULL
ORDER BY total_lost_hours DESC;
```

### Pattern 5: SRI Schema Migration & Deprecation Audit (Jan 13, 2027 Sunset)

Audits enterprise workloads in `INFORMATION_SCHEMA.JOBS` to measure migration from legacy `speed_reading_intervals` to modern `speed_reading_offsets` ahead of the January 13, 2027 sunset:

```sql
-- Job ID: rmisamplesql_sri_migration_audit_YYYYMMDDHHMMSS
-- Purpose: Audit query migration from speed_reading_intervals to speed_reading_offsets ahead of Jan 13, 2027 sunset
WITH rmi_jobs AS (
  SELECT
    job_id,
    user_email,
    query,
    creation_time,
    REGEXP_CONTAINS(query, r"UNNEST\(speed_reading_offsets\)") AS uses_offsets,
    REGEXP_CONTAINS(query, r"UNNEST\(speed_reading_intervals\)") AS uses_legacy_intervals
  FROM `region-us`.INFORMATION_SCHEMA.JOBS
  WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND job_type = 'QUERY'
    AND statement_type = 'SELECT'
    AND (query LIKE '%recent_roads_data%')
)
SELECT
  DATE(creation_time) AS audit_date,
  COUNT(*) AS total_recent_roads_queries,
  COUNTIF(uses_offsets) AS modern_offset_queries,
  COUNTIF(uses_legacy_intervals) AS legacy_interval_queries,
  ROUND(SAFE_DIVIDE(COUNTIF(uses_offsets), COUNTIF(uses_offsets) + COUNTIF(uses_legacy_intervals)) * 100, 1) AS migration_progress_pct
FROM rmi_jobs
WHERE uses_offsets OR uses_legacy_intervals
GROUP BY 1
ORDER BY audit_date DESC;
```

## 6. Spatial Masking vs. Attribute Name Sparsity in Road Selection

### Road Name Sparsity & Selection Risks

- **Attribute Sparsity**: In standard road network datasets, `display_name` coverage can be remarkably sparse. Up to 25%–30% of major mainline controlled-access highway segments (and higher percentages on rural/transition links) carry empty string (`""`) or null display names.
- **Selection Failure Risk**: Filtering strictly by road name string patterns (e.g., `WHERE display_name LIKE '%I-10%'`) will omit significant portions of the target corridor, resulting in fragmented spatial telemetry and broken downstream route calculations.

### Overture Maps Spatial Boundary Masking

- **The Solution (Spatial Masking)**: Rather than relying on fragile textual attributes like `display_name`, use external spatial reference boundaries (such as Overture Maps `transportation_segment` corridor geometries, bounding boxes, or administrative boundary polygons) to build a **pure spatial mask**.
- **Execution Pattern**: Select road network segments by evaluating spatial intersection (`ST_INTERSECTS` / `ST_DWITHIN`) against the spatial mask. This guarantees 100% geometric coverage of the target corridor regardless of missing, localized, or inconsistent road names.

## 7. Analytics Hub Linked Dataset Materialization Constraints & Patterns

- **Materialized Views Restriction**: When querying shared RMI datasets provisioned via Analytics Hub (e.g., `LINKED_DATASET_NAME`), BigQuery strictly forbids `CREATE MATERIALIZED VIEW` directly on linked tables (`Can't create materialized view on linked dataset`).
- **Clustered Table Materialization Pattern**: To pre-aggregate or materialize high-traffic corridors for low-latency BI dashboards:
  - Create a partitioned and clustered physical table in a writable target dataset with column-level descriptions:

    ```sql
    CREATE OR REPLACE TABLE `my_project.writable_dataset.corridor_materialized`
    (
      selected_route_id STRING OPTIONS(description="Unique identifier for the SelectedRoute resource."),
      record_time TIMESTAMP OPTIONS(description="Observation timestamp."),
      duration_in_seconds FLOAT64 OPTIONS(description="Traffic-aware duration in seconds.")
    )
    PARTITION BY DATE(record_time)
    CLUSTER BY selected_route_id
    OPTIONS (
      description="7-day materialized extract from Analytics Hub linked dataset."
    ) AS
    SELECT selected_route_id, record_time, duration_in_seconds
    FROM `LINKED_DATASET_NAME.historical_travel_time`
    WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY);
    ```

- **Standard Logical Views**: If live query pass-through is required without data duplication, `CREATE OR REPLACE VIEW` is fully supported on linked datasets.

## 8. Predictive Traffic Modeling: BQML ARIMA_PLUS vs. Foundation Model AI.FORECAST vs. ML.DETECT_CHANGE_POINTS vs. ML.TREND vs. ML.SEASONALITY

### Time-Series Anomaly Smoothing (`ds6_travel_time_forecasting.sql`)

- When training per-route `ARIMA_PLUS` models on high-frequency traffic history, severe one-off road disruptions (e.g., multi-lane highway accidents, extreme storms) can heavily distort recurring weekly/daily diurnal seasonality.
- Always set `clean_spikes_and_dips = TRUE` in the `OPTIONS` block of `CREATE MODEL` to automatically detect and smooth out anomalous historical outliers during time-series decomposition.

### Zero-Shot Multi-Route Forecasting (`ds7_zero_shot_forecasting.sql`)

- Rather than maintaining thousands of per-route `CREATE MODEL` pipelines, utilize Google Cloud's Time Series Foundation Model via `AI.FORECAST(..., model => 'TimesFM 2.0')`.
- TimesFM operates zero-shot (no prior training required), processing arbitrary 3-to-7 day context windows across thousands of independent corridors concurrently (`id_cols => ['selected_route_id']`) to generate robust 24-hour predictive horizons with prediction intervals in seconds.

### Multi-Corridor Structural Shift Detection (`ds8_change_point_detection.sql`)

- **Point Anomalies vs. Structural Breaks**: While IQR (`ds1`) and `ML.DETECT_ANOMALIES` isolate isolated 1-2 hour spikes, **`ML.DETECT_CHANGE_POINTS`** uncovers gradual and sustained regime shifts (e.g., construction phases, signal timing retiming, permanent bottleneck emergence).
- **Zero-Model Operation**: Evaluates time-series step changes directly on table expressions without model management (`TABLE daily_corridor_metrics`).
- **Multi-Route Analysis**: Passes `id_cols => ['selected_route_id']` to identify the exact transition windows (`begin_timestamp`, `end_timestamp`) and post-shift baseline statistics (`metrics.avg`, `metrics.stddev`) across the entire monitoring fleet simultaneously.

### Secular Trend Decomposition & Forward Projection (`ds9_corridor_trend_decomposition.sql`)

- **Directional Trajectory vs. Oscillations**: While forecasting models predict daily rush hour peak/valley cycles, **`ML.TREND`** uses `ARIMA_PLUS`'s in-database STL decomposition algorithm to isolate the pure, smoothed directional growth trajectory (`trend`), stripping away diurnal and weekend noise.
- **Forward Horizon Trend Projection**: Setting `horizon => 7` (or up to 30) projects the underlying secular trend into future weeks to forecast macroeconomic traffic drift without overfitting to short-term fluctuations.

### Diurnal & Day-of-Week Seasonality Decomposition (`ds10_corridor_seasonality_decomposition.sql`)

- **Additive Periodic Components**: While `ML.TREND` isolates the secular baseline, **`ML.SEASONALITY`** extracts the exact additive cyclic periodicities:
  - `daily`: Diurnal hour-of-day peak penalty or off-peak relief (in seconds relative to the baseline).
  - `weekly`: Day-of-week weekend vs. weekday traffic swing (in seconds).
- **Signal Timing & Logistics Calibration**: Enables traffic engineers to calibrate TOD (Time-of-Day) signal timing plans and logistics dispatch windows using grounded empirical diurnal swings without training or storing full models.

## 9. Automated Notebook Synchronization Tooling (`scripts/sync_notebooks.py`)

To ensure documentation and tutorial artifacts remain 100% synchronized with modular `.sql` asset libraries:

- Use `python3 src/rmi-sql/scripts/sync_notebooks.py` to programmatically extract SQL query bodies and business metadata from `assets/queries/` and inject them into `assets/notebooks/*.ipynb` code cells formatted with `%%bigquery --project {project_id} df_<query_name>`.
- Preserves parameter placeholders (`LINKED_DATASET_NAME`, `{project_id}`, `{dataset_id}`) across Colab and BigQuery Studio runtime environments.

## 10. Table & Column Description Inheritance Standard

When creating derived tables, views, or snapshots from upstream RMI datasets:

- **Mandatory Table/View Descriptions**: Every `CREATE TABLE`, `CREATE VIEW`, or `CREATE MODEL` statement must declare `OPTIONS(description = "...")` providing clear operational purpose, lineage, and business context.
- **Inherited Core Metadata**: Columns originating directly from RMI base tables (`selected_route_id`, `display_name`, `record_time`, `duration_in_seconds`, `static_duration_in_seconds`, `route_geometry`, `status`, `validation_error`, `route_attributes`) must inherit canonical descriptions via inline `column_name OPTIONS(description = "...")` declarations.
- **Detailed Dictionary Reference**: See the canonical glossary in **[`COLUMN_DESCRIPTIONS.md`](references/standards/COLUMN_DESCRIPTIONS.md)** for standardized definitions across all base and derived fields.

## 11. Road Network on BigQuery (`road_network`) Topology & Jurisdiction Patterns

### 10.1 Undirected Physical Arm Counting at Endpoints (`LEAST(seg_id, opp_id)`)

- **The Mid-Block Attribute Split Pitfall**: In `road_network`, road segments are directed half-edges paired via `opposite_direction_road_segment_id` and split whenever road attributes (names, lane counts, speed limits, surface) change. At a mid-block attribute split on an undivided two-way street, 2 incoming directed half-edges and 2 outgoing directed half-edges meet at the split coordinate (`in_degree = 2, out_degree = 2, total_directed_edges = 4`).
- **Why Naive Degree Counting Fails**: Classifying intersections via `in_degree + out_degree > 2` misclassifies **100% of mid-block two-way attribute splits (`~40.35%` of all network endpoint nodes)** as 4-way intersections.
- **Canonical Undirected Physical Arm Formula**: Collapse each bidirectional half-edge pair into a single canonical undirected physical arm using `LEAST(road_segment_id, COALESCE(opposite_direction_road_segment_id, road_segment_id))` before counting distinct arms meeting at an endpoint node (`ST_ASTEXT(endpoint)`):

  ```sql
  WITH endpoint_arms AS (
    SELECT
      ST_ASTEXT(ST_STARTPOINT(geometry)) AS node_wkt,
      ST_STARTPOINT(geometry) AS node_geom,
      LEAST(road_segment_id, COALESCE(opposite_direction_road_segment_id, road_segment_id)) AS undirected_arm_id,
      'OUTGOING' AS direction
    FROM `my_project.road_network.road_segments_latest`
    UNION ALL
    SELECT
      ST_ASTEXT(ST_ENDPOINT(geometry)) AS node_wkt,
      ST_ENDPOINT(geometry) AS node_geom,
      LEAST(road_segment_id, COALESCE(opposite_direction_road_segment_id, road_segment_id)) AS undirected_arm_id,
      'INCOMING' AS direction
    FROM `my_project.road_network.road_segments_latest`
  )
  SELECT
    node_wkt,
    ANY_VALUE(node_geom) AS intersection_geom,
    COUNT(DISTINCT undirected_arm_id) AS physical_arm_count
  FROM endpoint_arms
  GROUP BY node_wkt
  HAVING COUNT(DISTINCT undirected_arm_id) >= 3; -- True 3+ way physical intersections
  ```

### 10.2 Two-Way Centerline Coincidence & Reversed Vertex Invariant

- For `100%` of undivided two-way segment pairs (`Seg A ↔ Seg B` linked via `opposite_direction_road_segment_id`), both directions share the exact same physical centerline (`ST_EQUALS(a.geometry, b.geometry) = TRUE`, Hausdorff distance `0.0m`) with **reversed vertex ordering**:
  `ST_EQUALS(ST_STARTPOINT(a.geometry), ST_ENDPOINT(b.geometry)) = TRUE`.
- When rendering two-way corridors or deduplicating centerlines for spatial buffering, filter to canonical undirected representatives (`WHERE opposite_direction_road_segment_id IS NULL OR road_segment_id < opposite_direction_road_segment_id`) to avoid double-counting road length or rendering overlapping directional strokes.

### 10.3 Highway Shield Naming Convention (`SEARCH(names, ...)` vs. Abbreviated Shields)

- `road_network.names` stores spelled-out official route designations (`'Interstate 93'`, `'U.S. 101'`, `'State Route 99'`) rather than hyphenated shield abbreviations (`'I-93'`, `'US-101'`, `'SR-99'`).
- Querying `SEARCH(names, '`I-93`')` returns minor local streets named *"I-93"* rather than the interstate highway. Always include full official names alongside local variants and filter by `priority IN ('PRIORITY_CONTROLLED_ACCESS', 'PRIORITY_PRIMARY_HIGHWAY')`.

### 10.4 Spatial Jurisdiction Auditing of RMI Datasets (`routes_status` / `recent_roads_data`)

- When RMI datasets (`historical_roads_data_*`) do not expose an explicit country/jurisdiction metadata column, determine the geographic jurisdiction of registered `SelectedRoute` fleets by extracting `ST_CENTROID(route_geometry)` from recent partitions of `recent_roads_data` (or `routes_status`) and spatially joining against Overture Maps country polygons (`bigquery-public-data.overture_maps.division_area` where `subtype = 'country'`):

  ```sql
  WITH countries AS (
    SELECT country AS iso_country, geometry
    FROM `bigquery-public-data.overture_maps.division_area`
    WHERE subtype = 'country'
  ),
  route_centroids AS (
    SELECT
      selected_route_id,
      ST_CENTROID(ANY_VALUE(route_geometry)) AS centroid_geom
    FROM `my_project.rmi_dataset.recent_roads_data`
    WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
      AND route_geometry IS NOT NULL
    GROUP BY selected_route_id
  )
  SELECT
    c.iso_country,
    COUNT(DISTINCT r.selected_route_id) AS route_count
  FROM route_centroids r
  JOIN countries c
    ON ST_INTERSECTS(r.centroid_geom, c.geometry)
  GROUP BY c.iso_country
  ORDER BY route_count DESC;
  ```

## References

- [METRICS.md](references/standards/METRICS.md): Definitions of duration ratios and reliability.
- [KNOWN_LIMITATIONS.md](references/standards/KNOWN_LIMITATIONS.md): Privacy thresholds and historical data availability.
- [SAMPLE_DATASET_METRICS.md](references/standards/SAMPLE_DATASET_METRICS.md): Baseline summary metrics and route distributions.
- [COLUMN_DESCRIPTIONS.md](references/standards/COLUMN_DESCRIPTIONS.md): Canonical column dictionary and metadata inheritance standards.
- [queries/](assets/queries/): Curated SQL library grouped by persona.
- [BigQuery ML.DETECT_CHANGE_POINTS](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/bigqueryml-syntax-detect-change-points): Google Cloud reference documentation for time-series change point detection.
- [BigQuery ML.TREND](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/bigqueryml-syntax-trend): Google Cloud reference documentation for time-series trend component decomposition and forecasting.
- [BigQuery ML.SEASONALITY](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/bigqueryml-syntax-seasonality): Google Cloud reference documentation for time-series seasonality component decomposition.

## Related Skills

- **`rmi-personas`**: Business workflows and personas (Urban Planner, Data Scientist, Operations).
- **[`rmi-sampledatasets`](../rmi-sampledatasets/SKILL.md)**: Global sample datasets catalog, Analytics Hub exchange discovery, and snapshot baseline schemas.
- **[`bigquery-geospatial`](../bigquery-geospatial/SKILL.md)**: Advanced GIS handling, spatial outer joins, and CARTO extensions.
- **[`bigquery-practices`](../bigquery-practices/SKILL.md)**: General BigQuery SQL best practices, storage billing, and partition pruning.
- **[`rmi-data-foundation-bigquery`](../rmi-data-foundation-bigquery/SKILL.md)**: Foundation table schemas and batch pipelines.
- **[`rmi-data-realtime-bigquery`](../rmi-data-realtime-bigquery/SKILL.md)**: Real-time table schema and SRI logic.
- **[`rmi-data-realtime-pubsub`](../rmi-data-realtime-pubsub/SKILL.md)**: Upstream Pub/Sub streaming message schema.
