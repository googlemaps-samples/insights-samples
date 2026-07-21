# Road Sign Classification with Gemini

This notebook demonstrates how to use the Gemini 2.5 Flash model through Vertex AI to classify road signs from images.

## Overview

The notebook performs the following steps:

1.  **Configuration**: Sets up the Google Cloud project, region, and BigQuery dataset details.
2.  **Data Fetching**: Queries a BigQuery table to retrieve Google Cloud Storage (GCS) URIs for images that are classified as road sign assets (`ASSET_CLASS_ROAD_SIGN`).
3.  **Image Classification**: For each image URI, it calls the Gemini 2.5 Flash model.
4.  **Prompt Engineering**: A detailed prompt guides the model to act as an image analysis expert. The model is instructed to identify signs by their shape, color, and text, and then classify them into predefined categories:
    *   Stop
    *   Yield
    *   Speed Limit
    *   Pedestrian Crossing
    *   No Parking
    *   Turn
    *   Do not enter
    *   Street name
    *   Other
5.  **Structured Output**: The model is instructed to return its findings in a structured JSON format, including the sign identified, the reasoning behind the classification, and a confidence score (`High` or `Medium`).
6.  **Results**: The notebook iterates through the list of images and prints the JSON output from the model for each one.

## How to Use

1.  **Set up your environment**: Make sure you have the required Python libraries installed (`google-cloud-bigquery`, `google-cloud-aiplatform`).
2.  **Configure the notebook**: Update the configuration cells with your `PROJECT_ID`, `REGION`, and the correct BigQuery `DATASET_ID` and `TABLE_ID`.
3.  **Run the notebook**: Execute the cells in order to fetch the image data and perform the classification.
