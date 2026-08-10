# Export Street View Insights to Vertex AI Manged Datasets

This directory contains `create_vertex_dataset.py`, a utility script designed to
fetch Street View image URLs (`gcs_uri`s) from a BigQuery observations table and
seamlessly format them into a JSONL file that complies with Vertex AI's import
requirements for image datasets.

Once generated, the JSONL file is uploaded to your specified Google Cloud
Storage bucket so it can be ingested by Vertex AI Managed Datasets for training
or visualization.

## Prerequisites

-   You must have the Google Cloud SDK (`gcloud`) installed and authorized.
-   The default GCP Project must be correctly configured: `gcloud config set
    project PROJECT_ID`
-   The following Python packages must be installed: `pip install
    google-cloud-bigquery google-cloud-storage`

## 1. Configure the Variables

Open the `create_vertex_dataset.py` script and examine the Default Configuration
variables explicitly defined at the top of the file. You may modify these
directly in the code, pass them via command-line arguments or by setting
environment variables.

The required args are:

-   arg `--project_id` or env variable `GOOGLE_CLOUD_PROJECT`: Your Project ID
-   arg `--bucket_name` or env variable `GCS_BUCKET_NAME`: The destination
    Google Cloud Storage bucket where the JSONL file will be uploaded

The optional args are:

-   `--table_id` or variable `TABLE_ID`: The BigQuery table id from which to
    fetch the raw image URIs. Ensure the table contains a column named `gcs_uri`
    (e.g., `cropped_observations_latest`).
-   `--dataset_id` or variable `DATASET_ID`: The name of the dataset.
-   `--gcs_folder` or variable `GCS_DESTINATION_FOLDER`: The folder *inside* the
    GCS bucket where the JSONL file will be stored (e.g.,
    `street_view_insights`).
-   `--limit` or variable `LIMIT_URLS`: The maximum number of URLs to fetch from
    the table (useful for creating small sample datasets).
-   `--include_labels`: Include `asset_type` as labels in Vertex AI Multi-Label
    Classification format. Ensure the table contains an `asset_type` column.

The output filename will be determined by the dataset ID, limit, and a random
4-letter suffix.

## 2. Run the Script

Run the script from your terminal:

```bash
# Set your project ID
export GOOGLE_CLOUD_PROJECT="your-project"
export GCS_BUCKET_NAME="your-bucket"

# Run with default variables defined in the script file
python3 create_vertex_dataset.py

# Or, override the variables using command-line arguments
python3 create_vertex_dataset.py \
    --project_id "${PROJECT_ID}" \
    --dataset_id "imagery_insights___us" \
    --table_id "cropped_observations_latest" \
    --bucket_name ${BUCKET_NAME} \
    --limit 500 \
    --include_labels
```

The script will query BigQuery, locally generate a JSONL file ending with a
random 4-letter alphanumeric suffix to guarantee uniqueness (e.g.
`imagery_insights___us_500_abcd.jsonl`), and upload it to your destination GCS
bucket.

At the end of the script's output, it will print the **GCS URI** of the uploaded
file. **Copy this URI**, you will need it in the next step.

## 3. Import the file in Vertex AI

To visualize the resulting dataset within Vertex AI for analysis or training,
follow the standard Managed Dataset import flow. For detailed documentation, see
the official
[Agent Platform Docs](https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/training/using-managed-datasets).

1.  Navigate to the Google Cloud Console and open **Vertex AI > Datasets**.
2.  Click **+ CREATE** at the top.
3.  Name your dataset and select **Image** > **Image classification
    (Single-label)** or whichever data type is most appropriate for your
    application, and select your project's region.
4.  Click **Create** to proceed to the Data Import screen.
5.  Choose **Select import files from Cloud Storage**.
6.  Paste the **GCS URI** that was copied at the end of Step 2 (e.g.,
    `gs://{your_bucket}/${DATASET_ID}_${LIMIT}_abcd.jsonl`) into the *Import
    file path* box.
7.  Click **Continue**.

Vertex AI will parse the JSONL file and begin pulling the image URLs into the
dataset interface. Once the ingestion job finishes, you can explore the Street
View data visually within the UI.
