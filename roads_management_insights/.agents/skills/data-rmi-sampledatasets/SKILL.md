---
name: data-rmi-sampledatasets
description: Specialized guidance for working with RMI sample datasets, particularly the Boston October 2025 snapshot. Use when Gemini CLI needs to validate queries against sample data, estimate production costs based on sample baselines, or ensure correct temporal filtering for static snapshots.
---

# RMI Sample Datasets

This skill provides comprehensive context, architectural scaling methods, and strict static temporal constraints for working with the Road Management Insights (RMI) public sample datasets in BigQuery.

---

## 1. Multi-Region Sample Catalog

RMI maintains several localized, pre-subscribed sample datasets. Always align your queries with the spatial boundaries and specific temporal windows of each snapshot:

| Catalog ID / Region | Core Data Tables | Temporal Bounds (UTC) | Scan Base | Reference Document |
| :--- | :--- | :--- | :--- | :--- |
| **Boston Snapshot** | `historical_travel_time`, `recent_roads_data`, `routes_status` | `2025-10-01` to `2025-10-31` | ~400 MB | [boston_2025.md](references/boston_2025.md) |
| **Paris Snapshot** | `historical_travel_time`, `recent_roads_data`, `routes_status` | Check local table metadata | ~250 MB | Subscription metadata |
| **Tokyo Snapshot** | `historical_travel_time`, `recent_roads_data`, `routes_status` | Check local table metadata | ~500 MB | Subscription metadata |

### Sample Schema Validation & Nullability Exceptions
While production datasets maintain high-frequency real-time updates and strict active lifecycle states, public sample datasets have unique structural behaviors that you must account for during analytical query design:
*   **Frozen Operational States**: All routes in `routes_status` for sample datasets hold a permanent `STATUS_RUNNING` status (except for pre-configured demonstration routes highlighting validation failures, which hold static `STATUS_INVALID` and `VALIDATION_ERROR_LOW_ROAD_USAGE` properties).
*   **Static Geometries**: The `route_geometry` and nested `interval_coordinates` are completely frozen snapshot paths. Spatial proximity queries (e.g. `ST_DWITHIN`) are highly predictable and cheap to scan since paths do not dynamic-reroute over the historical snapshot period.
*   **Date Partition Boundaries**: All partitioning keys (`record_time`) strictly fall within the documented regional timeframe bounds. Never write queries extending outside these bounds when validating analytical behavior.
*   **`road_segment_ids` Schema Threshold**: The `road_segment_ids` column was introduced on **June 19, 2026**. Telemetry snapshots captured prior to this date (e.g. October 2025 sample slices) contain empty arrays (`[]`). Always guard segment unnesting queries with `LEFT JOIN UNNEST` or enforce `record_time >= '2026-06-19' AND ARRAY_LENGTH(road_segment_ids) > 0`.

---

## 2. Key Principles for Sample Usage

### 1. The Static Temporal Anchor Mandate
Because these datasets are historical snapshots, any queries utilizing `CURRENT_TIMESTAMP()`, `CURRENT_DATE()`, or relative offsets (e.g., `TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)`) will return **zero results**.
*   **Mandatory Pattern**: You **must** replace all relative time filters with static datetime literals matching the snapshot's timeframe.

```sql
-- INCORRECT (Returns 0 rows)
WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)

-- CORRECT (Captures the Boston snapshot window)
WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
```

### 2. Multi-Tiered Cost and Fleet Scaling Projections
The sample datasets are lightweight, making queries inexpensive (typically < $0.01 per scan). When evaluating query designs, use the **Scaling Multipliers** below to project storage costs and scan byte sizes for massive enterprise or governmental fleets:

| Scenario / Fleet Tier | Number of Routes | Multiplier vs. Sample | Projected Monthly Bytes | Cost Category |
| :--- | :--- | :--- | :--- | :--- |
| **Sample Dataset** | 500 Routes | 1x (Baseline) | ~400 MB | Negligible (< $0.01) |
| **Small Production** | 5,000 Routes | 10x | ~4 GB | Minimal (< $0.05) |
| **Enterprise Fleet** | 50,000 Routes | 100x | ~40 GB | Moderate (~$0.20) |
| **Mega Fleet (Nationwide)** | 500,000 Routes | 1,000x | ~400 GB | Strategic (~$2.00) |

### 3. Complexity Classes & Algorithmic Cost Bounds
Downstream queries are grouped into mathematical complexity tiers based on their scanning growth properties:
*   **O(T) - Time-Dependent (Linear Growth)**: Trend queries scanning across the entire historical table (e.g., full-year average speed profiles). Storage scan sizes and costs grow linearly with time.
*   **O(1) - Time-Invariant (Flat Cost)**: Operational analytics using specific partition filters (e.g., analyzing peak commute times for any single week). Costs remain perfectly flat regardless of total database size.
*   **O(R) - Route-Dependent (Metadata Growth)**: Administrative queries on `routes_status`. Costs scale linearly with the number of monitored routes.

---

## 3. Troubleshooting & Common Pitfalls

| Symptom / Error | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **Zero rows returned** | Using relative datetime functions like `CURRENT_TIMESTAMP()`. | Replace with static anchors (e.g., `BETWEEN '2025-10-01' AND '2025-11-01'`). |
| **Inaccurate Dry Run Cost** | Dry run reports full-table scan bytes because of wildcard usage. | Always verify the specific dataset schema and apply partition filters on `record_time` first. |
| **Mismatched coordinate comparisons** | Attempting joins on floating-point coordinates. | Never join on spatial latitude/longitude. Use `selected_route_id` as the robust join key. |
| **Query dry run lists no partition pruning** | Filtering `record_time` using dynamic calculations (e.g., `EXTRACT`). | Avoid applying functions on the column side of comparisons (e.g., use `record_time >= '2025-10-01'` instead of `EXTRACT(MONTH FROM record_time) = 10`). |

---

## 4. References & Linked Artifacts
*   [Google Maps Platform - RMI Sample Data Listings](https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/1024202510105/locations/us/dataExchanges/roads_management_insights_sample_data_1987fdc8958/listings)
*   [Boston 2025 Dataset Metadata Reference](references/boston_2025.md)
*   [RMI Multipliers & Ingestion Costs](references/metrics.md)

---

## 5. Examples

### Example 1: Morning Commute Peak Performance Audit
Analyze average speed drops during morning rush hour (7:00 AM - 9:00 AM) across the entire Boston network for the October 2025 snapshot:
```sql
SELECT 
  selected_route_id,
  AVG(duration_in_seconds) AS avg_peak_duration,
  AVG(static_duration_in_seconds) AS free_flow_duration,
  -- Compute Peak Travel Time Index (TTI)
  SAFE_DIVIDE(
    AVG(duration_in_seconds), 
    AVG(static_duration_in_seconds)
  ) AS peak_tti
FROM 
  `my_project.boston_oct_2025_sample_data.historical_travel_time`
WHERE 
  -- Static Temporal Anchor to capture the Boston snapshot
  record_time BETWEEN '2025-10-01' AND '2025-11-01'
  -- Morning commute hour bounds
  AND EXTRACT(HOUR FROM record_time) BETWEEN 7 AND 9
GROUP BY 
  selected_route_id
ORDER BY 
  peak_tti DESC;
```

### Example 2: Operational Route Status & Attribute Mapping
Count active routes and list their failure/validation states grouped by custom regions defined in route metadata:
```sql
SELECT 
  JSON_EXTRACT_SCALAR(route_attributes, '$.region') AS region,
  status,
  validation_error,
  COUNT(1) AS route_count
FROM 
  `my_project.boston_oct_2025_sample_data.routes_status`
GROUP BY 
  region,
  status,
  validation_error
ORDER BY 
  route_count DESC;
```
