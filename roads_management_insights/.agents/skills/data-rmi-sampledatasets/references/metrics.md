# RMI Sample Dataset Metrics & Scaling

This reference provides scale and cost baselines for the RMI sample datasets, primarily focused on `boston_oct_2025_sample_data`.

## Sample Baseline (Boston 2025)
| Table Name | Full Table Scan (Bytes) | Est. Cost ($5/TB) |
| :--- | :--- | :--- |
| **`historical_travel_time`** | ~150 MB | < $0.01 |
| **`recent_roads_data`** | ~250 MB | < $0.01 |
| **`routes_status`** | < 1 MB | < $0.01 |

## Scaling Multipliers (Route Volume)
Use these multipliers to estimate costs when moving from the sample dataset to production-scale fleets.

| Scenario | Monitoring Load | Multiplier vs. Sample |
| :--- | :--- | :--- |
| **Sample Dataset** | 500 Routes | 1x |
| **Small Production** | 5,000 Routes | 10x |
| **Enterprise Fleet** | 50,000 Routes | 100x |
| **Mega Fleet** | 500,000 Routes | 1000x |

## Complexity Classes
- **O(T) - Time-Dependent**: Trend queries across the entire table (e.g., "Full year analysis"). Costs grow linearly with time.
- **O(1) - Time-Invariant**: Operational queries using partition filters (e.g., "Last 7 days"). Costs remain flat regardless of total table size.
- **O(R) - Route-Dependent**: Metadata queries on `routes_status`. Costs grow linearly with the number of monitored routes.

## Optimization Strategies
1.  **Materialize for Trends**: Pre-aggregate metrics into monthly tables to avoid full scans of the raw history.
2.  **Partition Pruning**: Always filter by `record_time` to minimize scanned bytes.
3.  **Clustering**: Filter by `selected_route_id` early to leverage block-level pruning.
