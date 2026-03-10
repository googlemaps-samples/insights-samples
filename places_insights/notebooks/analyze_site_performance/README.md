# Analyze Site Performance with Places Insights and BigQuery ML

This directory contains a complete Geospatial Machine Learning workflow demonstrating how to combine internal operational metrics with external environmental data to diagnose the location factors that drive site success.

By leveraging **Places Insights**, **BigQuery ML**, and **H3 Spatial Indexing**, this sample shows how to move beyond anecdotal explanations and quantify exactly how local competitive density and neighborhood characteristics dictate performance.

## Directory Contents

*   **`places_insights_analyze_site_performance_bigquery_ml.ipynb`**: The primary interactive workflow. It demonstrates how to ingest site data, engineer features using Spatial Joins (`ST_DWITHIN`) against the Places Insights dataset, train a Robust Linear Regression model in BigQuery ML, and visualize city-wide expansion opportunities using an interactive H3 grid map.
*   **`places_insights_analyze_site_performance_data_generation.ipynb`**: An optional supplementary notebook. It demonstrates how to dynamically generate a realistic, synthetic training dataset of store locations in London by scoring geographic points based on their proximity to real-world amenities.
*   **`store_performance_london.csv`**: The static, pre-generated dataset created by the data generation notebook. This allows users to run the main BigQuery ML workflow immediately without needing to generate their own data.

## Getting Started

### Prerequisites

To execute these notebooks, you will need:
1.  **Google Cloud Project**: With billing enabled and BigQuery active.
2.  **Places Insights Access**: Your project must be subscribed to the [GB Places Insights dataset](https://developers.google.com/maps/documentation/placesinsights/cloud-setup) in BigQuery.
3.  **Google Maps Platform API Key**: Required to render the interactive map visualizations. You must enable the **Maps JavaScript API** and **Maps Tiles API** on this key.

### Execution Order

1.  *(Optional)* Run `places_insights_analyze_site_performance_data_generation.ipynb` to see how the synthetic correlation between performance and amenities is mathematically generated.
2.  Run `places_insights_analyze_site_performance_bigquery_ml.ipynb`. The notebook automatically fetches the provided `store_performance_london.csv` dataset directly from GitHub to proceed with the BigQuery ML training and prospecting visualization. *(Note: If you ran the optional data generation step, you can modify the notebook to ingest your custom generated file instead).*