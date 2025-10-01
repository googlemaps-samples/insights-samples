#!/bin/bash
# This script deploys both Cloud Run services and creates a .env file
# with their URLs for the local client to use.

set -e

echo "Deploying 'analyze-volume-images' service..."
gcloud run deploy analyze-volume-images \
    --source . \
    --command="python3","src/main.py" \
    --region us-central1 \
    --allow-unauthenticated \
    --max-instances=100 \
    --memory=2Gi \
    --timeout=3600

SERVICE_URL=$(gcloud run services describe analyze-volume-images --region us-central1 --format='value(status.url)')
echo "SERVICE_URL=$SERVICE_URL" > .env

echo "Deploying 'populate-tasks' service..."
gcloud run deploy populate-tasks \
    --source . \
    --command="python3","src/populate_with_cloud_run.py","--mode","serve" \
    --region us-central1 \
    --no-allow-unauthenticated \
    --max-instances=100 \
    --memory=2Gi \
    --timeout=3600

POPULATE_SERVICE_URL=$(gcloud run services describe populate-tasks --region us-central1 --format='value(status.url)')
echo "POPULATE_SERVICE_URL=$POPULATE_SERVICE_URL" >> .env

echo "Deployment complete. Service URLs written to .env file."