# Utility Pole Lean Angle Detection

This notebook demonstrates how to use the Gemini 1.5 Flash model with code execution to determine the lean angle of utility poles from images.

## Description

The notebook automates the process of analyzing utility pole images to detect their lean angle. It performs the following steps:

1.  **Fetch Image URIs**: It queries a BigQuery table to get the Google Cloud Storage (GCS) URIs of the utility pole images to be analyzed.
2.  **Image Analysis with Gemini**: For each image, it uses the Gemini 1.5 Flash model. The model is given a prompt that instructs it to use code execution to perform a series of image processing tasks.
3.  **Computer Vision Techniques**: The prompt guides the model to perform Canny edge detection and Hough line transforms to identify the pole within the image and calculate its angle relative to the vertical axis.
4.  **Display Results**: The final output is a pandas DataFrame that lists each asset's ID along with its calculated lean angle.

## Configuration

Before running the notebook, you must update the variables in the "Configuration" section with your own settings:

*   `PROJECT_ID`: Your Google Cloud Project ID.
*   `REGION`: The Google Cloud region for your project.
*   `MODEL_ID`: The Gemini model to be used (e.g., "gemini-1.5-flash-001").
*   `BIGQUERY_DATASET_ID`: The ID of the BigQuery dataset containing the image data.
*   `BIGQUERY_TABLE`: The ID of the BigQuery table with the image URIs.
*   `ASSET_TYPE`: The asset type to filter for in the BigQuery table (e.g., "ASSET_CLASS_UTILITY_POLE").
*   `LIMIT`: The maximum number of images to process.

## Usage

1.  Open the `utility_pole_lean_angle_detection.ipynb` notebook.
2.  Fill in your project-specific details in the "Configuration" section.
3.  Execute the cells of the notebook in order.

The notebook will then connect to BigQuery, process the images using the Gemini model, and display a table of the results.