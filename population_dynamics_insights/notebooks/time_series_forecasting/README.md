# 📈 PDI Economic Forecasting

> **⚠️ Important Requirement:** To run the queries in this notebook, your Google Cloud Project must have access to the **US Population Dynamics Insights dataset**. For instructions on how to request and configure access, see [Set up Population Dynamics Insights](https://developers.google.com/maps/documentation/population-dynamics-insights/cloud-setup).

### Overall Goal

This guide demonstrates how to use **Population Dynamics Insights (PDI)** to improve time-series forecasting. 

**The Scenario:** You want to predict county-level unemployment rates. Traditional auto-regressive models rely entirely on historical momentum. This notebook demonstrates how to train a machine learning model using PDI's 330-dimensional embeddings to teach the model the underlying geographic, environmental, and behavioral "DNA" of a location.

By comparing a standard baseline model against a PDI-enhanced model, we mathematically isolate and visualize the predictive power of spatial features.

### Key Technologies Used

*   **[Population Dynamics Insights](https://developers.google.com/maps/documentation/population-dynamics-insights/overview):** To provide the underlying 330-dimensional embeddings capturing geographic, environmental, and map features.
*   **[BigQuery GIS](https://cloud.google.com/bigquery):** To execute spatial overlays and demographic math natively in the data warehouse.
*   **[Data Commons API](https://docs.datacommons.org/api/python/v2/):** To programmatically fetch historical economic ground-truth data.
*   **[LightGBM](https://lightgbm.readthedocs.io/):** To train gradient-boosted decision trees on tabular spatial data.

### How to Use This Notebook

1.  **Prerequisites:** Enable the **BigQuery API** and the **Google Earth Engine API** in your Google Cloud Project.
2.  **Authentication:** Configure an environment variable in the Colab "Secrets" tab named `GCP_PROJECT_ID`. A Data Commons key must also be added to the relevant secret named `DC_API_KEY`. For more information about obtaining a Data Commons key, including how to use a trial key, see the [Authentication Section](https://docs.datacommons.org/api/python/v2/#authentication) of the [Data Commons Python API V2 documentation](https://docs.datacommons.org/api/python/v2/).
3.  **Run the Cells:** Execute the cells in order from top to bottom.