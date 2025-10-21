# Utility Pole Badge Reader

This notebook demonstrates how to extract badge numbers from utility pole imagery using Google Cloud's Vertex AI and BigQuery.

## Workflow

1.  **Configuration**: Set your GCP Project ID, Region, and BigQuery Dataset ID.
2.  **Query BigQuery**: Fetch asset IDs and GCS URIs for utility pole images from your BigQuery dataset.
3.  **Group Images**: Group the images by asset ID.
4.  **Enhance and Read Badges**: For each asset, the notebook iterates through the images, enhances them using a nano-Banana model, and then uses a Gemini model to read the badge number.
5.  **Consolidate Badge Numbers**: If multiple badge numbers are read for the same asset, they are consolidated into a single, most likely number.
6.  **Display Results**: The final results are displayed in a pandas DataFrame.

## Requirements

*   Google Cloud SDK
*   Python 3
*   Jupyter Notebook
*   google-cloud-bigquery
*   google-genai

## Usage

1.  Install the required libraries.
2.  Set the `PROJECT_ID`, `REGION`, and `DATASET_ID` variables in the notebook.
3.  Run the notebook cells sequentially.
