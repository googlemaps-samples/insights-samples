# Image Classification Service with Gemini 2.5 Flash

This project provides a web service for classifying images from GCS URIs using the Gemini 2.5 Flash model via Google Cloud's Vertex AI. It is designed to be deployed as a container on Google Cloud Run.

## Prerequisites

*   Google Cloud SDK installed and authenticated.
*   A GCP project with Vertex AI and BigQuery APIs enabled.
*   A BigQuery table with a `gcs_uri` column containing the URIs of the images to be classified.

## Configuration

Before deploying the service, make sure to update the following variables in `analyze_images.py`:

*   `PROJECT_ID`: Your GCP Project ID.
*   `REGION`: The GCP region where Vertex AI is enabled.
*   `BIGQUERY_SQL_QUERY`: The BigQuery query to retrieve the GCS URIs.

## Deployment to Cloud Run

To deploy the service to Cloud Run, follow these steps:

1.  **Navigate to the project directory:**

    ```bash
    cd analyze_images_from_cloud_run
    ```

2.  **Deploy to Cloud Run using gcloud:**

    ```bash
    gcloud run deploy analyze-images-cloud-run \
        --project=sarthaks-lab \
        --region=us-central1 \
        --source . \
        --allow-unauthenticated \
        --platform managed \
        --max-instances=1
    ```

    **Note:** The `--source .` command will build the container image from the `Dockerfile` in the current directory and deploy it to Cloud Run.

## Usage

Once the service is deployed, you can send a POST request to the service URL with a JSON payload to trigger the image classification.

**Example using `curl`:**

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"prompt": "What is in this image?"}' \
YOUR_CLOUD_RUN_SERVICE_URL
```

The service will then execute the BigQuery query, classify the images, and return the results as a JSON response.