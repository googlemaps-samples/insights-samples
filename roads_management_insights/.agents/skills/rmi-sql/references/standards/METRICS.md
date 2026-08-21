# Industry Standard Metrics Backlog

This document tracks industry-standard transportation and logistics metrics, assessing their computability with the current RMI dataset and identifying any required dependencies or data gaps.

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

| Metric Name | Definition | Status | Assessment / Gaps |
| :--- | :--- | :--- | :--- |
| **Travel Time Index (TTI)** | Ratio of actual travel time to free-flow travel time. | ✅ Computable | Directly maps to our `duration_ratio`. Uses `SAFE_DIVIDE(duration, static_duration)`. |
| **Buffer Time Index (BTI)** | Extra time "buffer" needed to ensure on-time arrival at 95% confidence. | ✅ Computable | Realized via `(95th_percentile - average) / average`. Requires historical trend data. |
| **Planning Time Index (PTI)** | Total time needed to ensure 95% on-time arrival (95th percentile / free-flow). | ✅ Computable | Realized via `95th_percentile / static_duration`. |
| **Delay per Mile** | Total delay hours divided by total route length. | ✅ Computable | Requires `route_length` attribute (GA) or Road Network API geometry (Preview). |
| **Level of Service (LOS)** | A-F ranking based on speed/density thresholds. | ⚠️ Conditional | Requires domain-specific speed thresholds per road priority (Preview). |
| **Vehicle Hours of Delay (VHD)** | Sum of delay time multiplied by volume. | ❌ Gap | Requires **Traffic Volume/Flow** data, which is not natively in the RMI export. |

## 2. Retail & Logistics Performance

| Metric Name | Definition | Status | Assessment / Gaps |
| :--- | :--- | :--- | :--- |
| **On-Time Arrival Probability** | Heuristic probability of meeting a specific delivery window based on historical reliability. | ✅ Computable | Calculated using the distribution of `duration_in_seconds` for a specific route and hour. |
| **Predictability Score** | 1 / Standard Deviation of travel time. High score indicates a "stable" route. | ✅ Computable | Uses `STDDEV_POP(duration_in_seconds)` over a 30-day window. |
| **Congestion Exposure** | Percentage of a route's total time spent in `TRAFFIC_JAM` or `SLOW` states. | ✅ Computable | Calculated by summing the durations of SRIs in restricted states vs total duration. |

## 3. Environmental & Sustainability Metrics

| Metric Name | Definition | Status | Assessment / Gaps |
| :--- | :--- | :--- | :--- |
| **Idling Emission Impact** | Estimated carbon output specifically during "stop-and-go" periods. | ⚠️ Conditional | Requires vehicle-class emission factor models and SRI state transitions. |
| **Fuel Waste Index** | Estimated fuel consumed during "Excess Delay" periods (Duration - Static Duration). | ⚠️ Conditional | Requires joining with external **Fuel Consumption Models** based on speed profiles. |
| **Carbon Footprint per Trip** | Total estimated CO2 for a specific SelectedRoute record. | ⚠️ Conditional | Requires external **Emissions Factor** datasets mapped to average speeds. |

## 4. Operations & Safety Metrics

| Metric Name | Definition | Status | Assessment / Gaps |
| :--- | :--- | :--- | :--- |
| **Bottleneck Frequency** | Number of times a segment reaches a specific congestion threshold. | ✅ Computable | Realized via `UNNEST(speed_reading_intervals)` and counting `TRAFFIC_JAM` states. |
| **Start-Stop Frequency** | Number of vehicle restarts or "stop-and-go" cycles detected on a segment. | ✅ Computable | Inferred from `TRAFFIC_JAM` to `NORMAL` transitions in SRIs. (Inspired by Project Green Light). |
| **Incident Response Time** | Time between incident report and return to baseline flow. | ⚠️ Conditional | Requires an **External Incident Feed** (Waze, DOT) for correlation. |

## 5. Advanced Research-Driven Metrics (Experimental Context)
*Note: These metrics are inspired by Google Research initiatives but may not represent current RMI product outputs.*

| Metric Name | Concept / Paper Reference | Status | Assessment / Gaps |
| :--- | :--- | :--- | :--- |
| **Cycle Length Offset** | Analyzing signal phase synchronization. [Reference: [Project Green Light](https://research.google/blog/google-research-2023-beyond-traffic-light-optimization/)] | ⚠️ Conditional | Requires signal timing data (not in RMI). |
| **Phase Alignment (Green Wave)** | Modeling corridor-level continuous flow. [Reference: [Project Green Light](https://research.google/blog/google-research-2023-beyond-traffic-light-optimization/)] | ✅ Computable | Can be modeled by analyzing concurrent `NORMAL` states across sequential SelectedRoutes. |
