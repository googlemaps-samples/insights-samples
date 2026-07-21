# Street View Visualization App

This application provides an interactive visualization of geographic data from the `ga_sample.json` file. It allows users to explore the data in a split-screen view, with a map on one side and a Google Street View panorama on the other.

## Overview

The application is a Flask web server that serves a single-page web application. The frontend is built with HTML, CSS, and JavaScript, and it uses the Google Maps API to display the map and Street View imagery.

The application has the following features:
*   **Split-screen view**: A map on the left and a Street View panorama on the right.
*   **Data navigation**: "Previous" and "Next" buttons to navigate through the data points.
*   **Camera pose controls**: A "Use Camera Pose" toggle to switch between the observation's location and the camera's location. When enabled, individual toggles for "Heading", "Pitch", and "Roll" allow for fine-grained control over the camera's orientation.
*   **Photographer POV**: A "Load Photographer POV" toggle to load the location and marker using the `StreetViewPanorama.getPhotographerPov()` method.
*   **3D map viewer**: A separate 3D map viewer to display all the data points as pins on a 3D map.

## Deployment

To build and deploy this application, you can use the following `gcloud` command from your terminal, after navigating into the `streetview_visualization_app` directory:

```bash
gcloud run deploy imagery-insights-visualization \
  --source=. \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --project=imagery-insights-sandbox