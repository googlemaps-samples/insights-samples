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
│       ├── utility_pole_subclassification_using_full_frame_svi/ # Cataloged full-frame pole sub-classification & equipment audit
│       └── vegetation_encroachment_detection_using_full_frame_svi/ # Multi-view vegetation hazard audit
├── lidar/                                   # 3D LiDAR (.laz) spatial library & skills (Full-Frame & Panoramic)
│   ├── svi_lidar/                           # Shared .laz streaming, 2964.42 fisheye, True Color RGB & 3D geometry
│   └── skills/                              # Production 3D LiDAR & Image+LiDAR fusion skills
│       ├── analyze_building_and_driveway_clearance_3d_lidar/ # Commercial frontage, 1st-floor height & truck pull-in clearance
│       ├── fuse_image_and_3d_lidar/           # Bidirectional 3D->2D depth-masked Gemini crops & 2D->3D box casting
│       ├── measure_roadside_assets_3d_lidar/  # Pure-3D pole height/lean, sign WxH, tree crown & facade flatness
│       ├── project_and_colorize_3d_lidar/     # 2D front-surface overlay & Z-buffered True Color RGB 3D .ply draping
│       └── slice_road_curb_and_sidewalk_3d_lidar/ # Perpendicular road width, curb step & sidewalk width/slope slices
└── panoramic/                               # 360-degree panoramic scene analytics
    ├── notebooks/                           # Panoramic sequential & material analysis notebooks
    └── skills/                              # Production ADK skills for panoramic data
        ├── surface_material_detection_using_panoramic_svi/ # Dedicated ground/road surface material audit
        └── utility_pole_subclassification_using_panoramic_svi/ # Multi-view utility pole sub-classification & equipment audit
```

---

## 🗄️ Canonical BigQuery Architecture

All notebooks and skills query directly from the canonical dataset views in BigQuery:

*   **Dataset ID**: `imagery_insights___us`
*   **Panoramic Views**: `imagery_insights___us.pano_observations_latest`
*   **Full-Frame Views**: `imagery_insights___us.full_frame_observations_latest`
*   **3D LiDAR Views (Full-Frame & Panoramic)**: `imagery_insights_lidar___us.full_frame_lidar_metadata_latest` and `imagery_insights_lidar___us.pano_lidar_metadata_latest` (see [`lidar/`](lidar/))
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

## 🚀 Running Production Skills {#skills}

### Pre-requesites

1. Install the [Antigravity CLI](https://antigravity.google/product/antigravity-cli).

2. Set up your [Application Default Credentials](http://https://docs.cloud.google.com/docs/authentication/provide-credentials-adc) (ADC):

```sh
gcloud auth application-default login
```

3. _(Recommended)_ Set your GCP project ID in your shell environment:

```sh
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
```

4. _(Recommended)_ Use a python [virtual environment](https://docs.python.org/3/library/venv.html) for any python package dependencies
installed by the skill:

```sh
# create virtual environment
$ python3 -m venv .venv
$ source .venv/bin/activate
```

### Loading the skill

Run the Antigravity CLI:

```sh
$ agy
```

Load the skills directly such as:

```
Load skill at 'street_view_insights/full_frame/skills/analyze_utility_pole'

Load skill at 'street_view_insights/full_frame/skills/utility_pole_subclassification_using_full_frame_svi'

Load skill at 'street_view_insights/full_frame/skills/vegetation_encroachment_detection_using_full_frame_svi'

Load skill at 'street_view_insights/lidar/skills/project_and_colorize_3d_lidar'

Load skill at 'street_view_insights/lidar/skills/measure_roadside_assets_3d_lidar'

Load skill at 'street_view_insights/lidar/skills/slice_road_curb_and_sidewalk_3d_lidar'

Load skill at 'street_view_insights/lidar/skills/fuse_image_and_3d_lidar'

Load skill at 'street_view_insights/lidar/skills/analyze_building_and_driveway_clearance_3d_lidar'

Load skill at 'street_view_insights/panoramic/skills/surface_material_detection_using_panoramic_svi'

Load skill at 'street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi'
```

> Alternatively, you can reference these folders via standard Antigravity CLI agent skills folders as described [here](https://antigravity.google/docs/cli/plugins#agent-skills).

Run the skill of your choice:

```
/analyze-utility-pole Inspect the utility pole from asset t1:...

/analyze-utility-pole Reconcile images for asset t1:...

/analyze-utility-pole Compare images for asset t1:...

/utility-pole-subclassification-using-full-frame-svi Audit cataloged utility poles around GPS coordinates <lat,lng>

/utility-pole-subclassification-using-full-frame-svi Audit cataloged utility pole asset t1:...

/vegetation-encroachment-detection-using-full-frame-svi Audit full-frame observations for asset t1:...

/vegetation-encroachment-detection-using-full-frame-svi Audit a specific observation o1:...

/vegetation-encroachment-detection-using-full-frame-svi Audit a direct image gs://...

/project-and-colorize-3d-lidar Colorize 3D LiDAR point cloud in True Color RGB for observation o1:...

/measure-roadside-assets-3d-lidar Measure 3D pole height, lean angle, and sign dimensions for observation o1:...

/slice-road-curb-and-sidewalk-3d-lidar Slice roadway width, curb reveal, and sidewalk width/slope for observation o1:...

/fuse-image-and-3d-lidar Run depth-masked 3D-to-2D Gemini crop check and 2D-to-3D box cast for observation o1:...

/analyze-building-and-driveway-clearance-3d-lidar Analyze first-floor height, driveway width, and truck clearance for observation o1:...

/surface-material-detection-using-panoramic-svi Audit observation o1:...

/surface-material-detection-using-panoramic-svi Audit GPS coordinates <lat,lng>

/surface-material-detection-using-panoramic-svi Audit a direct image gs://...

/utility-pole-subclassification-using-panoramic-svi Audit utility poles around GPS coordinates <lat,lng>

/utility-pole-subclassification-using-panoramic-svi Audit utility poles around observation o1:...
```

### Cleanup

If you created a python virtual environment above, you can easily deactivate and remove it as follows:

```sh
$ deactivate

$ rm -rf .venv
```
