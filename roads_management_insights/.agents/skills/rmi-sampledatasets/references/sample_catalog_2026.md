# Global RMI Sample Datasets Catalog (2026)

This reference outlines the complete catalog of 11 multi-region sample datasets published on BigQuery Analytics Hub via exchange **`rmi_sampledata_v2_ga_prod`**.

---

## 1. Analytics Hub Public Data Exchange

- **Exchange URL**: [Analytics Hub: `rmi_sampledata_v2_ga_prod`](https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/1024202510105/locations/us/dataExchanges/rmi_sampledata_v2_ga_prod)
- **Project**: `1024202510105`
- **Location**: `us`
- **Exchange ID**: `rmi_sampledata_v2_ga_prod`
- **Access Model**: Publicly subscribable by any user with a Google account to link directly into their own BigQuery project without egress or storage fees.

---

## 2. Regional Listings Matrix

| # | Listing ID | Region / Metro Area | Source BigQuery Dataset | Primary Route Monitoring Strategy | Timeframe |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **`boston_ga`** | Boston, MA (USA) | `src_boston_ga` | Priority road network (`CONTROLLED_ACCESS`, `LIMITED_ACCESS`, `PRIMARY_HIGHWAY`, `SECONDARY_ROAD`, `MAJOR_ARTERIAL`, `MINOR_ARTERIAL`) (~1,847 routes) | Spring/Summer 2026 |
| 2 | **`src_buenosaires_ga`** | Buenos Aires (Argentina) | `src_buenosaires_ga` | Top road priorities across Ciudad Autónoma de Buenos Aires | Spring/Summer 2026 |
| 3 | **`detroit_ga`** | Detroit, MI (USA) | `src_detroit_ga` | Priority corridors (`CONTROLLED_ACCESS`, `PRIMARY_HIGHWAY`, `SECONDARY_ROAD`) | Spring/Summer 2026 |
| 4 | **`manhattan_ga`** | Manhattan / NYC (USA) | `src_manhattan_ga` | OD pairs from Manhattan to major airports (LGA, JFK, EWR) with 0 intermediate waypoints for dynamic pathing | Spring/Summer 2026 |
| 5 | **`paris_ga`** | Paris (France) | `src_paris_ga` | Blvd Périphérique ring-road and intersecting radial feeder segments | Spring/Summer 2026 |
| 6 | **`rome_ga`** | Rome (Italy) | `src_rome_ga` | OD pairs from Colosseum to suburban destinations (Cerveteri, Piana del Sole, Castel Gandolfo, Villa Adriana) | Spring/Summer 2026 |
| 7 | **`saopaulostate_ga`** | São Paulo State (Brazil) | `src_saopaulostate_ga` | Top road priorities within 200 km radius of central São Paulo | Spring/Summer 2026 |
| 8 | **`singapore_ga`** | Singapore | `src_singapore_ga` | Major expressway and arterial network across Singapore | Spring/Summer 2026 |
| 9 | **`sydney_ga`** | Sydney (Australia) | `src_sydney_ga` | Metropolitan highways (`CONTROLLED_ACCESS`, `LIMITED_ACCESS`) | Spring/Summer 2026 |
| 10 | **`tokyo_ga`** | Tokyo (Japan) | `src_tokyo_ga` | Major priority roads across Tokyo 23 Wards | Spring/Summer 2026 |
| 11 | **`westyorkshire_ga`** | West Yorkshire (UK) | `src_westyorkshire_ga` | Regional corridor monitoring for West Yorkshire | Spring/Summer 2026 |

---

## 3. Subscribing via CLI

Use the [`api-analyticshub`](../api-analyticshub/SKILL.md) client to programmatically subscribe to any of these listings:

```bash
source api-analyticshub/scripts/analyticshub_v1.sh

# Example: Subscribe to the Boston listing into your project
sub_req=$(create_subscribe_listing_request_json "projects/my-project/datasets/ah_rmi_boston")
analyticshub_projects_locations_dataExchanges_listings_subscribe \
  "1024202510105" "us" "rmi_sampledata_v2_ga_prod" "boston_ga" "${sub_req}"
```

---

## 4. Key Schema Notes & Thresholds

1. **`road_segment_ids` Schema Threshold**: Introduced on **June 19, 2026**. Telemetry recorded on or after this date includes populated road segment arrays for path variation analysis. Always guard unnesting queries:
   ```sql
   WHERE record_time >= '2026-06-19' AND ARRAY_LENGTH(road_segment_ids) > 0
   ```
2. **Static Timeframe Clamping**: All sample datasets are time-bounded. When evaluating queries, anchor timestamps to the documented snapshot window (e.g. `record_time BETWEEN '2026-06-01' AND '2026-06-30'`).
