# Table: historical_travel_time

## 1. Overview
This table provides accumulated, historical trip duration data for your selected routes. It is the primary dataset for long-term behavior analysis, strategic planning, and identifying seasonal traffic trends.

## 2. Core Definitions
- **Traffic-Aware Duration**: The estimated total travel time at the specific `record_time`, factoring in real-world traffic conditions.
- **Static Duration**: The "free-flow" baseline travel time, calculated without traffic considerations.
- **Record Time**: The UTC timestamp when the routing calculation was performed.

## 3. Technical Behaviors & Facts
- **Aggregation**: Data is collected periodically and written in **hourly batches**.
- **Data Latency**: After a new route is created in the Roads Selection API, expect a wait of up to 1 hour for data to begin populating in this table.
- **Partitioning**: Partitioned by **day** based on the `record_time` column. 
- **Expiration**: Each partition has a **10-year expiration policy**, supporting multi-year trend analysis.
- **Retention**: If a route is deleted from the Roads Selection API, no new data is written, but historical records remain until their partition expires.

## 4. Analytical Guidance
- **Cost Optimization**: Always include a filter on `record_time` (e.g., `WHERE DATE(record_time) = '2026-03-01'`) to ensure BigQuery can prune partitions and minimize scan costs.
- **Congestion Metrics**:
    - **TTI (Travel Time Index)**: `SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)`. Values > 1.0 indicate delay relative to free-flow.
- **Clustering**: The table is typically clustered by `selected_route_id` to speed up route-specific lookups.

## 5. Usage Example: Calculating Monthly Average Delay
```sql
-- Calculate the average Travel Time Index (TTI) per route for a specific month
SELECT 
  selected_route_id,
  AVG(SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)) as avg_tti,
  COUNT(*) as data_points
FROM `historical_travel_time`
WHERE record_time >= '2026-03-01' AND record_time < '2026-04-01'
GROUP BY 1
HAVING data_points > 100
ORDER BY avg_tti DESC;
```

## 6. Usage Example: Route Geometry Over Time
```sql
-- Retrieve the geometry of a specific route to verify the path taken during a peak window
SELECT 
  selected_route_id,
  record_time,
  route_geometry
FROM `historical_travel_time`
WHERE selected_route_id = 'my-route-001'
  AND DATE(record_time) = '2026-03-15'
  AND EXTRACT(HOUR FROM record_time) = 8
ORDER BY record_time;
```
