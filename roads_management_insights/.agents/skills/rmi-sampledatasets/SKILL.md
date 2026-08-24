---
name: rmi-sampledatasets
description: Specialized guidance for discovering, subscribing to, and working with Roads Management Insights (RMI) public sample datasets across global metropolitan areas (Boston, Paris, Tokyo, Detroit, Manhattan, Rome, Singapore, Sydney, Buenos Aires, São Paulo State). Use when Gemini CLI needs to list available datasets from Analytics Hub via api-analyticshub, validate queries against sample data, estimate production costs based on sample baselines, or ensure correct temporal filtering for static snapshots.
dependencies:
  - api-analyticshub
  - bigquery-practices
---

# RMI Sample Datasets (`rmi-sampledatasets`)

This skill provides comprehensive context, architectural scaling methods, automated listing discovery tools, and strict static temporal constraints for working with the Roads Management Insights (RMI) public sample datasets published on BigQuery Analytics Hub.

---

## 1. Multi-Region Global Sample Catalog

RMI maintains 11 localized, pre-subscribed sample datasets on Google Cloud Analytics Hub. Anyone with a standard Google account can access and subscribe to these listings directly into their own BigQuery project for zero-copy, zero-egress analysis:

- **Public Analytics Hub Exchange**: [Analytics Hub Data Exchange: `rmi_sampledata_v2_ga_prod`](https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/1024202510105/locations/us/dataExchanges/rmi_sampledata_v2_ga_prod)
- **Publisher Project ID**: `1024202510105`
- **Location**: `us`
- **Exchange ID**: `rmi_sampledata_v2_ga_prod`

### Active Regional Listings Snapshot

> [!TIP]
> **Dynamic Exchange Discovery Recommended**: The table below represents a documented reference snapshot. Because new sample regions, extended time windows, and updated snapshot listings are continuously published to the exchange, **always prefer querying the live Analytics Hub exchange dynamically** using the bundled discovery tool ([`scripts/list_sample_datasets.sh`](scripts/list_sample_datasets.sh)) or the [`api-analyticshub`](../api-analyticshub/SKILL.md) API client to inspect the most up-to-date catalog.

| # | Listing ID | Metro Area / Region | Source BigQuery Dataset | Primary Route Monitoring Strategy | Baseline Window |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **`boston_ga`** | **Boston, MA (USA)** | `src_boston_ga` | Priority road network (`CONTROLLED_ACCESS`, `LIMITED_ACCESS`, `PRIMARY_HIGHWAY`, `SECONDARY_ROAD`, `MAJOR_ARTERIAL`, `MINOR_ARTERIAL`) (~1,847 routes) | Spring/Summer 2026 |
| 2 | **`src_buenosaires_ga`** | **Buenos Aires (Argentina)** | `src_buenosaires_ga` | Top road priorities across Ciudad Autónoma de Buenos Aires | Spring/Summer 2026 |
| 3 | **`detroit_ga`** | **Detroit, MI (USA)** | `src_detroit_ga` | Priority corridors (`CONTROLLED_ACCESS`, `PRIMARY_HIGHWAY`, `SECONDARY_ROAD`) | Spring/Summer 2026 |
| 4 | **`manhattan_ga`** | **Manhattan / NYC (USA)** | `src_manhattan_ga` | Origin-Destination pairs from Manhattan to major airports (LGA, JFK, EWR) with 0 intermediate waypoints for dynamic pathing | Spring/Summer 2026 |
| 5 | **`paris_ga`** | **Paris (France)** | `src_paris_ga` | Blvd Périphérique ring-road and connected radial feeder segments | Spring/Summer 2026 |
| 6 | **`rome_ga`** | **Rome (Italy)** | `src_rome_ga` | Origin-Destination pairs from Colosseum to suburban destinations (Cerveteri, Piana del Sole, Castel Gandolfo, Villa Adriana) | Spring/Summer 2026 |
| 7 | **`saopaulostate_ga`** | **São Paulo State (Brazil)** | `src_saopaulostate_ga` | Top road priorities within 200 km radius of central São Paulo | Spring/Summer 2026 |
| 8 | **`singapore_ga`** | **Singapore** | `src_singapore_ga` | Major expressway and arterial network across Singapore | Spring/Summer 2026 |
| 9 | **`sydney_ga`** | **Sydney (Australia)** | `src_sydney_ga` | Metropolitan highways (`CONTROLLED_ACCESS`, `LIMITED_ACCESS`) | Spring/Summer 2026 |
| 10 | **`tokyo_ga`** | **Tokyo (Japan)** | `src_tokyo_ga` | Major priority roads across Tokyo 23 Wards | Spring/Summer 2026 |
| 11 | **`westyorkshire_ga`** | **West Yorkshire (UK)** | `src_westyorkshire_ga` | Regional corridor monitoring for West Yorkshire | Spring/Summer 2026 |




---

## 2. Automated Discovery Tooling (`scripts/list_sample_datasets.sh`)

This skill includes an executable CLI discovery tool [`scripts/list_sample_datasets.sh`](scripts/list_sample_datasets.sh) that leverages the [`api-analyticshub`](../api-analyticshub/SKILL.md) API client to query the live Analytics Hub exchange and output real-time metadata.

### Usage Commands

```bash
# 1. Format and print human-readable catalog table and route criteria
./scripts/list_sample_datasets.sh

# 2. Output raw JSON payload from the Analytics Hub API for automated parsing
./scripts/list_sample_datasets.sh --json
```

### Subscribing to a Listing via API

To link any listing directly into your destination BigQuery project:

```bash
source api-analyticshub/scripts/analyticshub_v1.sh

# 1. Create subscription payload
sub_payload=$(create_subscribe_listing_request_json "projects/MY_PROJECT/datasets/ah_rmi_boston")

# 2. Subscribe to listing
analyticshub_projects_locations_dataExchanges_listings_subscribe \
  "1024202510105" "us" "rmi_sampledata_v2_ga_prod" "boston_ga" "${sub_payload}"
```

---

## 3. Key Principles for Sample Dataset Usage

### 1. The Static Temporal Anchor Mandate
Because public sample datasets are historical snapshots, any queries utilizing `CURRENT_TIMESTAMP()`, `CURRENT_DATE()`, or relative offsets (e.g. `TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)`) will return **zero rows**.
* **Mandatory Pattern**: You **must** replace all relative time filters with static datetime literals matching the snapshot's active timeframe (e.g. June 2026).

```sql
-- INCORRECT (Returns 0 rows on static sample datasets)
WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)

-- CORRECT (Captures the active Spring/Summer 2026 snapshot window)
WHERE record_time BETWEEN '2026-06-01' AND '2026-07-01'
```

### 2. The `road_segment_ids` Schema Threshold (June 19, 2026)
The `road_segment_ids` column was introduced on **June 19, 2026**. Telemetry snapshots captured prior to this date contain empty arrays (`[]`). Always guard segment unnesting queries:
```sql
WHERE record_time >= '2026-06-19'
  AND ARRAY_LENGTH(road_segment_ids) > 0
```

### 3. Route Attributes Metadata & Mandatory Type Casting
Routes in `routes_status` include a JSON string column `route_attributes` containing automatically populated contextual metadata. 

> [!IMPORTANT]
> **Strict String Key-Value Representation**: RMI route attributes are defined as a strict `map<string, string>`. Consequently, **all values are stored as string literals**, even inherently numeric properties (e.g., `route_length_meters` is stored as `"128.088"` rather than a float, and `num_of_roads` is stored as `"3"` rather than an integer). You **must explicitly typecast** these values using `SAFE_CAST()` in BigQuery SQL when performing arithmetic, aggregations, or numeric range filtering (e.g., `SAFE_CAST(JSON_VALUE(route_attributes, '$.route_length_meters') AS FLOAT64) >= 500.0`) to avoid lexicographical string comparison errors.

| Attribute Key | Storage Type | Logical Type | Description | Example String Value |
| :--- | :--- | :--- | :--- | :--- |
| **`sampledataset`** | `STRING` | String | Metropolitan region or partition identifier. | `"boston"`, `"paris"`, `"sydney"` |
| **`priority`** | `STRING` | Enum String | Road hierarchy class (`ROAD_PRIORITY_CONTROLLED_ACCESS`, `ROAD_PRIORITY_PRIMARY_HIGHWAY`, `ROAD_PRIORITY_SECONDARY_ROAD`, `ROAD_PRIORITY_LIMITED_ACCESS`, `ROAD_PRIORITY_MAJOR_ARTERIAL`, `ROAD_PRIORITY_MINOR_ARTERIAL`). | `"ROAD_PRIORITY_CONTROLLED_ACCESS"` |
| **`route_length_meters`** | `STRING` | Float | Modeled physical length of the route corridor in meters (requires `SAFE_CAST(... AS FLOAT64)`). | `"128.088"` |
| **`num_of_roads`** | `STRING` | Integer | Number of underlying road segments composing the corridor (requires `SAFE_CAST(... AS INT64)`). | `"1"`, `"3"` |
| **`road_first_placeid`** | `STRING` | Place ID | Google Maps Place ID for the first/entry segment of the corridor. | `"ChIJBaTdJ76uEmsRouRmspMwbFQ"` |
| **`road_last_placeid`** | `STRING` | Place ID | Google Maps Place ID for the last/exit segment of the corridor. | `"ChIJLY-VzAmVEmsR_L_4WFvlXxo"` |
| **`node_origin_id`** / **`node_destination_id`** | `STRING` | String | Topological node identifiers for corridor endpoints. | `"Lk-M8QaThtw"`, `"CmseLaD6kKs"` |
| **`roads_snapshot`** | `STRING` | Date String | Date identifier of the underlying road network geometry snapshot. | `"20260518"` |
| **`create_time`** / **`origin`** / **`destination`** | `STRING` | Timestamp / Coordinates | Registration timestamp and coordinate strings for fixed OD pairs (e.g. Manhattan, Rome). | `"2025-10-15T01:10:45.490Z"` |

#### BigQuery Extraction & Casting Pattern
```sql
SELECT 
  selected_route_id,
  display_name,
  JSON_VALUE(route_attributes, '$.priority') AS road_priority,
  -- Explicit SAFE_CAST for numeric attributes stored as strings
  SAFE_CAST(JSON_VALUE(route_attributes, '$.route_length_meters') AS FLOAT64) AS length_meters,
  SAFE_CAST(JSON_VALUE(route_attributes, '$.num_of_roads') AS INT64) AS segment_count
FROM 
  `LINKED_DATASET_NAME.routes_status`
WHERE 
  -- Numeric range filter using SAFE_CAST
  SAFE_CAST(JSON_VALUE(route_attributes, '$.route_length_meters') AS FLOAT64) >= 500.0
  AND JSON_VALUE(route_attributes, '$.priority') = 'ROAD_PRIORITY_CONTROLLED_ACCESS';
```

### 4. Multi-Tiered Cost and Fleet Scaling Projections
The sample datasets are lightweight and highly partitioned, making interactive validation queries inexpensive (< $0.01 per scan). Use the scaling multipliers below to project production costs:

| Fleet Tier | Monitored Routes | Multiplier vs. Sample Base | Monthly Bytes (Approx.) | Scan Cost Category |
| :--- | :--- | :--- | :--- | :--- |
| **Sample Baseline** | ~1,850 Routes | 1x (Base) | ~1.6 GB / month | Negligible (< $0.01) |
| **City-Wide Fleet** | ~10,000 Routes | ~5.4x | ~8.6 GB / month | Minimal (< $0.05) |
| **State / Regional Fleet** | ~50,000 Routes | ~27x | ~43 GB / month | Moderate (~$0.22) |
| **Mega Fleet (Nationwide)** | ~500,000 Routes | ~270x | ~430 GB / month | Strategic (~$2.15) |

### 5. Complexity Classes
- **O(T) - Time-Dependent (Linear Growth)**: Multi-month longitudinal trend queries. Storage scan sizes grow linearly with time.
- **O(1) - Time-Invariant (Flat Cost)**: Operational queries with bounded partition pruning (`record_time BETWEEN ...`).
- **O(R) - Route-Dependent (Metadata Growth)**: Administrative queries filtering on `routes_status`.

---

## 4. Troubleshooting & Common Pitfalls

| Symptom / Error | Root Cause | Corrective Recovery Action |
| :--- | :--- | :--- |
| **Zero rows returned** | Using relative datetime functions like `CURRENT_TIMESTAMP()`. | Replace with static anchors (e.g. `BETWEEN '2026-06-01' AND '2026-07-01'`). |
| **`road_segment_ids` empty or missing** | Querying date partitions prior to June 19, 2026 threshold. | Add filter `WHERE record_time >= '2026-06-19' AND ARRAY_LENGTH(road_segment_ids) > 0`. |
| **Inaccurate Dry Run Cost** | Missing date partition filters causing full-table scan estimate. | Apply partition filters on `record_time` first before evaluating dry-run byte counts. |
| **Mismatched coordinate comparisons** | Attempting joins on floating-point latitude/longitude coordinates. | Never join on spatial float coordinates. Use `selected_route_id` as the robust primary join key. |

---

## 5. References & Linked Artifacts

* [Analytics Hub Data Exchange: `rmi_sampledata_v2_ga_prod`](https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/1024202510105/locations/us/dataExchanges/rmi_sampledata_v2_ga_prod)
* [Boston 2026 Dataset Metadata Reference](references/boston_2026.md)
* [RMI Multipliers & Ingestion Costs](references/metrics.md)
* [Discovery Script: `list_sample_datasets.sh`](scripts/list_sample_datasets.sh)

---

## 6. Examples

### Example 1: Morning Commute Peak Performance Audit
Analyze average speed drops during morning rush hour (7:00 AM – 9:00 AM UTC) across the Boston network for June 2026:
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
  `LINKED_DATASET_NAME.historical_travel_time`
WHERE 
  -- Static Temporal Anchor matching active Spring/Summer 2026 snapshot
  record_time BETWEEN '2026-06-01' AND '2026-07-01'
  -- Morning commute hour bounds
  AND EXTRACT(HOUR FROM record_time) BETWEEN 7 AND 9
GROUP BY 
  selected_route_id
ORDER BY 
  peak_tti DESC;
```

### Example 2: Operational Route Status & Attribute Mapping
Count active routes and list validation states grouped by custom regions defined in route metadata:
```sql
SELECT 
  JSON_VALUE(route_attributes, '$.priority') AS priority_tier,
  status,
  validation_error,
  COUNT(1) AS route_count
FROM 
  `LINKED_DATASET_NAME.routes_status`
GROUP BY 
  priority_tier,
  status,
  validation_error
ORDER BY 
  route_count DESC;
```
