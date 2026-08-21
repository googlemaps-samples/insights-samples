# Boston October 2025 Sample Dataset

This reference provides the technical details for the primary RMI sample dataset used for testing and validation.

## Dataset Identity
- **Full Name**: `boston_oct_2025_sample_data`
- **Region**: Boston, MA (USA)
- **Timeframe**: 2025-10-01 to 2025-10-31 (UTC)

## Table Schema Overview
The dataset contains the standard RMI tables with a specific snapshot of data:

1.  **`historical_travel_time`**: Hourly travel time observations for ~500 routes.
2.  **`recent_roads_data`**: Real-time snapshots (last 60 days of the snapshot window).
3.  **`routes_status`**: Metadata for the ~500 routes monitored in this period.

## Critical Date Filters
When querying this dataset, you **MUST** use static date anchors instead of `CURRENT_TIMESTAMP()` to ensure you are scanning the relevant data window.

### Standard Timeframe Filter
```sql
WHERE record_time BETWEEN '2025-10-01' AND '2025-11-01'
```

### Morning Peak Filter
```sql
WHERE EXTRACT(HOUR FROM record_time) BETWEEN 7 AND 9
  AND record_time BETWEEN '2025-10-01' AND '2025-11-01'
```

## Joins and Key Relationships
- **Join Key**: Use `selected_route_id` to join all three tables.
- **Route Filtering**: Use `routes_status` to filter by route attributes (e.g., `display_name`, `origin_address`) before joining with large historical tables.

## Dataset Limitations
- **No real-time updates**: This is a static snapshot. `CURRENT_TIMESTAMP()` queries will return zero results.
- **Geographic Bounds**: Analysis is limited to the Greater Boston area.
- **Route Volume**: ~500 routes. Scaling tests for "Mega Fleet" scenarios should use the multipliers defined in [metrics.md](metrics.md).
