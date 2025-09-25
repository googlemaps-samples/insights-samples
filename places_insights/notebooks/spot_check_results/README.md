# Spot-Checking Places Insights Data with Functions and Sample Place IDs

### Overall Goal

This notebook demonstrates a workflow for spot-checking Places Insights data. It starts with a high-level statistical query to find restaurant density and then **directly visualizes both the high-level density and ground-truth sample locations from the city's busiest areas on a single, combined map.**

### Key Technologies Used

*   **[Places Insights](https://developers.google.com/maps/documentation/placesinsights):** To provide the Places Data and Place Count Function.
*   **[BigQuery](https://cloud.google.com/bigquery):** To run the `PLACES_COUNT_PER_H3` function, which provides aggregated place counts and `sample_place_ids`.
*   **[Google Maps Place Details API](https://developers.google.com/maps/documentation/places/web-service/place-details):** To fetch rich, detailed information (name, address, rating, and a Google Maps link) for the specific `sample_place_ids`.
*   **[Google Maps 2D Tiles](https://developers.google.com/maps/documentation/tile/2d-tiles-overview):** To use Google Maps as the basemap.
*   **Python Libraries:**
    * **[GeoPandas](https://geopandas.org/en/stable/)** for spatial data manipulation.
    * **[Folium](https://python-visualization.github.io/folium/latest/)** for creating the final interactive, layered map.

See [Google Maps Platform Pricing](https://mapsplatform.google.com/intl/en_uk/pricing/) For API costs assocated with running this notebook.

### The Step-by-Step Workflow

1.  **Query Aggregated Data:** We begin by querying BigQuery to count all highly-rated, operational restaurants across London, grouping them into H3 hexagonal cells. This query provides the statistical foundation for our analysis and, crucially, a list of `sample_place_ids` for each cell.

2.  **Identify Hotspots & Fetch Details:** The notebook then **automatically** identifies the 20 busiest H3 cells. It consolidates the `sample_place_ids` from all of these top hotspots into a single master list and uses the Places API to fetch detailed information for each one.

3.  **Create a Combined Visualization:** In the final step, we generate a single, layered map.
    *   The **base layer** is a choropleth "heatmap" showing restaurant density across the entire city.
    *   The **top layer** displays individual pins for all the sample restaurants from the top 20 hotspots, providing a direct, ground-level view of the locations that make up the aggregated counts. Each pin's popup includes a link to open the location directly in Google Maps.

### **How to Use This Notebook**

1.  ** Set Up Secrets:** Before you begin, you must configure two secrets in the Colab "Secrets" tab (the **🔑 key icon** on the left menu):
    *   `GCP_PROJECT`: Your Google Cloud Project ID with access to Places Insights.
    *   `GMP_API_KEY`: Your Google Maps Platform API key. Ensure the **Maps Tile API** is enabled for this key in your GCP console.

2.  **Run the Cells:** Once the secrets are set, simply run the cells in order from top to bottom. Each visualization will appear as the output of its corresponding code cell.