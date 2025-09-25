# Roads Management Insights CLI

## Overview

This is a command-line interface (CLI) for interacting with services related to Google Maps Platform Roads Management Insights (RMI). It provides a set of shell scripts to wrap the REST APIs, allowing you to manage resources like BigQuery Sharing (formerly known as Analytics Hub) data exchanges and listings directly from your terminal.

`rmi.sh` serves as the primary entry point for common, high-level tasks.

## Prerequisites

Before using this CLI, you must have the following tools installed:

1.  **Google Cloud CLI**: The `gcloud` command-line tool.
    -   Installation instructions: [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)
2.  **jq**: A lightweight and flexible command-line JSON processor.
    -   Installation instructions: [https://jqlang.github.io/jq/download/](https://jqlang.github.io/jq/download/)
3.  **Bash**: A standard Unix shell.

## Setup & Authentication

This CLI uses Application Default Credentials (ADC) to authenticate with Google Cloud APIs. Before running any commands, you must authenticate with gcloud:

```sh
gcloud auth application-default login
```

## Usage

The main script for user interaction is `rmi.sh`. You can call functions within it directly from your terminal.

**Note on Project IDs**: In the examples below, `<RMI_PROJECT_ID>` refers to your Google Cloud project ID with access to Roads Management Insights. This may be referred to as `GCP_PROJECT_ID` in your environment.

### Example 1: Find the RMI Data Exchange

To find the specific Roads Management Insights data exchange available to your project in a given location, use the `rmi_exchange_get` function.

**Usage:**
```sh
./rmi.sh rmi_exchange_get <RMI_PROJECT_ID> <LOCATION>
```

**Example:**
```sh
./rmi.sh rmi_exchange_get my-rmi-project us
```

This will return the data exchange details as a JSON object.

### Example 2: List RMI Listings

To list the available datasets (listings) within the Roads Management Insights data exchange, use the `rmi_listing_list` function.

**Usage:**
```sh
./rmi.sh rmi_listing_list <RMI_PROJECT_ID> <LOCATION>
```

**Example:**
```sh
./rmi.sh rmi_listing_list my-rmi-project us
```

This will return a JSON object containing all available listings in the RMI data exchange for your project.

### Example 3: Subscribe to a BigQuery Listing

To subscribe to an RMI BigQuery listing and create a linked dataset in your project, use the `rmi_subscribe_bigquery` function.

**Usage:**
```sh
./rmi.sh rmi_subscribe_bigquery <RMI_PROJECT_ID> <LOCATION> <BQ_PROJECT_ID> <BQ_DATASET_ID> [BODY_FILE]
```

-   `<RMI_PROJECT_ID>`: Your GCP project ID that has access to RMI.
-   `<LOCATION>`: The location of the RMI data exchange (e.g., `us`).
-   `<BQ_PROJECT_ID>`: The project where the linked BigQuery dataset will be created.
-   `<BQ_DATASET_ID>`: The name for the new linked dataset.
-   `[BODY_FILE]` (Optional): The path to a JSON file containing the request body. If not provided, a default body will be generated.

**Example (Default Body):**
```sh
./rmi.sh rmi_subscribe_bigquery my-rmi-project us my-data-project rmi_linked_dataset
```
This will subscribe to the first available BigQuery listing and create a new dataset named `rmi_linked_dataset` in `my-data-project`.

**Example (Custom Body):**

First, create a JSON file (e.g., `subscribe_body.json`) with your custom request body:
```json
{
  "destinationDataset": {
    "datasetReference":{
      "projectId": "my-data-project",
      "datasetId": "my_custom_rmi_dataset"
    },
    "friendlyName":"My Custom RMI Dataset",
    "description":"A custom description.",
    "labels":{
        "env":"dev"
    },
    "location":"us"
  }
}
```

Then, call the function with the path to your file:
```sh
./rmi.sh rmi_subscribe_bigquery my-rmi-project us my-data-project my_custom_rmi_dataset subscribe_body.json
```

## Script Reference

*   `rmi.sh`: Main entry point with high-level functions for RMI use cases.
*   `services/auth.sh`: Contains shared functions for authentication and making API calls.
*   `services/analyticshub_v1.sh`: A complete client library for the BigQuery Analytics Hub API.
*   `services/road_selection.sh`: (Placeholder) Intended for the Road Selection API.
*   `services/roads_v2.sh`: (Placeholder) Intended for the Roads v2 API.
