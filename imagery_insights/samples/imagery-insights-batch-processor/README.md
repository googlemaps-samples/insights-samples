# Image Analysis Batch Processor

This application provides a scalable, task-based architecture for analyzing a large volume of images using Google Cloud Run, Cloud Tasks, BigQuery, and Vertex AI's Gemini Pro Vision model.

## Overview

For a detailed explanation of the system design, please see the [`ARCHITECTURE.md`](./ARCHITECTURE.md) file.

## Setup

1.  **Enable APIs:**

    *   Cloud Run API
    *   Cloud Tasks API
    *   Vertex AI API
    *   BigQuery API
    *   Cloud Pub/Sub API

2.  **Grant IAM Permissions:**

    *   Run the following commands to grant the necessary roles to your service account:

        ```bash
        gcloud projects add-iam-policy-binding sarthaks-lab \
            --member="serviceAccount:635092392839-compute@developer.gserviceaccount.com" \
            --role="roles/cloudtasks.enqueuer"

        gcloud projects add-iam-policy-binding sarthaks-lab \
            --member="serviceAccount:635092392839-compute@developer.gserviceaccount.com" \
            --role="roles/bigquery.dataEditor"

        gcloud projects add-iam-policy-binding sarthaks-lab \
            --member="serviceAccount:635092392839-compute@developer.gserviceaccount.com" \
            --role="roles/aiplatform.user"

        gcloud projects add-iam-policy-binding sarthaks-lab \
            --member="serviceAccount:635092392839-compute@developer.gserviceaccount.com" \
            --role="roles/cloudtasks.queueAdmin"

        gcloud projects add-iam-policy-binding sarthaks-lab \
            --member="serviceAccount:635092392839-compute@developer.gserviceaccount.com" \
            --role="roles/run.invoker"
        
        gcloud projects add-iam-policy-binding sarthaks-lab \
            --member="serviceAccount:635092392839-compute@developer.gserviceaccount.com" \
            --role="roles/pubsub.publisher"
        ```

3.  **Configure the application:**

    *   Open the `config.py` file and update the following variables:
        *   `GCP_PROJECT`: Your Google Cloud Project ID.
        *   `LOCATION`: The GCP region for Cloud Tasks and Vertex AI (e.g., `us-central1`).
        *   `BIGQUERY_RESULTS_DATASET`: The BigQuery dataset for the results table.
        *   `BIGQUERY_RESULTS_TABLE`: The name of the results table.
        *   `BIGQUERY_SOURCE_DATASET`: The BigQuery dataset for the source table.
        *   `BIGQUERY_SOURCE_TABLE`: The name of the source table.
        *   `TASK_QUEUE_PREFIX`: The prefix for the Cloud Tasks queue name (e.g., `image-analysis-queue-`).
        *   `SERVICE_ACCOUNT_EMAIL`: The email of the service account used by the Cloud Run services.

4.  **Build, Deploy, and Configure:**

    The `deploy.sh` script automates the entire deployment and configuration process. It will deploy both services, fetch their URLs, and create a `.env` file for the local client to use.

    ```bash
    bash deploy.sh
    ```

## Workflow Summary

This application is designed to be fully automated after the initial setup. Here is the end-to-end workflow:

1.  **Deployment:** You deploy the two Cloud Run services (`main` and `populate`) from your local machine.
2.  **Configuration:** You update the `config.py` file with the URLs of your deployed services and your service account email.
3.  **Initiation:** You run the `populate_with_cloud_run.py --mode shard` command from your local machine.
4.  **Automated Execution:**
    *   The script calls the `/setup` endpoint, which creates the necessary BigQuery table and Cloud Tasks queue.
    *   The script creates a Pub/Sub topic and a push subscription that points to your `populate` service.
    *   The script publishes messages to the Pub/Sub topic, each representing a "shard" (a range of rows) of your source BigQuery table.
    *   Pub/Sub automatically pushes these messages to your `populate` service.
    *   The `populate` service scales up and, for each message it receives, it queries its assigned shard from BigQuery and creates a task in Cloud Tasks for each row.
    *   Cloud Tasks automatically sends these tasks to your `main` service's `/process` endpoint.
    *   The `main` service scales up, processes the images with Gemini, and stores the results in the final BigQuery table.

Once you run the `shard` command, the rest of the pipeline is triggered and managed automatically by Google Cloud.

## Usage

1.  **Prepare the Local Environment:**

    *   Before running the population script, you need to set up a local Python environment and install the required dependencies.

        ```bash
        # Create a virtual environment
        python3 -m venv .venv

        # Activate the virtual environment
        source .venv/bin/activate

        # Install the dependencies
        pip install -r requirements.txt
        ```
    **Note:** If you have run this before, you should re-run `pip install -r requirements.txt` to ensure you have the latest dependencies.

2.  **Start the Process:**

    *   After deploying both services and preparing your local environment, run the following command.
    
        **Note:** This script is idempotent. It will first tear down any existing resources (BigQuery table, Cloud Tasks queue, Pub/Sub topic, and subscription) from a previous run before creating new ones to ensure a clean start.

    *   This executes the `populate_with_cloud_run.py` script in `shard` mode, which will:
        1.  Call the `/setup` endpoint on the `main` service to create the necessary BigQuery and Cloud Tasks resources.
        2.  Create the Pub/Sub topic.
        3.  Create a push subscription that triggers the `populate-tasks` service.
        4.  Publish all the sharding messages to the topic, kicking off the entire process.

        ```bash
        python3 src/populate_with_cloud_run.py --mode shard
        ```

## Monitor the Queue

*   You can monitor the progress of the image analysis by viewing the Cloud Tasks queue in the Google Cloud Console.

## View the results

*   The results of the analysis will be stored in the BigQuery results table.

## Teardown

*   To delete the BigQuery table and the Cloud Tasks queue, run the `teardown.sh` script.

    ```bash
    bash teardown.sh
    ```

## Testing

To test the `/process` endpoint, you first need to install the required libraries locally:

```bash
pip install -r requirements.txt
```

Then, you can run the `test_process_endpoint.py` script:

```bash
python src/tests/test_process_endpoint.py