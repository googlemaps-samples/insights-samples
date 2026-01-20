# Object Detection with Few-Shot Learning for Utility Pole Analysis

This notebook demonstrates how to use the Gemini 1.0 Pro model with a few-shot learning approach to detect transformers on utility poles from images stored in Google Cloud Storage. The image URIs are fetched from a BigQuery table, and the model provides a JSON output with the count of detected transformers.

## Prerequisites

Before running this notebook, ensure you have the following:

*   A Google Cloud Platform (GCP) project.
*   The Vertex AI and BigQuery APIs enabled in your GCP project.
*   A BigQuery dataset and table containing the GCS URIs of the images to be analyzed.
*   The following Python libraries installed:
    *   `google-cloud-bigquery`
    *   `google-genai`

You can install the required libraries by running the following command:

```bash
pip install --upgrade google-cloud-bigquery google-genai
```

## Configuration

The following variables in the notebook need to be configured with your specific GCP project details:

*   `PROJECT_ID`: Your GCP Project ID.
*   `REGION`: The GCP region where your resources are located (e.g., `us-central1`).
*   `MODEL_ID`: The ID of the Gemini model to use (e.g., `gemini-1.0-pro`).
*   `BIGQUERY_DATASET_ID`: The ID of your BigQuery dataset.
*   `BIGQUERY_TABLE`: The name of your BigQuery table containing the image URIs.
*   `ASSET_TYPE`: The asset type to filter for in the BigQuery table (e.g., `ASSET_CLASS_UTILITY_POLE`).
*   `LIMIT`: The maximum number of images to process.

## Running the Notebook

1.  **Install Libraries:** Run the first cell to install the necessary Python libraries.
2.  **Configure Variables:** In the "Configuration" section, replace the placeholder values with your GCP project details.
3.  **Initialize Vertex AI:** Run the cell to initialize the Vertex AI SDK.
4.  **Fetch Image URIs:** Execute the BigQuery query to fetch the GCS URIs of the images.
5.  **Define Classification Function:** Run the cell that defines the `classify_image_with_gemini` function.
6.  **Classify Images:** Run the final cell to classify the images and see the JSON output from the model.

## Example Output

The model will provide a JSON output for each image, similar to the following:

```json
{
  "type": "utility pole",
  "transformers": 1,
  "telephone_or_junction_boxes": 0,
  "additional_notes": ""
}