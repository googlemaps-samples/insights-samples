# Street View Insights Visualization App

This application provides an interactive visualization of geographic data from the `ga_sample.json` file. It allows users to explore the data in a split-screen view, with a map on one side and a Google Street View panorama on the other.

## Overview

The application is a Flask web server that serves a single-page web application. The frontend is built with HTML, CSS, and JavaScript, and it uses the Google Maps API to display the map and Street View imagery.

The application has the following features:
*   **Split-screen view**: A map on the left and a Street View panorama on the right.
*   **Data navigation**: "Previous" and "Next" buttons to navigate through the data points.
*   **Camera pose controls**: A "Use Camera Pose" toggle to switch between the observation's location and the camera's location. When enabled, individual toggles for "Heading", "Pitch", and "Roll" allow for fine-grained control over the camera's orientation.
*   **Photographer POV**: A "Load Photographer POV" toggle to load the location and marker using the `StreetViewPanorama.getPhotographerPov()` method.
*   **3D map viewer**: A separate 3D map viewer to display all the data points as pins on a 3D map.

## Prerequisites

Set your project ID:

```bash
PROJECT_ID=<your GCP project>
```

Authenticate with Google Cloud

```bash
gcloud auth login
```

Services required:

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com --project=$PROJECT_ID
```

## Optional Requirements.

Acquire a Google Maps API key using instructions [here](https://developers.google.com/maps/documentation/javascript/get-api-key).

### Requires Roles

To get the permissions that you need to complete this quickstart, ask your administrator to grant you the following IAM roles:

* Cloud Run Admin (`roles/run.admin`) on the project
* Cloud Run Source Developer (`roles/run.sourceDeveloper`) on the project
* Service Account User (`roles/iam.serviceAccountUser`) on the service identity
* Logs Viewer (`roles/logging.viewer`) on the project

## Deployment

To build and deploy this application, you can use the following `gcloud` command from your terminal, after navigating into the `streetview_visualization_app` directory:

```bash
MAPS_API_KEY=<your Google Maps API key>
APP_NAME=svi-visualization-app
REGION=us-central1
gcloud run deploy $APP_NAME \
  --source=. \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --set-env-vars="MAPS_API_KEY=${MAPS_API_KEY}" \
  --project=$PROJECT_ID
```

> If your GCP project or organization does not allow unauthenticated applications, replace the `--allow-unauthenticated` flag above with `--no-allow-unauthenticated` when you deploy.  You can then use [gcloud run services proxy](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy) to connect from your local machine to the Cloud Run application.

## Cleanup

```bash
gcloud run services delete $APP_NAME --region=$REGION
```
