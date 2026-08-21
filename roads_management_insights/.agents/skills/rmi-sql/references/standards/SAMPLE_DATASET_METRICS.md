# RMI Sample Dataset Metrics

This document provides scale and cost baselines for the `LINKED_DATASET_NAME` dataset. These numbers are used to estimate the "Bytes Processed" for the sample queries in this library.

## Dataset Overview: `LINKED_DATASET_NAME`
- **Region**: Boston, MA (USA)
- **Timeframe**: October 1, 2025 – October 31, 2025 (31 Days)
- **Scale**:
    - **Total SelectedRoutes**: ~500 active routes.
    - **Total Records (Historical)**: ~372,000 (Calculated as: 500 routes * 24 hours * 31 days).
    - **Total Records (Recent)**: Hourly snapshots for the last 60 days.
    - **Table Size (Historical)**: ~150 MB (Uncompressed).
    - **Table Size (Recent)**: ~250 MB (Includes nested SRI data).
    - **Table Size (Status)**: < 1 MB.

## Cost Estimation Baselines (BigQuery On-Demand)
*Note: Estimates are based on full table scans of specific columns required for the query.*

| Table Name | Full Table Scan (Bytes) | Est. Cost ($5/TB) |
| :--- | :--- | :--- |
| **`historical_travel_time`** | ~150 MB | < $0.01 |
| **`recent_roads_data`** | ~250 MB | < $0.01 |
| **`routes_status`** | < 1 MB | < $0.01 |

## Scaling & Cost Dynamics

Understanding how costs evolve as data accumulates (Time) and the monitoring footprint grows (Routes) is critical for budget planning.

### 1. Scaling by Time (Data Accumulation)
- **Time-Series / Trend Queries**: Queries that analyze "All Time" trends (e.g., `up1_corridor_trend`) scale **linearly** with data accumulation. A 1-year analysis is ~12x more expensive than a 1-month analysis.
    - **Complexity Class**: **O(T)** (Time-dependent)
- **Operational / Snapshot Queries**: Queries using a fixed temporal filter (e.g., `WHERE record_time >= CURRENT_TIMESTAMP - 7 days`) stay **flat** in cost regardless of how many years of data are in the table, thanks to BigQuery's partition pruning.
    - **Complexity Class**: **O(1)** (Time-invariant)
- **Retention Cap**: `recent_roads_data` cost is naturally capped at 60 days of accumulation.

### 2. Scaling by Route Volume (Fleet Size)
- **Metadata Queries**: Queries on `routes_status` (e.g., `de2_data_cleaning`, `rmip3_segment_estimation`) scale **linearly** with the number of routes.
    - **Complexity Class**: **O(R)** (Route-dependent)
- **Join Complexity**: Joins between `routes_status` and `historical_travel_time` (e.g., filtering history by a custom route attribute) grow in cost as the Cartesian product of (Routes * Time) increases.

### 3. Order of Magnitude Comparison

| Scenario | Monitoring Load | Historical Accumulation | Est. Scan Size (HTT) | Cost Profile |
| :--- | :--- | :--- | :--- | :--- |
| **Sample Dataset** | 500 Routes | 1 Month | ~150 MB | Negligible |
| **Small Production** | 5,000 Routes | 1 Year | ~18 GB | Low (<$0.10) |
| **Enterprise Fleet** | 50,000 Routes | 1 Year | ~180 GB | Moderate (~$0.90) |
| **Mega Fleet** | 500,000 Routes | 5 Years | ~9 TB | Significant (~$45.00) |

## Optimizing for Growth

To prevent costs from spiraling as your dataset reaches "Mega Fleet" scale, adopt these patterns:

1.  **Materialize for Trends**: Don't run long-term trend queries against the raw `historical_travel_time` table daily. Instead, create a **Materialized View** or an incremental table that stores pre-aggregated weekly/monthly metrics.
2.  **Static Date Anchors**: When building dashboards, use static date filters or parameters to prevent the query from defaulting to an unintentional full table scan.
3.  **Clustering over Filtering**: When looking for a specific route across years of data, ensure `selected_route_id` is the first column in your `WHERE` clause to take advantage of BigQuery's block-level metadata pruning.

## Query Metadata Reference
For each sample query, we provide an **Estimated Bytes Processed** value based on the columns accessed and the assumption of no partition pruning. In a real-world multi-terabyte dataset, these numbers would be significantly higher.
