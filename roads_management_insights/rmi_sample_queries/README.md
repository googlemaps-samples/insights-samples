# Road Management Insights (RMI) - Sample Query Library

This folder contains a curated library of SQL queries and interactive notebooks designed for the Road Management Insights (RMI) BigQuery dataset. These assets are organized by analytical persona to help users quickly find the right starting point for their specific use case.

## 📂 Folder Structure

- **`/queries`**: A collection of verified SQL queries categorized by persona. These queries demonstrate best practices for querying the RMI data model, including travel time analysis, bottleneck detection, and spatial joins.
- **`/notebooks`**: Interactive Jupyter notebooks ready to be opened in Google Colab or BigQuery Studio. These notebooks provide a guided environment to execute the sample queries against the RMI sample dataset.

## 🚀 Getting Started

1. **Browse Queries**: Explore the roles below to find working SQL samples for your specific business questions.
2. **Interactive Analysis**: Open the `.ipynb` files in the `/notebooks` directory for a guided, hands-on experience.
3. **Dataset**: All queries are designed to run against the `boston_oct_2025_sample_data` shared dataset.

---

## 👥 Query Catalog by Persona

### Traffic Operations Manager
*Real-time monitoring and immediate bottleneck detection.*

1.  **Peak Hour Delay Analysis**: What is the average travel time delay during the morning peak (7-9 AM) for the top 10 most congested routes?
    *   [View SQL](queries/traffic_operations_manager/tom1_peak_hour_delay.sql)
2.  **Persistent Bottlenecks**: Which road segments (SRIs) have been in a 'TRAFFIC_JAM' state most frequently?
    *   [View SQL](queries/traffic_operations_manager/tom2_persistent_bottlenecks.sql)
3.  **Operational Health Check**: Which routes are currently flagged with a 'LOW_ROAD_USAGE' validation error?
    *   [View SQL](queries/traffic_operations_manager/tom3_operational_health.sql)
4.  **Data Collection Latency**: Are there any active routes that have stopped sending data near the end of the snapshot period?
    *   [View SQL](queries/traffic_operations_manager/tom4_data_latency.sql)
5.  **Significant Event Detection**: Which routes experienced a travel time more than double their static baseline?
    *   [View SQL](queries/traffic_operations_manager/tom5_significant_event_detection.sql)

### Urban Planner
*Long-term trends and infrastructure planning.*

1.  **Long-Term Corridor Performance**: What has been the week-over-week trend in the average delay ratio for a specific corridor?
    *   [View SQL](queries/urban_planner/up1_corridor_trend.sql)
2.  **Traffic Monitoring Density**: Which geographic areas show the highest concentration of RMI route monitoring?
    *   [View SQL](queries/urban_planner/up3_monitoring_density.sql)
3.  **Weekend vs. Weekday Trends**: How does average travel time in the afternoon (2-5 PM) differ between weekdays and weekends?
    *   [View SQL](queries/urban_planner/up4_weekend_vs_weekday.sql)
4.  **Before-and-After Impact Analysis**: Has the average travel time on routes passing through a recent construction zone improved?
    *   [View SQL](queries/urban_planner/up2_impact_analysis.sql)
5.  **Geofenced Congestion**: Within a specific downtown polygon, which routes are currently seeing travel times more than 50% above baseline?
    *   [View SQL](queries/urban_planner/up5_geofenced_congestion.sql)

### Data Scientist
*Statistical analysis and predictive modeling.*

1.  **Outlier Detection (IQR)**: Identify travel time records that are statistical outliers for a specific route.
    *   [View SQL](queries/data_scientist/ds1_outlier_detection.sql)
2.  **Route Integrity Audit**: Which routes have a captured geometry that deviates significantly from the intended length?
    *   [View SQL](queries/data_scientist/ds4_route_integrity_audit.sql)
3.  **Persistent Unreliability Audit**: Group consecutive travel time spikes into failure windows (streaks).
    *   [View SQL](queries/data_scientist/ds5_reliability_ranking.sql)
4.  **Route Similarity Clustering**: Group routes based on their diurnal morning, midday, and evening delay profiles.
    *   [View SQL](queries/data_scientist/ds2_similarity_clustering.sql)
5.  **Predictive Feature Engineering**: Generate a high-quality, gap-aware feature set with regularized hourly grids.
    *   [View SQL](queries/data_scientist/ds3_feature_engineering.sql)
6.  **Travel Time Forecasting (ARIMA)**: Train and backtest a predictive model for future travel times.
    *   [View SQL](queries/data_scientist/ds6_travel_time_forecasting.sql)
7.  **Zero-Shot Forecasting (TimesFM)**: Forecast next-day traffic for multiple routes simultaneously without training.
    *   [View SQL](queries/data_scientist/ds7_zero_shot_forecasting.sql)

### RMI Planner
*Business value and monitoring scale.*

1.  **Usage Growth Projection**: Forecast data volume and compute spend for larger route fleets.
    *   [View SQL](queries/rmi_planner/rmip1_usage_projection.sql)
2.  **Customer ROI (Value at Risk)**: Quantify the total hours of delay across critical corridors.
    *   [View SQL](queries/rmi_planner/rmip2_customer_roi.sql)
3.  **Road Segment Estimation**: Estimate physical scale of the addressable monitoring network.
    *   [View SQL](queries/rmi_planner/rmip3_segment_estimation.sql)
4.  **Administrative Geofencing**: Create reusable city boundaries for localized reporting.
    *   [View SQL](queries/rmi_planner/rmip4_area_boundary.sql)

### Data Engineer
*Data pipelines and analysis-ready datasets.*

1.  **Create Materialized Subset**: Create filtered, high-performance materialized views.
    *   [View SQL](queries/data_engineer/de1_materialized_view.sql)
2.  **Data Cleaning**: Produce a typed, cleaned version of route metadata.
    *   [View SQL](queries/data_engineer/de2_data_cleaning.sql)
3.  **SRI Flattening**: Transform nested arrays into flattened spatial records with distance metrics.
    *   [View SQL](queries/data_engineer/de3_sri_flattening.sql)
4.  **Attribute Extraction**: Pivot JSON attributes into distinct, typed columns.
    *   [View SQL](queries/data_engineer/de4_attribute_extraction.sql)
5.  **Data Freshness Audit**: Monitor latest arrival times across active routes.
    *   [View SQL](queries/data_engineer/de5_freshness_audit.sql)
6.  **Automated Status History**: Capture daily snapshots of route status using scheduled queries.
    *   [View SQL](queries/data_engineer/de7_routes_status_snapshot.sql)

### BigQuery Admin
*Platform health, cost governance, and performance optimization.*

1.  **Metadata Inventory**: Zero-cost check of row count and storage size for RMI tables.
    *   [View SQL](queries/bigquery_admin/bqa0_metadata_inventory.sql)
2.  **Scan Volume Monitoring**: Identify users or service accounts generating high scan volume.
    *   [View SQL](queries/bigquery_admin/bqa1_scan_volume.sql)
3.  **Cost Attribution Audit**: Identify jobs missing the mandatory naming prefix in their job IDs.
    *   [View SQL](queries/bigquery_admin/bqa2_cost_attribution.sql)
4.  **Identify Derived Resources**: Audit tables or views derived from the core RMI dataset.
    *   [View SQL](queries/bigquery_admin/bqa3_derived_resources.sql)
5.  **Repeated Query Patterns**: Detect frequent patterns (joins, JSON extraction) for pro-active optimization.
    *   [View SQL](queries/bigquery_admin/bqa4_query_patterns.sql)
6.  **Partition Pruning Audit**: Identify queries performing expensive full table scans instead of using partition filters.
    *   [View SQL](queries/bigquery_admin/bqa5_partition_pruning.sql)
7.  **Data Complexity Audit**: Audit spatial complexity (vertex count) and metadata size of actual records.
    *   [View SQL](queries/bigquery_admin/bqa6_data_complexity_audit.sql)


## 📄 License

Copyright 2026 Google LLC. Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at [https://www.apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0).
