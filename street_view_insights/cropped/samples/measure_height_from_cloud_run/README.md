# Utility Pole Height Estimation Service with Gemini 4 Hydrogen

This sample provides an authenticated Google Cloud Run web service for estimating utility pole heights from Street View Insights GCS URIs (`full_frame_observations_latest`) using **`gemini-4-hydrogen`** (`location="global"`).

## Prerequisites

*   Google Cloud SDK (`gcloud`) installed and authenticated.
*   A GCP project with Cloud Run, BigQuery, and Vertex AI APIs enabled.
*   A dedicated service account granted `roles/bigquery.jobUser`, `roles/bigquery.dataViewer` (on your subscribed Street View Insights dataset), `roles/storage.objectViewer` (on your Street View Insights imagery bucket), and `roles/aiplatform.user`.

## Configuration

Configure the service through environment variables at deployment time:

*   `PROJECT_ID`: Your GCP billing project ID.
*   `GEMINI_LOCATION`: Model endpoint location (`global` default; supports `global`, `us`, or `eu`).
*   `GEMINI_MODEL`: Defaults to `gemini-4-hydrogen`.
*   `BIGQUERY_DATASET`: Allowlisted Street View Insights dataset (`imagery_insights___us` or `imagery_insights___eu`).
*   `BIGQUERY_TABLE`: Allowlisted observations view (`full_frame_observations_latest` or `cropped_observations_latest`).
*   `ALLOWED_GCS_PREFIX`: Required `gs://<your-imagery-bucket>/` allowlist prefix enforced before calling Gemini.

## Deployment to Cloud Run

1.  **Navigate to the sample directory:**

    ```bash
    cd street_view_insights/cropped/samples/measure_height_from_cloud_run
    ```

2.  **Deploy with authentication enforced (`--no-allow-unauthenticated`):**

    ```bash
    export PROJECT_ID="YOUR_PROJECT_ID"
    export REGION="us-central1"
    export SERVICE_ACCOUNT_EMAIL="svi-height-sa@${PROJECT_ID}.iam.gserviceaccount.com"
    export ALLOWED_GCS_PREFIX="gs://YOUR_SVI_IMAGERY_BUCKET/"

    CLOUDSDK_CORE_INTERACTIVE_UX_STYLE=OFF gcloud run deploy analyze-images-cloud-run \
        --project="${PROJECT_ID}" \
        --region="${REGION}" \
        --source=. \
        --no-allow-unauthenticated \
        --service-account="${SERVICE_ACCOUNT_EMAIL}" \
        --set-env-vars="PROJECT_ID=${PROJECT_ID},GEMINI_LOCATION=global,GEMINI_MODEL=gemini-4-hydrogen,ALLOWED_GCS_PREFIX=${ALLOWED_GCS_PREFIX}" \
        --max-instances=2 \
        --quiet
    ```

## Usage

Send an authenticated `POST` request with a Google OIDC identity token:

```bash
SERVICE_URL=$(gcloud run services describe analyze-images-cloud-run \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format="value(status.url)" \
    --quiet)

curl -fsS -X POST "${SERVICE_URL}/" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token --audiences="${SERVICE_URL}")" \
    -H "Content-Type: application/json" \
    -d '{}'
```
