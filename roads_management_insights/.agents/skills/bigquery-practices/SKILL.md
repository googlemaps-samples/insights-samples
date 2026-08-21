---
name: bigquery-practices
description: Use this skill for general, product-agnostic BigQuery foundational knowledge, including SQL best practices, geospatial tips (ST_ functions), performance optimization (partition pruning, clustering), block-level table sampling, and temporal engineering.
---

# General BigQuery Best Practices

This skill provides the foundational technical expertise required to write efficient, accurate, and cost-effective SQL in BigQuery.

## 1. SQL Performance & Cost Control
- **Mandatory Partitioning**: Always filter by the partition column. Use `DECLARE` for dynamic filters to ensure the query optimizer can prune partitions effectively.
- **Clustering**: Ensure queries leverage clustering on high-cardinality or geography columns to minimize data scan volume.
- **Block-Level Table Sampling (`TABLESAMPLE SYSTEM`)**:
    - **Mechanics**: `TABLESAMPLE SYSTEM (N PERCENT)` samples at the 64 MB physical storage block level, NOT individual rows.
    - **Small Dataset Pitfall**: On small to medium datasets (~1–2 GB / ~20 blocks), using very small sampling percentages (e.g., `< 1%`) risks picking 0 storage blocks and returning empty results.
    - **Recommended Pattern**: Use `TABLESAMPLE SYSTEM (5 PERCENT)` for block-level scan cost reduction, combined with a secondary row filter (e.g., `WHERE RAND() < 0.0001` or date filters) to cap row counts for BQML / AI model invocations (`AI.GENERATE`) to ~10–25 rows without relying on restrictive `LIMIT` clauses.
- **Native SQL DDL Materialization vs Client Scripts**:
    - For multi-step analytical queries or BQML/`AI.GENERATE` pipelines, prefer pure `CREATE OR REPLACE TABLE dataset.table_name AS SELECT ...` DDL executed directly via `bq query --use_legacy_sql=false` over client-side Python execution. This eliminates shell-escaping issues with complex SQL prompts, provides native BigQuery job tracking, and produces persistent analytical tables.
- **Job Traceability**:
    - **Job IDs**: Implement consistent, meaningful job ID naming for better feature tracking and cost attribution:
        - **Format**: `<workspace/app_indicator>_<category_or_subcategory>_<yyyymmdd>_<hhmmsssss>[_<country_iso>_<admin_area_level_1>]` (where `hhmmsssss` embeds 3-digit padded milliseconds, and optional location suffixes capture the viewport context).
        - **Rationale for Milliseconds**: Rapid consecutive operations (e.g., map viewport panning/zooming, batch UI actions) can execute multiple parallel queries within the same second. Incorporating padded millisecond precision (`sss`) is highly recommended to completely avoid Job ID duplication and collision errors on BigQuery.
        - **Dynamic Geocoded Suffixes**: Enhance debugging and regional cost metrics by appending geocoded locations resolved via Google Maps' Geocoder on map idle. Always use **ISO country codes** (`short_name` from Geocoder address components, e.g., `us`, `au`) instead of full country names to keep the Job ID compact and standardized.
        - **Sanitization**: Convert the category, subcategory, and geocoded suffixes to lowercase. Normalize special characters, strip accents (NFD normalization), and replace non-alphanumeric characters or multiple contiguous underscores with a single underscore.
    - **Traceability Labels**: Always label queries to identify the specific agent initiating the job and the category of the task:
        - `agent`: Use the identifier of the active agent running the query (e.g., `--label agent:gemini-cli` or `--label agent:antigravity-cli`).
        - `usecase`: Label with the specific task category (e.g., `--label usecase:rmi-analysis` or `--label usecase:cost-estimation`).
    - **Contextual Labels**: Enhance trace granularity with optional K-V pairs:
        - `persona`: e.g., `persona:data-scientist`
        - `env`: e.g., `env:sample` or `env:prod`
        - `region`: e.g., `region:boston` or `region:tokyo`
        - `billing_group`: e.g., `billing_group:research`
        - `optimization`: e.g., `optimization:spatial-join`
- **Handling Nested Data**: Use `CROSS JOIN UNNEST()` for flattening arrays and repeated records.
- **Safe Operations**: Always use `SAFE_DIVIDE` and `SAFE_CAST` to prevent query failures on malformed or unexpected data.
- **Dry-Run vs. Actual Cost Discrepancy**:
    - **Parametric TVFs & Functions**: When using Table-Valued Functions (TVFs) or queries filtering with dynamic parameters (e.g., viewport boundaries `@xmin, @ymin, @xmax, @ymax` or dynamic dates), a dry run evaluates the query statically and must estimate a worst-case scenario (full unpruned scan). The actual execution resolves these parameters, using **partition pruning** and **spatial clustering** to scan only a fraction of the estimated data, resulting in significantly lower actual costs.
    - **Query Results Caching**: Dry runs always estimate bytes processed assuming zero cache hits. Actual runs will utilize BigQuery's query cache for exact matches within 24 hours, returning results instantly at **0 bytes processed**.

## 2. Geospatial Tips (`ST_` Functions)
- **Geometry Type**: Standardize on the `GEOGRAPHY` data type (WGS84).
- **Specialized Handling**: Activate **`bigquery-geospatial`** for advanced GIS capabilities, including spatial outer joins (The Two-Join Trick), subdividing heavy geometries, and CARTO Analytics Toolbox extensions (H3/Quadbin).
- **Shape Validation**: Use `ST_GEOMETRYTYPE(geog)` to explicitly filter for required shapes.
- **Spatial Optimizers**: Prioritize `ST_INTERSECTS` for high-performance spatial joins. Avoid mixing spatial predicates with standard equality joins in the same clause when possible.
- **Group By Workaround**: BigQuery does not support `GROUP BY` on `GEOGRAPHY`. Use `ANY_VALUE(geog_column)` or convert to string (`ST_ASTEXT`) for grouping.
- **Repair & Validity**: Use `make_valid => TRUE` during ingestion to handle self-intersecting polygons or overlapping vertices.
- **Simplification**: Use `ST_Simplify` to reduce geometry complexity for visualization or lower-latency responses.
- **Geography Clustering on Selected Routes**: For efficient viewport-based filtering in RMI dashboards, tables must be clustered by `priority` followed by `geometry`. To support this, the `priority` field must exist as a top-level `STRING` column (while keeping nested attributes intact).
- **Avoid ST_UNION_AGG on Large Datasets**: For high-volume spatial datasets (>100,000 rows), never use `ST_UNION_AGG` to calculate a global bounding box. Doing so leads to slot exhaustion and query timeouts. Instead, extract coordinates using `ST_BOUNDINGBOX(geog)` and perform fast scalar `MIN`/`MAX` aggregation on the bounding box component elements.
- **Tiled Extraction Edge-Redundancy & Logical Fusion Bloom (The Compound-Key Mitigation)**: When extracting large regional road networks using multi-tile grid strategies (e.g., Zoom 12/13 tile grids), border-crossing segments are retrieved redundantly across adjacent queries. Due to different tile-containment cuts, these edge duplicates often suffer from slight centimeter-level coordinate offsets, bypassing exact-match spatial/string deduplication. Left unchecked, downstream logical graph fusion engines treat these offsets as distinct physical lanes, bloating total network lengths by **1% to 4%** (e.g., +700km in London, +1,000km in Kuala Lumpur) and double-counting telemetry metrics.
  - *Mitigation*: Implement a POSIX-compliant compound hashing filter (such as an AWK compound hash of `name` and exact `coordinates`) at Step 1 of baseline ingestion to purge tile-edge coordinate offsets before running recursive topological healing and logical graph fusion.

## 3. Temporal Engineering

- **Timezone Management**: Standardize on UTC storage and use `DATETIME(timestamp, "target_timezone")` for local conversions at query time.
- **Aggregations**: Use `TIMESTAMP_TRUNC` for temporal rollups (hour, day, month).

## 4. BigQuery ML (BQML)
BigQuery provides a seamless machine learning experience by allowing you to train and deploy models using standard SQL.

### Lifecycle & Capabilities
- **In-Database Training**: Use `CREATE MODEL` to train models directly on RMI data without egressing to external tools.
- **Model Types**:
    - **Time-Series**: `ARIMA_PLUS` for forecasting future travel times based on historical seasonality.
    - **Clustering**: `KMEANS` for segmenting road network behavior or identifying typical traffic profiles.
    - **Regression/Classification**: `LINEAR_REG_` and `LOGISTIC_REG_` for predicting delay ratios or incident probability.
- **Seamless Deployment**: Models are stored as first-class BigQuery objects, enabling easy sharing and auditing via standard SQL.

### Model Metadata & Description Constraints
- **`CREATE MODEL` Syntax Constraint**: The `OPTIONS(...)` clause in `CREATE MODEL` is reserved strictly for ML hyperparameters (e.g. `model_type`, `num_clusters`, `auto_arima`, `clean_spikes_and_dips`). Attempting to set `description = "..."` directly inside `CREATE MODEL ... OPTIONS(...)` causes a syntax error: `Query error: unsupported option description`.
- **Best Practice Documentation Patterns**:
  1. *SQL Header Comments*: Include standard `-- Model Description: ...` comment blocks above the `CREATE MODEL` statement.
  2. *Post-Creation DDL*: To populate description metadata in the BigQuery schema catalog, execute an explicit `ALTER MODEL` statement after model training finishes:
     ```sql
     ALTER MODEL `my_project.my_dataset.my_model`
     SET OPTIONS(description = "K-Means traffic profile clustering model.");
     ```

## 5. BigQuery CLI Gotchas
When using the `bq` command-line tool, be mindful of flag inconsistencies between subcommands:

- **Regional Location Flag (`--location`)**:
    - When creating datasets or querying tables in non-US locations (e.g., `asia-northeast1`), always explicitly pass `--location=asia-northeast1` to `bq query`, `bq ls`, and `bq show` to avoid cross-region job dispatch failures (`Not found: Table ... in location US`).
- **Write Disposition:**
    - For `bq query`, use `--append_table` or `--replace`.
    - For `bq load`, use `--replace`. (Avoid `--write_disposition=WRITE_TRUNCATE` which is often ignored or causes errors in newer versions).
- **Source Formats:** Always explicitly set `--source_format=PARQUET` or `--source_format=NEWLINE_DELIMITED_JSON` to avoid auto-detection failures on large datasets.
- **Clustering and Schema Incompatibilities:** Running `bq load --replace` with modified `--clustering_fields` on an existing table will fail with:
    > `Incompatible table partitioning specification`
    BigQuery does not permit changing the clustering or partitioning structures of a table during a load-replace operation. You must drop the table first using `bq rm -f <PROJECT_ID>:<DATASET_ID>.<TABLE_ID>` before running `bq load`.
- **Typed Ingestion from JSON Strings (JQ Casting):** Standard API responses often encapsulate numbers as strings inside nested JSON attributes. To load them as native types (like `NUMERIC` or `INTEGER` rather than generic `STRING` or `JSON` fields), pre-process the files with `jq` to extract and explicitly cast those fields using `tonumber`.
    - *Example JQ Filter*: `(.routeAttributes.num_of_roads | select(. != null and . != "") | tonumber // null)`
- **Parquet Loading Schema/Description Omissions**: When loading tables directly from Parquet files (`bq load --source_format=PARQUET`), BigQuery infers columns and data types automatically but silently strips column descriptions and metadata annotations. Since BigQuery does not accept schema JSON files containing descriptions during a Parquet load, the standard mitigation is to execute an immediate SQL `ALTER TABLE <table_name> ALTER COLUMN <column_name> SET OPTIONS(description="...")` DDL statement post-load to restore complete column-level metadata.
- **Wildcard Load Jobs (Serverless Integration)**: When syncing massive datasets (50,000+ records) from serverless functions, avoid loading raw records via API row insertions. Instead, dump the files page-by-page to GCS and run a single, transactional Wildcard Load Job (`WRITE_TRUNCATE` and wildcard path `gs://bucket/path/*.jsonl`). This maintains flat serverless memory and executes fully on the BigQuery side.
- **Enterprise Certificate Proxy (ECP) Transient Connection Refusal (Errno 61)**: On macOS clients using enterprise security proxies (ECP), programmatic API calls or wrapper scripts executing standard SDK operations (such as loading data or running queries) can trigger transient `ConnectionRefusedError` (Errno 61) exceptions due to local proxy connection lockouts. When this occurs, running the identical `bq` CLI command directly in a fresh interactive terminal session re-authenticates the network/proxy handshake, unblocking subsequent automated script operations without unsetting proxy credentials (which would cause `Invalid Credentials` errors on strict corporate networks).


## 6. BigQuery Meta-Data (INFORMATION_SCHEMA)
Use BigQuery `INFORMATION_SCHEMA` views to introspect dataset metadata, monitor operations, and manage costs.

- **Introspection**: Use these views to discover tables, views, and column definitions programmatically.
- **Operations**: Monitor active and completed jobs, including `total_bytes_processed` and `total_bytes_billed` for cost attribution.
- **Optimization**: Analyze partition metadata to ensure partition pruning is functioning as expected.

## 7. Downstream Metadata Preservation (Derived Tables)
When creating derived tables, views, or summary metrics from base tables (such as RMI foundation or real-time tables), **always adopt and copy the upstream column descriptions as much as possible**. This guarantees that downstream consumers, BI dashboards, and analytical agents maintain the same level of rich, high-fidelity metadata.
- **Dataform/SQLX Implementation**: Re-use descriptions inside the Dataform config schema blocks for any columns propagated downstream.
- **DDL Tables & Views**: Explicitly set column descriptions on derived views or tables using `ALTER TABLE ALTER COLUMN SET OPTIONS (description=...)` or `ALTER VIEW ALTER COLUMN SET OPTIONS (description=...)`.

## 8. BigQuery Remote Functions (User-Defined Functions)
When designing and deploying custom or standard BigQuery Remote Functions backed by Cloud Run/Functions:
- **Ensuring Infrastructure Sync (Terraform triggers)**: When defining the SQL function registering the remote endpoint using `null_resource` or standard Terraform resources, standard triggers (such as matching on the Cloud Run endpoint URI) will NOT trigger recreation if you only modify the function signature, SQL parameter types, or function metadata descriptions. 
  - *Mitigation*: Introduce a signature/version tracker parameter or **include the description text itself** directly into the `null_resource` triggers block (e.g. `description = local.description_text`). Any modifications to the function's parameters, SQL types, or metadata/descriptions will trigger an automatic recreation in BigQuery on the next `terraform apply`.
- **Handling Dual Parameter Formats (The Polymorphic String Pattern)**: Instead of creating duplicate remote functions or forcing users to construct raw JSON objects, you can accept a single `STRING` argument (e.g. `origin_or_place`) and programmatically inspect the prefix in the backend container:
  - If it matches a WKT Point pattern (e.g., starts with `POINT`), parse it into coordinate latitude/longitude objects.
  - Otherwise, treat it as a Place ID or resource name (e.g., prepending `places/` if needed).
  This keeps standard SQL signatures elegant while completely exposing the underlying Google Maps API's dual origin capabilities.
- **Function Descriptions & Examples**: Always populate the `description` attribute in the remote function's `OPTIONS` block. This exposes interactive help text and SQL usage examples directly within the Google Cloud Console BigQuery Routine details page, significantly reducing onboarding friction for downstream analysts.
- **Service Account Project Realignment & State Import**:
  - *The Project Default Pitfall*: When declaring `google_service_account` resources in Terraform, omitting the `project` argument defaults the resource to the provider's active project at creation time. If the provider's project is later updated, Terraform does not automatically detect that the service account needs to be recreated in the new project. Always explicitly set `project = var.project_id` in `google_service_account` resource blocks to force clean project-level tracking and recreation.
  - *Managing 409 Conflicts via State Import*: If a service account (or any other force-new resource) already exists in the target project, running `terraform apply` will fail with a `409 Conflict: Already Exists` error. Reconcile this by running `terraform import <resource_address> <gcp_resource_id>` to import the physical resource into the state, allowing subsequent apply steps to cleanly attach IAM roles and configure permissions.
- **Production-Grade Container Optimization Patterns**:
  - *Graceful NULL Short-Circuiting*: Never let null, empty, or whitespace-only inputs propagate to regex parses or API requests. Implement immediate short-circuiting checks at the container's entrypoint to return standard JSON/SQL `null` instantly. This reduces container execution latency, saves CPU cycles, and keeps Cloud Run logs clean of warning exceptions.
  - *Raw Telemetry Coordinate Deduplication*: Telemetry streams often have consecutive duplicate GPS coordinates (stopped or idling vehicles). Filter out sequential duplicates in the container before forwarding them to third-party endpoints to optimize network bandwidth and prevent remote API validation failures.
  - *Clean Geometry Stitching (Boundary Deduplication)*: When stitching individual segment-based results into a combined `LINESTRING` geometry, consecutive duplicate coordinates at segment boundary junctions must be deduplicated. This results in mathematically valid, clean WKT strings that prevent downstream BigQuery spatial slot-hour query inflation.
  - *Deduplicated Multi-lingual/Locale Arrays*: When mapping multilingual options to alternative name arrays, use unique collection structures (like a JavaScript `Set` object) to filter out duplicate names resulting from overlapping fallback locales.



## 9. JSON & Array Telemetry Parsing
- **Integer Scaling vs Float Division**: Converting raw epoch timestamps (seconds/nanos) using `TIMESTAMP_MICROS` requires an `INT64` type. Use integer division `DIV(nanos, 1000)` instead of `SAFE_DIVIDE`, as `SAFE_DIVIDE` yields a `FLOAT64` which causes type compatibility errors unless cast.
- **Array Flattening**: Combine `JSON_VALUE_ARRAY` with `ARRAY_TO_STRING(..., "|")` to flatten arrays (e.g. `road_segment_ids`) into indexable string lists for high-performance querying without using expensive `UNNEST` scalar operations.
- **Materialized Views Constraint on Arrays**: BigQuery Materialized Views prohibit complex array functions, subqueries, and `UNNEST` expressions. If your query needs to parse nested arrays or geometries from JSON columns, you must use physical tables updated via scheduled jobs or ELT (e.g., Dataform/dbt) instead of Materialized Views.

## 10. Rich Markdown Rendering in Console UI
- **GitHub-Flavored Markdown Parsing**: The native Google Cloud Console BigQuery UI parses and renders standard GitHub-Flavored Markdown (`#`, `###`, `**`, lists, links) inside table, view, and column descriptions.
- **Triple-Quoted Literals (`"""..."""`)**: When applying descriptions via DDL (such as `ALTER TABLE ... SET OPTIONS` or inside Dataform compilation targets), wrap the Markdown string in triple double-quotes (`"""`) to naturally preserve multi-line layouts and nested single/double quotes without throwing syntax parsing exceptions.
- **Escaping Backticks**: When writing JavaScript-templated DDL generators (such as within Dataform `.sqlx` blocks or custom JS includes), ensure any Markdown backticks (\`) intended for inline code rendering are properly escaped as `\`` to prevent runtime JS compile-time conflicts.

## 11. View & Materialized View Schema Management
- **Standard Views Schema Bindings (`SELECT *` Caveat)**: When a standard view using `SELECT *` is defined on top of a physical base table, BigQuery evaluates the schema at compilation/definition time. If new columns are subsequently added to the base physical table, the view **will NOT dynamically/automatically propagate those new columns** to consumers until the view is explicitly recreated or replaced. To prevent schema synchronization lag and ensure robust governance, always explicitly list columns in view definitions.
- **Materialized Views formatting updates (Terraform replacement)**: In Terraform, any changes (including minor whitespace or indentation refactoring) to the SQL query within a `materialized_view` block are detected as logical query modifications, which **forces replacement (drop and recreate)** of the table/MV resource. To allow non-disruptive formatting and SQL updates of materialized views, ensure `deletion_protection = false` is declared on the `google_bigquery_table` resource. Dropping and recreating materialized views has zero data loss risk since they automatically and dynamically rebuild from the underlying partitioned base tables.
- **Geography Clustering on Materialized Views**: BigQuery fully supports clustering on columns of type `GEOGRAPHY` inside Materialized Views. This is highly effective for accelerating spatial bounding-box or point-overlapping queries on high-volume telemetry datasets.

## 12. Primary & Foreign Key Constraints (Unenforced Metadata-only Joins)
- **Unenforced/Declarative Contracts**: BigQuery supports Primary and Foreign Key constraints, but they are strictly **NOT ENFORCED** on write. It is up to your upstream pipeline (e.g. using `QUALIFY ROW_NUMBER() OVER(PARTITION BY key_column) = 1` filters) to physically guarantee uniqueness.
- **Query Optimization (Join Pruning)**: Declaring Primary and Foreign Keys tells the BigQuery Query Optimizer that join keys are unique. The optimizer utilizes this to prune redundant outer-joins (Join Elimination), swap joins dynamically, and optimize aggregates. This accelerates multi-million row topological or telemetry joins dramatically.
- **In-place Schema Changes (`ALTER TABLE`)**: Because constraints are metadata-only, you can add or drop keys on existing tables instantly, without recreating, dropping, or duplicating the underlying tables:
  ```sql
  -- Drop Key
  ALTER TABLE dataset.table DROP PRIMARY KEY;
  -- Add Key
  ALTER TABLE dataset.table ADD PRIMARY KEY(place_id) NOT ENFORCED;
  -- Add Foreign Key
  ALTER TABLE dataset.table ADD CONSTRAINT fk_start FOREIGN KEY (start_node_id) REFERENCES dataset.nodes(node_id) NOT ENFORCED;
  ```
- **Unified ID Consistency**: Always align primary keys across base, enriched, and modeled tables (e.g. using `place_id` instead of raw `name` strings) to ensure uniform schema conventions and simplify downstream analytical joins.

## 13. Dynamic Metadata Description Injection
- **Orchestrated Table Documentation**: Instead of manual SQL scripts or fragile DDL arrays, integrate description metadata updates directly into your orchestrator (e.g., pipeline scripts) after loading and model building steps.
- **Automated Schema Sync**: Programmatically query dataset metadata catalogs or loop through tables to inject professional, de-branded description markdown strings into the `OPTIONS(description=...)` parameters, ensuring live cloud datasets and local markdown files are always 100% in sync.
- **Ingestion Schema-level Descriptions**: When loading data programmatically (e.g., via `@google-cloud/bigquery`'s `table.load()`), always configure the `schema.fields` array to contain detailed `description` properties for every column. Overwriting or creating a table this way guarantees that metadata is transactionally registered directly during the write transaction.

## 14. Upstream Change Propagation (Table Row Count Guard)
- **The Problem**: During pipeline resumption, steps check if BigQuery tables exist. If a table exists from a previous run, the step may be skipped. However, if a previous run was a partial/clipped run with outdated rows, skipping the step results in stale, corrupt, or incomplete downstream data.
- **The Solution (Row Count Guard)**: Implement a row count verification guard. Check the existing target table's row count against the source file's total segment count. If a count mismatch is detected, trigger an upstream change propagation that forces dropping and fully reloading downstream views and tables. This maintains strict transactional consistency between files and cloud databases.

## 15. Centralized Native SQL UDFs vs. JavaScript UDFs (Performance & Optimization)
- **Zero V8 Engine Start-up Latency**: Standard JavaScript-based UDFs in BigQuery require separate V8 runtime context instantiations inside each active slot. This adds substantial serialization, de-serialization, and start-up overhead. Translating formulas into native standard SQL mathematical statements completely avoids this context switching.
- **Inlining & Query Planner Optimization**: BigQuery's query planner is completely blind to the internal operations of JavaScript UDFs, treating them as black-box execution blocks that prevent filter pushdown, index utilization, and partition/spatial pruning. Conversely, native SQL UDFs are fully compiled and inlined directly into the query execution tree, allowing BigQuery to aggressively optimize and speed up slot usage.
- **Translating Trigonometry to SQL**: Traditional mathematical coordinates projection formulas (like Mercator tile mapping `tile2lat`, `tile2lon`, `lon2tile`, `lat2tile`) containing trigonometric, logarithmic, or hyperbolic functions can be translated cleanly into native standard SQL (e.g., using `SINH`, `COSH`, `LN`, `TAN`, `COS`, and exact $\pi$ represented by `ACOS(-1)`):
  ```sql
  -- Native SQL tile2lat UDF
  CREATE OR REPLACE FUNCTION `utility_functions_us.tile2lat`(y INT64, z INT64) RETURNS FLOAT64 AS (
    ATAN(SINH(ACOS(-1) * (1.0 - 2.0 * y / POW(2.0, z)))) * 180.0 / ACOS(-1)
  );
  ```

## 16. Table-Valued Functions (TVFs) for DRYing Complex Spatial Query Logic
- **DRYing Out Entire Multi-Stage CTE Pipelines**: Standard scalar UDFs are great for individual value calculations, but when an entire query pipeline (e.g., multi-stage hierarchical Quadtree spatial grid filtering containing CTEs and UNNEST loops) is duplicated across several boundary SQL files, it increases maintenance friction. Table-Valued Functions (TVFs) allow you to parameterize and centralize the entire query pipeline as a database-level virtual table function.
- **Structure and Invocation**: Define a persistent TVF accepting inputs (such as a geometry representing the boundary and an integer zoom level) and returning a virtual table. This cuts down complex 230-line coordinate-generation SQL files to simple 20-line declarative definitions:
  ```sql
  -- Invoke central TVF from a short regional configuration template
  SELECT * FROM `my_project.utility_functions_us.generate_tile_grid`(
    (SELECT boundary_geom FROM closed_geom),
    zoom
  ) ORDER BY id;
  ```
- **BigQuery Geography Constraints on TVFs**: When returning or manipulating datasets within TVFs, be mindful of BigQuery's strict geography constraints. For example, trying to run standard uniqueness grouping on `GEOGRAPHY` columns (such as `SELECT DISTINCT boundary_geom`) is prohibited. Resolve this by bypassing redundant distinct subqueries and returning the input scalar parameter or standard scalar selectors directly.
- **Regional Deployment Isolation**: Just like scalar UDFs, Table Functions are strictly region-scoped. Deploy copies of the TVFs across regional datasets (e.g., `utility_functions_us`, `utility_functions_us_central1`), and use dynamic string substitution in wrapper scripts to rewrite the dataset reference before executing queries.

## 17. Storage Billing Optimization: Physical vs. Logical Storage Model
BigQuery allows datasets to be billed based on **Logical storage** (uncompressed data size) or **Physical storage** (compressed on-disk size).
- **The Telemetry & Spatial Savings Pattern**: High-volume telemetry, JSON logs, and spatial tables exhibit high compression ratios (often 3:1 to 10:1) with BigQuery's Capacitor storage format.
- **When to Choose Physical Storage**:
  - If compressed size is $< 50\%$ of logical size, configure dataset storage billing to `PHYSICAL`:
    ```sql
    ALTER SCHEMA `my_project.my_dataset`
    SET OPTIONS(storage_billing_model = 'PHYSICAL');
    ```
  - *Caveat*: Physical storage charges for Time Travel and Fail-safe storage; manage Time Travel windows (e.g. reduce from 7 days to 2 days for ephemeral staging datasets) to maximize net cost savings:
    ```sql
    ALTER SCHEMA `my_project.my_dataset`
    SET OPTIONS(max_time_travel_hours = 48);
    ```

## 18. Search Indexes & Vector Search (`VECTOR_SEARCH` & Embeddings)
Modern BigQuery provides native search indexes and vector search directly in SQL without requiring external vector databases.
- **Search Indexes for Semi-Structured Text & JSON**:
  - Create a search index over text or JSON columns:
    ```sql
    CREATE SEARCH INDEX IF NOT EXISTS roads_search_idx
    ON `my_project.my_dataset.road_segments`(ALL COLUMNS);
    ```
  - Query using the index-accelerated `SEARCH()` function:
    ```sql
    SELECT * FROM `my_project.my_dataset.road_segments`
    WHERE SEARCH(data, 'highway OR bridge');
    ```
- **Native Vector Similarity Search**:
  - Generate embeddings using BQML `ML.GENERATE_EMBEDDING` with Vertex AI text-embedding models:
    ```sql
    CREATE OR REPLACE TABLE `my_project.my_dataset.poi_embeddings` AS
    SELECT * FROM ML.GENERATE_EMBEDDING(
      MODEL `my_project.my_dataset.text_embed_model`,
      (SELECT place_id, name, address FROM `my_project.my_dataset.places`),
      STRUCT(TRUE AS flatten_json_output)
    );
    ```
  - Perform high-speed top-$K$ cosine or euclidean similarity search:
    ```sql
    SELECT query.query_text, base.place_id, base.name, distance
    FROM VECTOR_SEARCH(
      TABLE `my_project.my_dataset.poi_embeddings`,
      'ml_generate_embedding_result',
      (SELECT ml_generate_embedding_result, content AS query_text FROM ML.GENERATE_EMBEDDING(
        MODEL `my_project.my_dataset.text_embed_model`,
        (SELECT "coffee shops with outdoor seating" AS content)
      )),
      top_k => 10,
      distance_type => 'COSINE'
    );
    ```

## 19. Continuous Queries & Storage Write API
- **Storage Write API (Default, Committed, Pending)**:
  - Deprecate legacy `tabledata.insertAll` in favor of the gRPC-based **Storage Write API** for 50%+ lower ingestion cost, streaming deduplication, and exactly-once delivery.
  - Use `CommittedStream` for immediate row visibility or `PendingStream` + `CommitWriteStream` for multi-batch atomic transactions.
- **BigQuery Continuous Queries**:
  - Run SQL continuously over streaming sources (Pub/Sub topics or BigQuery change data capture) and output directly to Pub/Sub, Bigtable, or downstream tables:
    ```sql
    EXPORT DATA
    OPTIONS (
      format = 'CLOUD_PUBSUB',
      uri = 'https://pubsub.googleapis.com/projects/my-project/topics/live-alerts'
    ) AS
    SELECT
      route_id,
      travel_duration_seconds,
      CURRENT_TIMESTAMP() AS alert_time
    FROM `my_project.my_dataset.recent_roads_stream`
    WHERE travel_duration_seconds > 1800;
    ```

## 20. Zero-Copy Governance: Row & Column Level Security with Data Masking
- **Row-Level Security (RLS)**:
  - Restrict row visibility based on session identity (`SESSION_USER()`) without proliferating filtered views:
    ```sql
    CREATE OR REPLACE ROW ACCESS POLICY regional_access_filter
    ON `my_project.my_dataset.customer_telemetry`
    GRANT TO ('group:apac-analysts@example.com')
    FILTER USING (region = 'APAC');
    ```
- **Column-Level Security & Dynamic Data Masking**:
  - Attach Policy Tags to sensitive fields (e.g. driver PII or VIN numbers) and define Data Masking Rules (`DEFAULT_MASKING_VALUE`, `HASH(SHA256)`, or custom masking routines).
- **Authorized Datasets & Views**:
  - Grant views or entire datasets authorized access to upstream source tables, allowing external consumers to query transformed metrics without granting direct permissions on raw data.

## 21. Query Execution Plan Diagnostics: Shuffle Spills, Skew & Bottlenecks
When troubleshooting slow or expensive queries in the Cloud Console or via `INFORMATION_SCHEMA.JOBS`:
- **Stage Wait Time**: High wait time indicates slots are saturated or blocked waiting for previous stages to finish.
- **Data Skew & Slot Hotspots**: If `max_slot_ms` is $>5\times$ higher than `avg_slot_ms` in a join or aggregation stage, one slot is processing a hot key (e.g., joining on `NULL` or a generic default value). *Mitigation*: Nullify or filter out hot keys before the join.
## 22. Analytics Hub Linked Dataset Materialization Constraints & Workarounds
- **Materialized Views Prohibition**: BigQuery explicitly disallows creating Materialized Views (`CREATE MATERIALIZED VIEW`) directly on top of Analytics Hub shared / linked datasets (`Can't create materialized view on linked dataset`).
- **The Clustered Table Materialization Pattern**: To cache or pre-aggregate high-cost query outputs from linked datasets for high-speed downstream querying:
  - Create a partitioned and clustered physical table in a writable target dataset:
    ```sql
    CREATE OR REPLACE TABLE `my_project.writable_dataset.corridor_summary`
    (
      route_id STRING OPTIONS(description="Unique identifier for the route."),
      record_time TIMESTAMP OPTIONS(description="Observation timestamp."),
      avg_delay_ratio FLOAT64 OPTIONS(description="Average delay ratio.")
    )
    PARTITION BY DATE(record_time)
    CLUSTER BY route_id
    OPTIONS (
      description="Materialized 7-day extract from Analytics Hub linked telemetry dataset."
    ) AS
    SELECT route_id, record_time, SAFE_DIVIDE(duration, static_duration) AS avg_delay_ratio
    FROM `LINKED_DATASET_NAME.historical_travel_time`
    WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY);
    ```
- **Standard Logical Views**: If automatic live query pass-through is preferred without data duplication, standard views (`CREATE OR REPLACE VIEW`) are fully supported on linked datasets.

## References
- [jobs.json](references/table_schema/jobs.json): Schema for the `JOBS` view (BY_PROJECT, BY_USER).
- [partitions.json](references/table_schema/partitions.json): Schema for the `PARTITIONS` view.
- [tables.json](references/table_schema/tables.json): Schema for the `TABLES` view.
- [views.json](references/table_schema/views.json): Schema for the `VIEWS` view.
- [bigquery_core.md](references/bigquery_core.md): Deep dive into GIS functions and general SQL performance.
- [bigquery_ml.md](references/bigquery_ml.md): General BigQuery ML usage patterns.

## Related Skills
- **[`bigquery-geospatial`](../bigquery-geospatial/SKILL.md)**: Deep dive into BigQuery GIS capabilities (`GEOGRAPHY` types, `ST_*` functions, S2 indexing, and CARTO toolbox).
- **[`bigquery-saved-queries`](../bigquery-saved-queries/SKILL.md)**: Managing and deploying persistent queries and Dataform repositories.
- **[`api-dataform`](../api-dataform/SKILL.md)**: Programmatic Dataform API reference, workspace lifecycles, and SQLX compilation.
- **[`api-analyticshub`](../api-analyticshub/SKILL.md)**: Zero-copy dataset sharing, data exchanges, and cross-project subscription patterns.

## Examples

### 1. Optimized Partitioned & Clustered Query with Traceability Labels
Construct queries that strictly leverage partition filters and include auditing job indicators:
```sql
-- Query Options:
-- Job ID: workspace_analysis_20260612_084500123_us_ca
-- Labels: agent:<active-agent-id>, usecase:<task-category>, env:prod

SELECT 
  route_id, 
  TIMESTAMP_TRUNC(record_time, HOUR) as hour_bucket,
  AVG(travel_duration_seconds) as avg_duration
FROM 
  `my_project.rmi_dataset.recent_roads_data`
WHERE 
  -- Partition pruning filter (mandatory)
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  -- Clustering column filter
  AND route_id = "route-sf-downtown-101"
GROUP BY 
  1, 2
ORDER BY 
  hour_bucket DESC;
```
