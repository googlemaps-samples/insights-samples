# Bounding Box Detection of Utility Pole Attachments

This notebook demonstrates how to use the Gemini 1.5 Flash model to detect bounding boxes of telephone attachments in images from the Imagery Insights Utility Pole dataset.

## Description

The notebook performs the following steps:

1.  **Configuration**: Sets up the Google Cloud Project ID, region, and BigQuery dataset details.
2.  **Imports**: Imports the necessary libraries, including the Vertex AI SDK and BigQuery client library.
3.  **Fetch Image URIs**: Queries a BigQuery table to retrieve the GCS URIs of utility pole images.
4.  **Define Classification Function**: Defines a function that takes an image URI and a prompt, then uses the Gemini 1.5 Flash model to identify and return bounding boxes for telecommunications-related objects in the image.
5.  **Classify Images**: Loops through the fetched image URIs and applies the classification function to each, printing the results.

## Configuration

Before running the notebook, you need to configure the following variables in the "Configuration" section:

*   `PROJECT_ID`: Your Google Cloud Project ID.
*   `REGION`: The Google Cloud region where you want to run the notebook.
*   `BIGQUERY_DATASET_ID`: The BigQuery dataset ID containing the imagery data.
*   `BIGQUERY_TABLE_ID`: The BigQuery table ID with the image URIs.
*   `QUERY_LIMIT`: The maximum number of images to process.
*   `ASSET_TYPE`: The type of asset to analyze (e.g., "ASSET_CLASS_UTILITY_POLE").
*   `MODEL`: The name of the Gemini model to use (e.g., "gemini-1.5-flash-001").

## Usage

1.  Open the `bbox_detection_of_attachment.ipynb` notebook.
2.  Update the "Configuration" section with your specific project details.
3.  Run the cells in the notebook sequentially.

The notebook will then fetch the image URIs from BigQuery, process each image using the Gemini model, and print the bounding box information for the detected attachments.