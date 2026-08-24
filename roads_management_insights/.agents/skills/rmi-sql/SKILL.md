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

This skill provides expert-level procedural knowledge for applying BigQuery capabilities to RMI-specific data structures and business use cases.

## 1. RMI-Specific Analytical Patterns

### Path & Bottleneck Analysis
- **Segment-Level Traffic (SRIs)**: Unnesting `speed_reading_intervals` from `recent_roads_data`.
- **Visualization Optimization**: `interval_coordinates` is an array of `ST_Point`. To create intuitive polylines for data viz, use `ST_MAKELINE(interval_coordinates)`.
- **Path Integrity**: Always filter for `ST_LineString` on traffic-aware datasets (e.g., `routes_status`). **Apply this filter as early as possible (e.g., in the first CTE)** to optimize performance. *Note: Static road network tables typically don't require this check.*
- **Route Deviation Audit**: Filter for routes where the actual physical length (`ST_LENGTH(route_geometry)`) deviates significantly from the intended `route_length` (stored in `route_attributes`). Apply a tolerance ratio (e.g., `0.9` to `1.1`) in the early CTEs to exclude unreliable records:
    ```sql
    WHERE SAFE_DIVIDE(ST_LENGTH(route_geometry), SAFE_CAST(JSON_VALUE(route_attributes, '$.route_length') AS FLOAT64)) BETWEEN 0.9 AND 1.1
    ```
- **Dynamic Path Variation & Detour Detection (`road_segment_ids`)**:
  - *Fingerprinting Path Variants*: Use `ARRAY_TO_STRING(road_segment_ids, '|')` to convert the segment Place ID sequence into a string fingerprint that can be grouped (`GROUP BY 1, 2, 3`).
  - *June 19, 2026 Temporal Schema Threshold*: The `road_segment_ids` column was added on **June 19, 2026**. Telemetry records prior to this date contain empty/NULL arrays. All queries using `road_segment_ids` MUST enforce:
    ```sql
    WHERE record_time >= '2026-06-19' AND ARRAY_LENGTH(road_segment_ids) > 0
    ```
  - *Detour Delay Multiplier*: Aggregate variants into an array sorted by sample count (`ARRAY_AGG(STRUCT(...) ORDER BY num_of_records DESC)`). Index `0` is the dominant baseline path; subsequent indices are detour variants. Compute `SAFE_DIVIDE(variations[OFFSET(1)].avg_duration_in_seconds, variations[OFFSET(0)].avg_duration_in_seconds)` to isolate high-penalty congestion diversions.

### Reliability & Performance Metrics
- **Local Time Conversion**: `record_time` is stored in UTC. For intuitive reporting, always convert to the local timezone using `DATETIME(record_time, "America/New_York")` (or appropriate zone).
- **Duration Ratio**: Calculate traffic impact using `SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)`.
- **JSON Attributes**: Parse custom RMI metadata using `JSON_VALUE(route_attributes, '$.key')`.

### Telemetry Payload Unpacking & Geometry Reconstruction
When querying raw streaming tables like `eval_disruptions_original` or `eval_disruptions_deduped`, telemetry payload shapes (nested JSON arrays containing `stretches`, `centroid`, etc.) must be dynamically converted to native geospatial geometry:
- **Centroid Extraction**: Use `ST_GEOGPOINT` on parsed latitude and longitude fields.
- **Stretch Path Assembly**: Dynamic geometries represented as nested arrays of points inside a parent array must be built using a two-level unnest-aggregation process:
  1. Map each nested position to `ST_GEOGPOINT`.
  2. Assemble coordinate arrays into a continuous path using `ST_MAKELINE`.
  3. Aggregate the lines across the parent array into a unified `GEOGRAPHY` type using `ST_UNION_AGG`.
  
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
- **Job ID Convention**: All RMI queries MUST follow the `rmisqlfactory_<queryid>_<timestamp>` format.
- **Mandatory Joins**: Standard practice joins `routes_status` with `historical_travel_time` or `recent_roads_data` via `selected_route_id`.

## 3. Query Execution Guardrails & CLI Driver Standards

### Safe Parsing Guardrails
- **Null & Malformed Protection**: Never use raw `CAST(...)` or `PARSE_TIMESTAMP(...)` on unstructured JSON fields or user routeAttributes. Always use `SAFE_CAST(...)` and `SAFE.PARSE_TIMESTAMP(...)` to prevent execution crashes on dirty/null inputs.

### CLI Driver & `bq query` Input Pipe
- **Comment Header Flag Recursion Avoidance**: Queries with SQL comment headers starting with `--` (such as `-- Job ID: rmisqlfactory_...`) trigger flag parsing recursion in the `bq` CLI if passed as raw positional arguments. Always pipe SQL query strings via standard input (`input=query` in Python `subprocess.run`) or pass temporary file handles (`bq query ... < query.sql`).

### Job Labeling vs Multi-Statement Sessions
- **Submission-Time Job Labels**: Single SQL query files should not execute `SET @@query_label = "..."` (which requires multi-statement session contexts). Instead, attach metadata labels at job submission time:
  - **CLI**: `bq query --label=persona:urban_planner --label=usecase:corridor_trend`
  - **Python SDK**: `job_config.labels = {"persona": "urban_planner", "usecase": "corridor_trend"}`

### Parallel Dry-Run Validation (`scripts/dry_run_all_queries.py`)
- **Fast Zero-Cost Syntax Verification**: Execute `bq query --dry_run` with `ThreadPoolExecutor(max_workers=10)` to validate SQL syntax, schema resolution, and byte scan estimates across query libraries in parallel without executing database scans or incurring costs.


## 4. Geospatial Optimization & Derived Tables

### Hourly Array Aggregation Optimization
When transforming raw high-resolution spatial tables (e.g. 2-minute sampling frequency, giving 720 records per day) into geospatially-clustered derived tables, using `ARRAY_AGG` directly on unnested records causes massive nested array inflation. This bloats network transport size and impacts client-side rendering.
- **The Optimization:** Perform a two-stage aggregation. In the first stage (intermediate CTE), group by `record_date, selected_route_id, ST_ASTEXT(coords), EXTRACT(HOUR FROM record_time) AS hour` and use logical aggregations to capture the worst-case speed state inside each hour:
  ```sql
  CASE
    WHEN LOGICAL_OR(sri.speed = 'TRAFFIC_JAM') THEN 'TRAFFIC_JAM'
    WHEN LOGICAL_OR(sri.speed = 'SLOW') THEN 'SLOW'
    ELSE 'NORMAL'
  END AS speed
  ```
- In the second stage, aggregate the consolidated hourly records into the final nested array `ARRAY_AGG(STRUCT(hour, speed))`. This guarantees at most 24 elements per road segment, shrinking database size and payload by over 95%.

```sql
WITH hourly_stage AS (
  SELECT 
    selected_route_id,
    EXTRACT(HOUR FROM record_time) AS hour_of_day,
    CASE 
      WHEN LOGICAL_OR(sri.speed = 'TRAFFIC_JAM') THEN 'TRAFFIC_JAM'
      WHEN LOGICAL_OR(sri.speed = 'SLOW') THEN 'SLOW'
      ELSE 'NORMAL'
    END AS worst_hourly_speed
  FROM `dataset.recent_roads_data`, UNNEST(speed_reading_intervals) AS sri
  WHERE ST_GEOMETRYTYPE(route_geometry) = 'ST_LineString'
    AND record_time >= '2026-06-15 00:00:00' AND record_time < '2026-06-16 00:00:00'
  GROUP BY selected_route_id, hour_of_day
)
SELECT 
  selected_route_id,
  ARRAY_AGG(STRUCT(hour_of_day, worst_hourly_speed) ORDER BY hour_of_day) AS hourly_congestion_profile
FROM hourly_stage
GROUP BY selected_route_id;
```

### Preventing Geography Grouping & Mixing
- BigQuery does not allow `GROUP BY` on complex `GEOGRAPHY` objects directly.
- **Group by WKT Text:** Always group on `ST_ASTEXT(coords)` to ensure mathematically distinct geometries are isolated and not blended.
- **Deterministic Reconstruction:** In the SELECT list, use `ST_GEOGFROMTEXT(geometry_wkt)` of the grouped WKT string. This is deterministic and guarantees zero risk of mixing or blending distinct geometries, which can happen with non-deterministic aggregations like `ANY_VALUE`.

## 5. Spatial Masking vs. Attribute Name Sparsity in Road Selection

### Road Name Sparsity & Selection Risks
- **Attribute Sparsity**: In standard road network datasets, `display_name` coverage can be remarkably sparse. Up to 25%–30% of major mainline controlled-access highway segments (and higher percentages on rural/transition links) carry empty string (`""`) or null display names.
- **Selection Failure Risk**: Filtering strictly by road name string patterns (e.g., `WHERE display_name LIKE '%I-10%'`) will omit significant portions of the target corridor, resulting in fragmented spatial telemetry and broken downstream route calculations.

### Overture Maps Spatial Boundary Masking
- **The Solution (Spatial Masking)**: Rather than relying on fragile textual attributes like `display_name`, use external spatial reference boundaries (such as Overture Maps `transportation_segment` corridor geometries, bounding boxes, or administrative boundary polygons) to build a **pure spatial mask**.
- **Execution Pattern**: Select road network segments by evaluating spatial intersection (`ST_INTERSECTS` / `ST_DWITHIN`) against the spatial mask. This guarantees 100% geometric coverage of the target corridor regardless of missing, localized, or inconsistent road names.

## 6. Analytics Hub Linked Dataset Materialization Constraints & Patterns

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

## 7. Predictive Traffic Modeling: BQML ARIMA_PLUS vs. Foundation Model AI.FORECAST

### Time-Series Anomaly Smoothing (`ds6_travel_time_forecasting.sql`)
- When training per-route `ARIMA_PLUS` models on high-frequency traffic history, severe one-off road disruptions (e.g., multi-lane highway accidents, extreme storms) can heavily distort recurring weekly/daily diurnal seasonality.
- Always set `clean_spikes_and_dips = TRUE` in the `OPTIONS` block of `CREATE MODEL` to automatically detect and smooth out anomalous historical outliers during time-series decomposition.

### Zero-Shot Multi-Route Forecasting (`ds7_zero_shot_forecasting.sql`)
- Rather than maintaining thousands of per-route `CREATE MODEL` pipelines, utilize Google Cloud's Time Series Foundation Model via `AI.FORECAST(..., model => 'TimesFM 2.0')`.
- TimesFM operates zero-shot (no prior training required), processing arbitrary 3-to-7 day context windows across thousands of independent corridors concurrently (`id_cols => ['selected_route_id']`) to generate robust 24-hour predictive horizons with prediction intervals in seconds.

## 8. Automated Notebook Synchronization Tooling (`scripts/sync_notebooks.py`)

To ensure documentation and tutorial artifacts remain 100% synchronized with modular `.sql` asset libraries:
- Use `python3 src/rmi-sql/scripts/sync_notebooks.py` to programmatically extract SQL query bodies and business metadata from `assets/queries/` and inject them into `assets/notebooks/*.ipynb` code cells formatted with `%%bigquery --project {project_id} df_<query_name>`.
- Preserves parameter placeholders (`LINKED_DATASET_NAME`, `{project_id}`, `{dataset_id}`) across Colab and BigQuery Studio runtime environments.

## 9. Table & Column Description Inheritance Standard

When creating derived tables, views, or snapshots from upstream RMI datasets:
- **Mandatory Table/View Descriptions**: Every `CREATE TABLE`, `CREATE VIEW`, or `CREATE MODEL` statement must declare `OPTIONS(description = "...")` providing clear operational purpose, lineage, and business context.
- **Inherited Core Metadata**: Columns originating directly from RMI base tables (`selected_route_id`, `display_name`, `record_time`, `duration_in_seconds`, `static_duration_in_seconds`, `route_geometry`, `status`, `validation_error`, `route_attributes`) must inherit canonical descriptions via inline `column_name OPTIONS(description = "...")` declarations.
- **Detailed Dictionary Reference**: See the canonical glossary in **[`COLUMN_DESCRIPTIONS.md`](references/standards/COLUMN_DESCRIPTIONS.md)** for standardized definitions across all base and derived fields.

## References
- [METRICS.md](references/standards/METRICS.md): Definitions of duration ratios and reliability.
- [KNOWN_LIMITATIONS.md](references/standards/KNOWN_LIMITATIONS.md): Privacy thresholds and historical data availability.
- [SAMPLE_DATASET_METRICS.md](references/standards/SAMPLE_DATASET_METRICS.md): Baseline summary metrics and route distributions.
- [COLUMN_DESCRIPTIONS.md](references/standards/COLUMN_DESCRIPTIONS.md): Canonical column dictionary and metadata inheritance standards.
- [queries/](assets/queries/): Curated SQL library grouped by persona.

## Related Skills
- **[`rmi-personas`](../rmi-personas/SKILL.md)**: Business workflows and personas (Urban Planner, Data Scientist, Operations).
- **[`rmi-sampledatasets`](../rmi-sampledatasets/SKILL.md)**: Global sample datasets catalog, Analytics Hub exchange discovery, and snapshot baseline schemas.
- **[`bigquery-geospatial`](../bigquery-geospatial/SKILL.md)**: Advanced GIS handling, spatial outer joins, and CARTO extensions.
- **[`bigquery-practices`](../bigquery-practices/SKILL.md)**: General BigQuery SQL best practices, storage billing, and partition pruning.
- **[`rmi-data-foundation-bigquery`](../rmi-data-foundation-bigquery/SKILL.md)**: Foundation table schemas and batch pipelines.
- **[`rmi-data-realtime-bigquery`](../rmi-data-realtime-bigquery/SKILL.md)**: Real-time table schema and SRI logic.
- **[`rmi-data-realtime-pubsub`](../rmi-data-realtime-pubsub/SKILL.md)**: Upstream Pub/Sub streaming message schema.
