---
name: bigquery-practices
description: Foundational BigQuery best practices for SQL performance, geospatial functions, temporal engineering, BQML, vector search, storage optimization (physical vs. logical), execution diagnostics, and enterprise governance.
---

# General BigQuery Best Practices

This skill provides foundational technical expertise, architecture patterns, and operational workarounds for writing efficient, accurate, cost-effective, and enterprise-grade SQL on BigQuery.

---

## 1. SQL Performance & Cost Optimization

### 1.1 Mandatory Partitioning & Clustering
- **Partition Pruning**: Always filter by the partition column (e.g., `record_time` or `DATE(timestamp)`). Use `DECLARE` for dynamic parameter filters to ensure the query optimizer prunes unneeded storage partitions effectively before scanning.
- **High-Cardinality Clustering**: Ensure tables leverage clustering on frequently filtered dimensions (e.g., `route_id`, `corridor_id`, `priority`, or `GEOGRAPHY` columns) to minimize byte scan volumes.

### 1.2 Block-Level Table Sampling (`TABLESAMPLE SYSTEM`)
- **Mechanics**: `TABLESAMPLE SYSTEM (N PERCENT)` samples at the 64 MB physical Capacitor storage block level, NOT individual rows.
- **Small Dataset Pitfall**: On small to medium datasets (~1–2 GB / ~20 blocks), using very small sampling percentages (e.g., `< 1%`) risks selecting 0 physical storage blocks and returning empty results.
- **Recommended Pattern**: Use `TABLESAMPLE SYSTEM (5 PERCENT)` for block-level scan cost reduction, combined with a secondary deterministic row filter (e.g., `WHERE RAND() < 0.0001` or bounded date filters) to cap row counts for BQML / AI model invocations (`AI.GENERATE`) to ~10–25 rows without relying on restrictive `LIMIT` clauses.

### 1.3 Declarative Primary & Foreign Keys for Join Elimination (`NOT ENFORCED`)
- **Unenforced/Declarative Contracts**: BigQuery supports Primary and Foreign Key constraints, but they are strictly **NOT ENFORCED** on write. Upstream pipelines (e.g., using `QUALIFY ROW_NUMBER() OVER(PARTITION BY key_column ORDER BY updated_at DESC) = 1`) must physically guarantee uniqueness.
- **Query Optimization (Join Elimination)**: Declaring Primary and Foreign Keys informs the BigQuery Query Optimizer that join keys are unique. The optimizer utilizes this to prune redundant outer-joins, reorder joins dynamically, and optimize aggregations, accelerating multi-million row joins dramatically.
- **In-Place Schema Changes (`ALTER TABLE`)**: Because constraints are metadata-only, you can add or drop keys on existing tables instantly without rewriting or duplicating tables:
  ```sql
  -- Drop constraint
  ALTER TABLE dataset.table DROP PRIMARY KEY;
  -- Add Primary Key
  ALTER TABLE dataset.table ADD PRIMARY KEY(place_id) NOT ENFORCED;
  -- Add Foreign Key
  ALTER TABLE dataset.table ADD CONSTRAINT fk_start FOREIGN KEY (start_node_id) REFERENCES dataset.nodes(node_id) NOT ENFORCED;
  ```

### 1.4 Storage Billing Optimization: Physical vs. Logical Storage Model
BigQuery allows dataset storage to be billed based on **Logical storage** (uncompressed data size) or **Physical storage** (compressed on-disk size).
- **The Telemetry & Spatial Savings Pattern**: High-volume telemetry, JSON logs, and spatial tables exhibit high compression ratios (often 3:1 to 10:1) with BigQuery's Capacitor storage format.
- **When to Choose Physical Storage**:
  - If compressed physical size is $< 50\%$ of logical size, configure dataset storage billing to `PHYSICAL`:
    ```sql
    ALTER SCHEMA `my_project.my_dataset`
    SET OPTIONS(storage_billing_model = 'PHYSICAL');
    ```
  - *Time Travel Management*: Physical storage charges for Time Travel and Fail-safe storage; reduce Time Travel windows (e.g. from 7 days to 2 days for ephemeral staging datasets) to maximize net cost savings:
    ```sql
    ALTER SCHEMA `my_project.my_dataset`
    SET OPTIONS(max_time_travel_hours = 48);
    ```

### 1.5 Dry-Run vs. Actual Cost Discrepancy (TVFs, Parameters & Query Cache)
- **Parametric TVFs & Functions**: When using Table-Valued Functions (TVFs) or queries filtering with dynamic parameters (e.g., viewport boundaries `@xmin, @ymin, @xmax, @ymax`), a dry run evaluates the query statically and must estimate a worst-case scenario (full unpruned scan). The actual execution resolves parameters, using partition pruning and spatial clustering to scan only a fraction of the estimated data.
- **Query Results Caching**: Dry runs always estimate bytes processed assuming zero cache hits. Actual runs utilize BigQuery's query cache for exact matches within 24 hours, returning results instantly at **0 bytes processed**.

### 1.6 Safe Arithmetic & String Casting
- **Defensive Expressions**: Always use `SAFE_DIVIDE` and `SAFE_CAST` to prevent query runtime failures on malformed, division-by-zero, or missing data attributes.

---

## 2. Temporal Engineering

> [!TIP]
> **Dedicated Geospatial Capabilities**: For all GIS functions (`GEOGRAPHY` types, `ST_*` functions, S2/H3 spatial indexing, spatial joins, buffer clipping, and CARTO analytics toolbox), refer to the dedicated [`bigquery-geospatial`](../bigquery-geospatial/SKILL.md) skill.

### 2.1 Timezone Management & Storage Standards
- **Storage Standard**: Store all timestamps in UTC (`TIMESTAMP` data type).
- **Local Conversions**: Convert to local metropolitan time zones at query time: `DATETIME(timestamp, "America/New_York")` or `DATETIME(timestamp, "Asia/Tokyo")`.

### 2.2 Temporal Aggregations & Longitudinal Rollups
- **Bucket Aggregations**: Use `TIMESTAMP_TRUNC(record_time, HOUR)` or `TIMESTAMP_TRUNC(record_time, DAY)` for consistent longitudinal bucket aggregations.
- **Date Partition Anchoring**: When querying static historical snapshots or partitioning tables, anchor queries using explicit date/timestamp bounds (e.g., `record_time BETWEEN '2026-06-01' AND '2026-06-30'`) rather than dynamic relative time offsets like `TIMESTAMP_SUB(CURRENT_TIMESTAMP(), ...)`.


---

## 3. Programmability, BQML & Serverless Integration

### 3.1 Centralized Native SQL UDFs vs. JavaScript UDFs
- **Zero V8 Context Overhead**: Standard JavaScript UDFs require separate V8 runtime context instantiations in every active slot, introducing significant serialization and start-up latency. Translating formulas into pure SQL mathematical statements completely eliminates context switching.
- **Query Planner Inlining**: JavaScript UDFs are black boxes to the BigQuery query planner (preventing filter pushdown and partition/spatial pruning). Native SQL UDFs are compiled and inlined directly into the execution tree.
- **Trigonometry in Pure SQL**: Convert complex projection formulas (like Mercator tile mapping) into native SQL:
  ```sql
  CREATE OR REPLACE FUNCTION `utility_functions_us.tile2lat`(y INT64, z INT64) RETURNS FLOAT64 AS (
    ATAN(SINH(ACOS(-1) * (1.0 - 2.0 * y / POW(2.0, z)))) * 180.0 / ACOS(-1)
  );
  ```

### 3.2 Table-Valued Functions (TVFs) for Multi-Stage CTE Pipelines
- **DRYing Complex Pipelines**: While scalar UDFs return single values, Table-Valued Functions (TVFs) parameterize and centralize entire multi-stage CTE query pipelines (such as spatial grid generation or dynamic corridor slicing) as database-level virtual table functions:
  ```sql
  SELECT * FROM `my_project.utility_functions_us.generate_tile_grid`(
    (SELECT boundary_geom FROM closed_geom),
    zoom_level
  ) ORDER BY tile_id;
  ```

### 3.3 Cloud Run Remote Functions (Polymorphic String Pattern & State Sync)
When deploying BigQuery Remote Functions backed by Cloud Run:
- **Polymorphic String Pattern**: Accept a single `STRING` parameter (e.g. `origin_or_place`) and inspect the prefix programmatically: if it starts with `POINT`, parse as WKT coordinates; otherwise, treat as a Google Maps Place ID.
- **Terraform Infrastructure Triggers**: When declaring remote function SQL registrations in Terraform, include the function's description text or parameter hash in `null_resource` triggers (`description = local.description_text`) so changes to SQL types or docstrings trigger automatic recreation.
- **Container Optimizations**:
  - *NULL Short-Circuiting*: Return SQL `null` immediately for empty or whitespace strings before invoking API requests.
  - *Coordinate Deduplication*: Filter consecutive duplicate GPS points in the container before forwarding to remote APIs to save bandwidth and compute.

### 3.4 In-Database Machine Learning (BQML: `ARIMA_PLUS`, `KMEANS`)
- **In-Database Lifecycle**: Train and execute models directly on data in BigQuery using `CREATE MODEL` without data egress:
  - `ARIMA_PLUS`: Time-series forecasting for travel times and congestion seasonality.
  - `KMEANS`: Route behavioral clustering (e.g. commuter corridors vs. commercial freight).
  - `LINEAR_REG_` / `LOGISTIC_REG_`: Predicting delay ratios or incident probabilities.
- **Model Description Syntax Constraint**: `OPTIONS(...)` in `CREATE MODEL` only accepts ML hyperparameters. Setting `description = "..."` inside `CREATE MODEL` throws a syntax error. Use post-creation `ALTER MODEL` DDL instead:
  ```sql
  ALTER MODEL `my_project.my_dataset.my_model`
  SET OPTIONS(description = "K-Means traffic profile clustering model.");
  ```

### 3.5 Native Search Indexes & Vector Similarity Search (`VECTOR_SEARCH`)
- **Search Indexes for Text & JSON**:
  ```sql
  CREATE SEARCH INDEX IF NOT EXISTS roads_search_idx
  ON `my_project.my_dataset.road_segments`(ALL COLUMNS);
  ```
- **Vector Similarity Search**: Generate embeddings via BQML Vertex AI models and query top-$K$ nearest neighbors:
  ```sql
  SELECT query.query_text, base.place_id, base.name, distance
  FROM VECTOR_SEARCH(
    TABLE `my_project.my_dataset.poi_embeddings`,
    'ml_generate_embedding_result',
    (SELECT ml_generate_embedding_result, content AS query_text FROM ML.GENERATE_EMBEDDING(
      MODEL `my_project.my_dataset.text_embed_model`,
      (SELECT "electric vehicle charging plazas" AS content)
    )),
    top_k => 10,
    distance_type => 'COSINE'
  );
  ```

---

## 4. Ingestion, Pipelines & Storage Architecture

### 4.1 Storage Write API & Continuous Queries
- **Storage Write API**: Deprecate legacy `tabledata.insertAll` in favor of the gRPC-based Storage Write API for 50%+ lower ingestion cost, streaming deduplication, and exactly-once delivery (`CommittedStream` for immediate visibility, `PendingStream` for atomic multi-batch commits).
- **BigQuery Continuous Queries**: Run continuous SQL over streaming sources (Pub/Sub topics) and export directly to Pub/Sub or downstream tables:
  ```sql
  EXPORT DATA
  OPTIONS (
    format = 'CLOUD_PUBSUB',
    uri = 'https://pubsub.googleapis.com/projects/my-project/topics/live-alerts'
  ) AS
  SELECT route_id, travel_duration_seconds, CURRENT_TIMESTAMP() AS alert_time
  FROM `my_project.my_dataset.recent_roads_stream`
  WHERE travel_duration_seconds > 1800;
  ```

### 4.2 JSON & Array Telemetry Parsing
- **Integer Scaling**: Converting epoch nanoseconds via `TIMESTAMP_MICROS` requires an `INT64`. Use integer division `DIV(nanos, 1000)` instead of `SAFE_DIVIDE` (which yields `FLOAT64`).
- **Array Flattening**: Combine `JSON_VALUE_ARRAY` with `ARRAY_TO_STRING(..., "|")` to flatten arrays (e.g. `road_segment_ids`) into indexable string representations for high-performance querying without scalar `UNNEST` overhead.

### 4.3 View & Materialized View Lifecycle Management
- **Standard Views Schema Bindings (`SELECT *` Caveat)**: Views using `SELECT *` evaluate schema at definition time. If new columns are added to base physical tables, standard views do NOT propagate them until replaced. Always explicitly list columns in view definitions.
- **Materialized Views on Arrays**: BigQuery Materialized Views prohibit complex array functions and `UNNEST` expressions. Use scheduled physical tables (Dataform/dbt) when nested array transformations are required.
- **Terraform Formatting on MVs**: Whitespace changes in `materialized_view` SQL force resource replacement. Ensure `deletion_protection = false` is declared on MV resources.

### 4.4 Analytics Hub Linked Dataset Materialization Constraints
- **Materialized Views Prohibition**: Creating Materialized Views directly on top of Analytics Hub shared/linked datasets is disallowed (`Can't create materialized view on linked dataset`).
- **Clustered Table Materialization Pattern**: Pre-aggregate high-cost queries from linked datasets into a writable target dataset using partitioned and clustered physical tables.

### 4.5 Upstream Change Propagation & Row Count Verification Guards
- **Row Count Guard Pattern**: When orchestrating multi-stage pipelines, verify the target table's row count against the source file/upstream segment count before skipping steps to prevent stale or truncated data from persisting across pipeline runs.

---

## 5. Observability, Security & Enterprise Governance

### 5.1 Standardized Job ID Formatting & Millisecond Precision
- **Format**: `<workspace/app_indicator>_<category_or_subcategory>_<yyyymmdd>_<hhmmsssss>[_<country_iso>_<admin_area_level_1>]`
- **Millisecond Precision (`sss`)**: Rapid parallel queries (e.g. UI viewport panning) can execute within the same second. Embedding 3-digit padded milliseconds prevents BigQuery Job ID collision errors.
- **Sanitization**: Lowercase all tokens, strip accents (NFD normalization), and replace non-alphanumeric characters with single underscores.

### 5.2 Query Traceability & Contextual Labels
Always attach auditing labels to `bq query` invocations:
- `agent`: Active agent identifier (e.g., `agent:antigravity-cli`).
- `usecase`: Task category (e.g., `usecase:rmi-analysis`).
- `env`: Environment tag (`env:prod`, `env:sample`).
- `region`: Target region (`region:boston`, `region:tokyo`).

### 5.3 Query Execution Plan Diagnostics: Shuffle Spills & Slot Skew
Monitor `INFORMATION_SCHEMA.JOBS` for performance bottlenecks:
- **Slot Skew**: If `max_slot_ms` is $> 5\times$ higher than `avg_slot_ms` in a join or aggregation stage, a worker slot is processing a hot key (e.g. joining on `NULL` or generic defaults). Filter or nullify hot keys before joining.
- **Shuffle Spills**: High shuffle bytes spilled to disk indicate large unpartitioned joins that should be pre-filtered or broadcasted.

### 5.4 Zero-Copy Governance: Row-Level Security, Column-Level Security & Data Masking
- **Row-Level Security (RLS)**: Restrict visibility based on caller identity (`SESSION_USER()`):
  ```sql
  CREATE OR REPLACE ROW ACCESS POLICY regional_access_filter
  ON `my_project.my_dataset.customer_telemetry`
  GRANT TO ('group:apac-analysts@example.com')
  FILTER USING (region = 'APAC');
  ```
- **Column-Level Security & Data Masking**: Attach Policy Tags to sensitive fields and configure Dynamic Data Masking rules (`DEFAULT_MASKING_VALUE`, `HASH(SHA256)`).

### 5.5 BigQuery CLI Gotchas & Console Markdown DDL
- **Regional Flag (`--location`)**: Always explicitly supply `--location=<region>` (e.g. `--location=asia-northeast1`) to avoid cross-region query dispatch failures (`Not found: Table ... in location US`).
- **Load Replace vs Clustering**: `bq load --replace` with modified `--clustering_fields` fails with an incompatible specification error. Drop the table first before loading with new clustering fields.
- **Markdown in Descriptions**: BigQuery Console parses GitHub-Flavored Markdown in table and column descriptions. Wrap strings in triple double-quotes (`"""..."""`) in DDL statements to preserve formatting.

---

## References

### Official Google Cloud Documentation
* **Partitioning & Clustering**:
  * [BigQuery Partitioned Tables Guide](https://cloud.google.com/bigquery/docs/partitioned-tables)
  * [BigQuery Clustered Tables Guide](https://cloud.google.com/bigquery/docs/clustered-tables)
  * [Table Sampling (`TABLESAMPLE SYSTEM`)](https://cloud.google.com/bigquery/docs/table-sampling)
  * [Table Constraints (Primary & Foreign Keys `NOT ENFORCED`)](https://cloud.google.com/bigquery/docs/table-constraints)
* **Storage & Billing**:
  * [BigQuery Storage Billing Models (Physical vs. Logical)](https://cloud.google.com/bigquery/docs/storage-billing-models)
* **Programmability & Streaming**:
  * [BigQuery Storage Write API](https://cloud.google.com/bigquery/docs/write-api)
  * [BigQuery Continuous Queries](https://cloud.google.com/bigquery/docs/continuous-queries-introduction)
  * [Table-Valued Functions (TVFs)](https://cloud.google.com/bigquery/docs/table-functions)
  * [User-Defined Functions (UDFs)](https://cloud.google.com/bigquery/docs/user-defined-functions)
  * [Remote Functions with Cloud Run](https://cloud.google.com/bigquery/docs/remote-functions)
* **Machine Learning & AI Search**:
  * [BigQuery ML Introduction](https://cloud.google.com/bigquery/docs/bqml-introduction)
  * [BigQuery Vector Search (`VECTOR_SEARCH`)](https://cloud.google.com/bigquery/docs/vector-search)
  * [BigQuery Search Indexes (`CREATE SEARCH INDEX`)](https://cloud.google.com/bigquery/docs/search-index)
* **Security, Governance & Observability**:
  * [Row-Level Security Overview](https://cloud.google.com/bigquery/docs/row-level-security-intro)
  * [Column-Level Security & Dynamic Data Masking](https://cloud.google.com/bigquery/docs/column-data-masking-intro)
  * [Query Execution Plan Diagnostics](https://cloud.google.com/bigquery/docs/query-plan-explanation)
  * [`INFORMATION_SCHEMA` Overview](https://cloud.google.com/bigquery/docs/information-schema-intro)

### Local Schemas & Helper Scripts
- [jobs.json](references/table_schema/jobs.json): Schema for `INFORMATION_SCHEMA.JOBS`.
- [partitions.json](references/table_schema/partitions.json): Schema for `INFORMATION_SCHEMA.PARTITIONS`.
- [tables.json](references/table_schema/tables.json): Schema for `INFORMATION_SCHEMA.TABLES`.
- [views.json](references/table_schema/views.json): Schema for `INFORMATION_SCHEMA.VIEWS`.
- [generate_job_id.sh](scripts/generate_job_id.sh): Standardized Job ID generation helper script.
- [estimate_query_cost.sh](scripts/estimate_query_cost.sh): Query byte scan cost calculator.
- [bigquery_practices_helpers.sh](scripts/bigquery_practices_helpers.sh): Bash wrapper functions for BigQuery query dispatch and label formatting.

## Related Skills

- **[`bigquery-geospatial`](../bigquery-geospatial/SKILL.md)**: Advanced BigQuery GIS capabilities (`GEOGRAPHY` types, S2 indexing, and CARTO H3/Quadbin toolbox).
- **[`bigquery-saved-queries`](../bigquery-saved-queries/SKILL.md)**: Managing persistent queries and Dataform SQLX pipelines.
- **[`api-analyticshub`](../api-analyticshub/SKILL.md)**: Zero-copy data sharing, exchanges, and listing subscription workflows.


---

## Examples

### Example 1: Partitioned & Clustered Query with Traceability Labels
```sql
-- Job ID: workspace_analysis_20260612_084500123_us_ma
-- Labels: agent:antigravity-cli, usecase:rmi-analysis, env:prod, region:boston

SELECT 
  selected_route_id, 
  TIMESTAMP_TRUNC(record_time, HOUR) AS hour_bucket,
  AVG(duration_in_seconds) AS avg_duration,
  AVG(static_duration_in_seconds) AS free_flow_duration,
  SAFE_DIVIDE(AVG(duration_in_seconds), AVG(static_duration_in_seconds)) AS delay_ratio
FROM 
  `my_project.rmi_dataset.routes_realtime`
WHERE 
  -- Partition pruning filter (mandatory)
  record_time BETWEEN '2026-06-01' AND '2026-06-30'
  -- Clustering column filter
  AND selected_route_id = "route-boston-expressway-93"
GROUP BY 
  1, 2
ORDER BY 
  hour_bucket DESC;
```

### Example 2: Vector Search & Search Index Query
```sql
SELECT 
  query.query_text, 
  base.place_id, 
  base.name, 
  distance
FROM VECTOR_SEARCH(
  TABLE `my_project.my_dataset.poi_embeddings`,
  'ml_generate_embedding_result',
  (SELECT ml_generate_embedding_result, content AS query_text FROM ML.GENERATE_EMBEDDING(
    MODEL `my_project.my_dataset.text_embed_model`,
    (SELECT "logistics warehouses near interstate" AS content)
  )),
  top_k => 5,
  distance_type => 'COSINE'
);
```
