---
name: rmi-traffic-metrics-grounding
description: >
  Standard traffic performance metrics computable from RMI BigQuery
  tables. Covers congestion severity (TTI), delay, travel time
  reliability (LOTTR, BTI, PTI, CoV), congestion frequency, speed
  breakdowns (jam/slow fractions), before/after impact analysis, and
  network-wide congestion rates. Use when the user asks about traffic
  conditions, congestion, reliability, predictability, delay, travel
  time variability, congestion frequency, or network health.
---

# RMI Traffic Metrics Grounding Skill

## Metrics

### A1. Travel Time Index (TTI)

-   **Triggers**: "how congested", "congestion level", "traffic conditions",
    "delay ratio", "delay index", "avg_delay_ratio", "avg_delay_index"
-   **Formula**: TTI = duration_in_seconds / static_duration_in_seconds
-   **Interpretation**: 1.0 = free-flow. 1.3 = 30% slower.
-   **Aliases**: "delay ratio", "delay index", "congestion ratio". When the user
    asks for any of these, use this TTI formula (`duration / static`).

```sql
SELECT
  selected_route_id,
  display_name,
  record_time,
  SAFE_DIVIDE(
    duration_in_seconds,
    static_duration_in_seconds
  ) AS tti
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds > 0
```

### A2. Delay Per Trip

-   **Triggers**: "extra time", "delay", "added travel time"
-   **Formula**: Delay = duration_in_seconds - static_duration_in_seconds
-   **Interpretation**: absolute excess seconds. Negative = faster than
    free-flow (low traffic).

```sql
SELECT
  selected_route_id,
  display_name,
  record_time,
  duration_in_seconds
    - static_duration_in_seconds AS delay_seconds
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds > 0
```

### A3. Buffer Time Index (BTI)

-   **Triggers**: "how unpredictable", "reliability", "extra buffer"
-   **Formula**: BTI = (P95(duration) - AVG(duration)) / AVG(duration)
-   **Interpretation**: fraction of extra time to budget beyond average. BTI >
    0.5 = unreliable.

```sql
SELECT
  selected_route_id,
  ANY_VALUE(display_name) AS display_name,
  EXTRACT(
    HOUR FROM record_time
      AT TIME ZONE '<TIMEZONE>' -- e.g., 'America/New_York', 'America/Los_Angeles'
  ) AS local_hour,
  AVG(duration_in_seconds) AS avg_duration,
  APPROX_QUANTILES(
    duration_in_seconds, 100
  )[OFFSET(95)] AS p95_duration,
  SAFE_DIVIDE(
    APPROX_QUANTILES(
      duration_in_seconds, 100
    )[OFFSET(95)] - AVG(duration_in_seconds),
    AVG(duration_in_seconds)
  ) AS bti
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
GROUP BY selected_route_id, local_hour
```

### A4. Planning Time Index (PTI)

-   **Triggers**: "worst case travel time", "how much time to plan"
-   **Formula**: PTI = P95(duration) / AVG(static_duration)
-   **Interpretation**: near-worst-case vs. free-flow. PTI = 2.0 means plan
    double the free-flow time to arrive on time 95% of trips.

```sql
SELECT
  selected_route_id,
  ANY_VALUE(display_name) AS display_name,
  AVG(static_duration_in_seconds) AS avg_free_flow,
  APPROX_QUANTILES(
    duration_in_seconds, 100
  )[OFFSET(95)] AS p95_duration,
  SAFE_DIVIDE(
    APPROX_QUANTILES(
      duration_in_seconds, 100
    )[OFFSET(95)],
    AVG(static_duration_in_seconds)
  ) AS pti
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds > 0
GROUP BY selected_route_id
```

### A5. Level of Travel Time Reliability (LOTTR)

-   **Triggers**: "is this route reliable", "LOTTR", "federal reliability"
-   **Formula**: LOTTR = P80(duration) / P50(duration)
-   **FHWA time periods**: AM Peak (weekday hours 6–9), Midday (weekday hours
    10–15), PM Peak (weekday hours 16–19), Weekend (Sat/Sun hours 6–19 only)
-   **Interpretation**: < 1.50 = "reliable" per federal standard.

```sql
SELECT
  selected_route_id,
  ANY_VALUE(display_name) AS display_name,
  CASE
    WHEN EXTRACT(
           DAYOFWEEK FROM record_time
             AT TIME ZONE '<TIMEZONE>'
         ) IN (1, 7)
         AND EXTRACT(
               HOUR FROM record_time
                 AT TIME ZONE '<TIMEZONE>'
             ) BETWEEN 6 AND 19
      THEN 'Weekend'
    WHEN EXTRACT(
           DAYOFWEEK FROM record_time
             AT TIME ZONE '<TIMEZONE>'
         ) NOT IN (1, 7)
         AND EXTRACT(
               HOUR FROM record_time
                 AT TIME ZONE '<TIMEZONE>'
             ) BETWEEN 6 AND 9
      THEN 'AM_Peak'
    WHEN EXTRACT(
           DAYOFWEEK FROM record_time
             AT TIME ZONE '<TIMEZONE>'
         ) NOT IN (1, 7)
         AND EXTRACT(
               HOUR FROM record_time
                 AT TIME ZONE '<TIMEZONE>'
             ) BETWEEN 10 AND 15
      THEN 'Midday'
    WHEN EXTRACT(
           DAYOFWEEK FROM record_time
             AT TIME ZONE '<TIMEZONE>'
         ) NOT IN (1, 7)
         AND EXTRACT(
               HOUR FROM record_time
                 AT TIME ZONE '<TIMEZONE>'
             ) BETWEEN 16 AND 19
      THEN 'PM_Peak'
    ELSE 'Off_Peak'
  END AS time_period,
  SAFE_DIVIDE(
    APPROX_QUANTILES(
      duration_in_seconds, 100
    )[OFFSET(80)],
    APPROX_QUANTILES(
      duration_in_seconds, 100
    )[OFFSET(50)]
  ) AS lottr
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
GROUP BY selected_route_id, time_period
```

### A6. Travel Time Variability (CoV)

-   **Triggers**: "how consistent", "variability", "spread of travel times"
-   **Formula**: CoV = STDDEV(duration) / AVG(duration)
-   **Interpretation**: dimensionless spread. High CoV + moderate TTI =
    unpredictable even when not severely congested.

```sql
SELECT
  selected_route_id,
  ANY_VALUE(display_name) AS display_name,
  AVG(duration_in_seconds) AS avg_duration,
  STDDEV(duration_in_seconds) AS stddev_duration,
  SAFE_DIVIDE(
    STDDEV(duration_in_seconds),
    AVG(duration_in_seconds)
  ) AS cov
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
GROUP BY selected_route_id
```

### A7. Percent Time Congested

-   **Triggers**: "how often congested", "frequency of congestion", "percent of
    time"
-   **Formula**: % Congested = count(TTI > threshold) / count(all)
-   **Threshold**: default TTI > 1.25. Ask user for preference.
-   **Interpretation**: temporal frequency of congestion. Distinct from TTI.

```sql
SELECT
  selected_route_id,
  ANY_VALUE(display_name) AS display_name,
  COUNT(*) AS total_observations,
  COUNTIF(
    SAFE_DIVIDE(
      duration_in_seconds,
      static_duration_in_seconds
    ) > 1.25
  ) AS congested_observations,
  SAFE_DIVIDE(
    COUNTIF(
      SAFE_DIVIDE(
        duration_in_seconds,
        static_duration_in_seconds
      ) > 1.25
    ),
    COUNT(*)
  ) AS pct_time_congested
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds > 0
GROUP BY selected_route_id
```

### A8. Before/After Comparison (Δ Metric)

-   **Triggers**: "impact of construction", "before and after", "did the new
    road help", "change since"
-   **Formula**: ΔM = M_after - M_before (any metric)
-   **Parameters**: a date cutoff (from the user) and a base metric
-   **Interpretation**: positive Δ for TTI/Delay = worsened; negative =
    improved.

The example below uses TTI. Substitute any metric formula depending on the
user's request. Dynamically inline timestamps as `TIMESTAMP('YYYY-MM-DD',
'<TIMEZONE>')` during SQL synthesis using the roadway's local timezone. Ensure
before and after date ranges are balanced to avoid seasonal bias.

```sql
SELECT
  selected_route_id,
  ANY_VALUE(display_name) AS display_name,
  AVG(IF(
    record_time < TIMESTAMP('2025-10-15', '<TIMEZONE>'), -- Cutoff date and local timezone dynamically inlined
    SAFE_DIVIDE(
      duration_in_seconds,
      static_duration_in_seconds
    ),
    NULL
  )) AS tti_before,
  AVG(IF(
    record_time >= TIMESTAMP('2025-10-15', '<TIMEZONE>'), -- Cutoff date and local timezone dynamically inlined
    SAFE_DIVIDE(
      duration_in_seconds,
      static_duration_in_seconds
    ),
    NULL
  )) AS tti_after,
  AVG(IF(
    record_time >= TIMESTAMP('2025-10-15', '<TIMEZONE>'),
    SAFE_DIVIDE(
      duration_in_seconds,
      static_duration_in_seconds
    ),
    NULL
  )) - AVG(IF(
    record_time < TIMESTAMP('2025-10-15', '<TIMEZONE>'),
    SAFE_DIVIDE(
      duration_in_seconds,
      static_duration_in_seconds
    ),
    NULL
  )) AS delta_tti
FROM `{PROJECT_ID}.{RMI_DATASET}.historical_travel_time`
WHERE duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds IS NOT NULL
  AND static_duration_in_seconds > 0
GROUP BY selected_route_id
```

### B1. Congestion Fraction (Jam + Non-Normal)

-   **Triggers**: "jam percentage", "how much of the route is jammed", "speed
    breakdown"
-   **Formulas**:
    -   Jam% = count(TRAFFIC_JAM) / count(all intervals)
    -   NonNormal% = count(SLOW + TRAFFIC_JAM) / count(all intervals)
-   **Source**: `recent_roads_data` → `UNNEST(speed_reading_intervals)`
-   **Interpretation**: Jam% = severe only. NonNormal% = any degradation.

```sql
SELECT
  selected_route_id,
  ANY_VALUE(display_name) AS display_name,
  record_time,
  COUNTIF(sri.speed = 'NORMAL') AS normal_count,
  COUNTIF(sri.speed = 'SLOW') AS slow_count,
  COUNTIF(sri.speed = 'TRAFFIC_JAM') AS jam_count,
  COUNT(*) AS total_intervals,
  SAFE_DIVIDE(
    COUNTIF(sri.speed = 'TRAFFIC_JAM'),
    COUNT(*)
  ) AS jam_fraction,
  SAFE_DIVIDE(
    COUNTIF(sri.speed IN ('SLOW', 'TRAFFIC_JAM')),
    COUNT(*)
  ) AS non_normal_fraction
FROM `{PROJECT_ID}.{RMI_DATASET}.recent_roads_data`,
  UNNEST(speed_reading_intervals) AS sri
GROUP BY selected_route_id, record_time
```

### B2. Network Congestion Rate

-   **Triggers**: "how many routes jammed", "network-wide congestion", "overall
    network health"
-   **Formula**: NCR = count(routes with any JAM) / count(all routes)
-   **Source**: `recent_roads_data`
-   **Interpretation**: fraction of monitored routes with at least one
    TRAFFIC_JAM segment per hour.

```sql
SELECT
  TIMESTAMP_TRUNC(record_time, HOUR, '<TIMEZONE>') AS local_hour,
  COUNT(DISTINCT selected_route_id) AS total_routes,
  COUNT(DISTINCT IF(
    EXISTS(
      SELECT 1
      FROM UNNEST(speed_reading_intervals) s
      WHERE s.speed = 'TRAFFIC_JAM'
    ),
    selected_route_id,
    NULL
  )) AS jammed_routes,
  SAFE_DIVIDE(
    COUNT(DISTINCT IF(
      EXISTS(
        SELECT 1
        FROM UNNEST(speed_reading_intervals) s
        WHERE s.speed = 'TRAFFIC_JAM'
      ),
      selected_route_id,
      NULL
    )),
    COUNT(DISTINCT selected_route_id)
  ) AS network_congestion_rate
FROM `{PROJECT_ID}.{RMI_DATASET}.recent_roads_data`
GROUP BY local_hour
ORDER BY local_hour
```

## Caveats

1.  **Timezone**: `record_time` is stored as UTC. Always apply `AT TIME ZONE
    '<TIMEZONE>'` (using the appropriate local IANA timezone for the target
    region/roadway, e.g., `'America/New_York'`, `'America/Los_Angeles'`,
    `'America/Chicago'`, etc.) when extracting hours, days, or day-of-week for
    peak period classification. Anchor literal cutoff timestamps using
    `TIMESTAMP('YYYY-MM-DD', '<TIMEZONE>')`.

2.  **No numeric speed**: RMI provides categorical speed
    (NORMAL/SLOW/TRAFFIC_JAM), not km/h. Never report "average speed."

3.  **Null-safety**: always filter `WHERE duration_in_seconds IS NOT NULL`; use
    `SAFE_DIVIDE` for all division; guard `static_duration_in_seconds > 0`
    before dividing.

4.  **LOTTR time periods**: use FHWA definitions strictly — AM Peak (weekday
    hours 6–9), Midday (weekday hours 10–15), PM Peak (weekday hours 16–19),
    Weekend (Sat/Sun hours 6–19 only). Weekend overnight hours (0–5, 20–23) and
    all weekday off-peak hours are 'Off_Peak'. BigQuery `EXTRACT(DAYOFWEEK)`
    returns 1 = Sunday, 7 = Saturday.

5.  **% Time Congested threshold (A7)**: default to TTI > 1.25. Ask the user if
    they want a different threshold.

6.  **Percentile computation**: `APPROX_QUANTILES(value, 100)` returns a
    101-element array (indices 0–100). `[OFFSET(N)]` extracts the Nth
    percentile. For P95 use `[OFFSET(95)]`, for P80 use `[OFFSET(80)]`. Adapt
    the offset for any user-requested percentile.
