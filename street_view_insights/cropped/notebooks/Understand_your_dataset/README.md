# Analyze Imagery Insights Dataset

This notebook is designed to analyze asset and observation data from Imagery Insights.

## Prerequisites

- A Google Cloud Platform (GCP) project.
- A BigQuery dataset containing `all_assets` and `all_observations` tables.
- The following Python libraries installed:
    - `pandas-gbq`
    - `matplotlib`

You can install them by running:
```bash
pip install pandas-gbq matplotlib
```

## Configuration

Before running the notebook, you need to configure your GCP `project_id` and `dataset_id` in the second cell of the notebook.

## How to Use

1.  **Set up your environment**: Make sure you have the necessary libraries installed and have authenticated with your GCP account.
2.  **Configure the notebook**: Open the notebook and replace the placeholder values for `project_id` and `dataset_id` with your actual GCP project ID and dataset ID.
3.  **Run the notebook**: Execute the cells in the notebook sequentially.

## What the Notebook Does

1.  **Data Retrieval**: Connects to a specified BigQuery project and dataset to fetch `all_assets` and `all_observations` tables.
2.  **SQL Query Construction**: Formulates a SQL query to join the asset and observation data, count unique observations per asset and snapshot, and create geographical points from location coordinates.
3.  **Data Processing**: Reads the query results into a pandas DataFrame for in-memory analysis.
4.  **Statistical Calculation**: Computes overall statistics, including the total number of unique assets, observations, and snapshots. It also determines the distribution of observations per asset.
5.  **Data Visualization**: Generates a pie chart to visually represent the distribution of assets based on their number of observations.
6.  **Tabular Output**: Formats and displays key statistics and data samples in a clear, tabular format.