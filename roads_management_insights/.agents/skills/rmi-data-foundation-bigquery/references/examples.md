# Historical Roads Data Query Examples

This reference provides common SQL patterns for analyzing the `historical_travel_time` dataset.

## 1. Daily Average Travel Time per Route

Calculates the average traffic-aware duration for each route over the last 30 days.

```sql
SELECT
  selected_route_id,
  display_name,
  DATE(record_time) as record_date,
  AVG(duration_in_seconds) as avg_duration_seconds
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY
  1, 2, 3
ORDER BY
  3 DESC, 4 DESC;
```

## 2. Peak Hour vs. Free Flow Delay

Calculates the delay percentage during peak hours compared to static (free-flow) duration.

```sql
SELECT
  selected_route_id,
  display_name,
  EXTRACT(HOUR FROM record_time) as hour_of_day,
  AVG(duration_in_seconds) as avg_actual,
  AVG(static_duration_in_seconds) as avg_static,
  (AVG(duration_in_seconds) - AVG(static_duration_in_seconds)) / NULLIF(AVG(static_duration_in_seconds), 0) * 100 as delay_percentage
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY
  1, 2, 3
HAVING
  hour_of_day BETWEEN 7 AND 9 OR hour_of_day BETWEEN 16 AND 18
ORDER BY
  delay_percentage DESC;
```

## 3. Route Reliability (95th Percentile Travel Time)

Measures the variance in travel time to assess reliability.

```sql
SELECT
  selected_route_id,
  display_name,
  PERCENTILE_CONT(duration_in_seconds, 0.95) OVER(PARTITION BY selected_route_id) as p95_duration,
  AVG(duration_in_seconds) OVER(PARTITION BY selected_route_id) as avg_duration
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY);
```

## 4. Corridor Performance Audit

Aggregates data for multiple routes that form a corridor.

```sql
SELECT
  DATE(record_time) as day,
  SUM(duration_in_seconds) as corridor_total_duration,
  SUM(static_duration_in_seconds) as corridor_free_flow_duration
FROM
  `my_project.rmi_foundation.historical_travel_time`
WHERE
  display_name LIKE '%Main St%'
  AND record_time >= '2025-10-01'
GROUP BY
  1
ORDER BY
  1;
```
