# RMI Known Limitations (Data & Infrastructure)

This document tracks technical limitations, data gaps, or metrics that are frequently requested by users but currently **cannot be realized** with the standard RMI export or surrounding infrastructure, along with architectural invariants and deprecation schedules.

## Purpose

This serves as a critical input for the **Feasibility Assessment** step of the AI agent workflow. If a request matches an item here, the agent can provide a precise explanation of the current limitation and recommend appropriate mitigations.

**Note on Roadmap**: While certain limitations documented here are currently being addressed by the RMI product roadmap, these upcoming features are not fully documented in this project until they are ready for official Preview or GA release.

---

## 1. Data Invariants & Schema Constraints

| Feature / Field | Constraint / Invariant | Safe Query Mitigation |
| :--- | :--- | :--- |
| **Road Closures & Duration Nullability** | When `has_road_closure = true`, `duration_in_seconds` and `speed_reading_offsets` are omitted (`NULL`) because travel duration cannot be computed for an impassable corridor. | **Mandatory**: Do not use naive `WHERE duration_in_seconds IS NOT NULL` without auditing closures! When filtering for passable traffic, use `WHERE (has_road_closure IS FALSE OR has_road_closure IS NULL) AND duration_in_seconds IS NOT NULL`. To audit closures, query `WHERE has_road_closure = TRUE`. |
| **Legacy SRI Coordinate Sunset** | `speed_reading_intervals` (with `interval_coordinates` and `ST_MAKELINE`) is phasing out and may cease population on or after **January 13, 2027**. | Migrate all production analytical queries to `speed_reading_offsets` (`start_offset`, `end_offset`, `speed`) available as of October 8, 2026. |
| **Topological Road Segment IDs Cutoff** | `road_segment_ids` was added on **June 19, 2026**. Records prior to this cutoff contain empty or NULL arrays. | Enforce `WHERE record_time >= '2026-07-01' AND ARRAY_LENGTH(road_segment_ids) > 0` and always use `LEFT JOIN UNNEST(road_segment_ids)`. |
| **Offset-Based Speed Intervals Cutoff** | `speed_reading_offsets` was introduced on **October 8, 2026**. Historical partitions prior to this date contain NULL for offsets. | Use `speed_reading_offsets` for queries analyzing data from October 8, 2026 onward. Use COALESCE patterns during transition windows. |
| **Custom Route Attributes Capacity** | `route_attributes` supports a maximum of **25 key-value string pairs** (keys $\le 100$ characters, values must be stringified). | For high-cardinality metadata exceeding 25 pairs, maintain an external correlation table in BigQuery keyed by `selected_route_id`. |
| **Short Route Metrics** | `static_duration_in_seconds` is often NULL for routes shorter than **~23 meters**. | **Mandatory**: Perform per-row filtering (`WHERE (static_duration_in_seconds > 0 OR has_road_closure IS TRUE)`) early in CTEs before calculating ratios. |

---

## 2. Fundamental Data Gaps

| Requested Information | Limitation Status | Future Path / Alternative |
| :--- | :--- | :--- |
| **Traffic Volume / Flow Rate** | Absolute vehicle counts (Volume) are not included in the standard foundation RMI export. | Integration with RMI Vehicle Counts (preview) or 3rd-party sensor aggregators. |
| **Vehicle Type Breakdown** | Metrics (duration, speed) are aggregated across all vehicle classes. Separate breakdowns (e.g., Trucks, EVs) are not provided. | Statistical modeling based on external fleet distributions. |
| **Lane-Level Metrics** | Data is provided at the segment level. No distinction is made between HOV, express, or general-purpose lanes. | High-precision data research. |
| **Real-time Incident Causes** | Specific incident causes/details (accident details, construction permits) are not bundled with foundation RMI. RMI measures the *impact* (delay/closure) only. | Correlation with RMI Real-Time Disruptions or external incident feeds. |
| **Historical SRI Archive** | `recent_roads_data` maintains a rolling 60-day window. Long-term historical SRI analysis is limited by this retention period. | Deploy daily scheduled snapshot queries to a customer-managed partitioned archive table. |

---

## 3. Technical & Privacy Constraints

| Requested Information | Constraint | Mitigation / Reference |
| :--- | :--- | :--- |
| **Individual Vehicle Telemetry** | Raw individual vehicle traces are not exported to protect driver privacy. RMI data is aggregated at the route and segment level. | Use aggregate Speed Reading Offsets (`speed_reading_offsets`). |
| **Differential Privacy (DP)** | To ensure user anonymity, RMI data employs DP techniques like **clamping** and **geographic thresholding**. | Metrics are only released for partitions with enough users. [Ref: [Google Privacy Research](https://blog.google/technology/safety-security/google-privacy-sandbox-differential-privacy/)] |
| **Sub-meter Path Precision** | Captured geodesic lines are accurate within approximately 10 meters. Sub-meter (lane-level) path precision is not currently available. | Use Road Network API v2 for surveyed centerlines. |

---

## 4. Infrastructure & Compatibility

| Requested Information | Constraint | Future Path |
| :--- | :--- | :--- |
| **Cross-Basemap Stable IDs** | Universal mapping between Google Place IDs / Road IDs and external identifiers (e.g., OSM, HERE) is not natively provided. | SharedStreets or spatial intersection with Overture Maps. |
| **Native Microscopic Simulation** | Predictive simulation of the ripple effect of network changes is not supported natively within BigQuery. | Integration with traffic simulation platforms (e.g., Aimsun, MATSim). |

---

## 5. Metric Transparency

| Requested Information | Limitation / Lack of Exposure |
| :--- | :--- |
| **Travel Time Computation** | The specific proprietary machine learning algorithms used by Google to compute `duration_in_seconds` are not exposed. |
| **Speed Classification Thresholds** | The exact speed delta thresholds used to categorize segments into `NORMAL`, `SLOW`, `TRAFFIC_JAM`, and `TRAFFIC_JAM_HEAVY` are dynamically calibrated by Google Maps and not published as fixed static constants. |
