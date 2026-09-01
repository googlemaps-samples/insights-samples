# RMI Query Catalog (GA)

This catalog maps business questions, analytical use cases, and persona objectives to runnable SQL sample assets available in the **General Availability (GA)** stage. All queries adhere to standard BigQuery GIS and RMI best practices.

---

## 1. BigQuery Admin
*Operational health, resource contention, security, slot allocations, and query cost auditing.*

1. **Metadata Inventory and Partition Overview**: How can I quickly check the row count and storage size of all RMI tables using zero-cost metadata queries?
   * [View SQL](../queries/bigquery_admin/bqa0_metadata_inventory.sql)
2. **Query Scan Volume & Billing Cost Audit**: Which user accounts and scheduled jobs are consuming the most billable scan volume on RMI tables?
   * [View SQL](../queries/bigquery_admin/bqa1_scan_volume.sql)
3. **Cost Attribution per Business Persona**: How do I attribute query execution costs to specific persona workflows and business departments?
   * [View SQL](../queries/bigquery_admin/bqa2_cost_attribution.sql)
4. **Unmanaged Derived Dataset & View Inventory**: How do I discover all unmanaged views and derived tables created on top of RMI tables?
   * [View SQL](../queries/bigquery_admin/bqa3_derived_resources.sql)
5. **High-Frequency Query Pattern & SRI Audit**: Which queries frequently unnest high-resolution Speed Reading Intervals (`speed_reading_intervals`), and what is their compute impact?
   * [View SQL](../queries/bigquery_admin/bqa4_query_patterns.sql)
6. **Full Table Scan & Partition Pruning Audit**: Which queries fail to apply partition pruning on `record_time` or `record_date`?
   * [View SQL](../queries/bigquery_admin/bqa5_partition_pruning.sql)
7. **Query Structural Complexity Audit**: How can I audit query complexity and geometry join performance across the platform?
   * [View SQL](../queries/bigquery_admin/bqa6_data_complexity_audit.sql)

---

## 2. Data Engineer
*Data pipelines, geometry integrity checks, SRI array flattening, and analysis-ready datasets.*

1. **Create Materialized Subset**: How do I generate a filtered, high-performance 7-day materialized view of `historical_travel_time` for a specific corridor?
   * [View SQL](../queries/data_engineer/de1_materialized_view.sql)
2. **Data Cleaning & Typed Column Promotion**: How do I produce a cleaned, typed version of route metadata with custom JSON attributes promoted to typed columns?
   * [View SQL](../queries/data_engineer/de2_data_cleaning.sql)
3. **SRI Flattening & Distance Metrics**: How do I transform nested SRI arrays into flattened spatial records with cumulative distance progress metrics?
   * [View SQL](../queries/data_engineer/de3_sri_flattening.sql)
4. **Attribute Extraction & Pivoting**: How do I parse unstructured JSON route attributes into structured columns?
   * [View SQL](../queries/data_engineer/de4_attribute_extraction.sql)
5. **Data Freshness Audit**: How do I monitor ingestion latency and delay across active routes?
   * [View SQL](../queries/data_engineer/de5_freshness_audit.sql)
6. **2-Stage Hourly Pre-Aggregation Pattern**: How do I transform 2-minute telemetry arrays into lightweight hourly profiles (>95% payload reduction) without losing peak traffic events?
   * [View SQL](../queries/data_engineer/de6_hourly_preaggregation.sql)
7. **Automated Status History**: How do I capture daily automated snapshots of route status using scheduled queries?
   * [View SQL](../queries/data_engineer/de7_routes_status_snapshot.sql)

---

## 3. Data Scientist
*Statistical analysis, anomaly detection, time-series forecasting, and route behavioral clustering.*

1. **Outlier Detection (Z-Score & IQR)**: How do I identify travel time records that are statistical outliers for a specific route?
   * [View SQL](../queries/data_scientist/ds1_outlier_detection.sql)
2. **Route Similarity Clustering**: How do I group routes based on their diurnal morning, midday, and evening delay profiles?
   * [View SQL](../queries/data_scientist/ds2_similarity_clustering.sql)
3. **Predictive Feature Engineering**: How do I generate a regularized, gap-aware hourly feature set for ML modeling?
   * [View SQL](../queries/data_scientist/ds3_feature_engineering.sql)
4. **Route Geometry Integrity Audit**: Which routes have a captured polyline geometry length that deviates significantly from the intended length?
   * [View SQL](../queries/data_scientist/ds4_route_integrity_audit.sql)
5. **Reliability Ranking & Persistence**: How do I compute Buffer Index (P95) and group consecutive delay spikes into persistent failure windows?
   * [View SQL](../queries/data_scientist/ds5_reliability_ranking.sql)
6. **Travel Time Forecasting (ARIMA_PLUS)**: How do I train and backtest a time-series model for future corridor travel times?
   * [View SQL](../queries/data_scientist/ds6_travel_time_forecasting.sql)
7. **Zero-Shot Multi-Route Forecasting (TimesFM)**: How do I forecast next-day traffic for multiple routes simultaneously using Google's TimesFM foundation model without per-route training?
   * [View SQL](../queries/data_scientist/ds7_zero_shot_forecasting.sql)
8. **Corridor Structural Shift Detection (ML.DETECT_CHANGE_POINTS)**: When did baseline corridor travel times undergo structural regime shifts or level changes without training custom models?
   * [View SQL](../queries/data_scientist/ds8_change_point_detection.sql)
9. **Corridor Secular Trend Decomposition & Forward Projection (ML.TREND)**: What is the underlying directional growth trajectory of corridor travel times once seasonal noise is removed, and where is it heading?
   * [View SQL](../queries/data_scientist/ds9_corridor_trend_decomposition.sql)
10. **Corridor Seasonality Decomposition & Diurnal Wave Extraction (ML.SEASONALITY)**: What are the exact additive hour-of-day and day-of-week recurring congestion penalties across monitored corridors?
   * [View SQL](../queries/data_scientist/ds10_corridor_seasonality_decomposition.sql)

---

## 4. RMI Planner
*Commercial ROI, value at risk, service tier analysis, and addressable monitoring scale.*

1. **Usage Growth Projection**: How do I forecast data volume and BigQuery compute spend as the monitored fleet scales?
   * [View SQL](../queries/rmi_planner/rmip1_usage_projection.sql)
2. **Customer ROI (Value at Risk)**: How do I quantify total hours of delay and financial value at risk across critical corridors?
   * [View SQL](../queries/rmi_planner/rmip2_customer_roi.sql)
3. **Road Segment Scale Estimation**: How do I estimate the physical scale and segment count of the addressable monitoring network?
   * [View SQL](../queries/rmi_planner/rmip3_segment_estimation.sql)
4. **Administrative Geofencing**: How do I create reusable city boundaries and geofences for localized business reporting?
   * [View SQL](../queries/rmi_planner/rmip4_area_boundary.sql)

---

## 5. Traffic Operations Manager
*Real-time corridor monitoring, severe incident alerts, and signal intervention auditing.*

1. **Peak Hour Delay Analysis**: What is the average travel time delay during morning peak hours (7-9 AM) for the top congested routes?
   * [View SQL](../queries/traffic_operations_manager/tom1_peak_hour_delay.sql)
2. **Persistent Bottlenecks**: Which road segments (SRIs) have been in a 'TRAFFIC_JAM' state most frequently?
   * [View SQL](../queries/traffic_operations_manager/tom2_persistent_bottlenecks.sql)
3. **Operational Health Check**: Which routes are currently flagged with a 'LOW_ROAD_USAGE' or operational error?
   * [View SQL](../queries/traffic_operations_manager/tom3_operational_health.sql)
4. **Data Collection Latency**: Are there any active routes that have stopped sending data near the end of the snapshot period?
   * [View SQL](../queries/traffic_operations_manager/tom4_data_latency.sql)
5. **Significant Event Alerts**: Which routes experienced a travel time more than double their free-flow baseline?
   * [View SQL](../queries/traffic_operations_manager/tom5_significant_event_detection.sql)
6. **Dynamic Detour & Path Variation Detection**: Which routes exhibit alternate detour trajectories and high delay penalties based on `road_segment_ids`Place ID sequences?
   * [View SQL](../queries/traffic_operations_manager/tom6_dynamic_detour_detection.sql)

---

## 6. Urban Planner
*Long-term performance trends, before-and-after project impact, and transit policy validation.*

1. **Long-Term Corridor Performance**: What is the week-over-week trend in the average delay ratio for a specific corridor?
   * [View SQL](../queries/urban_planner/up1_corridor_trend.sql)
2. **Before-and-After Impact Analysis**: Has average travel time on routes passing through a recent construction zone improved since completion?
   * [View SQL](../queries/urban_planner/up2_impact_analysis.sql)
3. **Traffic Monitoring Density**: Which geographic areas show the highest concentration of RMI route monitoring?
   * [View SQL](../queries/urban_planner/up3_monitoring_density.sql)
4. **Weekend vs. Weekday Trends**: How does average travel time in the afternoon differ between weekdays and weekends?
   * [View SQL](../queries/urban_planner/up4_weekend_vs_weekday.sql)
5. **Geofenced Congestion**: Within a specific downtown polygon, which routes are seeing travel times more than 50% above baseline?
   * [View SQL](../queries/urban_planner/up5_geofenced_congestion.sql)
