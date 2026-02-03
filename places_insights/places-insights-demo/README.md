# Places Insights Demo Application

This is a client-side web application that demonstrates how to query and visualize Google Places Insights data. It allows users to define geographic search areas, apply a variety of filters, and see aggregated results from Google BigQuery displayed on a Google Map.

The application is built entirely with HTML, CSS, and JavaScript, using the Google Maps Platform JavaScript API for mapping, Deck.gl for H3 heatmap visualizations, and Google Identity Services for client-side OAuth 2.0 authentication.

---

## Prerequisites

Before you can run this application, you must have a Google Cloud project with billing enabled and ensure the following are set up:

### 1. Places Insights Subscription

This demo queries the Places Insights datasets in BigQuery. You must subscribe to these datasets in the Google Cloud Marketplace for the countries you wish to query.

*   **Action:** Visit the [Places Insights product page](https://developers.google.com/maps/documentation/placesinsights) and follow the instructions to subscribe to the datasets for your project.

### 2. Enabled APIs

Ensure the following APIs are enabled in your Google Cloud project:

*   **BigQuery API** (for running the queries)
*   **Maps JavaScript API** (for displaying the map)
*   **Geocoding API** (for centering the map on countries/regions)
*   **Routes API** (for the "Route Search" feature)
*   **Places API (New)** (for the Place Autocomplete web components and Place Details)
*   **Places UI Kit API** (Required for the `<gmp-place-details-compact>` component used in the H3 Function demo)

### 3. IAM Permissions

The Google account you authorize with must have the appropriate IAM permissions in your Cloud project to run BigQuery jobs. At a minimum, this typically includes:

*   `BigQuery Job User`
*   `BigQuery Resource Viewer`

---

## Setup

Follow these steps to configure and run the application locally.

### 1. Create an OAuth 2.0 Client ID

This application uses client-side OAuth 2.0 to authorize users to run BigQuery queries on their own behalf.

1.  In the Google Cloud Console, navigate to **APIs & Services > Credentials**.
2.  Click **+ CREATE CREDENTIALS** and select **OAuth client ID**.
3.  For "Application type", select **Web application**.
4.  Give it a name (e.g., "Places Insights Demo").
5.  Under **Authorized JavaScript origins**, click **+ ADD URI**.
6.  Enter the origin for your local development server. For most  servers, this is `http://localhost:8000`.
7.  Click **CREATE**.
8.  Copy the **Your Client ID** value. You will need this in the next step.

### 2. Create a Google Maps Platform API Key

1.  On the same **Credentials** page, click **+ CREATE CREDENTIALS** and select **API key**.
2.  Copy the generated API key.
3.  **Important:** For security in a production environment, you should restrict this key to your website's domain and ensure it only has access to the APIs listed in the Prerequisites section.

### 3. Configure the Application

1.  In the project directory, find the file named `config.js.template` (or create a new `config.js` file).
2.  **Rename** this file to `config.js`.
3.  Open `config.js` and fill in the placeholder values with your project-specific credentials:

    ```javascript
    window.APP_CONFIG = {
      // Your Google Cloud Project ID
      GCP_PROJECT_ID: 'YOUR_GCP_PROJECT_ID',

      // The OAuth 2.0 Client ID you created in Step 1
      OAUTH_CLIENT_ID: 'YOUR_OAUTH_CLIENT_ID.apps.googleusercontent.com',

      // The Google Maps Platform API Key you created in Step 2
      MAPS_API_KEY: 'YOUR_MAPS_API_KEY',

      /**
       * Defines which dataset to query.
       * Options: 'FULL' or 'SAMPLE'
       * - 'FULL': Queries the full country datasets (e.g., places_insights___us.places).
       * - 'SAMPLE': Queries the city sample datasets (e.g., places_insights___us___sample.places_sample).
       */
      DATASET: 'FULL',
    };
    ```

4.  **Dataset Selection:** Set the `DATASET` parameter to `'SAMPLE'` if you are using the [sample datasets](https://developers.google.com/maps/documentation/placesinsights/cloud-setup#sample_data), or `'FULL'` if you have subscribed to the [full datasets](https://developers.google.com/maps/documentation/placesinsights/cloud-setup#full_data).
5.  **Security Note:** The `config.js` file **must not be committed to version control**.

### 4. Run a Local Server

Because of browser security policies related to OAuth 2.0, you cannot run this application by opening the `index.html` file directly. You must serve it from a local web server.

1.  Open a terminal in the project's root directory.
2.  If you have Python 3 installed, you can run a simple server with the command:
    ```sh
    python3 -m http.server 8000
    ```
3.  Open your web browser and navigate to `http://localhost:8000`.

---

## How to Use the Application

For a detailed walkthrough, click the **Help** button in the application's sidebar.

### Quick Start

1.  **Select a Location:** Choose a country or city you have subscribed to in Places Insights.
2.  **Authorize:** Sign in with your Google account to enable querying.
3.  **Choose a Demo Type:**
    *   **Circle Search:** Click on the map to define a search radius.
    *   **Polygon Search:** Draw a custom shape on the map or paste a WKT string.
    *   **Region Search:** Search by administrative names like "London" or "California". You can add multiple regions to search at once.
    *   **Route Search:** Select an origin and destination to search along a calculated driving route.
    *   **Places Count Per H3 (Function):** Uses server-side BigQuery functions for high-performance density mapping. This mode supports **low counts (0-4)** and **sample place markers**.
4.  **Apply Filters:** Narrow your search using the collapsible filter sections:
    *   **Place Types:** Select types and optionally check **"Match Primary Type Only"** for stricter filtering.
    *   **Attributes:** Filter by Rating, Business Status (Operational/Closed), Price, etc.
    *   **Opening Hours:** Filter by day and time (Standard modes only).
    *   **Brands:** Filter by brand name or category (US Standard mode only).
5.  **Visualize:**
    *   Leave **Show H3 Density Map** unchecked for simple aggregate counts (Standard modes only).
    *   Check the box to visualize the results as a color-coded heatmap of hexagonal cells.
6.  **Run Search:** Click the "Run Search" button to execute the query and see the results on the map.

### Interactive Features (H3 Function Mode)
When running the **Places Count Per H3** demo:
1.  **Click a Hexagon:** Click on any colored H3 cell on the map. This will load up to 20 sample markers for places within that cell.
2.  **View Details:** Click on any of the yellow markers to open a **Place Details Card** containing rich information (photos, reviews, opening hours) powered by the Places UI Kit.