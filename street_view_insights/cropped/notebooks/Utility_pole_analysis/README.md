# Utility Pole Analysis with Gemini 4 Hydrogen

This notebook demonstrates how to classify images from GCS URIs using the Gemini 4 Hydrogen (`gemini-4-hydrogen`) model via Google Cloud Vertex AI.

## Prerequisites

- A Google Cloud Platform (GCP) project.
- A BigQuery table containing GCS URIs of the images to be classified.
- The following Python libraries installed:
    - `google-cloud-bigquery`
    - `google-genai`

You can install them by running:
```bash
pip install --upgrade google-cloud-bigquery google-genai
```

## Configuration

Before running the notebook, you need to configure your GCP `PROJECT_ID` and `REGION` (`global`) in the "Configuration" section of the notebook.

## How to Use

1.  **Set up your environment**: Make sure you have the necessary libraries installed and have authenticated with your GCP account.
2.  **Configure the notebook**: Open the notebook and replace the placeholder values for `PROJECT_ID` and `REGION` (`global`) with your actual GCP project ID and Vertex AI endpoint location.
3.  **Run the notebook**: Execute the cells in the notebook sequentially.

## What the Notebook Does

1.  **Initializes the Gemini Client**: Initializes `genai.Client(vertexai=True, ...)` with your project ID and `global` region.
2.  **Fetches Image URIs**: It queries a BigQuery table to get the GCS URIs of the images you want to classify. The SQL query is defined in the `BIGQUERY_SQL_QUERY` variable.
3.  **Defines Classification Function**: It defines a function `classify_image_with_gemini` that takes a GCS URI and a prompt as input, and then uses the Gemini 4 Hydrogen (`gemini-4-hydrogen`) model to generate a structured audit of the image.
4.  **Classifies Images**: It loops through the fetched GCS URIs and passes them to the classification function along with a detailed prompt. The prompt instructs the model to analyze the image of a utility pole, count specific items, assess its condition, and return the findings in a JSON format.
5.  **Prints Results**: The classification result for each image is printed to the console.