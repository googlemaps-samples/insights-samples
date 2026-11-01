# Industry Standard Metrics Backlog

This document tracks industry-standard transportation and logistics metrics, assessing their computability with modern RMI datasets (`speed_reading_offsets`, `has_road_closure`, `road_segment_ids`) and identifying required dependencies or data gaps.

## Assessment Framework

- **Name**: Common industry name of the metric.
- **Definition**: Technical formula or business definition.
- **Status**:
  - ✅ **Computable**: Can be realized with GA/Preview RMI data.
  - ⚠️ **Conditional**: Requires external data (Weather, Incidents, etc.).
  - ❌ **Gap**: Fundamental data (e.g., Volume/Flow) is currently missing.
- **Implementation**: Link to sample SQL or technical capability.

---

## 1. Reliability & Congestion Metrics

| Metric Name | Definition | Status | Assessment / Implementation |
| :--- | :--- | :--- | :--- |
| **Travel Time Index (TTI)** | Ratio of actual travel time to free-flow travel time. | ✅ Computable | Directly maps to `delay_ratio`. Uses `SAFE_DIVIDE(duration_in_seconds, static_duration_in_seconds)` filtering out road closures where duration is NULL. |
| **Buffer Time Index (BTI)** | Extra time "buffer" needed to ensure on-time arrival at 95% confidence. | ✅ Computable | Realized via `(95th_percentile - average) / average`. Requires historical trend data. |
| **Planning Time Index (PTI)** | Total time needed to ensure 95% on-time arrival (95th percentile / free-flow). | ✅ Computable | Realized via `95th_percentile / static_duration_in_seconds`. |
| **Delay per Mile** | Total delay hours divided by total route length. | ✅ Computable | Requires `route_attributes.route_length` or `ST_LENGTH(route_geometry)`. |
| **Detour Delay Multiplier** | Ratio of travel duration along detour path variations vs. baseline path. | ✅ Computable | Realized via `SAFE_DIVIDE(detour_avg_duration, baseline_avg_duration)` comparing `historical_travel_time.road_segment_ids` against `routes_status.road_segment_ids` when `dynamic_routing = true`. |
| **Full Road Closure Downtime** | Total hours or observation count during which a corridor was impassable. | ✅ Computable | Realized via `COUNTIF(has_road_closure IS TRUE)` and tracking closure timestamps where `duration_in_seconds IS NULL`. |
| **Level of Service (LOS)** | A-F ranking based on speed/density thresholds. | ⚠️ Conditional | Requires domain-specific speed thresholds per road priority class. |
| **Vehicle Hours of Delay (VHD)** | Sum of delay time multiplied by volume. | ❌ Gap | Requires **Traffic Volume/Flow** data, which is not natively in the foundation RMI export (available in RMI Vehicle Counts preview). |

## 2. Retail & Logistics Performance

| Metric Name | Definition | Status | Assessment / Implementation |
| :--- | :--- | :--- | :--- |
| **On-Time Arrival Probability** | Heuristic probability of meeting a specific delivery window based on historical reliability. | ✅ Computable | Calculated using distribution of `duration_in_seconds` for a specific route and hour on open corridors. |
| **Predictability Score** | 1 / Standard Deviation of travel time. High score indicates a "stable" route. | ✅ Computable | Uses `STDDEV_POP(duration_in_seconds)` over a 30-day window. |
| **Congestion Exposure** | Percentage of a route's total distance spent in `TRAFFIC_JAM_HEAVY`, `TRAFFIC_JAM`, or `SLOW` states. | ✅ Computable | Calculated via `speed_reading_offsets` integer arithmetic: `SUM(CASE WHEN speed IN ('TRAFFIC_JAM_HEAVY', 'TRAFFIC_JAM') THEN (end_offset - start_offset) END) / route_length`. |
| **Standstill Gridlock Mileage** | Total kilometers of road under complete standstill (`TRAFFIC_JAM_HEAVY`). | ✅ Computable | Sum of `(end_offset - start_offset) / 1000.0` for intervals with `speed = 'TRAFFIC_JAM_HEAVY'`. |

## 3. Environmental & Sustainability Metrics

| Metric Name | Definition | Status | Assessment / Implementation |
| :--- | :--- | :--- | :--- |
| **Idling Emission Impact** | Estimated carbon output specifically during "stop-and-go" gridlock. | ⚠️ Conditional | Modeled using `TRAFFIC_JAM_HEAVY` duration and vehicle-class emission factor models. |
| **Fuel Waste Index** | Estimated fuel consumed during "Excess Delay" periods (Duration - Static Duration). | ⚠️ Conditional | Requires joining with external **Fuel Consumption Models** based on speed profiles. |
| **Carbon Footprint per Trip** | Total estimated CO2 for a specific SelectedRoute record. | ⚠️ Conditional | Requires external **Emissions Factor** datasets mapped to average speeds. |

## 4. Operations & Safety Metrics

| Metric Name | Definition | Status | Assessment / Implementation |
| :--- | :--- | :--- | :--- |
| **Bottleneck Frequency** | Number of times a segment reaches a severe congestion threshold. | ✅ Computable | Realized via `UNNEST(speed_reading_offsets)` and counting `TRAFFIC_JAM` and `TRAFFIC_JAM_HEAVY` occurrences. |
| **Start-Stop Frequency** | Number of vehicle restarts or "stop-and-go" cycles detected along a corridor. | ✅ Computable | Inferred from transitions between `NORMAL` and `TRAFFIC_JAM` / `TRAFFIC_JAM_HEAVY` in sequential offsets. |
| **Closure Incident Duration** | Time elapsed between first detection of `has_road_closure = true` and restoration of passable flow. | ✅ Computable | Calculated via `MIN(record_time)` to `MAX(record_time)` on contiguous closure intervals. |
| **Incident Response Time** | Time between external incident report and return to baseline flow. | ⚠️ Conditional | Requires an **External Incident Feed** (Waze, DOT, or RMI Real-Time Disruptions) for correlation. |

## 5. Advanced Research-Driven Metrics (Experimental Context)

*Note: These metrics are inspired by Google Research initiatives but may not represent current RMI product outputs.*

| Metric Name | Concept / Paper Reference | Status | Assessment / Implementation |
| :--- | :--- | :--- | :--- |
| **Cycle Length Offset** | Analyzing signal phase synchronization. [Reference: [Project Green Light](https://research.google/blog/google-research-2023-beyond-traffic-light-optimization/)] | ⚠️ Conditional | Requires signal timing data (not in foundation RMI). |
| **Phase Alignment (Green Wave)** | Modeling corridor-level continuous flow. [Reference: [Project Green Light](https://research.google/blog/google-research-2023-beyond-traffic-light-optimization/)] | ✅ Computable | Can be modeled by analyzing concurrent `NORMAL` states across sequential SelectedRoutes. |
