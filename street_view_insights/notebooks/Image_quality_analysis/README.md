# Image Quality Analysis using Gemini

This notebook demonstrates how to use the Gemini model to perform various quality analyses on images stored in Google Cloud Storage.

## Overview

The notebook fetches image URIs from a BigQuery table and then uses the Gemini model to analyze the following quality aspects for each image:

*   **Black Blurb Percentage:** Calculates the percentage of black or near-black pixels.
*   **Resolution:** Determines the width and height of the image.
*   **Sharpness:** Calculates a sharpness score based on the variance of the Laplacian.
*   **Brightness:** Calculates the average brightness of the image.
*   **Distortion:** Provides a qualitative assessment of lens distortion.

The results of the analysis are then compiled into a pandas DataFrame for easy viewing and further analysis.

## Prerequisites

Before running this notebook, ensure you have the following:

*   A Google Cloud Platform project with the Vertex AI API enabled.
*   A BigQuery table containing the GCS URIs of the images you want to analyze.
*   Authentication configured for your GCP project.

## Installation

The notebook requires the following Python libraries:

```bash
pip install --upgrade google-cloud-bigquery google-cloud-aiplatform pandas
```

## Usage

1.  **Configuration:**
    *   Set the `PROJECT_ID`, `REGION`, `MODEL_ID`, `BIGQUERY_TABLE`, `ASSET_TYPE`, and `LIMIT` variables in the "Configuration" section of the notebook.

2.  **Run the Notebook:**
    *   Execute the cells in the notebook sequentially.

The notebook will then:
1.  Fetch the image URIs from your BigQuery table.
2.  Analyze each image using the specified prompts and the Gemini model.
3.  Display the analysis results in a pandas DataFrame.
