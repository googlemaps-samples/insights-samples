# Image Analysis Batch Processor

This application provides a scalable, task-based architecture for analyzing a large volume of images using Google Cloud Run, Cloud Tasks, BigQuery, and Vertex AI's Gemini Pro Vision model.

## Architecture

For a detailed explanation of the system design, please see the [`ARCHITECTURE.md`](./ARCHITECTURE.md) file.

## End-to-End Guide

This guide provides a single, cohesive set of instructions to get the application running.

### Step 1: Prerequisites

1.  **Google Cloud SDK:** Ensure you have the `gcloud` command-line tool installed and initialized.
2.  **Authentication:** You must be authenticated with `gcloud`. Run `gcloud auth login` if you haven't already.
3.  **Project:** Your `gcloud` CLI must be configured with a default project. Run `gcloud config set project YOUR_PROJECT_ID` to set it.

### Step 2: Configure Deployment Settings

1.  Navigate to the `scripts` directory.
2.  **Manually create** a `deploy.env` file by copying the example template. This file provides the necessary configuration for the deployment script itself.
    ```bash
    cp scripts/deploy.env.example scripts/deploy.env
    ```
3.  Open `scripts/deploy.env` and replace the placeholder values with your specific GCP project information:
    *   `PROJECT_ID`: Your Google Cloud project ID.
    *   `REGION`: The GCP region where you want to deploy the services (e.g., `us-central1`).
    *   `SERVICE_ACCOUNT_EMAIL`: The email of the service account that the Cloud Run services will use.

### Step 3: Deploy the Services

Run the deployment script from the root of the project.

```bash
bash scripts/deploy.sh
```

The script will perform the following actions:
1.  **Enable APIs:** It will enable all the necessary GCP APIs.
2.  **Grant IAM Permissions:** It will grant the required IAM roles to your service account.
3.  **Deploy Services:** It will deploy both the `analyze-volume-images` and `populate-tasks` Cloud Run services.
4.  **Automatically create the root `.env` file:** The script will create a `.env` file in the project's root directory containing the live URLs of your deployed services.

### Step 4: Prepare the Local Environment

Set up a local Python virtual environment and install the required dependencies.

```bash
# Create a virtual environment
python3 -m venv .venv

# Activate the virtual environment
source .venv/bin/activate

# Install the dependencies
pip install -r requirements.txt
```

### Step 5: Start the Processing

Run the population script from the root of the project. This will kick off the entire automated workflow.

```bash
python3 src/populate_with_cloud_run.py
```

## Monitoring

You can monitor the progress of the image analysis by viewing the Cloud Tasks queue in the Google Cloud Console.

## Results

The results of the analysis will be stored in the BigQuery results table.

## Teardown

To delete the resources created by the application, run the `teardown.sh` script from the root of the project.

```bash
bash scripts/teardown.sh
```

## Testing

To test the `/process` endpoint locally, first install the dependencies as shown in Step 4, then run the test script:

```bash
python src/tests/test_process_endpoint.py