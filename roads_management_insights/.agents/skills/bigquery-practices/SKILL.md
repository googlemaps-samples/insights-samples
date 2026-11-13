---
name: bigquery-practices
description: "Use this skill for foundational BigQuery best practices for SQL performance, geospatial functions, temporal engineering, BQML, vector search, storage optimization (physical vs. logical), execution diagnostics, and enterprise governance."
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

- **The Telemetry & Spatial Savings Pattern**: High-volume telemetry, JSON logs, and spatial tables exhibit high compression ratios (often 3:1 to 18:1) with BigQuery's Capacitor storage format.
- **Exact `INFORMATION_SCHEMA.TABLE_STORAGE` Cost Accounting (Avoiding Time-Travel Double-Counting)**:
  - In `region-<loc>.INFORMATION_SCHEMA.TABLE_STORAGE`, **`active_physical_bytes` already includes `time_travel_physical_bytes`**, whereas **`fail_safe_physical_bytes` is NOT included in `active_physical_bytes`**.
  - Therefore, total billable active physical bytes = `(active_physical_bytes + fail_safe_physical_bytes)` (billed at the region's active physical rate) plus `long_term_physical_bytes` (billed at the region's long-term physical rate). Never add `time_travel_physical_bytes` to `active_physical_bytes`, as doing so double-counts time-travel bytes.
  - Separate **Base Capacitor Compression Ratio** (pure columnar compression before retention overhead) from **Effective Compression Ratio** (including time-travel and 7-day fail-safe overhead):

    ```sql
    -- Base Capacitor compression ratio (excluding time-travel and fail-safe bytes)
    SAFE_DIVIDE(
      total_logical_bytes,
      NULLIF((active_physical_bytes - time_travel_physical_bytes) + long_term_physical_bytes, 0)
    ) AS base_compression_ratio,

    -- Effective billable compression ratio (including time-travel and fail-safe bytes)
    SAFE_DIVIDE(
      total_logical_bytes,
      NULLIF(active_physical_bytes + fail_safe_physical_bytes + long_term_physical_bytes, 0)
    ) AS effective_compression_ratio
    ```

- **Capacitor RLE Compression Collapse on Unclustered Time-Partitioned Tables (`1.76x` vs. `15x+`)**:
  - Because BigQuery active physical storage is priced at `2.0x` the active logical rate (e.g., `$0.040/GiB-mo` physical vs. `$0.020/GiB-mo` logical in `US`/`EU`), a dataset must achieve **`> 2.0x` effective compression** for `PHYSICAL` billing to be cheaper than `LOGICAL` billing.
  - When a daily time-partitioned table (`PARTITION BY DATE(start_time)`) with repeated `GEOGRAPHY` polylines (`polyline` / `route_geometry`) or entity identifiers (`road_segment_id` / `selected_route_id`) lacks a `CLUSTER BY` clause and is written in timestamp-ordered (`start_time`) batches, every adjacent row in Capacitor belongs to a different entity and geometry. Run-Length Encoding (RLE) run lengths collapse to `1`, inflating physical storage by **8x to 9x** (`~170-192 B/row` physical vs. `~17-32 B/row` when entity-sorted, dropping compression to `1.76x-1.87x`).
  - **Remediation**: Always declare `CLUSTER BY <entity_id>` (e.g., `CLUSTER BY road_segment_id, road_priority` or `CLUSTER BY selected_route_id`) on time-partitioned spatial telemetry tables so Capacitor physically co-locates repeated entity geometries within each daily partition, restoring `14x-16x` RLE compression (`~88%` physical byte reduction).
- **When to Choose Physical Storage**:
  - If compressed physical size (including time-travel and fail-safe bytes) is `< 50%` of logical size (`effective_compression_ratio > 2.0`), configure dataset storage billing to `PHYSICAL`:

    ```sql
    ALTER SCHEMA `my_project.my_dataset`
    SET OPTIONS(storage_billing_model = 'PHYSICAL');
    ```

  - *Time Travel Management*: Physical storage charges for Time Travel and Fail-safe storage; reduce Time Travel windows (e.g. from 7 days to 2 days for high-churn rolling tables or staging datasets) to maximize net cost savings:

    ```sql
    ALTER SCHEMA `my_project.my_dataset`
    SET OPTIONS(max_time_travel_hours = 48);
    ```

  - *Avoid Full-Table `DELETE WHERE TRUE` + `INSERT` on Snapshot Tables (`3.0x` Physical Storage Bloat)*: Refreshing a `_latest` snapshot table by running `DELETE FROM dataset.table_latest WHERE TRUE; INSERT INTO dataset.table_latest ...` retains every deleted Capacitor block in `time_travel_physical_bytes` (for up to 7 days) and `fail_safe_physical_bytes` (for an additional 7 days), multiplying billable physical storage by **2.0x to 3.0x** and forcing full `SEARCH INDEX` rebuilds. Instead, apply incremental `MERGE` statements from the partition delta table (where typical weekly road or entity churn is `< 3%`), or use `CREATE OR REPLACE TABLE ... CLONE` from a staging table with `max_time_travel_hours = 48`.
  - *Spatial Locality vs. Random String ID Clustering Penalty on Single-Snapshot `GEOGRAPHY` Tables (`+75.8%` Active Physical Storage)*: Unlike multi-day telemetry tables (where `CLUSTER BY entity_id` groups repeated observations of the same entity), on a **single-snapshot spatial entity table** (`1 row per entity`, e.g., `131.9M` road segments in `roads_us_latest`), changing clustering from `(priority, geometry)` (which co-locates spatially adjacent `LINESTRING`s and shared street names within S2 cells) to a pseudo-random string identifier (`CLUSTER BY road_segment_id` / `ChIJ...`) scatters spatially adjacent rows across all Capacitor blocks. Empirically, this degrades columnar compression on WKB coordinates and nested `names[]` structs, **increasing current active physical storage by `+75.8%`** (`39.311 GB` vs. `22.355 GB` for the exact same `57.402 GB` logical bytes, dropping compression from `2.57x` to `1.46x`—below the `2.0x` physical billing breakeven) while still scanning `88.8%` (`50.97 GB`) on dynamic multi-ID joins (`UNNEST(ids)`). Keep `(priority, geometry)` on the primary table and accelerate point/batch ID lookups via `CREATE SEARCH INDEX ON table(names, id_col)` plus an explicitly named ID-clustered companion table (`<entity>_by_id`).
  - *Per-Table `bq show --format=json` Fallback When `INFORMATION_SCHEMA.TABLE_STORAGE` Returns `Access Denied`*: Querying `region-<loc>.INFORMATION_SCHEMA.TABLE_STORAGE` requires dataset/project metadata permissions that often return `Access Denied` on cross-project test or shared datasets where the caller only has `roles/bigquery.dataViewer`. In those environments, inspect `bq show --format=json <project>:<dataset>.<table>` (`tables.get`), which exposes the exact physical storage counters (`numBytes`, `numActivePhysicalBytes`, `numTimeTravelPhysicalBytes`, `numLongTermPhysicalBytes`, `numTotalPhysicalBytes`) per table without requiring `INFORMATION_SCHEMA.TABLE_STORAGE` access.

### 1.5 Dry-Run vs. Actual Cost Discrepancy (TVFs, Parameters & Query Cache)

- **Parametric TVFs & Functions**: When using Table-Valued Functions (TVFs) or queries filtering with dynamic parameters (e.g., viewport boundaries `@xmin, @ymin, @xmax, @ymax`), a dry run evaluates the query statically and must estimate a worst-case scenario (full unpruned scan). The actual execution resolves parameters, using partition pruning and spatial clustering to scan only a fraction of the estimated data.
- **Query Results Caching**: Dry runs always estimate bytes processed assuming zero cache hits. Actual runs utilize BigQuery's query cache for exact matches within 24 hours, returning results instantly at **0 bytes processed**.

### 1.6 Safe Arithmetic & String Casting

- **Defensive Expressions**: Always use `SAFE_DIVIDE` and `SAFE_CAST` to prevent query runtime failures on malformed, division-by-zero, or missing data attributes.

### 1.7 BigQuery CLI (`bq`) Query Dispatch: Stdin Streaming vs. Positional Arguments

- **The Problem with Positional SQL Strings**: When dispatching queries through `bq query ... "<sql>"`, lines starting with `--` (standard SQL comments, such as `-- Analysis Query`) or long multi-line SQL statements are parsed by Google's `absl.flags` library. If a comment line resembles an unknown option flag, `absl.flags` invokes `_damerau_levenshtein` typo suggestion calculations recursively, triggering a fatal error:
  `RecursionError: maximum recursion depth exceeded while calling a Python object`.
- **The Stdin Streaming Pattern**: Always stream queries to `bq` via **standard input (`stdin`)** rather than passing the query as a positional CLI argument. Piping via stdin completely bypasses flag parsing in `absl.flags`, eliminates the recursion hazard, and safely handles multi-line SQL with extensive documentation comments:

  ```bash
  # POSIX Bash: Stream query via pipe
  printf '%s' "${SQL_QUERY}" | bq query \
    --use_legacy_sql=false \
    --format=json \
    --label=datacloud:antigravity
  ```

  ```typescript
  // Node.js API Proxy / Backend Service
  import { spawn } from 'child_process';

  const bqProcess = spawn('bq', [
    'query',
    '--use_legacy_sql=false',
    '--format=json',
    '--label=datacloud:antigravity',
  ]);

  // Write SQL directly to standard input and close stream
  bqProcess.stdin.write(sqlQuery);
  bqProcess.stdin.end();
  ```

### 1.8 Persistent Python Client + Storage Read API vs. CLI Subprocess Overhead & `bq load` Watchdog

- **The CLI Subprocess & JSON Bottleneck**: In multi-stage pipelines executing 30+ sequential SQL statements and Python graph steps, dispatching each step via `bq query --format=json` and `bq load` subprocesses spends **~50% of total wall-clock time** in Python CLI startup (`~27%`), OAuth2 proxy handshakes, and JSON stdout/load serialization (`~22%`). Replacing per-step `bq` CLI subprocesses with a single persistent `google.cloud.bigquery.Client` + `google.cloud.bigquery_storage_v1.BigQueryReadClient` session (reading via Arrow and uploading via in-memory Parquet `io.BytesIO` buffers) cuts end-to-end runtime by **2.2x to 2.5x** (e.g., `911 s` $\to$ `406 s`).
- **Concurrent Multi-Table Arrow Reads (`query_many`)**: When a Python step loads 5–10 input tables, fetch them concurrently using a `ThreadPoolExecutor` over `Client.query(...).to_arrow()`, reducing multi-table input load wall time by **4x** (`39 s` $\to$ `9 s`).
- **Preventing Indefinite `bq load` Resumable Upload Hangs**: The `bq load` CLI can hang indefinitely (`60+ min`) when its underlying `httplib2` resumable upload socket stalls without a socket read timeout. Always prefer `bigquery.Client.load_table_from_file(..., timeout=(60, 180), retry=DEFAULT_RETRY)` with explicit connect/read timeouts; where a `bq` CLI fallback is retained, wrap CLI calls in a parent-process watchdog script that terminates stalled child processes after a bounded timeout.

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

### 2.3 Time Travel Limits vs. Partition Expiration & Long-Term Snapshots

- **Platform Maximum of 7 Days**: BigQuery Time Travel (`FOR SYSTEM_TIME AS OF <timestamp>`) is strictly hard-capped at a platform maximum of **168 hours (7 days)** (configurable between 48 and 168 hours at the dataset level via `max_time_travel_hours`).
- **Cannot Bypass or Extend Partition Expiration**: Time Travel **cannot** be used to query or recover data older than 7 days from the current moment, regardless of table partition retention (e.g. attempting `FOR SYSTEM_TIME AS OF TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 65 DAY)` on a 60-day rolling table will fail immediately with an `Invalid snapshot time` error). Once partitions expire and fall outside the 7-day recovery window, they are permanently purged by garbage collection.
- **Long-Term Point-in-Time Preservation Patterns**:
  - *Extending Partition Retention*: If data is needed across a longer rolling window (e.g., 70–90 days), increase partition retention directly: `ALTER TABLE dataset.table SET OPTIONS (partition_expiration_days = 90);`.
  - *BigQuery Table Snapshots*: For point-in-time preservation across weeks/months without duplicating baseline storage costs, create Table Snapshots (`CREATE SNAPSHOT TABLE dataset.table_snap CLONE dataset.table OPTIONS (expiration_timestamp = ...)`). Only delta/modified blocks are billed.
  - *Coldline/Archive Exports*: For regulatory or compliance archives beyond operational query windows, export older partitions to Cloud Storage in Parquet or Avro format.

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

- **Search Indexes for Text, Doubly-Nested `ARRAY<STRUCT>`, & Point ID Lookups**:
  - BigQuery's `SEARCH(col, '`phrase`')` predicate natively traverses doubly-nested `ARRAY<STRUCT<... ARRAY<STRUCT<text STRING>>>>` fields without requiring `UNNEST`, and uses backticks inside the search query string (`` '`Interstate 93`' ``) to enforce exact phrase token matching.
  - Declaring a multi-column `SEARCH INDEX` over both nested text structures and high-cardinality string ID columns accelerates both text search and `WHERE id = '...'` / `WHERE fk_id IN (...)` point lookups without adding a secondary table cluster key:

  ```sql
  CREATE SEARCH INDEX IF NOT EXISTS roads_search_idx
  ON `my_project.my_dataset.road_segments_latest`(
    names,
    road_segment_id,
    opposite_direction_road_segment_id
  );
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
  ```

### 3.6 BigQuery ML Zero-Join Multimodal Inference (`TABLE <cte>` Input Column Passthrough)

- **The Secondary Join Anti-Pattern**: When invoking `ML.GENERATE_TEXT` over a candidate set (e.g. candidate images or spatial shortlists), passing a subquery `(SELECT uri, content_type, prompt FROM candidate_cte)` forces analysts to author an expensive post-inference join `JOIN candidate_cte ON candidate_cte.uri = ml_res.uri` to re-attach metadata columns (`observation_id`, `camera_heading`, `distance_meters`, `location_geom`). This introduces hash join overhead, inflates query execution plans, and risks join mismatches on duplicate or shared URIs.
- **Canonical Solution (`TABLE <cte_name>` Syntax)**: Pass the entire CTE directly using the `TABLE <cte_name>` table argument:

  ```sql
  WITH candidate_observations AS (
    SELECT
      observation_id,
      pano_id,
      camera_heading_deg,
      gcs_uri,
      gcs_uri AS uri,
      'image/jpeg' AS content_type,
      'Analyze this image for coin parking equipment. Output JSON.' AS prompt
    FROM `my_project.my_dataset.v_observations_by_pano`
    WHERE pano_id = 'OS5q9kbT5N5PRMHogyx5BQ'
  )
  SELECT
    observation_id,
    pano_id,
    camera_heading_deg,
    JSON_VALUE(TRIM(REGEXP_REPLACE(REGEXP_REPLACE(ml_generate_text_llm_result, r'^```(?:json)?\s*', ''), r'\s*```$', '')), '$.is_commercial') AS is_commercial,
    gcs_uri
  FROM ML.GENERATE_TEXT(
    MODEL `my_project.my_dataset.gemini_38_flash`,
    TABLE candidate_observations,
    STRUCT(0.1 AS temperature, TRUE AS flatten_json_output)
  );
  ```

- **Benefits**: BigQuery ML automatically preserves and streams all input columns through to the output relation alongside `ml_generate_text_llm_result`, completely eliminating secondary joins and simplifying production SQL pipelines.

### 3.7 BigQuery `AI.GENERATE` Model Params Contract & `generationConfig` Requirement

- **The `model_params` Contract**: In BigQuery Standard SQL `AI.GENERATE(prompt, endpoint => '...', model_params => JSON '...')`, the `model_params` argument expects a JSON string strictly conforming to the Vertex AI / Gemini API `generateContent` REST request body schema (`https://ai.google.dev/api/generate-content`).
- **The Top-Level Parameter Pitfall**: Passing sampling hyperparameters directly at the top level of `model_params` (e.g., `model_params => JSON '{"temperature": 0.2}'`) causes an immediate runtime execution failure:
  ```text
  The model_params is invalid and does not conform to the GenerateContent request body https://ai.google.dev/api/generate-content. Please check the model_params input.
  ```
- **Canonical Schema Structure**: Hyperparameters (`temperature`, `maxOutputTokens`, `topP`, `topK`, `stopSequences`, `responseMimeType`, `responseSchema`) **MUST** be nested inside `generationConfig`:
  ```sql
  -- Correct: nested under generationConfig
  AI.GENERATE(
    prompt,
    endpoint => 'gemini-2.5-flash',
    model_params => JSON '{"generationConfig": {"temperature": 0.2}}'
  )
  ```
  When combining tools (such as Google Maps or Google Search Grounding) with sampling parameters:
  ```sql
  -- Correct: tools and generationConfig side-by-side
  AI.GENERATE(
    prompt,
    endpoint => 'gemini-2.5-flash',
    model_params => JSON '{"tools": [{"googleMaps": {}}], "generationConfig": {"temperature": 0.2}}'
  )
  ```
- **The Dry-Run Validation Blindspot**: `bq query --dry_run` verifies query syntax, table existence, and column types, but **does not parse or validate the inner JSON schema of `model_params`**. An invalid JSON structure passes `--dry_run` with 0 bytes and fails only upon physical query execution. Always execute a live 1-row test query when authoring custom `model_params`.
- **Compile-Time Literal Constraint & The Decoupled Semantic Combo Index Pattern**:
  - The BigQuery GoogleSQL compiler strictly requires that `endpoint` and `model_params` in `AI.GENERATE` be **constant string/JSON literals or query parameters** (`Argument 'endpoint' / 'model_params' to BIGQUERYGOOGLESQL:AI.GENERATE must be a literal or query parameter`). You **cannot** dynamically pass column references (e.g. `endpoint => c.model_endpoint` or `model_params => c.params`) from a joined table.
  - **The Friction with Sequential Integer IDs**: Declaring configuration rows with sequential integers (`config_id: 1, 2, 3...`) forces tedious manual renumbering across both the `configs` CTE and the dispatch `CASE c.config_id` statement whenever options are added, pruned, or reordered.
  - **The Decoupled Semantic Combo Index Pattern**: Declare `config_id` as a composite semantic string: `<model>|<grounding_mode>|<temperature>`:
    ```sql
    WITH configs AS (
      SELECT 'gemini-3.8-flash|UNGROUNDED|0.2' AS config_id, 'gemini-3.8-flash' AS model, 'UNGROUNDED' AS mode, 0.2 AS temp
      UNION ALL SELECT 'gemini-3.8-flash|GOOGLE_MAPS|0.2', 'gemini-3.8-flash', 'GOOGLE_MAPS', 0.2
      UNION ALL SELECT 'gemini-3.1-pro-preview|GOOGLE_MAPS|0.2', 'projects/my-project/locations/global/publishers/google/models/gemini-3.1-pro-preview', 'GOOGLE_MAPS', 0.2
      UNION ALL SELECT 'gemini-3.8-flash|GOOGLE_MAPS|0.0', 'gemini-3.8-flash', 'GOOGLE_MAPS', 0.0
    ),
    benchmark_runs AS (
      SELECT
        c.*,
        CASE c.config_id
          WHEN 'gemini-3.8-flash|UNGROUNDED|0.2' THEN AI.GENERATE(
            p.content,
            endpoint => 'gemini-3.8-flash',
            model_params => JSON '{"generationConfig": {"temperature": 0.2, "seed": 42, "maxOutputTokens": 800, "mediaResolution": "MEDIA_RESOLUTION_HIGH"}}'
          )
          WHEN 'gemini-3.8-flash|GOOGLE_MAPS|0.2' THEN AI.GENERATE(
            p.content,
            endpoint => 'gemini-3.8-flash',
            model_params => JSON '{"tools": [{"googleMaps": {}}], "generationConfig": {"temperature": 0.2, "seed": 42, "maxOutputTokens": 800, "mediaResolution": "MEDIA_RESOLUTION_HIGH"}}'
          )
          WHEN 'gemini-3.1-pro-preview|GOOGLE_MAPS|0.2' THEN AI.GENERATE(
            p.content,
            endpoint => 'projects/my-project/locations/global/publishers/google/models/gemini-3.1-pro-preview',
            model_params => JSON '{"tools": [{"googleMaps": {}}], "generationConfig": {"temperature": 0.2, "seed": 42, "maxOutputTokens": 800, "mediaResolution": "MEDIA_RESOLUTION_HIGH", "thinkingConfig": {"thinkingBudget": 1024}}}'
          )
          WHEN 'gemini-3.8-flash|GOOGLE_MAPS|0.0' THEN AI.GENERATE(
            p.content,
            endpoint => 'gemini-3.8-flash',
            model_params => JSON '{"tools": [{"googleMaps": {}}], "generationConfig": {"temperature": 0.0, "seed": 42, "maxOutputTokens": 800, "mediaResolution": "MEDIA_RESOLUTION_HIGH"}}'
          )
        END AS res
      FROM prompt_table p
      CROSS JOIN configs c
    )
    ```
    **Key Architectural Advantage**: Because BigQuery's query optimizer short-circuits scalar `CASE` expressions per row, any branch in `benchmark_runs` that is not joined from `configs` is never executed. Developers can prune or filter configurations simply by commenting out lines in `configs`—**zero renumbering and zero CASE editing required**, while the resulting output table displays self-explaining, alphabetically sortable identifiers.

### 3.8 BigQuery AI / Multimodal Latency Engineering & `GenerationConfig` Rules

When executing large-scale BigQuery ML and `AI.GENERATE` queries over multimodal sensor data (imagery, text, embeddings), latency spikes are dominated by three primary factors:

1. **The Latency Contributors (Ranked by Impact)**:
   - **`thinkingConfig` (`thinkingBudget: 1024`) (+10s to 25s/call)**: For reasoning models (`gemini-2.5-pro`, `gemini-3.1-pro-preview`), setting a thinking budget generates hundreds of hidden Chain-of-Thought reasoning tokens before emitting output. Use only for complex spatial/mathematical deductions; avoid in interactive pipelines.
   - **External Tool Grounding (`googleMaps` / `googleSearch`) (+2s to 5s/call)**: Triggers an agentic loop: Pass 1 (generate search query) $\to$ external HTTPS RPC to Google Maps/Search backend $\to$ chunk injection $\to$ Pass 2 (grounded synthesis). Inherently triples end-to-end wall-clock latency per row.
   - **Combinatorial Multi-Model Cross-Joins & Quota Queueing (Multiplies total elapsed time by 10x+)**: Firing 10+ models across rows quickly saturates project Vertex AI quotas (RPM/TPM). BigQuery connections apply exponential retry backoff, causing queries to queue.
   - **`mediaResolution: "MEDIA_RESOLUTION_HIGH"` (+200ms to 800ms/image)**: Generates extra visual patches and tokens for fine-grained OCR (e.g. reading distant road signs), slightly increasing vision transformer prefill latency.

2. **Parameter Compatibility & Syntax Integrity Constraints**:
   - **`thinkingBudget` Model Compatibility**: Thinking is **strictly supported only on Pro reasoning models**. Passing `thinkingBudget` to Flash models (`gemini-3.8-flash`, `gemini-3.5-flash-lite`) triggers `INVALID_ARGUMENT: Thinking is not supported for this model`.
   - **`presencePenalty` & `frequencyPenalty` MUST Remain 0.0 for Structured JSON**: Penalizing token repetition degrades JSON schema compliance because valid JSON requires frequent repetition of standard structural tokens (`type`, `properties`, `box_2d`, `{`, `}`). Penalties induce missing close brackets and malformed JSON.
   - **`stopSequences` Redundancy**: In controlled generation (`output_schema` or `response_schema`), generation automatically stops at root object close `}`. Custom stop sequences are redundant and risk premature truncation if their delimiter appears in valid values.

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

- **Entity Identity Primary Clustering**: Every base table representing an entity type should be clustered primarily by its canonical entity-specific identity (e.g., `observations` by `observation_id`, `assets` by `asset_id`, `panos` by `pano_id`). Clustered primary keys ensure that entity point lookups and primary-key joins (`JOIN ... ON a.entity_id = b.entity_id`) are fast and cheap, scanning only the single micro-partition block where that identity resides.
- **Alternative Access Paths via `v_<entity>_by_<col>`**: When secondary columns also make sense as primary cluster keys (e.g. continuous spatial coordinates `location_geom`, categorical attributes `asset_type`, or parent keys `pano_id`), provide dedicated access paths using the canonical naming pattern `v_<entity>_by_<col>`.
- **Materialized View First, Logical View Fallback**:
  - Implement secondary access paths as **Materialized Views (`CREATE MATERIALIZED VIEW`)** whenever supported. This delivers dual benefits: 1-click **Cloud Console Preview tab** usability at zero query cost, and automatic query rewrites by the BigQuery optimizer.
  - If a required transformation is infeasible in a Materialized View (e.g., non-deterministic runtime functions like `CURRENT_TIMESTAMP()`, outer joins, window functions), fall back gracefully to a standard **Logical View (`CREATE VIEW`)**.
- **Standard Views Schema Bindings (`SELECT *` Caveat)**: Views using `SELECT *` evaluate schema at definition time. If new columns are added to base physical tables, standard views do NOT propagate them until replaced. Always explicitly list columns in view definitions.
- **Cloud Console Usability (1-Click Data Preview)**: Standard logical views (`CREATE VIEW`) do not provide a "Preview" tab in the BigQuery Cloud Console, forcing analysts to submit ad-hoc SQL queries simply to inspect sample rows. In contrast, **Materialized Views (`CREATE MATERIALIZED VIEW`) fully support the 1-click Preview tab** at zero query cost, exactly like physical base tables.
- **Primary Cluster Key Naming Standard (`v_<entity>_by_<cluster_key>`)**: When offering secondary clustered access paths via Materialized Views, adopt the suffix standard `v_<entity>_by_<cluster_key>` (e.g., `v_assets_by_location` vs. `v_assets_by_type`). This informs users and BI tools of the leading cluster key without requiring inspection of table DDL.
- **The Non-Deterministic Function Barrier & Query-Time Pushdown Pattern**:
  - BigQuery Materialized Views strictly prohibit non-deterministic time and context functions (`CURRENT_TIMESTAMP()`, `CURRENT_DATE()`, `SESSION_USER()`), throwing `Query error: Materialized view query cannot use functions that depend on current time`.
  - **Anti-Pattern**: Forcing an entire view to remain a standard logical view (`CREATE VIEW`) solely to expose a dynamic boolean flag (such as `is_active: CURRENT_TIMESTAMP() < expires_at`). This sacrifices the 1-click Cloud Console Preview tab, micro-partition block pruning, and automatic optimizer rewrites for all columns in that view.
  - **Canonical Solution (Query-Time Pushdown)**: Store the static threshold or expiration timestamp (e.g. `image_expires_at`) directly in the Materialized View (`v_<entity>_by_<col>`). End-users and analytical queries evaluate `WHERE expires_at > CURRENT_TIMESTAMP()` at query time. This preserves a **100% Materialized View consumption layer** across the entire public schema while maintaining exact runtime freshness.
- **DDL Type Migration Gate**: BigQuery does not allow replacing a logical view with a materialized view in place (`Invalid value: ... is currently a VIEW`). Migration scripts must explicitly drop the legacy object first (`DROP VIEW IF EXISTS ...; DROP MATERIALIZED VIEW IF EXISTS ...; CREATE MATERIALIZED VIEW ...;`).
- **Materialized View Silent Invalidation on Base Table Recreation (`IF NOT EXISTS` Hazard & Pre-emptive Drop Pattern)**:
  - When underlying physical base tables are deleted and recreated (e.g., during full table refreshes, schema migrations, or re-clustering in Dataform/dbt/Bash), BigQuery marks all dependent Materialized Views as permanently invalid:
    ```text
    Materialized view my_dataset.v_observations_by_location references table my_dataset.observations which was deleted and recreated. The view must be deleted and recreated as well.
    ```
  - **The Silent Invalidation Trap**: Idempotent DDL statements like `CREATE MATERIALIZED VIEW IF NOT EXISTS` **silently skip** existing objects because their name is present in the dataset catalog. The DDL reports success without repairing the broken binding, leaving the view permanently failing on read queries.
  - **Canonical Mitigation**: Pipeline DDL scripts must always execute explicit pre-emptive drop statements (`DROP MATERIALIZED VIEW IF EXISTS <mv_name>; DROP VIEW IF EXISTS <mv_name>;`) before `CREATE MATERIALIZED VIEW`, guaranteeing that Materialized Views are always rebuilt against the new base table instance.
- **Materialized Views on Arrays**: BigQuery Materialized Views prohibit complex array functions and `UNNEST` expressions. Use scheduled physical tables (Dataform/dbt) when nested array transformations are required.
- **Terraform Formatting on MVs**: Whitespace changes in `materialized_view` SQL force resource replacement. Ensure `deletion_protection = false` is declared on MV resources.

### 4.4 Analytics Hub Linked Dataset Materialization Constraints & Publisher Observability

- **Materialized Views Prohibition**: Creating Materialized Views directly on top of Analytics Hub shared/linked datasets is disallowed (`Can't create materialized view on linked dataset`).
- **Clustered Table Materialization Pattern**: Pre-aggregate high-cost queries from linked datasets into a writable target dataset using partitioned and clustered physical tables.
- **Multi-Region `SCHEMATA_REPLICAS` Deduplication**:
  - Querying `region-<loc>.INFORMATION_SCHEMA.SCHEMATA_REPLICAS` returns **all global replicas** of every dataset present in that region, not just the local replica.
  - Multi-region collectors must filter `WHERE LOWER(location) = LOWER('<loc>')` and inspect `replica_primary_assigned = TRUE` to distinguish primary datasets from secondary cross-region replicas.
- **Publisher Telemetry IAM Split (`SCHEMATA_LINKS` vs. `SHARED_DATASET_USAGE`)**:
  - On an Analytics Hub publisher host project, `roles/bigquery.metadataViewer` grants read access to `INFORMATION_SCHEMA.SCHEMATA_LINKS` (which lists linked subscriber project numbers and organizations), `TABLE_STORAGE`, and `PARTITIONS`, but returns `Access Denied` on `region-<loc>.INFORMATION_SCHEMA.SHARED_DATASET_USAGE`.
  - Querying `SHARED_DATASET_USAGE` (to observe subscriber query job counts and bytes processed against shared datasets) requires `bigquery.datasets.listSharedDatasetUsage` (granted via `roles/bigquery.resourceViewer` or `roles/bigquery.dataOwner` on the publisher host project). Multi-region metadata collectors should pre-wire `SHARED_DATASET_USAGE` queries across all active regions with a graceful fallback on `Access Denied` so downstream pipelines run cleanly before and after IAM elevation.

### 4.5 Upstream Change Propagation & Row Count Verification Guards

- **Row Count Guard Pattern**: When orchestrating multi-stage pipelines, verify the target table's row count against the source file/upstream segment count before skipping steps to prevent stale or truncated data from persisting across pipeline runs.

---

### 4.x Cross-Region Dataset Replication (DDL-only; Terraform workaround)
- **DDL**, run with `--location=<primary>`:
  - Add: ``ALTER SCHEMA `proj.ds` ADD REPLICA `us-east4` OPTIONS(location="us-east4")``
  - Drop: ``ALTER SCHEMA IF EXISTS `proj.ds` DROP REPLICA `us-east4` ``
  - There is **no** `IF NOT EXISTS`/`IF EXISTS` on the replica itself, only on the schema. So re-adding an existing replica fails.
- **Limits**:
  - One replica per location, and it can't be the primary location.
  - A replica can be added and then dropped only a limited number of times in the same location (4).
  - Replication into sub-regions of the primary multi-region isn't allowed.
  - Track progress with `INFORMATION_SCHEMA.SCHEMATA_REPLICAS.creation_complete`.
- **Terraform**: `hashicorp/google` (checked up to 8.4.0) has **no** replica argument on `google_bigquery_dataset`. The working pattern is `terraform_data` with `for_each = toset(var.region_replicas)`:
  - Put project, dataset, primary and replica locations in `input`, because destroy-time provisioners may only reference `self`.
  - `triggers_replace` on those same values.
  - A `local-exec` create provisioner runs `bq query --use_legacy_sql=false --location=<primary> 'ALTER SCHEMA ... ADD REPLICA ...'`, and a `when = destroy` provisioner runs `DROP REPLICA`.
  - Removing a location from the list drops only that replica.
  - Caveats: requires an authenticated `bq` on the runner, and replicas changed outside Terraform are not detected as drift.
- **Shell quoting in HCL**: wrap the SQL in single quotes inside the command string. Backticks inside double quotes are shell command substitution. Validate the location strings with a regex (`^[a-z][a-z0-9-]*[a-z0-9]$`) first, so interpolation is injection-safe.
- `google_bigquery_job` is **not** a good fit. Jobs are immutable and can't express the drop-on-removal lifecycle.

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

### 5.5 BigQuery CLI Gotchas, Dataset Metadata & Console Markdown DDL

- **Regional Flag (`--location`)**: Always explicitly supply `--location=<region>` (e.g. `--location=asia-northeast1`) to avoid cross-region query dispatch failures (`Not found: Table ... in location US`).
- **Load Replace vs Clustering**: `bq load --replace` with modified `--clustering_fields` fails with an incompatible specification error. Drop the table first before loading with new clustering fields.
- **Markdown in Descriptions**: BigQuery Console parses GitHub-Flavored Markdown in dataset, table, and column descriptions. Wrap strings in triple double-quotes (`"""..."""`) in DDL statements to preserve formatting.
- **Dataset-Level (`SCHEMA`) Descriptions Are Never Set by Table Operations**: `bq load`, `CREATE OR REPLACE TABLE`, and `ALTER TABLE ... SET OPTIONS(description = ...)` only populate table-level metadata and leave the parent dataset (`SCHEMA`) description blank (`NULL`). Pipelines that auto-create datasets must explicitly pass `--description` on `bq mk --dataset` / `bq update --dataset --description "..." project:dataset` or run SQL DDL:

  ```sql
  ALTER SCHEMA `my_project.my_dataset`
  SET OPTIONS (
    description = """Authoritative domain dataset summary, lineage, and attribution."""
  );
  ```

- **Auditing Blank Dataset Descriptions (`INFORMATION_SCHEMA.SCHEMATA_OPTIONS`)**: Apply dataset/table descriptions *before* running automated Data Quality (DQ) gates, and verify both dataset and table catalog descriptions in the DQ gate. Note two SQL gotchas when auditing dataset descriptions across a project:
  1. Use `STARTS_WITH(s.schema_name, 'prefix_')` instead of `LIKE 'prefix_%'` because `_` is a single-character wildcard in SQL `LIKE` (matching `prefixstats`).
  2. `SCHEMATA_OPTIONS.option_value` stores string literals wrapped in double quotes (e.g. `"\"...\""`), so check both `IS NULL` and trimmed empty strings:

  ```sql
  SELECT
    s.schema_name,
    s.location,
    o.option_value AS raw_description
  FROM `my_project`.INFORMATION_SCHEMA.SCHEMATA AS s
  LEFT JOIN `my_project`.INFORMATION_SCHEMA.SCHEMATA_OPTIONS AS o
    ON s.catalog_name = o.catalog_name
   AND s.schema_name = o.schema_name
   AND o.option_name = 'description'
  WHERE STARTS_WITH(s.schema_name, 'domain_')
    AND (o.option_value IS NULL OR TRIM(o.option_value, '" ') = '')
  ORDER BY s.schema_name;
  ```

---

## 6. Field Lessons: Recovery, Pipeline Hygiene & CLI Gotchas
* **Layout, pruning verification and vector-SQL gotchas → [layout_pruning_and_sql_gotchas.md](references/layout_pruning_and_sql_gotchas.md):**
  * Prove a missing partition or cluster with a **real run**: billed bytes plus input `records_read`. Dry runs ignore cluster pruning, and `LIMIT` stops early.
  * Partitioning costs about one block per partition on all-month point lookups. Unpartitioned `CLUSTER BY id, date` wins for per-entity time series.
  * Clustering by a Hilbert-ordered INT64 (S2) key prunes `ST_INTERSECTSBOX` on a separate GEOGRAPHY column for free.
  * Dynamic `IN (SELECT …)` predicates and filters through joins do not prune clusters.
  * Fixes for: epsilon dimension for zero-vector cosine; no `SAFE.ML.DISTANCE`; `cos` is a reserved UDF name; correlated subqueries in `INSERT … SELECT`; `NOT IN UNNEST` is O(n²); cross joins from parallel arrays; DML bills the whole table; lowercase label values.
  * Single-scan `LAG()` change tables, and excluding `SCRIPT` parent jobs when summing spend.
* **Regional `INFORMATION_SCHEMA` Scoping (`region-<loc>.INFORMATION_SCHEMA.*`):** Querying `` `project`.INFORMATION_SCHEMA.COLUMNS `` searches the default multi-region (typically `US`) and returns 0 hits for regional datasets (e.g. `asia-northeast1`, `europe-west1`). When inspecting schemas, tables, or column metadata for regional datasets, always qualify with the explicit regional prefix:
  ```sql
  SELECT table_schema, table_name, column_name, data_type
  FROM `my-project`.`region-asia-northeast1`.INFORMATION_SCHEMA.COLUMNS
  WHERE table_schema = 'poc_dataset';
  ```
* **Google Sheets External Table Header Offset Hazard:** When wrapping a Google Sheet with a BigQuery external table (`googleSheetsOptions`), combining `skipLeadingRows: 1` with a range starting on the first data row (e.g., `range: "A2:I341"`) causes BigQuery to treat Row 2 as a header and silently drop it, resulting in an off-by-one row loss (e.g. 339 rows instead of 340). Either specify `range: "A1:..."` with `skipLeadingRows: 1` (skipping the true title row), OR specify `range: "A2:..."` with `skipLeadingRows: 0`.
* **Recover overwritten tables with time travel:** `SELECT ... FROM t FOR SYSTEM_TIME AS OF TIMESTAMP('...')`, within the time-travel window (default 7 days). Use it to compare "before vs after" without keeping permanent backup tables.
* **Recover SQL that was never committed:** query `region-<loc>.INFORMATION_SCHEMA.JOBS` (`query`, `destination_table`, `creation_time`) for the exact statement that built a live table. Then write it back into the repo so the repo and the live tables match.
* **Find who overwrote a table:** filter `INFORMATION_SCHEMA.JOBS` on `destination_table.table_id` and order by `creation_time`.
* **Materialize iterative steps:** for pointer-doubling and other self-join iterations, write each pass to a table. Don't nest `s0 -> s8` in one CTE chain: BigQuery inlines the CTEs and the query either times out or exceeds resources.
* **`bq` CLI flag order:** `--parameter=name::value` and other flags must come **before** the SQL argument. Otherwise you get "FATAL Flags positioning error".
* **Rule changes vs. data changes in issue feeds:** version detection rules (`rule_version`). When a rule changes, mark rows that are no longer produced `RETIRED_RULE_CHANGE`, never `FIXED_UPSTREAM`. Mark false positives caused by your own pipeline `RETRACTED_PIPELINE_BUG`. Only compare like-for-like rule versions across snapshots.
* **Correlated Scalar Subqueries in `UPDATE ... SET` Reject `ORDER BY ... LIMIT 1`:** BigQuery Standard SQL rejects `ORDER BY ... LIMIT 1` inside a correlated scalar subquery in an `UPDATE ... SET col = (SELECT s.val FROM source s WHERE s.key = t.key ORDER BY s.ts DESC LIMIT 1)` statement with `HTTP 400: Correlated subquery with ORDER BY and LIMIT is not supported`. Instead, either pre-aggregate in a `FROM` clause (`UPDATE target t SET col = s.val FROM (SELECT key, ARRAY_AGG(val ORDER BY ts DESC LIMIT 1)[OFFSET(0)] AS val FROM source GROUP BY key) s WHERE t.key = s.key`) or use an un-ordered aggregate scalar subquery (`(SELECT ANY_VALUE(s.val) FROM source s WHERE s.key = t.key)`).
* **Preserve Derived Warehouse Columns Across Partition-Decorator `WRITE_TRUNCATE` Loads:** Loading a daily partition via `table$YYYYMMDD` with `WRITE_TRUNCATE` from an upstream extractor replaces the partition rows using only the extractor's payload columns, leaving derived columns added via `ALTER TABLE ADD COLUMN` (e.g., `project_type`) `NULL` on the newly loaded partition. Always follow partition-decorator `WRITE_TRUNCATE` loads with an idempotent `UPDATE ... FROM` backfill step, and resolve `MAX(snapshot_date)` independently per table when joining multi-table partitioned snapshots so asynchronous table refreshes never produce `0`-row joins.

## References

### Official Google Cloud Documentation

- **Partitioning & Clustering**:
  - [BigQuery Partitioned Tables Guide](https://cloud.google.com/bigquery/docs/partitioned-tables)
  - [BigQuery Clustered Tables Guide](https://cloud.google.com/bigquery/docs/clustered-tables)
  - [Table Sampling (`TABLESAMPLE SYSTEM`)](https://cloud.google.com/bigquery/docs/table-sampling)
  - [Table Constraints (Primary & Foreign Keys `NOT ENFORCED`)](https://cloud.google.com/bigquery/docs/table-constraints)
- **Storage & Billing**:
  - [BigQuery Storage Billing Models (Physical vs. Logical)](https://cloud.google.com/bigquery/docs/storage-billing-models)
- **Programmability & Streaming**:
  - [BigQuery Storage Write API](https://cloud.google.com/bigquery/docs/write-api)
  - [BigQuery Continuous Queries](https://cloud.google.com/bigquery/docs/continuous-queries-introduction)
  - [Table-Valued Functions (TVFs)](https://cloud.google.com/bigquery/docs/table-functions)
  - [User-Defined Functions (UDFs)](https://cloud.google.com/bigquery/docs/user-defined-functions)
  - [Remote Functions with Cloud Run](https://cloud.google.com/bigquery/docs/remote-functions)
- **Machine Learning & AI Search**:
  - [BigQuery ML Introduction](https://cloud.google.com/bigquery/docs/bqml-introduction)
  - [BigQuery Vector Search (`VECTOR_SEARCH`)](https://cloud.google.com/bigquery/docs/vector-search)
  - [BigQuery Search Indexes (`CREATE SEARCH INDEX`)](https://cloud.google.com/bigquery/docs/search-index)
- **Security, Governance & Observability**:
  - [Row-Level Security Overview](https://cloud.google.com/bigquery/docs/row-level-security-intro)
  - [Column-Level Security & Dynamic Data Masking](https://cloud.google.com/bigquery/docs/column-data-masking-intro)
  - [Query Execution Plan Diagnostics](https://cloud.google.com/bigquery/docs/query-plan-explanation)
  - [`INFORMATION_SCHEMA` Overview](https://cloud.google.com/bigquery/docs/information-schema-intro)

### Local Schemas & Helper Scripts

- [jobs.json](references/table_schema/jobs.json): Schema for `INFORMATION_SCHEMA.JOBS`.
- [partitions.json](references/table_schema/partitions.json): Schema for `INFORMATION_SCHEMA.PARTITIONS`.
- [tables.json](references/table_schema/tables.json): Schema for `INFORMATION_SCHEMA.TABLES`.
- [views.json](references/table_schema/views.json): Schema for `INFORMATION_SCHEMA.VIEWS`.
- [generate_job_id.sh](scripts/generate_job_id.sh): Standardized Job ID generation helper script.
- [estimate_query_cost.sh](scripts/estimate_query_cost.sh): Query byte scan cost calculator.
- [bigquery_practices_helpers.sh](scripts/bigquery_practices_helpers.sh): Bash wrapper functions for BigQuery query dispatch and label formatting.
- [bench_table_layouts.sh](scripts/bench_table_layouts.sh): Physical layout A/B benchmark harness (`--nouse_cache` + `INFORMATION_SCHEMA.JOBS_BY_USER` billed bytes and Input-stage `records_read`), S2 Hilbert leaf-range predicate generator (`build_s2_covering_range_sql`), and zero-vector-safe cosine distance helper (`build_safe_cosine_distance_expr`).

## Related Skills

- **[`bigquery-geospatial`](../bigquery-geospatial/SKILL.md)**: Advanced BigQuery GIS capabilities (`GEOGRAPHY` types, S2 indexing, and CARTO H3/Quadbin toolbox).
- **`bigquery-saved-queries`**: Managing persistent queries and Dataform SQLX pipelines.
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
