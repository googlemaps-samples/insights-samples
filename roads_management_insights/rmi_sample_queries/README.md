# Roads Management Insights (RMI) - Sample Query Library

This directory contains a curated library of hand-written, verified SQL queries and interactive Jupyter notebooks designed for the **Roads Management Insights (RMI)** BigQuery dataset.

All sample queries and notebooks adhere to standard BigQuery GIS best practices, FinOps partition pruning, canonical column naming (`selected_route_id`, `record_time`), and query traceability comments.

---

## 📂 Folder Structure

* **[`/queries`](queries/)**: A collection of verified SQL queries categorized by analytical persona.
* **[`/notebooks`](notebooks/)**: Interactive Jupyter notebooks ready to be opened in Google Colab or BigQuery Studio.

---

## 👥 Query Catalog by Persona

### 1. [BigQuery Admin](queries/bigquery_admin/)
*Operational health, resource contention, security, slot allocations, and query cost auditing.*
* **bqa0**: [Metadata Inventory and Partition Overview](queries/bigquery_admin/bqa0_metadata_inventory.sql) — Zero-cost metadata check of row counts and storage scale.
* **bqa1**: [Query Scan Volume & Billing Cost Audit](queries/bigquery_admin/bqa1_scan_volume.sql) — Top scan consumers and billable query patterns.
* **bqa2**: [Cost Attribution per Business Persona](queries/bigquery_admin/bqa2_cost_attribution.sql) — Attribute compute costs by persona job headers.
* **bqa3**: [Unmanaged Derived Dataset & View Inventory](queries/bigquery_admin/bqa3_derived_resources.sql) — Audit downstream dependent views and tables.
* **bqa4**: [High-Frequency Query Pattern & SRI Audit](queries/bigquery_admin/bqa4_query_patterns.sql) — Identify heavy unnest operations.
* **bqa5**: [Full Table Scan & Partition Pruning Audit](queries/bigquery_admin/bqa5_partition_pruning.sql) — Detect unpartitioned queries.
* **bqa6**: [Query Structural Complexity Audit](queries/bigquery_admin/bqa6_data_complexity_audit.sql) — Audit query complexity and geometry join performance.
* 📓 **Notebook**: [BigQuery Admin Samples](notebooks/BigQuery_Admin_Samples.ipynb)

### 2. [Data Engineer](queries/data_engineer/)
*Data pipelines, geometry integrity checks, SRI array flattening, and analysis-ready datasets.*
* **de1**: [Create Materialized Subset](queries/data_engineer/de1_materialized_view.sql) — Filtered, high-performance 7-day materialized view.
* **de2**: [Data Cleaning & Typed Column Promotion](queries/data_engineer/de2_data_cleaning.sql) — Cleaned route metadata with typed columns.
* **de3**: [SRI Flattening & Distance Metrics](queries/data_engineer/de3_sri_flattening.sql) — Transform nested SRI arrays into flattened spatial records.
* **de4**: [Attribute Extraction & Pivoting](queries/data_engineer/de4_attribute_extraction.sql) — Parse unstructured JSON route attributes into columns.
* **de5**: [Data Freshness Audit](queries/data_engineer/de5_freshness_audit.sql) — Monitor ingestion latency across active routes.
* **de6**: [2-Stage Hourly Pre-Aggregation Pattern](queries/data_engineer/de6_hourly_preaggregation.sql) — Transform 2-minute telemetry into lightweight hourly profiles (>95% payload reduction).
* **de7**: [Automated Status History](queries/data_engineer/de7_routes_status_snapshot.sql) — Capture automated snapshots of route status.
* 📓 **Notebook**: [Data Engineer Samples](notebooks/Data_Engineer_Samples.ipynb)

### 3. [Data Scientist](queries/data_scientist/)
*Statistical analysis, anomaly detection, time-series forecasting, and route behavioral clustering.*
* **ds1**: [Outlier Detection (Z-Score & IQR)](queries/data_scientist/ds1_outlier_detection.sql) — Statistical travel time outlier detection.
* **ds2**: [Route Similarity Clustering](queries/data_scientist/ds2_similarity_clustering.sql) — Group routes by diurnal morning/midday/evening delay profiles.
* **ds3**: [Predictive Feature Engineering](queries/data_scientist/ds3_feature_engineering.sql) — Gap-aware regularized hourly feature set.
* **ds4**: [Route Geometry Integrity Audit](queries/data_scientist/ds4_route_integrity_audit.sql) — Polyline length deviation analysis.
* **ds5**: [Reliability Ranking & Persistence](queries/data_scientist/ds5_reliability_ranking.sql) — Buffer Index (P95) and consecutive delay failure windows.
* **ds6**: [Travel Time Forecasting (ARIMA_PLUS)](queries/data_scientist/ds6_travel_time_forecasting.sql) — Train time-series model for future corridor travel times.
* **ds7**: [Zero-Shot Spatial Speed Inference](queries/data_scientist/ds7_zero_shot_forecasting.sql) — Zero-shot spatial speed transfer modeling.
* 📓 **Notebook**: [Data Scientist Samples](notebooks/Data_Scientist_Samples.ipynb)

### 4. [RMI Planner](queries/rmi_planner/)
*Capacity planning, ROI analysis, corridor prioritization, and geographical coverage.*
* **rmip1**: [Route Registration Usage Projection](queries/rmi_planner/rmip1_usage_projection.sql) — SelectedRoute quota projections.
* **rmip2**: [Customer Value & FinOps ROI](queries/rmi_planner/rmip2_customer_roi.sql) — Value metric calculations.
* **rmip3**: [Corridor Segment Breakdown](queries/rmi_planner/rmip3_segment_estimation.sql) — Traversed road segment estimates.
* **rmip4**: [Area Coverage Bounding Box](queries/rmi_planner/rmip4_area_boundary.sql) — Spatial envelope calculation.
* 📓 **Notebook**: [RMI Planner Samples](notebooks/RMI_Planner_Samples.ipynb)

### 5. [Traffic Operations Manager](queries/traffic_operations_manager/)
*Real-time monitoring, incident detection, and congestion mitigation.*
* **tom1**: [Peak Hour Delay Analysis](queries/traffic_operations_manager/tom1_peak_hour_delay.sql) — Morning/evening peak delay rankings.
* **tom2**: [Persistent Bottlenecks](queries/traffic_operations_manager/tom2_persistent_bottlenecks.sql) — Road segments in persistent congestion states.
* **tom3**: [Operational Health Check](queries/traffic_operations_manager/tom3_operational_health.sql) — Validation error monitoring (`LOW_ROAD_USAGE`).
* **tom4**: [Data Collection Latency](queries/traffic_operations_manager/tom4_data_latency.sql) — Telemetry silence detection.
* **tom5**: [Significant Event Detection](queries/traffic_operations_manager/tom5_significant_event_detection.sql) — Severe delay spikes relative to static baselines.
* **tom6**: [Dynamic Detour & Routing Anomaly Detection](queries/traffic_operations_manager/tom6_dynamic_detour_detection.sql) — Detect network detours from baseline geometry.
* 📓 **Notebook**: [Traffic Operations Manager Samples](notebooks/Traffic_Operations_Manager_Samples.ipynb)

### 6. [Urban Planner](queries/urban_planner/)
*Infrastructure impact, long-term policy trends, and regional mobility.*
* **up1**: [Long-Term Corridor Performance Trend](queries/urban_planner/up1_corridor_trend.sql) — Week-over-week delay trends.
* **up2**: [Before-and-After Construction Impact](queries/urban_planner/up2_impact_analysis.sql) — Spatial before/after intervention analysis.
* **up3**: [Traffic Monitoring Density Analysis](queries/urban_planner/up3_monitoring_density.sql) — Heatmap concentration of monitoring.
* **up4**: [Weekend vs. Weekday Trends](queries/urban_planner/up4_weekend_vs_weekday.sql) — Comparative temporal analysis.
* **up5**: [Geofenced Downtown Congestion](queries/urban_planner/up5_geofenced_congestion.sql) — Spatial polygon filtering on congestion.
* 📓 **Notebook**: [Urban Planner Samples](notebooks/Urban_Planner_Samples.ipynb)

---

## 🛠️ Usage Guidelines

* **Parameterization**: All queries use `LINKED_DATASET_NAME` as the dataset placeholder. Replace with your actual BigQuery linked dataset name (e.g. `ah_rmi_boston` or `my_rmi_dataset`).
* **Partition Pruning**: Queries filtering `historical_travel_time` include date bounds on `record_time` to ensure minimal scan bytes.
* **Job ID Traceability**: All query headers follow the canonical `-- Job ID: rmisqlfactory_<persona>_YYYYMMDDHHMMSS` format.
