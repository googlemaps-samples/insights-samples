---
name: rmi-data-realtime-pubsub
description: Use this skill for technical details about the RMI Real-Time Pub/Sub stream, including message schema (Protobuf), key fields (SRIs, travel_duration), and integration patterns for live traffic operations.
---

# RMI Real-Time Data (Pub/Sub)

This skill provides the comprehensive technical specifications, schema definitions, and production-grade ingestion patterns for the Roads Management Insights (RMI) Real-Time data stream delivered via Google Cloud Pub/Sub. This low-latency message stream is optimized for live dashboard updates, real-time routing adjustments, and automated incident dispatch pipelines.

---

## 1. Pub/Sub Architecture & Authentication

### Dynamic Topic Topology
The standard RMI real-time stream is published to a dedicated publisher topic:
`projects/maps-platform-roads-management/topics/rmi-roadsinformation-PROJECT_NUMBER`
*   **PROJECT_NUMBER**: The unique numerical identifier of the customer's Google Cloud project.
*   **Permissions Required**: The service account reading from the subscription must hold the **Pub/Sub Subscriber** (`roles/pubsub.subscriber`) and **Pub/Sub Viewer** (`roles/pubsub.viewer`) roles on the local subscription resource.

---

## 2. Protobuf Schema Specification (Source of Truth)

The telemetry payloads are serialized using **Protocol Buffers (proto3)**. The exact message types, field definitions, and options are declared in the schema file, which acts as the absolute single source of truth. Refer directly to this compilable definition:

*   *Schema Source of Truth:* [roads_information.proto](references/schemas/roads_information.proto)

### Payload Constraints & Nullability Rules in Proto3
In proto3, fields are never "nullable" in the traditional database sense; instead, missing or unset fields revert to their type-specific zero-value defaults. Under RMI, you must enforce the following semantic expectations when validating incoming payloads:
*   **`selected_route_id`**: **Required**. Must never be empty (`""`). Must match `^[a-zA-Z0-9-]+$` and be 4 to 63 characters in length.
*   **`display_name`**: Optional. If unset, defaults to empty string `""`.
*   **`travel_duration`**: Optional message field. If routing calculations completely failed, this message block will be omitted (i.e. `has_travel_duration() == false`).
    *   ↳ **`duration_in_seconds`**: Must be `>= 0.0`.
    *   ↳ **`static_duration_in_seconds`**: Must be `> 0.0`.
*   **`speed_reading_intervals`**: Repeated field (array). Can contain `0` to many elements. An empty list indicates no speed reading warnings are active.
    *   ↳ **`interval_coordinates`**: Repeated field (array) containing `latitude` and `longitude` float coordinates within the speed reading interval.
    *   ↳ **`speed`**: Always resolves to `NORMAL`, `SLOW`, or `TRAFFIC_JAM`.
*   **`retrieval_time`**: **Required**. Custom `Timestamp` message representing when the observation was compiled. Contains `seconds` and `nanos`. In a direct BigQuery subscription, this maps to a nested `RECORD` column with `seconds` and `nanos` fields.
*   **`route_geometry`**: Optional. If routing failed, defaults to empty string `""`. Contains a GeoJSON string.

---

## 3. Direct BigQuery Subscription Ingestion (No-Code Integration)

For a fully managed, serverless, no-code ingestion pipeline, Google Cloud Pub/Sub allows subscribing directly to a topic and landing messages straight into a BigQuery table using a **BigQuery Subscription**.

### Schema Alignment (Source of Truth)
When configuring the subscription, you must use a BigQuery table that perfectly aligns with the Protobuf payload fields as well as standard Pub/Sub delivery metadata. Do not define the fields in an ad-hoc fashion. Use the official schema definition:

*   *BigQuery Landing Schema:* [roads_information_landing.json](references/tables/roads_information_landing.json)
*   *BigQuery Landing Table DDL:* [create_roads_information_landing.sql](references/queries/create_roads_information_landing.sql)

### Key Subscription Configuration Settings
To set up direct-to-BigQuery ingestion using this schema:
1.  **Delivery Type**: Select **Write to BigQuery**.
2.  **Target Table**: Point to your target BigQuery table created using the schema above.
3.  **Use Topic Schema**: Check this option. When enabled, Pub/Sub automatically deserializes the incoming Protocol Buffer messages and maps the fields directly to the corresponding columns in the BigQuery table.
4.  **Write Metadata**: Check this option. Checking this allows Pub/Sub to automatically populate the metadata fields: `subscription_name`, `message_id`, `publish_time`, and `attributes` into your BigQuery table.
5.  **Drop Unknown Fields**: Ensure this is unchecked to prevent data loss if any optional fields are added in future schema updates, or checked if you strictly enforce the declared schema.

### Automating Subscription Creation (gcloud CLI)
To automate IAM role provisioning and subscription creation programmatically, you can run the pre-configured deployment script:

*   *Subscription Provisioning Script:* [create_pubsub_bq_subscription.sh](scripts/create_pubsub_bq_subscription.sh)

This script performs the following critical tasks:
1.  Grants the necessary dataset/table write permissions (`roles/bigquery.dataEditor` and `roles/bigquery.metadataViewer`) to the Google-managed Pub/Sub service account (`service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com`).
2.  Executes the `gcloud pubsub subscriptions create` command with `--use-topic-schema` and `--write-metadata` toggles enabled.


### Partitioning & Clustering for Cost Optimization
Since real-time telemetry generates massive, continuous streams of telematic data (scaling to terabytes and hundreds of millions of rows), optimizing the physical layout of the landing table is critical to maintain fast response times and control query scanning costs.

*   **Time Partitioning (Daily on `partitioning_ts` or `publish_time`)**:
    *   **Recommendation**: Configure **Daily Partitioning** on a dedicated event-time timestamp column (such as **`partitioning_ts`** derived from the nested `retrieval_time.seconds` via an ingestion parser/transformer) or on Pub/Sub's native top-level **`publish_time`**.
    *   **Engineering Rationale**: Most traffic operational queries and ELT pipelines are time-bounded (e.g., retrieving the last 4 hours of data or processing new records incrementally). By partitioning the table, BigQuery prunes scans to the targeted days only, reducing query scan costs from terabytes (full table scan) to mere megabytes or gigabytes.
    *   **Example Query Pattern**: Downstream queries and standard views must filter on the partition column:
        ```sql
        WHERE partitioning_ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
        ```
*   **Clustering (Clustered by `selected_route_id`)**:
    *   **Recommendation**: Cluster the landing table by **`selected_route_id`**.
    *   **Engineering Rationale**: Since telematic telemetry is primarily queried, filtered, or joined on a per-route basis (e.g., pulling chronological timelines or calculating bottlenecks for a specific monitored route), clustering forces BigQuery to physically sort and co-locate data blocks containing the same `selected_route_id` within each daily partition. This results in incredibly fast, highly pruned, and low-cost reads.

---

## 4. Operational Best Practices

### At-Least-Once Delivery & Deduplication
Cloud Pub/Sub guarantees at-least-once message delivery. Duplicates are rare but can occur during network blips or client acknowledgements timeouts.
*   **Idempotency Strategy**: Always use the combination of `selected_route_id` and `retrieval_time` (specifically the `seconds` value) as a composite unique key to deduplicate incoming events in your downstream databases.

### Backpressure & Streaming Pull Tuning
High-frequency streams containing hundreds of routes require optimal consumer settings. Use Pub/Sub's **Streaming Pull** API with flow control to prevent overwhelming your ingestion workers:
*   `max_outstanding_messages`: Restrict the number of unacknowledged messages currently in-flight.
*   `max_outstanding_bytes`: Manage memory limits of the container processing the stream.

---

## 5. Troubleshooting & Operational Recovery

| Issue / Symptom | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **`PermissionDenied` (403) on Subscription** | Subscriber service account lacks IAM permissions. | Grant `roles/pubsub.subscriber` on the subscription resource to your client service account. |
| **Ingestion Worker Memory Crash** | Large bursts of messages causing out-of-memory. | Implement Pub/Sub Flow Control limits. Reduce `max_outstanding_messages` to `100` or `500` per worker thread. |
| **Accumulated unacknowledged messages (Backpressure)** | Ingest worker processing duration is exceeding the subscription's `ack_deadline_seconds`. | Increase the acknowledgement deadline (default is 10s; recommend setting to 60s) or optimize callback database write latency. |
| **Duplicate processing of identical telemetry** | Redelivery because processing took longer than `ack_deadline_seconds`. | Always acknowledge (`message.ack()`) messages **after** inserting them into a fast memory cache (e.g. Redis), but before performing long-running spatial analysis. |

---

## 6. References
* [Google Maps Platform - Roads Management Insights Overview](https://developers.google.com/maps/documentation/roads-management-insights/overview)
* [Google Maps Platform - RMI Guidelines & Governance](https://developers.google.com/maps/documentation/roads-management-insights/guidelines)
* [Google Maps Platform - RMI Real-Time Data](https://developers.google.com/maps/documentation/roads-management-insights/real-time-data)

---

## 7. Production Ingestion Pattern

### Python Client (Streaming Pull with Flow Control & BigQuery Loading)
For customized, high-performance, or hybrid subscriber deployments, you can deploy a custom streaming subscriber daemon to consume, deduplicate, and load the RMI telemetry payloads:

*   *Custom Python Ingest Client:* [consume_and_stream_to_bq.py](scripts/consume_and_stream_to_bq.py)

This production-grade script implements:
1.  **Asynchronous Streaming Pull** via `google-cloud-pubsub` utilizing subscriber callback frameworks.
2.  **Adaptive Backpressure Flow Control** bounding memory and in-flight limits.
3.  **Hybrid Deserialization** decoding both raw JSON string inputs and compiled binary Protobuf payloads.
4.  **High-performance Streaming Insertions** into BigQuery via `google-cloud-bigquery` streaming tables.
5.  **Bounded Deduplication Filtering** utilizing a rolling in-memory cache on composite `(selected_route_id, retrieval_time)` keys.

---

## 8. Downstream SQL Translation to Recent Roads Data Layout

While landing the Pub/Sub payloads directly as-is preserves the unedited Protobuf structure, downstream analytical apps and spatial visualization engines (such as Deck.gl) operate much more efficiently when timestamps are parsed into single native `TIMESTAMP` columns and the coordinate sequences are expressed directly as standard `GEOGRAPHY` polyline structures.

To bridge this gap cleanly, reference the production DDL, ELT SQL translation query, and corresponding target schema definition:

*   *Target Table DDL:* [create_recent_roads_data.sql](references/queries/create_recent_roads_data.sql)
*   *SQL Translation Query:* [translate_landing_to_recent_roads.sql](references/queries/translate_landing_to_recent_roads.sql)
*   *Transformed Table Schema:* [recent_roads_data_transformed.json](references/tables/recent_roads_data_transformed.json)

These files provide a robust and reusable blueprint for table provisioning, pipeline orchestration (e.g., inside Dataform or dbt), or on-the-fly transformations via standard logical views.

---

## 9. Architectural Alternatives to Materialized Views: The "Translated Table" Strategy

While **BigQuery Materialized Views** offer automated incremental maintenance, they are **unsuitable** for this specific real-time transformation. BigQuery strictly prohibits the use of `UNNEST` (array flattening), complex subqueries, and structural array reconstructions (`ARRAY(SELECT AS STRUCT ...)`) inside materialized view definitions. 

To achieve a production-grade, optimized downstream table layout, you must implement a **"Translated Table"** strategy. Below are the detailed options, architectural trade-offs, and exact code implementations to translate the raw landing schema into the optimized `recent_roads_data` structure.

---

### Option A: Standard Logical Views with Partition Pruning (Zero Operations, Live Reads)

*   **Mechanism**: Expose a standard SQL logical view (`CREATE VIEW`) using the [translate_landing_to_recent_roads.sql](references/queries/translate_landing_to_recent_roads.sql) query directly over the raw landing table.
*   **Pros**:
    *   **Zero Infrastructure**: Completely serverless; no scheduled pipelines, orchestrators, or cron jobs to monitor.
    *   **True Real-Time**: Downstream users see newly landed messages instantly as they arrive.
    *   **No Duplicate Storage**: Saves storage cost by avoiding physical replication of the parsed structures.
*   **Cons**:
    *   **On-Demand Compute Cost**: Every query on the view re-evaluates complex array parsing and GeoJSON geometry conversions, increasing slot usage for high-frequency reads.
*   **Implementation Guideline**:
    *   Downstream queries **must** filter on the partition column (`publish_time`) to ensure that partition pruning propagates down to the raw landing table:
        ```sql
        SELECT * FROM `my_project.rmi_realtime.recent_roads_view`
        WHERE publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR);
        ```

---

### Option B: The "Translated Table" via BigQuery SQL MERGE (Lightweight Scheduled Pipeline)

*   **Mechanism**: Maintain `recent_roads_data` as a physical table. Set up a **BigQuery Scheduled Query** or trigger a SQL script on a cron schedule (e.g., every 5 to 15 minutes) that executes a robust `MERGE` statement.
*   **Production MERGE Query Files & Deployers**:
    *   *Scheduled Merge Query Script:* [scheduled_merge_recent_roads.sql](references/queries/scheduled_merge_recent_roads.sql)
    *   *Automated Query Scheduling Script:* [schedule_merge_query.sh](scripts/schedule_merge_query.sh)
*   **Deduplication & Watermarking**:
    *   **Deduplication**: Pub/Sub guarantees at-least-once delivery, which can result in duplicate payloads. We use `ROW_NUMBER() OVER (PARTITION BY selected_route_id, retrieval_time.seconds ORDER BY publish_time DESC)` to ensure we only process the latest message per route/time combination.
    *   **Watermarking**: To avoid scanning the entire landing table on every run, the query uses a **1-hour rolling watermark lookback** (`publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)`). This window captures newly arrived telemetry and late-arriving messages without full table scans, merging updates seamlessly.
*   **Robust DDL & SQL MERGE Script**:
    ```sql
    MERGE `my_project.rmi_realtime.recent_roads_data` T
    USING (
      WITH raw_dedup AS (
        SELECT
          selected_route_id,
          display_name,
          -- Reconstruct UTC timestamp with microsecond precision
          TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND) AS record_time,
          travel_duration.duration_in_seconds AS duration_in_seconds,
          travel_duration.static_duration_in_seconds AS static_duration_in_seconds,
          SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
          road_segment_ids,
          speed_reading_intervals,
          publish_time,
          ROW_NUMBER() OVER (
            PARTITION BY selected_route_id, retrieval_time.seconds 
            ORDER BY publish_time DESC
          ) AS rn
        FROM
          `my_project.rmi_realtime.roads_information_landing`
        WHERE
          -- Watermark: Restrict to last 1 hour of landed data to minimize scan costs
          publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
      )
      SELECT
        selected_route_id,
        display_name,
        record_time,
        duration_in_seconds,
        static_duration_in_seconds,
        route_geometry,
        road_segment_ids,
        ARRAY(
          SELECT AS STRUCT
            [ST_MAKELINE(ARRAY(
              SELECT ST_GEOGPOINT(CAST(coord.longitude AS FLOAT64), CAST(coord.latitude AS FLOAT64))
              FROM UNNEST(interv.interval_coordinates) AS coord
            ))] AS interval_coordinates,
            interv.speed AS speed
          FROM UNNEST(speed_reading_intervals) AS interv
        ) AS speed_reading_intervals
      FROM raw_dedup
      WHERE rn = 1
    ) S
    ON T.selected_route_id = S.selected_route_id AND T.record_time = S.record_time
    WHEN NOT MATCHED THEN
      INSERT (selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry, road_segment_ids, speed_reading_intervals)
      VALUES (selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry, road_segment_ids, speed_reading_intervals);
    ```

---

### Option C: The "Translated Table" via Dataform / dbt Incremental Models (Professional ELT)

*   **Mechanism**: Manage your ELT pipeline using **Dataform** or **dbt**. Configure the `recent_roads_data` model as an **incremental** table. The compiler automatically creates and runs the incremental merge logic on a schedule.
*   **Pros**:
    *   **Lowest Query Cost**: Downstream tools query a fully pre-computed physical table with native spatial types and index-ready layouts.
    *   **Quality Gates**: Easily integrate schema validations, unit tests, and deduplication assertions before materialization.
    *   **Version Control**: Complete pipeline code is tracked in Git with automated CI/CD deployment support.
*   **Cons**:
    *   **Processing Latency**: Introduces a data delay equal to your execution schedule interval (e.g., 15 minutes).
*   **Implementation Guideline (Dataform SQLX Example)**:
    ```sql
    config {
      type: "incremental",
      schema: "rmi_realtime",
      uniqueKey: ["selected_route_id", "record_time"],
      bigquery: {
        partitionBy: "DATE(record_time)",
        clusterBy: ["selected_route_id"]
      }
    }

    SELECT
      selected_route_id,
      display_name,
      TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND) AS record_time,
      travel_duration.duration_in_seconds,
      travel_duration.static_duration_in_seconds,
      SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
      road_segment_ids,
      ARRAY(
        SELECT AS STRUCT
          [ST_MAKELINE(ARRAY(
            SELECT ST_GEOGPOINT(CAST(coord.longitude AS FLOAT64), CAST(coord.latitude AS FLOAT64))
            FROM UNNEST(interv.interval_coordinates) AS coord
          ))] AS interval_coordinates,
          interv.speed
        FROM UNNEST(speed_reading_intervals) AS interv
      ) AS speed_reading_intervals
    FROM
      ${ref("roads_information_landing")}
    ${when(incremental(), `WHERE publish_time > (SELECT MAX(record_time) FROM ${self()})`)}
    ```

---

### Option D: Real-Time Streaming In-Memory Transformation (Continuous Ingest to Translated Table)

*   **Mechanism**: Bypass the intermediate raw landing table entirely. Run a custom streaming ingestion worker (e.g., **Apache Beam on Cloud Dataflow**, a microservice in **Cloud Run**, or a containerized daemon in **GKE**) that consumes messages from the Pub/Sub topic, transforms the payloads in-memory, and stream-writes the clean layout straight into `recent_roads_data`.
*   **Pros**:
    *   **True Real-Time Materialization**: Combines the sub-second latency of Option A with the pre-computed query performance of Option B/C.
    *   **Consolidated Pipeline**: Eliminates the raw landing table, storing only the optimized final result.
*   **Cons**:
    *   **Operational Overhead**: Requires deploying, scaling, and monitoring streaming computing resources.
*   **Implementation Blueprint**: Use Python's `google-cloud-pubsub` and `google-cloud-bigquery` libraries as implemented in [consume_and_stream_to_bq.py](scripts/consume_and_stream_to_bq.py) to parse coordinate sequences and structure spatial types prior to streaming ingestion.

---

## 10. Historical Partition-Pruned Backfilling

To maintain optimal cost controls, the periodic Scheduled Query (Option B) executes using a **1-hour rolling watermark** on the raw landing table (`publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)`). This scans only newly arrived telemetry (~1.2 million rows per hour) instead of scanning the full history of several hundred million rows on every single run.

When initializing the transformed table, historical raw records already present in the landing table must be migrated using a one-time backfill.

### Optimized Daily Loop Pattern
Because the source table is partitioned daily on `partitioning_ts`, historical records can be backfilled safely and cheaply by running a day-by-day loop that enforces strict partition pruning.

The automation script [backfill_recent_roads.sh](scripts/backfill_recent_roads.sh) provides a production-grade implementation of this pattern.

#### Usage:
To backfill historical partitions day-by-day (e.g. from May 15 to June 12), run the script from the repository root:

```bash
PROJECT_ID="your-project-id" \
DATASET_ID="rmi" \
SOURCE_TABLE_ID="rmi_realtime_json" \
TARGET_TABLE_ID="recent_roads_data" \
./src/rmi-data-realtime-pubsub/scripts/backfill_recent_roads.sh "2026-05-15" "2026-06-12"
```

The script automatically:
1. Generates a list of target days portably.
2. Identifies partition boundaries and displays dry-run scanning sizes.
3. Issues a partition-pruned `MERGE` query for each individual day to avoid out-of-memory issues or excessive query scanning costs.
4. Uses traceable job IDs matching the workspace pattern (`rmi_realtime_backfill_<date>_<timestamp>`).





