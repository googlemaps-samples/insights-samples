# Aerial and Satellite Models: Region Search with BigQuery Vector Search

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
      <img src="https://www.gstatic.com/images/branding/gcpiconscolors/vertexai/v1/32px.svg" alt="Workbench logo"><br> Run in Workbench
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

This notebook provides an end-to-end blueprint for **metro-scale overhead imagery discovery and opportunity analysis** by combining **Google Maps Platform Aerial and Satellite Models (`ASM - Classification and Retrieval`)** on **Agent Platform Model Garden** (part of the **Google Earth AI** effort) with **BigQuery Vector Search**:
1. **Native-Resolution Tiling (`GeoTIFF` & Public-Domain `USGS NAIP`)** — slices Cloud-Optimized GeoTIFFs (`gs://.../*.tif`) at **100% native sensor resolution** (`224×224` or `512×512 px` windows via `rasterio`, zero resize distortion) or tiles a bounding box from federal **USDA/USGS NAIP (`USGSNAIPImagery`)** (`0.6 m` GSD), writing Model Garden `.jsonl` batch shards and loading BigQuery.
2. **ASM - Classification and Retrieval (`RS-SigLIP2`) on Agent Platform Model Garden** — deployed via [`google-research/remote-sensing`](https://github.com/google-research/remote-sensing/blob/main/remote_sensing/vertex_ai/utils.py) `remote_sensing.vertex_ai.utils` — encodes `224×224` or `512×512` overhead imagery tiles and natural-language prompts into a shared, L2-normalized **`1152-D` vector space**.
3. **BigQuery (`VECTOR_SEARCH` & `ML.DISTANCE`)** executes sub-second **Text-to-Tile Semantic Search**, **Tile-to-Tile Visual Similarity**, and **Opportunity Finder (Vector Algebra / Negative Background Subtraction)** queries in pure SQL (`$0/hr` idle GPU cost).
4. **Interactive Google Maps Visualization (`google.maps.Map`)** overlays and inspects the discovered tile footprints directly on an interactive Google Map.

---

## Consolidated Configuration Parameters (Step 2)

All user-configurable `# @param` fields are consolidated at the top of the notebook in **Step 2 (`Configuration & All Notebook Parameters`)**:

| Parameter Group | Parameters | Default / Options | Description |
| :--- | :--- | :--- | :--- |
| **1. Google Cloud, BigQuery & Google Maps** | `PROJECT_ID`, `REGION`, `BQ_DATASET`, `TILES_TABLE_NAME`, `QUERIES_TABLE_NAME`, `GMP_API_KEY` | `REGION="us-central1"`, `BQ_DATASET="rsfm_demo"`, `TILES_TABLE_NAME="region_tiles_la"` | Selects the Google Cloud project, BigQuery dataset/tables (`region_tiles_la` or `region_tiles_sf`), and Google Maps JavaScript API key (`GMP_API_KEY`) for Step 6. |
| **2. Native-Resolution Tiling (`GeoTIFF` or `USGS NAIP`)** | `BUILD_TILES_FROM_SCRATCH`, `SOURCE_GEOTIFF_URI`, `CAPTURE_DATE_ISO`, `AOI_NAME`, `AOI_MIN_LAT`, `AOI_MIN_LNG`, `AOI_MAX_LAT`, `AOI_MAX_LNG`, `TILE_SIZE_PX`, `TARGET_GSD_M`, `MAX_DEMO_TILES`, `MIN_TILE_STDDEV`, `FETCH_LIVE_NAIP_TILES`, `CREATE_VECTOR_INDEX` | `TILE_SIZE_PX=512`, `BUILD_TILES_FROM_SCRATCH=False` | Slices a Cloud Storage GeoTIFF (`SOURCE_GEOTIFF_URI`) at native sensor GSD or slices `USGSNAIPImagery` (`0.6 m` GSD), generates `.jsonl` batch shards, and populates BigQuery. |
| **3. ASM - Classification and Retrieval (`remote_sensing.vertex_ai.utils`)** | `DEPLOY_LIVE_ENDPOINT`, `EXISTING_ENDPOINT_ID`, `DISPLAY_NAME`, `MODEL_TYPE`, `MODEL_MODE`, `ACCELERATOR`, `USE_DEDICATED_ENDPOINT`, `MIN_REPLICA_COUNT`, `MAX_REPLICA_COUNT`, `RUN_BATCH_JOB_EXAMPLE` | `MODEL_TYPE="SIGLIP2_512_RC1"`, `MODEL_MODE="COMBINED"`, `ACCELERATOR="NVIDIA_L4"` | Configures `utils.create_model(...)` and `utils.deploy_model(...)` (`SIGLIP2_224_RC1` or `SIGLIP2_512_RC1`) or skips GPU deployment when `DEPLOY_LIVE_ENDPOINT=False` to query pre-computed BigQuery tables immediately. |
| **4. Search & Vector Algebra** | `SEARCH_QUERY_ID`, `SEED_TILE_ID`, `POSITIVE_QUERY_ID`, `NEGATIVE_QUERY_ID`, `NEGATIVE_WEIGHT`, `TOP_K_RESULTS`, `VISUAL_GRID_TILES` | `SEARCH_QUERY_ID="distribution_warehouses"`, `NEGATIVE_WEIGHT=0.5`, `TOP_K_RESULTS=10` | Configures Step 5A (Text-to-Tile Search), Step 5B (Tile-to-Tile Visual Similarity), and Step 5C (Opportunity Finder Vector Algebra). |
| **5. Resource Cleanup** | `UNDEPLOY_ENDPOINT_ON_FINISH`, `DELETE_ENDPOINT_AND_MODEL` | `UNDEPLOY_ENDPOINT_ON_FINISH=False` | Controls Step 7 GPU endpoint teardown. |

---

## Step-by-Step Notebook Walkthrough

1. **Step 1 — Setup & Authentication**: Installs `google-cloud-aiplatform`, `requests-toolbelt`, `rasterio`, and `google-cloud-bigquery`, clones [`google-research/remote-sensing`](https://github.com/google-research/remote-sensing) (`from remote_sensing.vertex_ai import utils`), and authenticates via Google Colab (`google.colab.userdata`) or Application Default Credentials (`google.auth.default()`).
2. **Step 2 — Configuration & All Notebook Parameters**: Consolidates all `# @param` settings into one top-of-notebook configuration form and displays a summary table including `utils.MODEL_CONFIGS[MODEL_TYPE]` and `utils.PLATFORM_CONFIGS[ACCELERATOR]`.
3. **Step 3 — ASM - Classification and Retrieval (`RS-SigLIP2`) on Agent Platform Model Garden**: Uses `utils.create_model(...)`, `utils.deploy_model(...)`, and `utils.b64_png(...)` to demonstrate online endpoint deployment (`endpoint.predict`) and serverless batch prediction (`batch_model.batch_predict` with `batch_model=True`).
4. **Step 3B — Native-Resolution Tiling & BigQuery Vector Indexing (`GeoTIFF` or `USGS NAIP`)**: Slices a Cloud-Optimized GeoTIFF (`tile_geotiff_native_gsd`) at native sensor GSD or slices a public-domain NAIP grid (`tile_usgs_naip_aoi_grid`), stages `file-list` / `.jsonl` inputs to Cloud Storage (`stage_batch_prediction_inputs`), and loads partitioned/clustered BigQuery vector tables (`ingest_batch_predictions_to_bigquery` / `embed_online_and_load_bigquery`).
5. **Step 4 — Inspect the BigQuery Spatial & `1152-D` Embedding Tables**: Summarizes tile coverage, `GEOGRAPHY` footprints, and indexed `1152-D` text queries.
6. **Step 5 — Three Metro-Scale BigQuery Retrieval Patterns**:
   - **5A (`Text-to-Tile Semantic Search`)**: Ranks regional tiles by cosine similarity (`1 - ML.DISTANCE(img, txt, 'COSINE')`) and regional z-score (`+σ`), and plots a visual grid of the top tiles.
   - **5B (`Tile-to-Tile Visual Similarity`)**: Finds the top $K$ visually similar footprints across the metro area given a seed `tile_id`.
   - **5C (`Opportunity Finder — Vector Algebra`)**: Computes normalized composite vector algebra (`+distribution_warehouses - 0.5 * solar_rooftops`) to identify large commercial warehouse roofs without existing solar installations.
7. **Step 6 — Interactive Google Maps Visualization (`google.maps.Map`)**: Renders a native interactive **Google Map** (`maps.googleapis.com/maps/api/js` in `hybrid` mode) with clickable `google.maps.Rectangle` overlays and `google.maps.InfoWindow` popups.
8. **Step 7 — Optional Resource Cleanup**: Undeploys or deletes (`endpoint.delete(force=True)`) any live GPU endpoint created during the session.
