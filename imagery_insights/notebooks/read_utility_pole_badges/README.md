# Imagery Insights: Read Utility Pole Badges

This notebook demonstrates how to use Google Cloud's Imagery Insights and Vertex AI to automatically read and consolidate identification badge numbers from images of utility poles.

## Overview

The notebook performs the following steps:

1.  **Queries BigQuery:** Fetches a list of utility pole assets and their corresponding imagery stored in Google Cloud Storage (GCS).
2.  **Image Analysis:** For each asset, it analyzes multiple images.
3.  **Badge Reading with Gemini:** It uses the Gemini 2.5 Flash Vision model to perform the following substeps:
    *   Enhance the image to improve the legibility of the badge.
    *   Read the badge number from the enhanced image.
4.  **Consolidation:** If multiple images for the same pole yield partial or different badge numbers, it consolidates them to determine the most likely correct badge number.
5.  **Results:** Displays the final results, mapping each asset ID to its consolidated badge number.

## Prerequisites

*   A Google Cloud project with the following APIs enabled:
    *   BigQuery API
    *   Vertex AI API
*   Authentication configured to access your Google Cloud project.
*   A BigQuery table containing observation data for utility poles, including GCS URIs to the imagery.

## Installation

This notebook requires the following Python libraries:

```bash
pip install --upgrade google-cloud-bigquery google-genai pandas
```

## Configuration

Before running the notebook, you need to configure the following variables in the second code cell:

*   `PROJECT_ID`: Your Google Cloud project ID.
*   `REGION`: The Google Cloud region for your project (e.g., `us-central1`).

## Usage

1.  Install the required libraries.
2.  Set your `PROJECT_ID` and `REGION` in the configuration cell.
3.  Update the `BIGQUERY_SQL_QUERY` to point to your BigQuery table and desired assets.
4.  Run all the cells in the notebook.

The final output will be a pandas DataFrame showing the `asset_id` and the consolidated `badge_number`.
