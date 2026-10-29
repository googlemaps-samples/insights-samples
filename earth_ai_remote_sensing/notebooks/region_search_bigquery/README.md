# Earth AI Remote Sensing: Region Search with BigQuery Vector Search

<table align="left">
  <td style="text-align: center">
    <a href="https://console.cloud.google.com/vertex-ai/colab/import/https:%2F%2Fraw.githubusercontent.com%2Fgooglemaps-samples%2Finsights-samples%2Fmain%2Fearth_ai_remote_sensing%2Fnotebooks%2Fregion_search_bigquery%2Fearth_ai_region_search_bigquery.ipynb?utm_source=earth_ai_remote_sensing_notebooks">
      <img width="32px" src="https://lh3.googleusercontent.com/JmcxdQi-qOpctIvWKgPtrzZdJJK-J3sWE1RsfjZNwshCFgE_9fULcNpuXYTilIR2hjwN" alt="Google Cloud Colab Enterprise logo"><br> Open in Colab Enterprise
    </a>
  </td>
  <td style="text-align: center">
    <a href="https://console.cloud.google.com/bigquery/import?url=https://github.com/googlemaps-samples/insights-samples/blob/main/earth_ai_remote_sensing/notebooks/region_search_bigquery/earth_ai_region_search_bigquery.ipynb&utm_source=earth_ai_remote_sensing_notebooks">
      <img src="https://www.gstatic.com/images/branding/gcpiconscolors/bigquery/v1/32px.svg" alt="BigQuery Studio logo"><br> Open in BigQuery Studio
    </a>
  </td>
  <td style="text-align: center">
    <a href="https://console.cloud.google.com/vertex-ai/workbench/deploy-notebook?download_url=https://raw.githubusercontent.com/googlemaps-samples/insights-samples/main/earth_ai_remote_sensing/notebooks/region_search_bigquery/earth_ai_region_search_bigquery.ipynb&utm_source=earth_ai_remote_sensing_notebooks">
      <img src="https://www.gstatic.com/images/branding/gcpiconscolors/vertexai/v1/32px.svg" alt="Vertex AI Workbench logo"><br> Run in Workbench
    </a>
  </td>
  <td style="text-align: center">
    <a href="https://github.com/googlemaps-samples/insights-samples/blob/main/earth_ai_remote_sensing/notebooks/region_search_bigquery/earth_ai_region_search_bigquery.ipynb">
      <img width="32px" src="https://upload.wikimedia.org/wikipedia/commons/9/91/Octicons-mark-github.svg" alt="GitHub logo"><br> View on GitHub
    </a>
  </td>
</table>
<br clear="all"/>

---

## Overall Goal

This notebook provides an end-to-end blueprint for **metro-scale overhead imagery discovery and opportunity analysis** by combining:
1. **Google Earth AI Remote Sensing (`google/remote-sensing-embeddings`)** on Vertex AI Model Garden to encode `512×512` overhead aerial/satellite imagery tiles and natural-language text prompts into a shared, L2-normalized **`1152-D` vector space**.
2. **BigQuery (`VECTOR_SEARCH` & `ML.DISTANCE`)** to execute sub-second **Text-to-Tile Semantic Search**, **Tile-to-Tile Visual Similarity**, and **Opportunity Finder (Vector Algebra)** queries in pure SQL (`$0/hr` idle GPU cost).
3. **Interactive Map Visualization (`Folium` + Google Maps 2D Tiles)** to overlay and inspect the discovered `307 m × 307 m` tile footprints on an interactive map.

---

## Consolidated Configuration Parameters (Step 2)

All user-configurable `# @param` fields are consolidated at the top of the notebook in **Step 2 (`Configuration & All Notebook Parameters`)**:

| Parameter Group | Parameters | Default / Options | Description |
| :--- | :--- | :--- | :--- |
| **1. Google Cloud & BigQuery** | `PROJECT_ID`, `REGION`, `BQ_DATASET`, `TILES_TABLE_NAME`, `QUERIES_TABLE_NAME`, `GMP_API_KEY` | `REGION="us-central1"`, `BQ_DATASET="rsfm_demo"`, `TILES_TABLE_NAME="region_tiles_la"` | Selects the GCP project, BigQuery dataset/tables (`region_tiles_la` or `region_tiles_sf`), and optional Google Maps 2D Tile API key. |
| **2. AOI & Public-Domain NAIP Grid** | `AOI_NAME`, `AOI_MIN_LAT`, `AOI_MIN_LNG`, `AOI_MAX_LAT`, `AOI_MAX_LNG`, `TILE_SIZE_PX`, `MAX_DEMO_TILES`, `FETCH_LIVE_NAIP_TILES` | `TILE_SIZE_PX=512`, `FETCH_LIVE_NAIP_TILES=False` | Bounding box and resolution for fetching live public-domain USDA/USGS NAIP (`0.6 m` GSD) orthoimagery tiles (`17 U.S.C. § 105`). |
| **3. Earth AI Model Garden** | `DEPLOY_LIVE_VERTEX_ENDPOINT`, `EXISTING_ENDPOINT_ID`, `DISPLAY_NAME`, `MODEL_TYPE`, `MODEL_MODE`, `ACCELERATOR`, `RUN_BATCH_JOB_EXAMPLE` | `MODEL_TYPE="SIGLIP2_512_RC1"`, `MODEL_MODE="COMBINED"`, `ACCELERATOR="NVIDIA_L4"` | Deploys or attaches to a live Vertex AI endpoint, launches a `BatchPredictionJob`, or skips GPU deployment (`DEPLOY_LIVE_VERTEX_ENDPOINT=False`) to query pre-computed BigQuery tables immediately. |
| **4. Search & Vector Algebra** | `SEARCH_QUERY_ID`, `SEED_TILE_ID`, `POSITIVE_QUERY_ID`, `NEGATIVE_QUERY_ID`, `NEGATIVE_WEIGHT`, `TOP_K_RESULTS`, `VISUAL_GRID_TILES` | `SEARCH_QUERY_ID="distribution_warehouses"`, `NEGATIVE_WEIGHT=0.5`, `TOP_K_RESULTS=10` | Configures Step 5A (Text-to-Tile Search), Step 5B (Tile-to-Tile Visual Similarity), and Step 5C (Opportunity Finder Vector Algebra). |
| **5. Resource Cleanup** | `UNDEPLOY_ENDPOINT_ON_FINISH`, `DELETE_ENDPOINT_AND_MODEL` | `UNDEPLOY_ENDPOINT_ON_FINISH=False` | Controls Step 7 Vertex AI GPU endpoint teardown. |

---

## Step-by-Step Notebook Walkthrough

1. **Step 1 — Setup & Authentication**: Installs `google-cloud-aiplatform`, `google-cloud-bigquery`, `folium`, and `remote_sensing.vertex_ai.utils`, and authenticates via either Google Colab (`google.colab.userdata`) or Application Default Credentials (`google.auth.default()`).
2. **Step 2 — Configuration & All Notebook Parameters**: Consolidates all 23 `# @param` settings into one top-of-notebook configuration form and displays a summary table of active settings.
3. **Step 3 — Earth AI Remote Sensing Model Garden Architecture & Feature Extraction**: Explains the two-tower vision-language architecture (`IMAGE_ONLY`, `TEXT_ONLY`, `COMBINED`) and demonstrates online endpoint deployment (`Endpoint.predict`) and batch prediction (`Model.batch_predict`).
4. **Step 4 — Inspect (or Populate) BigQuery Spatial & `1152-D` Embedding Tables**: Summarizes tile coverage (`17,589` tiles / `~1,660 km²` in LA South Bay; `7,244` tiles / `~684 km²` in SF Bay Area), lists indexed `1152-D` text queries, and optionally fetches live public-domain USGS NAIP imagery.
5. **Step 5 — Three Metro-Scale BigQuery Retrieval Patterns**:
   - **5A (`Text-to-Tile Semantic Search`)**: Ranks regional tiles by cosine similarity (`1 - ML.DISTANCE(img, txt, 'COSINE')`) and regional z-score (`+σ`), and plots a visual grid of the top USDA NAIP tiles.
   - **5B (`Tile-to-Tile Visual Similarity`)**: Finds the top $K$ visually similar footprints across the metro area given a seed `tile_id`.
   - **5C (`Opportunity Finder — Vector Algebra`)**: Computes normalized composite vector algebra (`+distribution_warehouses - 0.5 * solar_rooftops`) to identify large commercial warehouse roofs without existing solar installations.
6. **Step 6 — Interactive Map Visualization**: Renders an interactive Folium map with **Google Maps 2D Hybrid/Satellite Tiles**, red bounding boxes for Step 5A semantic search matches, and green dashed bounding boxes for Step 5C Opportunity Finder matches.
7. **Step 7 — Optional Resource Cleanup**: Undeploys or deletes any live Vertex AI GPU endpoint created during the session.
