# Geospatial Analysis with Places Insights Sample Data

### Overall Goal

This notebook serves as a technical introduction for developers and data analysts who have subscribed to the [Places Insights Sample Datasets](https://developers.google.com/maps/documentation/placesinsights/cloud-setup#sample_data).

Its primary purpose is to demonstrate how to query, aggregate, and visualize Google Maps Platform [Places Insights](https://developers.google.com/maps/documentation/placesinsights) data within a **BigQuery** environment. By running this notebook, you will learn how to transition from raw dataset subscriptions to actionable geospatial insights using Standard SQL and Python.

### Key Technologies Used

*   **[Places Insights](https://developers.google.com/maps/documentation/placesinsights):** A BigQuery dataset providing aggregated counts and attributes for Points of Interest (POIs).
*   **[BigQuery](https://cloud.google.com/bigquery):** Used to execute Standard SQL and Geospatial functions (such as `ST_DWITHIN` and `ST_GEOGPOINT`) on the dataset.
*   **[H3 (Hierarchical Geospatial Indexing)](https://h3geo.org/):** A hexagonal grid system used by the Places Insights SQL functions to normalize spatial data.
*   **[Google Maps 2D Tiles](https://developers.google.com/maps/documentation/tile/2d-tiles-overview):** Provides the high-resolution roadmap imagery used for the visualization layer.
*   **Python Libraries:**
    * **[Folium](https://python-visualization.github.io/folium/latest/)** for map rendering.
    * **[GeoPandas](https://geopandas.org/)** & **[Shapely](https://shapely.readthedocs.io/)** for processing coordinate reference systems and geometry objects.

**See [Google Maps Platform Pricing](https://mapsplatform.google.com/intl/en_uk/pricing/) and [BigQuery Pricing](https://cloud.google.com/bigquery/pricing) for costs associated with running this notebook.**

### The Step-by-Step Workflow

1.  **Configuration:** The notebook initializes the environment based on your selection of a Sample City (e.g., "New York City", "Tokyo", "London"). It automatically maps your selection to the correct **Analytics Hub Dataset ID** and geographic coordinates.

2.  **Direct Query Analysis (Radius Search):** We demonstrate how to count places that match specific criteria, such as `primary_type`, `business_status`, and boolean attributes like `allows_dogs`, within a set radius. We utilize the `WITH AGGREGATION_THRESHOLD` clause to compare amenity density across multiple neighborhoods programmatically.

3.  **H3 Density Analysis (Grid Search):** We utilize the predefined `PLACES_COUNT_PER_H3` SQL function to retrieve a normalized grid of place counts. This allows us to visualize macro-level commercial density across the entire city without manually defining boundaries.

4.  **Visualization:** We render the query results on interactive maps using **Folium** and **Google Maps 2D Tiles**:
    *   **Marker Map:** Visualizes the "Direct Query" results, identifying hotspots based on amenity concentration.
    *   **Choropleth Map:** Overlays the H3 hexagonal grid to visualize the "Function Query" density results.

### **How to Use This Notebook**

1.  **Prerequisites:**
    *   A Google Cloud Project with the **BigQuery API** and **Map Tiles API** enabled.
    *   A subscription to at least one of the [Places Insights Sample Datasets](https://developers.google.com/maps/documentation/placesinsights/cloud-setup#sample_data) via Analytics Hub.

2.  **Set Up Secrets:** Configure the following keys in the Colab "Secrets" tab (the **key icon** on the left menu):
    *   `GCP_PROJECT_ID`: Your Google Cloud Project ID.
    *   `GMP_API_KEY`: Your Google Maps Platform API key.

3.  **Run the Cells:** Run the cells in sequence to authenticate, execute the BigQuery jobs, and render the visualizations.