### **Site Selection in Las Vegas using Places Insights and BigQuery**

**Overall Goal**

This notebook demonstrates a multi-stage site selection workflow for a new coffee shop in Las Vegas. It combines broad competitive analysis, custom commercial suitability scoring, and target market density analysis to identify prime locations, then visualizes the results on a combined, interactive map.

**Key Technologies Used**

*  **[Places Insights](https://developers.google.com/maps/documentation/placesinsights)**: To provide the core Places dataset and the `PLACES_COUNT_PER_H3` function.
*   **[BigQuery](https://cloud.google.com/bigquery):**: To perform large-scale geospatial analysis and calculate suitability scores.
*   **[Google Maps Place Details API](https://developers.google.com/maps/documentation/places/web-service/place-details):** To fetch rich, detailed information (name, address, rating) for specific ground-truth locations.
*   **[Google Maps 2D Tiles](https://developers.google.com/maps/documentation/tile/2d-tiles-overview):** To use Google Maps as the interactive basemap.
*   **Python Libraries:**
    * **[GeoPandas](https://geopandas.org/en/stable/)** for spatial data manipulation.
    * **[Folium](https://python-visualization.github.io/folium/latest/)** for creating the final interactive, layered map.

See [Google Maps Platform Pricing](https://mapsplatform.google.com/intl/en_uk/pricing/) For API costs assocated with running this notebook.

**The Step-by-Step Workflow**

1.  **Analyze Competitor Density:** We begin by using BigQuery to analyze the distribution of major competitor brands across Clark County ZIP codes. This initial step helps identify broad areas with lower market saturation.

2.  **Identify Prime Commercial Zones:** The notebook then runs a more sophisticated query to calculate a custom suitability score for H3 hexagonal cells. This score is based on the weighted density of complementary businesses (restaurants, bars, casinos, tourist attractions), pinpointing the most commercially vibrant areas.

3.  **Find Target Market Hotspots & Synthesize:** Next, we use the `PLACES_COUNT_PER_H3` function to find the density of our target business type—coffee shops. The notebook then **automatically** cross-references these coffee shop counts with the highest-scoring suitability zones to identify the most promising cells for a new location.

4.  **Create a Combined Visualization:** In the final step, we generate a single, layered map. The **base layer** is a choropleth "heatmap" showing the suitability scores across Las Vegas. The **top layer** displays individual pins for existing coffee shops in the top-ranked zones, providing a direct, ground-level view of the current market landscape.

**How to Use This Notebook**

1.  **\*\*Set Up Secrets:\*\*** Before you begin, you must configure two secrets in the Colab “Secrets” tab (the 🔑 key icon on the left menu):
    *   `GCP_PROJECT`: Your Google Cloud Project ID with access to Places Insights.
    *   `GMP_API_KEY`: Your Google Maps Platform API key. Ensure the **Maps Tile API** and **Places API (new)** are enabled for this key in your GCP console.

2.  **Run the Cells:** Once the secrets are set, simply run the cells in order from top to bottom. Each visualization will appear as the output of its corresponding code cell.