# Analyzing Month-by-Month POI Openings & Closings with Places Insights Historical Data

> **⚠️ Important Requirement:** Before executing this notebook, ensure your Google Cloud project is subscribed to the relevant **Places Insights** country or sample dataset via Analytics Hub (defaulted to Great Britain: `places_insights___gb`) and that the **Map Tiles API** and **Places API (New)** are enabled on your Google Maps Platform API key. See [Set up Places Insights](https://developers.google.com/maps/documentation/placesinsights/cloud-setup) for onboarding instructions.

### Overall Goal

Static point-in-time POI counts often mask underlying commercial turnover: if a neighborhood has 25 operational establishments in January and 25 in August, a net count delta of `0` hides whether the market is stagnant or experiencing rapid retail churn (for example, 4 existing businesses closing while 4 new competitors open).

In this notebook, we use **Places Insights Historical Data** and the **`PLACES_COUNT_PER_H3`** function with the **`snapshot_date`** parameter to track **month-by-month POI openings, closings, and net growth across a target city at H3 spatial resolution**. While the notebook defaults to analyzing **`coffee_shop` locations across London, UK at H3 Resolution 9**, you can customize the **target country dataset, city coordinates, place type, H3 resolution, and historical date range** directly in **Step 2**.

### Key Technologies Used

*   **[Places Insights (`PLACES_COUNT_PER_H3`)](https://developers.google.com/maps/documentation/placesinsights/place-count-functions/places-count-per-h3):** Aggregates historical POI counts and up to 250 `sample_place_ids` per H3 hexagonal cell for any monthly `snapshot_date` back to January 2024.
*   **[Google Maps Map Tiles API (2D Tiles)](https://developers.google.com/maps/documentation/tile/2d-tiles-overview):** Provides official Google Maps road basemap tiles and dynamic viewport copyright attribution for Folium visualizations.
*   **[Google Maps Places API (New)](https://developers.google.com/maps/documentation/places/web-service/place-details):** Resolves `opened_place_ids` and `closed_place_ids` into ground-truth storefront names, addresses, and ratings.
*   **[BigQuery](https://cloud.google.com/bigquery):** Executes spatial H3 indexing and array set-difference window functions (`LAG()` + `UNNEST()`).
*   **Python Libraries:** **GeoPandas** (spatial geometry handling), **Folium** (interactive H3 choropleth mapping), **Plotly** (month-by-month diverging bar & trend charts), and **Requests** (REST API handshakes).

*Note: This notebook executes queries and API calls that incur costs. See [Google Maps Platform Pricing](https://mapsplatform.google.com/pricing/) and [BigQuery Pricing](https://cloud.google.com/bigquery/pricing) for details.*

### The Step-by-Step Workflow

1.  **Setup & Dual-Environment Authentication:** Authenticate to Google Cloud and load `GCP_PROJECT_ID` and `GMP_API_KEY` across either Consumer Colab or Enterprise/Local Jupyter.
2.  **Pipeline Configuration (Customizable Location & Place Type):** Configure the target dataset, location center/radius, place type (defaulted to London & `coffee_shop`), H3 resolution (`9`), and historical month window.
3.  **Google Maps 2D Tiles Session Handshake:** Initialize an authenticated 2D Map Tiles session, fetch live viewport attribution, and prepare official Google logo assets.
4.  **Historical H3 Snapshot & Churn Query (`PLACES_COUNT_PER_H3`):** Query monthly snapshots via `PLACES_COUNT_PER_H3` and compute month-over-month set differences on `sample_place_ids` per `h3_cell_index`.
5.  **Month-by-Month Trend Chart:** Plot a diverging bar and trend line chart contrasting monthly POI openings (`+`), closings (`-`), and net growth.
6.  **Interactive H3 Choropleth Map with Map Key:** Render an interactive Folium H3 map with an embedded visual Map Key over Google Maps 2D Tiles to inspect neighborhood-level openings and closings.
7.  **Ground-Truth Place Details Lookup:** Pass `opened_place_ids` and `closed_place_ids` from high-turnover H3 cells to the Places API (New) to inspect real storefront names and addresses.

### How to Use This Notebook

1.  **Prerequisites & Secrets:** Configure the following keys in the Colab "Secrets" tab (the **key icon** on the left menu):
    *   `GCP_PROJECT_ID`: Your Google Cloud Project ID authorized for the target APIs/datasets.
    *   `GMP_API_KEY`: A Google Maps Platform API key with **Map Tiles API** and **Places API (New)** enabled.
2.  **Customize Your Target Location & Place Type (Optional):** In **Step 2 (`Pipeline Configuration`)**, keep the default settings (**London, UK** and **`coffee_shop`**) or update `TARGET_LOCATION_NAME`, `LINKED_DATASET`, `CENTER_LAT`, `CENTER_LNG`, `SEARCH_RADIUS_METERS`, and `PLACE_TYPE` to analyze any other city or category.
3.  **Run the Cells:** Execute the cells in sequence from top to bottom.