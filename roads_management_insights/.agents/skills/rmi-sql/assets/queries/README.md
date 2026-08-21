# RMI Sample Queries (GA)

This directory contains a library of hand-written, verified SQL queries tailored for Road Management Insights (RMI) General Availability features. These queries serve as high-quality examples for AI agents and as ready-made answers for human analysts.

## Organizational Structure

Queries in this GA library are grouped by the **Analytical Persona** they support:

- **`traffic_operations_manager/`**: Real-time monitoring and bottleneck detection.
- **`urban_planner/`**: Long-term trends and spatial impact analysis.
- **`data_scientist/`**: Statistical modeling and predictive forecasting.
- **`rmi_planner/`**: Business value translation and monitoring scale.
- **`data_engineer/`**: Pipeline management and dataset optimization.
- **`bigquery_admin/`**: Platform health, cost governance, and performance optimization.

## Staged Extensions

To maintain stability, non-GA queries are located in separate skills:
- **Preview Queries**: See `rmi-sql-preview/assets/queries/` (e.g., Logistics Coordinator).
- **Experimental Queries**: See `rmi-sql-experimental/assets/queries/`.

## Quality Assurance (Evals)

Every query in this directory is backed by an evaluation file in **`tests/sql_evals/`**. These files document:
- **Features Verified**: Technical capabilities demonstrated.
- **Cost Profiling**: Complexity class and scan volume estimates.
- **Project Validation**: Results of empirical tests on standard RMI datasets.

## Usage Guidelines

- **Standard Dataset**: All samples are designed to run against the `LINKED_DATASET_NAME` dataset.
- **Best Practices**: These queries adhere to the standards defined in `bigquery-practices`.
- **Job ID Convention**: All RMI queries MUST follow the `rmisqlfactory_<queryid>_<timestamp>` format.
