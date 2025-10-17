# System Architecture

## 1. High-Level Overview

This document provides a detailed explanation of the Imagery Insights Batch Processor. The system is an automated, scalable, and robust pipeline built on Google Cloud. Its primary purpose is to process a large volume of images from a BigQuery source table, analyze each image using the Vertex AI Gemini model, and store the structured analysis results back into a new BigQuery table. The entire process, from resource creation to cleanup, is designed to be idempotent, meaning it can be run multiple times without causing errors or side effects.

## 2. Key Cloud Services

This project orchestrates several key Google Cloud services to create a powerful, serverless pipeline:

*   **Cloud Run:** Provides the serverless compute platform for our application logic. We deploy two distinct services:
    *   The **`main` service** acts as the central controller and the final worker. It handles the initial setup of cloud resources and the final processing of each image.
    *   The **`populate` service** acts as a high-throughput task creator, responsible for reading the source data and filling the task queue.
    Because it's serverless, each service can scale up to many instances independently to handle high volumes of requests in parallel, and scale down to zero when idle to save costs.

*   **Cloud Tasks:** This is a managed service for asynchronous task execution. We use it to create a durable, distributed queue of image analysis tasks. This decouples the task creation step from the task processing step, making the system more resilient. If an image analysis fails, Cloud Tasks can automatically retry it.

*   **Pub/Sub:** A real-time, serverless messaging service. We use it as a fan-out mechanism to trigger the `populate` service. A single "shard" message is published for each chunk of the source data, and Pub/Sub delivers these messages to multiple instances of the `populate` service, enabling massive parallelism in the task creation phase.

*   **BigQuery:** A serverless data warehouse. It serves two roles:
    *   **Source:** It holds the initial table of image metadata, including GCS URIs.
    *   **Destination:** It stores the final, structured results from the Gemini model's analysis.

*   **Vertex AI (Gemini Pro Vision):** This is the machine learning platform that provides the powerful Gemini model for multimodal analysis. The `main` service sends image data to the Gemini API and receives a structured JSON object containing the analysis.

## 3. Architecture Diagrams & Workflow

The architecture is best understood as a three-stage process.

### Stage 1: Setup and Shard Creation

This stage is initiated by the user on their local machine. It sets up all the necessary cloud resources for a unique, idempotent run of the pipeline.

```
meta {
  title "Stage 1: Setup and Shard Creation"
}

elements {
  group user_machine {
    name "User's Local Machine"

    card populate_script {
      name "populate_with_cloud_run.py"
      description "Initiates the entire pipeline"
      icon_url "https://drive.google.com/file/d/1LEzsFSqvHtnrO0_ZlP8mGuleuEejB89T/view?usp=sharing&resourcekey=0-2rJHOwvACwb8pTHH-Cho4w"
    }
  }

  gcp {
    card run as cloud_run_main {
      name "main service"
      description "Creates resources via /setup endpoint"
    }
    card tasks as cloud_tasks {
      name "Cloud Tasks"
      description "A unique queue is created for this run"
    }
    card pubsub as pubsub {
      name "Pub/Sub"
      description "A unique topic and subscription are created"
    }
  }
}

paths {
  populate_script --> cloud_run_main # 1. Calls /setup
  cloud_run_main --> cloud_tasks # 2. Creates unique queue
  populate_script --> pubsub # 3. Creates unique topic & subscription
  populate_script --> pubsub # 4. Publishes shard messages
}
```

*   **What it does:** The user runs the `populate_with_cloud_run.py` script. This script first calls the `/setup` endpoint of the `main` service, which creates a Cloud Tasks queue with a unique name (e.g., `image-analysis-queue-<uuid>`). This unique name is crucial for idempotency, as Cloud Tasks does not allow recreating a queue with the same name for several days after it's deleted. The unique name is returned to the local script. The script then creates a unique Pub/Sub topic and subscription. Finally, it calculates how many "shards" (chunks of data) are needed to process the entire source table and publishes one message per shard to the new Pub/Sub topic.

### Stage 2: Parallel Task Population

This stage is triggered automatically by the messages published in Stage 1. Its purpose is to read the source data from BigQuery and create a task for each image.

```
meta {
  title "Stage 2: Parallel Task Population"
}

elements {
  gcp {
    card pubsub as pubsub {
      name "Pub/Sub"
      description "Pushes shard messages"
    }
    card run as cloud_run_populate {
      name "populate service"
      description "Receives shard messages and creates tasks"
    }
    card bq as bigquery {
      name "BigQuery"
      description "Source of image data"
    }
    card tasks as cloud_tasks {
      name "Cloud Tasks"
      description "Receives a task for each image"
    }
  }
}

paths {
  pubsub --> cloud_run_populate # 1. Triggers service
  cloud_run_populate --> bigquery # 2. Queries a shard of data
  cloud_run_populate --> cloud_tasks # 3. Creates tasks
}
```

*   **What it does:** Pub/Sub pushes the shard messages to the `populate` service, which scales up to handle them in parallel. Each instance of the `populate` service receives a message containing a shard definition (e.g., `limit: 50, offset: 1000`) and the unique queue ID. It queries that specific shard of data from the source BigQuery table. For each row (representing one or more images of an asset), it creates a new task in the unique Cloud Tasks queue.

### Stage 3: Asynchronous Image Processing

This is the final stage, where the actual image analysis happens. It is triggered automatically by the tasks created in Stage 2.

```
meta {
  title "Stage 3: Asynchronous Image Processing"
}

elements {
  gcp {
    card tasks as cloud_tasks {
      name "Cloud Tasks"
      description "Sends tasks for processing"
    }
    card run as cloud_run_main {
      name "main service"
      description "Receives and processes tasks"
    }
    card vertex as vertex_ai {
      name "Vertex AI (Gemini)"
      description "Performs the image analysis"
    }
    card bq as bigquery {
      name "BigQuery"
      description "Stores the final analysis results"
    }
  }
}

paths {
  cloud_tasks --> cloud_run_main # 1. Sends task to /process endpoint
  cloud_run_main --> vertex_ai # 2. Sends image URIs for analysis
  vertex_ai --> cloud_run_main # 3. Returns structured JSON
  cloud_run_main --> bigquery # 4. Stores results
}
```

*   **What it does:** Cloud Tasks sends the tasks to the `/process` endpoint of the `main` service, which scales up to handle them in parallel. Each instance of the `main` service receives a task containing the GCS URIs for the images of a single asset. It sends these URIs to the Vertex AI Gemini model for analysis. The model returns a structured JSON object with the results. The `main` service then writes this structured data to the final BigQuery results table.

## 4. Code-Level Components & Scripts

*   **`main.py`:** The core worker and controller service.
    *   `/setup`: Creates the BigQuery results table and a unique Cloud Tasks queue. Returns the unique queue ID.
    *   `/process`: Receives a task payload, sends the image URIs to the Gemini API, and writes the structured JSON response to the BigQuery results table.
    *   `/teardown`: Deletes the BigQuery results table and the Cloud Tasks queue specified by the `task_queue_id` parameter.
*   **`populate_with_cloud_run.py`:** The task creation service and local client.
    *   When run locally (`python3 src/populate_with_cloud_run.py`), it orchestrates the setup and initiation of the pipeline.
    *   When deployed to Cloud Run, it runs as a `gunicorn` server, receiving Pub/Sub messages and creating tasks.
*   **`deploy.sh`:** A shell script that automates the deployment of both Cloud Run services. It uses the `gcloud run deploy` command with the `--command` flag to specify the correct entrypoint for each service from the single `Dockerfile`. After deployment, it fetches the service URLs and writes them to a `.env` file.
*   **`teardown.sh`:** A shell script that automates the complete cleanup of all resources created during a run. It reads the unique IDs from the `.env` file, calls the `/teardown` endpoint on the `main` service, deletes the Pub/Sub topic and subscription, and finally deletes the `.env` file to ensure a clean state.

## 5. Implementation Details

### Idempotency and State Management

The system is designed to be fully idempotent, meaning it can be run multiple times without causing errors or creating duplicate resources. This is achieved through the use of a unique `run_id` (generated from a `uuid`) for each execution.

*   **Unique Resource Names:** The `run_id` is appended to the names of the Cloud Tasks queue, the Pub/Sub topic, and the Pub/Sub subscription. This ensures that each run has its own isolated set of resources and avoids conflicts with previous or concurrent runs.
*   **`.env` file:** The `run_id` and the unique queue ID are stored in a `.env` file on the user's local machine. This file acts as a temporary state file for the current run, allowing the `teardown.sh` script to know which specific resources to delete. The `.env` file is deleted at the end of the teardown process, ensuring a clean state for the next run.
