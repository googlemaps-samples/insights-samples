# Boston 2026 Sample Dataset (`src_boston_ga`)

This reference provides technical details for the primary baseline RMI sample dataset used for testing, validation, and performance modeling.

---

## 1. Dataset Identity

- **Listing ID**: `boston_ga`
- **Source BigQuery Dataset**: `projects/1024202510105/datasets/src_boston_ga`
- **Exchange ID**: `projects/1024202510105/locations/us/dataExchanges/rmi_sampledata_v2_ga_prod`
- **Region**: Greater Boston Metropolitan Area, Massachusetts (USA)
- **Timeframe Window**: 2026-03-31 to 2026-07-01 (Primary dense analytical window: June 1 – June 30, 2026)
- **Monitored Fleet Scale**: 1,847 routes across 6 road priority tiers

---

## 2. Table Overview & Volume Baselines

1. **`historical_travel_time`**: ~56.1M records, partitioned by `record_time` (Day), clustered by `selected_route_id`.
2. **`recent_roads_data`**: ~42.0M records, partitioned by `record_time` (Day), clustered by `selected_route_id`. Contains Speed Reading Intervals (SRI) and nested geometries.
3. **`routes_status`**: 1,847 routes with metadata, JSON attributes (`route_attributes`), display names, and validation statuses.

---

## 3. Date Filters & Temporal Anchors

Always apply static temporal anchors to avoid 0-row results on static snapshots:

### Standard Active Window (June 2026)
```sql
WHERE record_time BETWEEN '2026-06-01' AND '2026-07-01'
```

### Morning Peak Window (7:00 AM – 9:00 AM UTC)
```sql
WHERE record_time BETWEEN '2026-06-01' AND '2026-07-01'
  AND EXTRACT(HOUR FROM record_time) BETWEEN 7 AND 9
```

### Detour & Path Variation Threshold
```sql
WHERE record_time >= '2026-06-19'
  AND ARRAY_LENGTH(road_segment_ids) > 0
```
