# Street View Insights (SVI) Framework

Welcome to the **Street View Insights (SVI)** sample library and skills framework. This directory provides production-ready Jupyter notebooks, CLI skills, and microservices for performing multimodal visual analysis on Google Street View imagery using **Gemini 3.5 Flash** and **Google Cloud BigQuery**.

---

## 📁 Repository Structure

```
street_view_insights/
├── cropped/                                 # Object-level cropped image analytics
│   ├── notebooks/                           # Legacy & object detection notebooks
│   ├── queries/                             # Standard SQL queries
│   └── samples/                             # Batch processor & visualization app
├── full_frame/                              # Wide-angle contextual scene analytics
│   ├── notebooks/                           # Full-frame contextual analysis notebooks
│   └── skills/                              # Production ADK skills for full-frame data
│       ├── analyze_utility_pole/              # Multi-view utility pole inspection & reconciliation
│       └── vegetation_encroachment_detection_using_full_frame_svi/ # Multi-view vegetation hazard audit
└── panoramic/                               # 360-degree panoramic scene analytics
    ├── notebooks/                           # Panoramic sequential & material analysis notebooks
    └── skills/                              # Production ADK skills for panoramic data
        └── surface_material_detection_using_panoramic_svi/ # Dedicated ground/road surface material audit
```

---

## 🗄️ Canonical BigQuery Architecture

All notebooks and skills query directly from the canonical dataset views in BigQuery:

*   **Dataset ID**: `imagery_insights___us`
*   **Panoramic Views**: `imagery_insights___us.pano_observations_latest`
*   **Full-Frame Views**: `imagery_insights___us.full_frame_observations_latest`
*   **Cropped Views**: `imagery_insights___us.cropped_observations_latest`

> **Note**: Do not reference legacy tables (`home_depot_full_scene`, `tracks_unnested`, `observations_view`, or `urls_view`).

---

## ⚡ Cloud-Native Execution Principles

1.  **Zero Local Image Downloads**:
    *   Images are processed 100% remotely in Google Cloud by passing native GCS URIs (`gs://...`) directly via `types.Part.from_uri(file_uri=gcs_uri, mime_type="image/jpeg")`.
2.  **Remote Code Execution Tool**:
    *   Gemini's native Python Code Execution tool (`tools=[{"code_execution": {}}]`) is enabled for remote bounding box slicing, crop inspections, and visual math in cloud execution containers.
3.  **Zero-Config Authentication & Auto-Project Resolution**:
    *   Authenticates via Application Default Credentials (ADC).
    *   CLI scripts and notebooks default to `YOUR_PROJECT_ID` placeholders with `google.auth.default()` auto-resolution.

---

## 🚀 Running Production Skills

### 1. Surface Material Detection (Panoramic)
```bash
python3 street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py \
    --observation-id <observation_id>
```

### 2. Vegetation Encroachment Detection (Full-Frame)
```bash
python3 street_view_insights/full_frame/skills/vegetation_encroachment_detection_using_full_frame_svi/scripts/analyze_vegetation_encroachment.py \
    --asset-id "t1:9737b62559f98bc84a3c9532b4449ccb:ffff01ee"
```

### 3. Utility Pole Analysis (Full-Frame & Cropped)
```bash
PROJECT_ID=...
DATASET_ID=...
ASSET_ID=...
IMAGE_VARIANT_TYPE="cropped"

python3 street_view_insights/full_frame/skills/analyze_utility_pole/scripts/analyze_utility_pole.py \
    --project=$PROJECT_ID \
    --dataset=$DATASET_ID \
    --task inspect \
    --data-type=$IMAGE_VARIANT_TYPE \
    --asset-id $ASSET_ID
```
