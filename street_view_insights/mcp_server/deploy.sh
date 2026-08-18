#!/bin/bash
set -e

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
PROJECT_ID="${PROJECT_ID:-YOUR_PROJECT_ID}"
REGION="us-central1"
SERVICE_NAME="streetview-imagery-insights-mcp"

echo "Building container and deploying to Cloud Run service: ${SERVICE_NAME} (project: ${PROJECT_ID})..."
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --port 8080

echo "Deployment complete!"
