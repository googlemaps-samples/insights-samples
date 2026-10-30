# Aerial and Satellite Models (Earth AI Remote Sensing)

This top-level directory contains end-to-end Google Colab Enterprise, BigQuery Studio, and Workbench notebooks demonstrating how to combine **Google Maps Platform Aerial and Satellite Models** on **Agent Platform Model Garden** (part of the **Google Earth AI Remote Sensing Foundation Models** effort, using **`RS-SigLIP2`**) with **BigQuery (`VECTOR_SEARCH` & `ML.DISTANCE`)** for regional overhead imagery search and opportunity discovery.

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
| **[`earth_ai_region_search_bigquery.ipynb`](./notebooks/region_search_bigquery/earth_ai_region_search_bigquery.ipynb)** | End-to-end blueprint for **metro-scale overhead imagery search** using **Aerial and Satellite Models (`RS-SigLIP2` `1152-D` embeddings)** on **Agent Platform Model Garden**, **BigQuery `ML.DISTANCE` / `VECTOR_SEARCH`**, and **Opportunity Finder vector algebra (`A − α·B`)**. | [Open in Colab Enterprise](https://console.cloud.google.com/vertex-ai/colab/import/https:%2F%2Fraw.githubusercontent.com%2Fgooglemaps-samples%2Finsights-samples%2Fmain%2Fearth_ai_remote_sensing%2Fnotebooks%2Fregion_search_bigquery%2Fearth_ai_region_search_bigquery.ipynb?utm_source=earth_ai_remote_sensing_notebooks) · [Open in BigQuery Studio](https://console.cloud.google.com/bigquery/import?url=https://github.com/googlemaps-samples/insights-samples/blob/main/earth_ai_remote_sensing/notebooks/region_search_bigquery/earth_ai_region_search_bigquery.ipynb&utm_source=earth_ai_remote_sensing_notebooks) |

---

## 🛰️ Reference Architecture: Embed Once on GPU → Search Unlimited Times in BigQuery SQL

| Stage | Component | Role | Frequency & Cost Profile |
| :--- | :--- | :--- | :--- |
| **1. Public-Domain Tile Grid** | **USDA / USGS NAIP ImageServer** | Slices a metropolitan Area of Interest (AOI) into geo-referenced `512×512 px` (`0.6 m` GSD, `~307 m × 307 m`) aerial orthoimagery tiles (`17 U.S.C. § 105`). | **One-time / Periodic** refresh. |
| **2. Feature Extraction** | **Aerial and Satellite Models (`RS-SigLIP2`)** *(Agent Platform Model Garden)* | Encodes overhead tiles (`IMAGE_ONLY` / Batch) and search prompts (`TEXT_ONLY` / Online) into shared, L2-normalized `ARRAY<FLOAT64>` (`1152-D`) vectors. | **One-time GPU job** for tiles; **< 50 ms** for new text prompts. |
| **3. Spatial & Vector Indexing** | **BigQuery (`GEOGRAPHY` + `VECTOR INDEX`)** | Stores tile bounding boxes, `1152-D` image vectors, and pre-encoded text vectors in native BigQuery tables. | **Serverless Storage** (`$0.02 / GB / month`). |
| **4. Metro-Scale Retrieval** | **BigQuery `ML.DISTANCE` & `VECTOR_SEARCH`** | Executes **Text-to-Tile Search**, **Tile-to-Tile Visual Similarity**, and **Opportunity Finder Vector Algebra (`pos - α·neg`)** with regional z-score (`+σ`) calibration. | **Pure SQL** (`$0/hr` idle GPU cost once indexed). |
