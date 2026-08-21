# RMI Known Limitations (Data & Infrastructure)

This document tracks technical limitations, data gaps, or metrics that are frequently requested by users but currently **cannot be realized** with the standard RMI export or surrounding infrastructure.

## Purpose
This serves as a critical input for the **Feasibility Assessment** step of the AI agent workflow. If a request matches an item here, the agent can provide a precise explanation of the current limitation.

**Note on Roadmap**: While certain limitations documented here are currently being addressed by the RMI product roadmap, these upcoming features are not fully documented in this project until they are ready for official Preview or GA release. **Early information and prototypes may be added under the `experimental/` stage** for internal project context, but will not be included in public-facing publications.

---

## 1. Data Gaps

| Requested Information | Limitation Status | Future Path |
| :--- | :--- | :--- |
| **Traffic Volume / Flow Rate** | Absolute vehicle counts (Volume) are not included in the standard RMI export. | Integration with 3rd-party sensor aggregators. |
| **Vehicle Type Breakdown** | Metrics (duration, speed) are aggregated across all vehicle classes. Separate breakdowns (e.g., Trucks, EVs) are not provided. | Statistical modeling based on external fleet distributions. |
| **Lane-Level Metrics** | Data is provided at the segment level. No distinction is made between HOV, express, or general-purpose lanes. | High-precision data research. |
| **Real-time Incident Details** | Specific incident causes/details are not bundled with RMI. RMI measures the *impact* (delay) only. | Correlation with external incident feeds in BigQuery. |
| **Historical SRI Archive** | `recent_roads_data` maintains a rolling 60-day window. Long-term historical SRI analysis is limited by this retention period. | Custom long-term archiving pipelines. |
| **Short Route Metrics** | `static_duration_in_seconds` is often NULL for routes shorter than **~23 meters**. | **Mandatory**: Perform per-row filtering (`WHERE static_duration_in_seconds > 0`) early in CTEs before calculating ratios. Do not assume route-level consistency. |

## 2. Technical & Privacy Constraints

| Requested Information | Constraint | Mitigation / Reference |
| :--- | :--- | :--- |
| **Individual Vehicle Telemetry** | Raw individual vehicle traces are not exported to protect driver privacy. RMI data is aggregated at the route and segment level. | Use aggregate Speed Reading Intervals (SRIs). |
| **Differential Privacy (DP)** | To ensure user anonymity, RMI data employs DP techniques like **clamping** and **geographic thresholding**. | Metrics are only released for partitions with enough users. [Ref: [Google Privacy Research](https://blog.google/technology/safety-security/google-privacy-sandbox-differential-privacy/)] |
| **Sub-meter Path Precision** | Captured geodesic lines are accurate within approximately 10 meters. Sub-meter (lane-level) path precision is not currently available. | Store raw coordinate sequences in separate metadata. |

## 3. Infrastructure & Compatibility

| Requested Information | Constraint | Future Path |
| :--- | :--- | :--- |
| **Cross-Basemap Stable IDs** | Universal mapping between Google `road_id` and external identifiers (e.g., OSM, HERE) is not natively provided. | SharedStreets or specialized mapping services. |
| **Native Microscopic Simulation** | Predictive simulation of the ripple effect of network changes is not supported natively within BigQuery. | Integration with simulation platformip. |

## 4. Metric Transparency

| Requested Information | Limitation / Lack of Exposure |
| :--- | :--- |
| **Travel Time Computation** | The specific proprietary algorithms used to compute `duration_in_seconds` are not exposed. |
| **Speed Classification Thresholds** | The exact thresholds used to categorize segments into `NORMAL`, `SLOW`, or `TRAFFIC_JAM` are not published. |
