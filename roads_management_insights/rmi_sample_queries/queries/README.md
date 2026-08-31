# Roads Management Insights (RMI) - SQL Query Library

This directory contains a curated library of hand-written, verified SQL queries tailored for **Roads Management Insights (RMI)** datasets in Google Cloud BigQuery.

---

## 📂 Query Categories by Persona

Queries in this library are grouped by analytical persona and operational responsibility:

* **[`traffic_operations_manager/`](traffic_operations_manager/)**: Real-time traffic monitoring, delay anomalies, peak congestion, and bottleneck detection.
* **[`urban_planner/`](urban_planner/)**: Long-term corridor performance, before-and-after infrastructure impact analysis, and downtown geofenced congestion.
* **[`data_scientist/`](data_scientist/)**: Statistical outlier detection (Z-score, IQR), route similarity clustering, predictive feature engineering, and ARIMA_PLUS travel time forecasting.
* **[`rmi_planner/`](rmi_planner/)**: Route registration capacity projection, customer ROI / value metrics, and spatial boundary coverage.
* **[`data_engineer/`](data_engineer/)**: Materialized views, data cleaning, SRI (Speed-to-Road-Interval) spatial flattening, attribute extraction, and data freshness monitoring.
* **[`bigquery_admin/`](bigquery_admin/)**: Dataset metadata inventory, scan byte monitoring, cost attribution, partition pruning audits, and derived resource tracking.

---

## 🛠️ Usage Guidelines

* **Target Dataset Placeholder**: All queries use `LINKED_DATASET_NAME` as the dataset placeholder. Replace `LINKED_DATASET_NAME` with your BigQuery linked dataset name (for example, `ah_rmi_boston` or `my_rmi_dataset`).
* **Partition Pruning**: Queries filtering on `historical_travel_time` include date bounds on `record_time` (e.g. `WHERE record_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)`) to prune partitions and minimize query scan costs.
* **Traceability Comments**: Query headers include structured comment headers (`-- Job ID: rmisqlfactory_<persona>_YYYYMMDDHHMMSS`) to support auditability and FinOps attribution.
