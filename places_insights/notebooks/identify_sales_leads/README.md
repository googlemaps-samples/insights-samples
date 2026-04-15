# Identify Net-New Field Sales Leads with Places Insights

> **⚠️ Important Requirement:** To run the queries in this notebook, your Google Cloud Project must have access to the **US Places Insights dataset**. For instructions on how to request and configure access, please see [Set up Places Insights](https://developers.google.com/maps/documentation/placesinsights/cloud-setup).

### Overall Goal

This notebook demonstrates an end-to-end data pipeline based on the [Places Insights Sales Leads Architecture](https://developers.google.com/maps/architecture/places-insights-sales-leads). It solves a common, high-value business problem: **finding every operational target business in a specific territory that is *not* already in your CRM.**

By visualizing commercial density and using spatial joins, this workflow transforms raw map data into a clean, actionable list of highly targeted sales prospects.

### Key Technologies Used

*   **[Places Insights](https://developers.google.com/maps/documentation/placesinsights):** To provide the underlying commercial datasets and geospatial count functions.
*   **[BigQuery](https://cloud.google.com/bigquery):** To execute analytical queries, handle complex polygons, and perform the final `LEFT JOIN` exclusion.
*   **[Address Validation API](https://developers.google.com/maps/documentation/address-validation):** To confidently translate unstructured CRM addresses into definitive `place_id`s.
*   **[Places API (Text Search)](https://developers.google.com/maps/documentation/places/web-service/text-search):** To serve as a highly accurate fallback for extracting establishment IDs.
*   **[Google Maps 2D Tiles](https://developers.google.com/maps/documentation/tile/2d-tiles-overview):** To visualize the territory density on an authentic Google basemap.
*   **Python Libraries:** **GeoPandas** (spatial manipulation), **Folium** (interactive mapping), and **Requests** (API calls).

*Note: This notebook executes queries and API calls that incur costs. See [Google Maps Platform Pricing](https://mapsplatform.google.com/pricing/) and [BigQuery Pricing](https://cloud.google.com/bigquery/pricing) for details.*

### The Step-by-Step Workflow

1.  **Define Target Place Types:** In a production environment, your first step is mapping your ideal customer profile to specific [Places Insights Place Types](https://developers.google.com/maps/architecture/places-insights-sales-leads#step_1_define_your_target_place_types). *For this notebook, we have pre-selected `['restaurant', 'bar', 'cafe', 'coffee_shop']` to focus on the food and beverage sector.*
2.  **Extract High-Potential Areas:** We use the `PLACES_COUNT_PER_H3` function combined with a public city boundary dataset to identify the most densely packed commercial zones in New York City, visualising the results on an interactive heatmap.
3.  **Normalize CRM Data:** We take a sample of raw, unstructured CRM addresses and pass them through a two-step API pipeline (Address Validation & Text Search) to extract the definitive Google Maps `place_id` for every existing customer.
4.  **Whitespace Exclusion Analysis:** We zoom in on the highest-density territory (Union Square) and run a BigQuery spatial query. By cross-referencing the businesses in the territory against our newly normalized CRM IDs, we filter out existing customers to reveal a list of 100% net-new sales leads.

### How to Use This Notebook

1.  **Prerequisites & Secrets:** Before running this notebook, you must configure two environment variables in the Colab "Secrets" tab (the **key icon** on the left menu):
    *   `GCP_PROJECT_ID`: Your Google Cloud Project ID. **Crucially, this project must be authorized to access the US Places Insights dataset (see [Set up Places Insights](https://developers.google.com/maps/documentation/placesinsights/cloud-setup)).**
    *   `GMP_API_KEY`: A Google Maps Platform API key with the following APIs enabled: *Address Validation API, Places API (New), and Map Tiles API*.
2.  **Authentication:** The first cell will prompt you to authenticate your Google Account. Ensure the account you use has BigQuery Data Viewer/Job User permissions for your Project ID.
3.  **Run the Cells:** Once authenticated, execute the cells in order from top to bottom to extract, visualize, and generate your leads.