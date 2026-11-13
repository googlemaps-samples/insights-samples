# RMI Sample Dataset Metrics & Scaling

This reference provides scale and cost baselines for the RMI sample datasets, primarily anchored to the baseline `src_boston_ga` dataset (~1,847 routes).

---

## 1. Sample Baseline (Boston 2026 Snapshot)

| Table Name | Monitored Fleet Scale | Full Table Scan (Bytes) | Est. Scan Cost ($5/TB) |
| :--- | :--- | :--- | :--- |
| **`historical_travel_time`** | 1,847 Routes (June 2026) | ~400 MB (1 month partition) | < $0.01 |
| **`recent_roads_data`** | 1,847 Routes (June 2026) | ~1.2 GB (1 month partition) | < $0.01 |
| **`routes_status`** | 1,847 Routes | < 2 MB | < $0.01 |

---

## 2. Scaling Multipliers (Route Volume Projections)

Use these multipliers to project enterprise storage costs, query scanning byte sizes, and slot utilization:

| Fleet Tier | Monitored Routes | Multiplier vs. Sample Base | Monthly Bytes (Approx.) | Scan Cost Category |
| :--- | :--- | :--- | :--- | :--- |
| **Sample Baseline** | ~1,850 Routes | 1x (Base) | ~1.6 GB / month | Negligible (< $0.01) |
| **City-Wide Fleet** | ~10,000 Routes | ~5.4x | ~8.6 GB / month | Minimal (< $0.05) |
| **State / Regional Fleet** | ~50,000 Routes | ~27x | ~43 GB / month | Moderate (~$0.22) |
| **Mega Fleet (Nationwide)** | ~500,000 Routes | ~270x | ~430 GB / month | Strategic (~$2.15) |

---

## 3. Complexity Classes

- **O(T) - Time-Dependent (Linear Growth)**: Multi-month / full-year longitudinal trend queries scanning across the entire historical partition range. Storage scan sizes and costs grow linearly with time.
- **O(1) - Time-Invariant (Flat Cost)**: Operational analytics with bounded partition pruning (e.g., single week or month). Costs remain constant regardless of table retention depth.
- **O(R) - Route-Dependent (Metadata Growth)**: Administrative queries filtering on `routes_status`. Costs scale linearly with route inventory size.

---

## 4. Query Optimization Strategies

1. **Partition Pruning**: Always filter by `record_time` using static datetime literals (e.g., `BETWEEN '2026-06-01' AND '2026-07-01'`) to avoid full-table scans.
2. **Cluster Pruning**: Filter by `selected_route_id` early in CTEs to leverage block-level pruning.
3. **Array Unnesting Safety**: Enforce `record_time >= '2026-06-19' AND ARRAY_LENGTH(road_segment_ids) > 0` before unnesting `road_segment_ids`.
