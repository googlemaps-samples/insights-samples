---
name: rmi-data-realtime-pubsub
description: Use this skill for technical details about the RMI Real-Time Pub/Sub stream, including message schema (Protobuf), key fields (SRIs, travel_duration), linear speed offsets, and integration patterns for live traffic operations.
---

# RMI Real-Time Data (Pub/Sub)

This skill provides comprehensive technical specifications, schema definitions, and production-grade ingestion patterns for the Roads Management Insights (RMI) Real-Time data stream delivered via Google Cloud Pub/Sub. This low-latency message stream is optimized for live operational dashboards, dynamic routing adjustments, incident detection, and automated dispatch pipelines.

---

## 1. Pub/Sub Architecture & Authentication

### Dual Topic Topologies

Google Cloud Pub/Sub delivers RMI real-time road telemetry via dedicated publisher topics provisioned under the service project `maps-platform-roads-management`. Depending on your downstream ingestion pipeline, two encoding options are available:

1. **JSON Encoding Topic (Recommended for BigQuery Subscriptions)**:
   ```text
   projects/maps-platform-roads-management/topics/rmi-roadsinformation-PROJECT_NUMBER-json
   ```
   * **Best Practice for BigQuery**: When creating a direct-to-BigQuery Pub/Sub subscription, Google recommends subscribing to the `-json` topic with **Use table schema** and **Drop unknown fields** enabled. This simplifies schema evolution and avoids protobuf descriptor registration overhead.

2. **Binary Protobuf Topic**:
   ```text
   projects/maps-platform-roads-management/topics/rmi-roadsinformation-PROJECT_NUMBER
   ```
   * Delivers raw binary-serialized `RoadsInformation` Protocol Buffer messages. Recommended for custom streaming subscribers (e.g., Python, Go, Java, Apache Beam) requiring minimal serialization bandwidth and maximum throughput.

* **PROJECT_NUMBER**: The unique numerical identifier of the customer's Google Cloud project.
* **Permissions Required**: The service account or client reading from the subscription must hold the **Pub/Sub Subscriber** (`roles/pubsub.subscriber`) and **Pub/Sub Viewer** (`roles/pubsub.viewer`) roles on the local subscription resource.

---

## 2. Protobuf Schema Specification & Evolution (October 8, 2026)

The telemetry payloads are serialized using **Protocol Buffers (proto3)**. The compilable definition serves as the canonical single source of truth:

* *Schema Source of Truth:* [roads_information.proto](references/schemas/roads_information.proto)

### Schema Evolution & Deprecation Timeline

Effective **October 8, 2026** (last updated October 30, 2026), Google Maps Platform introduced an evolved RMI Real-Time schema:
* **Transition Window**: October 8, 2026 to January 13, 2027.
* **Deprecation Cutoff Date**: **January 13, 2027**. On or after this date, legacy fields (`speed_reading_intervals`, `travel_duration`, and `retrieval_time`) may stop being populated.
* **Migration Imperative**: All consumers should adopt top-level duration fields, RFC 3339 `retrieval_timestamp`, and distance offset-based speed readings (`speed_reading_offsets`).

### Summary of New Fields (Fields 8–12)

| Field # | Name | Protobuf Type | Semantic Description | Nullability / Omission Rule |
| :--- | :--- | :--- | :--- | :--- |
| **8** | `speed_reading_offsets` | `repeated SpeedReadingOffset` | Distance-offset based speed reading intervals along the route polyline. | **Omitted** when `has_road_closure == true`. |
| **9** | `duration_in_seconds` | `float` | Near real-time traffic-aware travel duration in seconds. | **Omitted** when `has_road_closure == true`. |
| **10** | `static_duration_in_seconds` | `float` | Traffic-unaware travel duration in seconds under free-flow conditions. | Always populated (`> 0.0`). |
| **11** | `retrieval_timestamp` | `string` | RFC 3339 formatted UTC timestamp string (e.g. `"2026-10-08T15:04:05+00:00"`). | Populated for all valid observations. |
| **12** | `has_road_closure` | `bool` | Flag indicating whether the monitored route is subject to a full road closure. | `false` if route is open; `true` if fully closed. |

### Submessage: `SpeedReadingOffset`

Replaces the legacy coordinate-array based `SpeedReadingInterval` with precise linear distance offsets along the route geometry:

```protobuf
message SpeedReadingOffset {
  // Starting offset from the beginning of the route in meters (inclusive).
  int32 start_offset = 1;
  // Ending offset from the beginning of the route in meters (exclusive; equals start_offset of subsequent interval).
  int32 end_offset = 2;
  // Categorized traffic speed condition.
  string speed = 3;
}
```

* **Linear Distance Offsets**: Expressed in whole meters from the route origin (`0`). The `end_offset` of an interval strictly equals the `start_offset` of the subsequent interval, ensuring contiguous coverage without gaps.
* **Speed Categories**:
  * `"NORMAL"`: Traffic is flowing smoothly (green).
  * `"SLOW"`: Slowdown detected, but free-flowing (yellow).
  * `"TRAFFIC_JAM"`: Moderate-to-heavy congestion (red).
  * `"TRAFFIC_JAM_HEAVY"`: **New as of October 8, 2026**. Severe stand-still congestion (dark red).

### Deprecated Fields (Fields 3–5)

The following fields and their nested message types (`TravelDuration`, `Timestamp`, `LatLng`, `SpeedReadingInterval`) are deprecated and will be decommissioned after January 13, 2027:

* **`repeated SpeedReadingInterval speed_reading_intervals = 3;`**: Deprecated in favor of `speed_reading_offsets` (field 8). Reduces payload size by up to 70% by eliminating redundant coordinate arrays.
* **`TravelDuration travel_duration = 4;`**: Deprecated in favor of top-level `duration_in_seconds` (field 9) and `static_duration_in_seconds` (field 10).
* **`Timestamp retrieval_time = 5;`**: Deprecated in favor of the standard RFC 3339 string `retrieval_timestamp` (field 11).

### Proto3 Semantics & Road Closure Behavior

* **`selected_route_id`**: **Required**. Format `^[a-zA-Z0-9-]+$`, length 4–63 characters.
* **`has_road_closure`**:
  * When `has_road_closure == true`: The monitored road stretch has a total physical closure. In this state, `duration_in_seconds` and `speed_reading_offsets` are **omitted** from the payload. Downstream consumers and SQL queries must handle `NULL` durations safely.
  * When `has_road_closure == false`: `duration_in_seconds` and `speed_reading_offsets` are guaranteed to be populated.

---

## 3. Direct BigQuery Subscription Ingestion (No-Code Integration)

For a fully managed, zero-maintenance ingestion pipeline, Google Cloud Pub/Sub can stream messages directly into BigQuery tables using a **BigQuery Subscription**.

### Schema Alignment (Source of Truth)

The landing table schema supports both new October 2026 fields and legacy fields during the transition period:

* *BigQuery Landing Schema:* [roads_information_landing.json](references/tables/roads_information_landing.json)
* *BigQuery Landing Table DDL:* [create_roads_information_landing.sql](references/queries/create_roads_information_landing.sql)

### Recommended BigQuery Subscription Settings

| Parameter | Recommended Setting | Rationale |
| :--- | :--- | :--- |
| **Topic** | `rmi-roadsinformation-PROJECT_NUMBER-json` | JSON topic matches BigQuery table column names natively. |
| **Use Table Schema** | **Checked** (`--use-table-schema`) | Instructs Pub/Sub to map incoming JSON keys to table fields directly. |
| **Drop Unknown Fields** | **Checked** (`--drop-unknown-fields`) | Prevents ingestion blockage if Google introduces non-breaking optional fields. |
| **Write Metadata** | **Checked** (`--write-metadata`) | Appends `publish_time`, `message_id`, `subscription_name`, and `attributes`. |

### Automating Subscription Creation (`create_pubsub_bq_subscription.sh`)

Use the bundled deployment automation script:

* *Subscription Provisioning Script:* [create_pubsub_bq_subscription.sh](scripts/create_pubsub_bq_subscription.sh)

```bash
# Provision direct-to-BigQuery subscription against the recommended JSON topic
PROJECT_ID="my-project-id" \
PROJECT_NUMBER="123456789012" \
ENCODING="json" \
./scripts/create_pubsub_bq_subscription.sh
```

The script:
1. Grants `roles/bigquery.dataEditor` and `roles/bigquery.metadataViewer` to `service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com`.
2. Creates the Pub/Sub subscription pointing to the BigQuery landing table with `--use-table-schema`, `--drop-unknown-fields`, and `--write-metadata`.

### Remediating Existing Landing Tables & Subscriptions (`remediate_landing_tables.sh`)

For projects that deployed landing tables before October 8, 2026, existing tables will lack the 5 evolved columns (`speed_reading_offsets`, `duration_in_seconds`, `static_duration_in_seconds`, `retrieval_timestamp`, `has_road_closure`), causing direct BigQuery subscriptions to reject incoming messages (`SCHEMA_MISMATCH` or ingestion pause).

To audit and safely migrate existing tables without data loss, use the automated remediation tool:

* *Remediation Script:* [remediate_landing_tables.sh](scripts/remediate_landing_tables.sh)

```bash
# 1. Audit current landing tables and validate DDL in dry-run mode:
./scripts/remediate_landing_tables.sh

# 2. Apply non-breaking ALTER TABLE migrations and enable --drop-unknown-fields:
./scripts/remediate_landing_tables.sh --apply
```

This script:
1. Audits existing columns on both JSON (`rmi_realtime_json`) and binary (`rmi_realtime_binary`) landing tables.
2. Executes non-breaking `ALTER TABLE ADD COLUMN IF NOT EXISTS` DDL statements for missing columns.
3. Hardens subscriptions by enabling `--drop-unknown-fields` to prevent any future topic schema evolutions from halting ingestion.
4. Performs an end-to-end diagnostic health check.

### Partitioning & Clustering for Cost Optimization

* **Partitioning**: Daily partitioning on `publish_time` (`PARTITION BY DATE(publish_time)`). Telemetry arrives continuously; partitioning restricts queries to only the hours or days needed, cutting scan costs from terabytes to megabytes.
* **Clustering**: Clustered on `selected_route_id` (`CLUSTER BY selected_route_id`). Groups data by monitored route, optimizing per-route time-series analysis and spatial queries.

---

## 4. Operational Best Practices

### Deduplication Strategy

Cloud Pub/Sub guarantees at-least-once message delivery. Downstream ELT pipelines must deduplicate incoming records.

* **Composite Deduplication Key**: Use `(selected_route_id, record_time)` where `record_time` is resolved via:
  ```sql
  COALESCE(
    retrieval_timestamp,
    TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND)
  )
  ```
* **Window Deduplication**: In scheduled queries, apply:
  ```sql
  ROW_NUMBER() OVER (
    PARTITION BY selected_route_id, COALESCE(retrieval_timestamp, TIMESTAMP_SECONDS(retrieval_time.seconds))
    ORDER BY publish_time DESC
  ) AS rn
  ```
  and filter `WHERE rn = 1`.

### Backpressure & Flow Control

For custom subscriber clients consuming hundreds of routes:
* Set `max_outstanding_messages = 100` to `500` per worker thread.
* Set `max_outstanding_bytes = 50MB` to avoid out-of-memory errors during traffic surge periods.

---

## 5. Troubleshooting & Operational Recovery

| Issue / Symptom | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **`PermissionDenied` (403) on Subscription** | Subscriber service account lacks IAM permissions. | Grant `roles/pubsub.subscriber` on the subscription resource to your client service account. |
| **`duration_in_seconds` is NULL** | The route is currently experiencing a full road closure (`has_road_closure == true`). | Verify `has_road_closure`. If true, null duration is expected per official API contract; do not treat as an ingestion error. |
| **BigQuery Ingestion Stalled on Schema Mismatch** | Protobuf topic used without `--use-topic-schema`, or JSON topic used without `--use-table-schema`. | Switch to the JSON topic (`-json`) with `--use-table-schema` and `--drop-unknown-fields`, or ensure table matches [roads_information_landing.json](references/tables/roads_information_landing.json). |
| **Ingestion Worker Memory Crash** | Large bursts of messages causing out-of-memory. | Implement Pub/Sub Flow Control limits. Reduce `max_outstanding_messages` to `100` or `500` per worker thread. |
| **Accumulated unacknowledged messages (Backpressure)** | Ingest worker processing duration is exceeding the subscription's `ack_deadline_seconds`. | Increase the acknowledgement deadline (default is 10s; recommend setting to 60s) or optimize callback database write latency. |
| **Duplicate processing of identical telemetry** | Redelivery because processing took longer than `ack_deadline_seconds`. | Apply deduplication window on `(selected_route_id, retrieval_timestamp)`. Acknowledge (`message.ack()`) promptly after landing. |

---

## 6. References

* [Google Maps Platform - RMI Real-Time Data (Official Documentation)](https://developers.google.com/maps/documentation/roads-management-insights/real-time-data)
* [Google Maps Platform - Roads Management Insights Overview](https://developers.google.com/maps/documentation/roads-management-insights/overview)
* [Google Maps Platform - RMI Guidelines & Governance](https://developers.google.com/maps/documentation/roads-management-insights/guidelines)

---

## 7. Production Ingestion Pattern

### Python Client (Streaming Pull with Flow Control & BigQuery Loading)

For custom hybrid deployments, containerized daemons (GKE/Cloud Run), or edge compute workers:

* *Custom Python Ingest Client:* [consume_and_stream_to_bq.py](scripts/consume_and_stream_to_bq.py)

Key capabilities:
1. **Asynchronous Streaming Pull** via `google-cloud-pubsub` with callback architecture.
2. **Backpressure Flow Control** bounding memory (`50MB`) and concurrent unacked messages (`100`).
3. **Evolved Schema Parser**: Extracts `speed_reading_offsets`, top-level `duration_in_seconds`, `static_duration_in_seconds`, `retrieval_timestamp`, and `has_road_closure`, with seamless COALESCE fallback to legacy fields.
4. **Sliding Window Cache**: Deduplicates events in-memory using `(selected_route_id, retrieval_timestamp)`.
5. **Streaming Inserts**: Writes rows directly to BigQuery using `insert_rows_json`.

---

## 8. Downstream SQL Translation to Recent Roads Data Layout

While raw landing preserves the message structure, analytics applications and visualization layers (e.g. Deck.gl, MapLibre) require clean native types:
* `TIMESTAMP` with microsecond precision.
* Native `GEOGRAPHY` polylines for routes and intervals.
* Structured `speed_reading_offsets` and `has_road_closure` flags.

* *Target Table DDL:* [create_recent_roads_data.sql](references/queries/create_recent_roads_data.sql)
* *SQL Translation Query:* [translate_landing_to_recent_roads.sql](references/queries/translate_landing_to_recent_roads.sql)
* *Transformed Table Schema:* [recent_roads_data_transformed.json](references/tables/recent_roads_data_transformed.json)

### Transitional COALESCE Logic

To ensure 100% continuous data integrity while both publisher schemas coexist:

```sql
SELECT
  selected_route_id,
  display_name,
  -- Reconstruct UTC record timestamp: prefer new RFC 3339 string, fallback to legacy seconds/nanos
  COALESCE(
    retrieval_timestamp,
    TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND)
  ) AS record_time,
  
  -- Duration metrics: prefer top-level fields, fallback to legacy travel_duration
  COALESCE(duration_in_seconds, travel_duration.duration_in_seconds) AS duration_in_seconds,
  COALESCE(static_duration_in_seconds, travel_duration.static_duration_in_seconds) AS static_duration_in_seconds,
  
  -- Road closure flag
  COALESCE(has_road_closure, FALSE) AS has_road_closure,
  
  -- Parse route geometry into native GEOGRAPHY polyline
  SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
  
  road_segment_ids,
  
  -- Linear distance offset speed readings (Oct 2026 schema)
  speed_reading_offsets,
  
  -- Legacy coordinate-based intervals (retained for backward compatibility)
  ARRAY(
    SELECT AS STRUCT
      [ST_MAKELINE(ARRAY(
        SELECT ST_GEOGPOINT(CAST(coord.longitude AS FLOAT64), CAST(coord.latitude AS FLOAT64))
        FROM UNNEST(interv.interval_coordinates) AS coord
      ))] AS interval_coordinates,
      interv.speed AS speed
    FROM UNNEST(speed_reading_intervals) AS interv
  ) AS speed_reading_intervals
FROM
  `my_project.rmi_realtime.roads_information_landing`;
```

---

## 9. Architectural Alternatives to Materialized Views: The "Translated Table" Strategy

BigQuery strictly prohibits `UNNEST` and subqueries inside **Materialized Views**. Therefore, downstream pipelines must implement one of the following architectural options:

### Option A: Standard Logical Views with Partition Pruning (Zero Operations, Live Reads)

* **Mechanism**: Expose a standard SQL view (`CREATE VIEW`) wrapping `translate_landing_to_recent_roads.sql`.
* **Pros**: Zero infrastructure overhead, real-time availability, zero redundant storage.
* **Cons**: Re-evaluates array and geometry transformations on every read.
* **Query Pattern**: Always filter on the partition column:
  ```sql
  SELECT * FROM `my_project.rmi_realtime.recent_roads_view`
  WHERE publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR);
  ```

### Option B: The "Translated Table" via BigQuery SQL MERGE (Lightweight Scheduled Pipeline)

* **Mechanism**: Maintain `recent_roads_data` as a physical table updated periodically (e.g. every 10–15 minutes) via BigQuery Scheduled Queries.
* *Scheduled Merge Query Script:* [scheduled_merge_recent_roads.sql](references/queries/scheduled_merge_recent_roads.sql)
* *Automated Query Scheduling Script:* [schedule_merge_query.sh](scripts/schedule_merge_query.sh)
* **Watermark**: Uses a 1-hour rolling lookback (`publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)`), scanning only incremental records.
* **Inline Deduplication**:
  ```sql
  ROW_NUMBER() OVER (
    PARTITION BY selected_route_id, COALESCE(retrieval_timestamp, TIMESTAMP_SECONDS(retrieval_time.seconds))
    ORDER BY publish_time DESC
  ) AS rn
  ```

### Option C: The "Translated Table" via Dataform / dbt Incremental Models (Professional ELT)

* **Mechanism**: Manage transformations as incremental models in Dataform or dbt.
* **Pros**: Version-controlled, CI/CD automated, built-in data quality assertions.
* **Example Dataform SQLX Block**:
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
    COALESCE(
      retrieval_timestamp,
      TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND)
    ) AS record_time,
    COALESCE(duration_in_seconds, travel_duration.duration_in_seconds) AS duration_in_seconds,
    COALESCE(static_duration_in_seconds, travel_duration.static_duration_in_seconds) AS static_duration_in_seconds,
    COALESCE(has_road_closure, FALSE) AS has_road_closure,
    SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
    road_segment_ids,
    speed_reading_offsets,
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

### Option D: Real-Time Streaming In-Memory Transformation

* **Mechanism**: Ingestion daemons consume messages from Pub/Sub, transform geometries and offsets in-memory, and stream write directly into `recent_roads_data`.
* **Implementation Blueprint**: See [consume_and_stream_to_bq.py](scripts/consume_and_stream_to_bq.py).

---

## 10. Historical Partition-Pruned Backfilling

When initializing `recent_roads_data` or reprocessing historical periods, run partition-by-partition backfills to maintain strict cost predictability.

* *Backfill Script:* [backfill_recent_roads.sh](scripts/backfill_recent_roads.sh)

```bash
PROJECT_ID="my-project-id" \
DATASET_ID="rmi_realtime" \
SOURCE_TABLE_ID="roads_information_landing" \
TARGET_TABLE_ID="recent_roads_data" \
./scripts/backfill_recent_roads.sh "2026-05-15" "2026-06-12"
```

The script:
1. Generates date sequences portably.
2. Performs partition-pruned `MERGE` queries per day with full COALESCE support.
3. Performs dry-run size estimates prior to execution.
4. Uses traceable job IDs (`rmi_realtime_backfill_<date>_<timestamp>`).
