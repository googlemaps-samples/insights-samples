# Aerial and Satellite Models (Earth AI Remote Sensing)

This top-level directory contains end-to-end Google Colab Enterprise, BigQuery Studio, and Workbench notebooks demonstrating how to combine **Google Maps Platform Aerial and Satellite Models (`ASM - Classification and Retrieval`)** on **Agent Platform Model Garden** (part of the **Google Earth AI** effort, using **`RS-SigLIP2`**) with **BigQuery (`VECTOR_SEARCH` & `ML.DISTANCE`)** for native-resolution tiling, regional overhead imagery search, and opportunity discovery.

---

## 📁 Directory Structure

```text
earth_ai_remote_sensing/
├── README.md
└── notebooks/
    └── region_search_bigquery/
        ├── README.md
        └── earth_ai_region_search_bigquery.ipynb
```

---

## 📓 Notebooks

| Notebook | Description | Launch |
| :--- | :--- | :--- |
| **[`earth_ai_region_search_bigquery.ipynb`](./notebooks/region_search_bigquery/earth_ai_region_search_bigquery.ipynb)** | End-to-end blueprint for **native-resolution GeoTIFF / USGS NAIP tiling** and **metro-scale overhead imagery search** using **ASM - Classification and Retrieval (`RS-SigLIP2` `1152-D` embeddings)** on **Agent Platform Model Garden**, **BigQuery `ML.DISTANCE` / `VECTOR_SEARCH`**, and **Opportunity Finder vector algebra (`A − α·B`)**. | [Open in Colab Enterprise](https://console.cloud.google.com/vertex-ai/colab/import/https:%2F%2Fraw.githubusercontent.com%2Fgooglemaps-samples%2Finsights-samples%2Fmain%2Fearth_ai_remote_sensing%2Fnotebooks%2Fregion_search_bigquery%2Fearth_ai_region_search_bigquery.ipynb?utm_source=earth_ai_remote_sensing_notebooks) · [Open in BigQuery Studio](https://console.cloud.google.com/bigquery/import?url=https://github.com/googlemaps-samples/insights-samples/blob/main/earth_ai_remote_sensing/notebooks/region_search_bigquery/earth_ai_region_search_bigquery.ipynb&utm_source=earth_ai_remote_sensing_notebooks) |

---

## 🛰️ Reference Architecture: Tile at Native GSD → Embed Once on GPU → Search Unlimited Times in BigQuery SQL

| Stage | Component | Role | Frequency & Cost Profile |
| :--- | :--- | :--- | :--- |
| **1. Native-GSD Tile Grid** | **`rasterio` Windowed Tiler / USDA NAIP (`USGSNAIPImagery`)** | Slices Cloud-Optimized GeoTIFFs at native sensor GSD (`0.1–0.3 m/px` sweet spot; supports `0.3–3 m/px`) or public-domain `0.6 m` NAIP orthoimagery (`17 U.S.C. § 105`) into `224×224` or `512×512 px` chips and `file-list` / `.jsonl` batch inputs. | **One-time / Periodic** refresh. |
| **2. Feature Extraction** | **ASM - Classification and Retrieval (`RS-SigLIP2`)** *(Agent Platform Model Garden)* | Encodes overhead tiles (`IMAGE_ONLY` / Batch) and search prompts (`TEXT_ONLY` / Online) into shared, L2-normalized `ARRAY<FLOAT64>` (`1152-D`) vectors. | **One-time GPU job** for tiles; **< 50 ms** for new text prompts. |
| **3. Spatial & Vector Indexing** | **BigQuery (`PARTITION BY capture_date CLUSTER BY zone, tile_id` + `VECTOR INDEX`)** | Stores tile bounding boxes, `GEOGRAPHY` polygons, `1152-D` image vectors, and pre-encoded text vectors in native BigQuery tables. | **Serverless Storage** (`$0.02 / GB / month`). |
| **4. Metro-Scale Retrieval** | **BigQuery `ML.DISTANCE` & `VECTOR_SEARCH`** | Executes **Text-to-Tile Search**, **Tile-to-Tile Visual Similarity**, and **Opportunity Finder Vector Algebra (`pos - α·neg`)** with regional z-score (`+σ`) calibration. | **Pure SQL** (`$0/hr` idle GPU cost once indexed). |
