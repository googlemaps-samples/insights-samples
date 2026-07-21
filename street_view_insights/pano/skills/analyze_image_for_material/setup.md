# Onboarding & Project Setup

This guide details how to set up dependencies, authenticate with Google Cloud, and verify your BigQuery dataset schema to onboard the **Road Surface Material Detection** skill.

---

## Step 1: Install Python Dependencies

Run the following command to install the required libraries:
```bash
pip install google-genai google-cloud-bigquery pillow
```

---

## Step 2: Authenticate with Google Cloud

Your environment needs Google Cloud credentials configured to query BigQuery and call Vertex AI APIs.

### On a Local Developer Machine
Run the following command to log in:
```bash
gcloud auth application-default login
```

### In a Container or Cloud Run Environment
Assign a custom service account to the execution runtime, and ensure it has been granted:
*   `roles/bigquery.jobUser` (Project level)
*   `roles/bigquery.dataViewer` (Dataset level)
*   `roles/aiplatform.user` (Project level)

---

## Step 3: Dataset Schema Alignment

To run queries by Track ID or Coordinates, your BigQuery tables must conform to the following schema guidelines:

### 1. Tracks Table
Contains geographical track geometries and references to imagery observation frames.
*   `trackId` (STRING, Nullable): Unique identifier for a track sequence.
*   `geometry` (GEOGRAPHY, Nullable): Spatial representation of the track coordinates.
*   `observationIds` (STRING, REPEATED): Ordered array of observation identifiers.

### 2. Image URLs Table
Maps observation IDs to GCS storage URIs.
*   `observationId` (STRING, Nullable): Unique identifier for an observation frame.
*   `signedUrl` (STRING, Nullable): Fully qualified GCS URI (e.g., `gs://bucket/path.jpg`) or HTTP signed URL pointing to the image.

---

## Step 4: Run the Onboarding Check

We provide an automated onboarding script that checks package dependencies, authentication states, BigQuery tables, column schemas, and Vertex AI responsiveness.

Set your target environment variable configurations:
```bash
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export BIGQUERY_DATASET="your_dataset_name"
export BIGQUERY_TRACKS_TABLE="your_tracks_table"  # Optional, default: tracks
export BIGQUERY_URLS_TABLE="your_urls_table"      # Optional, default: urls_new
```

Run the onboarding script:
```bash
python3 skills/analyze_image_for_material/scripts/onboard_check.py
```

### Expected Successful Output
```
=== ONBOARDING SYSTEM & CONFIGURATION CHECK ===

[1] Checking Python package dependencies...
  ✓ google-genai is installed.
  ✓ google-cloud-bigquery is installed.
  ✓ pillow is installed.

[2] Checking Google Cloud Project parameters...
  - Target Project: your-gcp-project-id
  - Target Dataset: your_dataset_name
  - Tracks Table:   your_tracks_table
  - URLs Table:     your_urls_table
  - Vertex Region:  us-central1

[3] Verifying BigQuery dataset and schema alignment...
  ✓ Dataset 'your_dataset_name' found.
  ✓ Table 'your_tracks_table' schema aligns (trackId, observationIds, geometry present).
  ✓ Table 'your_urls_table' schema aligns (observationId, signedUrl present).

[4] Verifying Vertex AI connection & model availability...
  ✓ Vertex AI Client initialized and model is responsive.

🎉 ONBOARDING VERIFICATION SUCCESSFUL! Project is fully ready to run the skill.
```
