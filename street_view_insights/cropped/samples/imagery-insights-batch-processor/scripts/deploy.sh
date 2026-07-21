#!/bin/bash
# This script automates the deployment of the Image Analysis Batch Processor.
# It enables the necessary APIs, grants IAM permissions, and deploys both
# Cloud Run services.

set -e

# Change to the parent directory of the script
cd "$(dirname "$0")/.."

# --- Configuration ---
# Load environment variables from deploy.env file
if [ -f "scripts/deploy.env" ]; then
    source "scripts/deploy.env"
else
    echo "Error: deploy.env file not found. Please create one from deploy.env.example."
    exit 1
fi

# --- Pre-flight Checks ---
# Check if the user is authenticated with gcloud
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo "You are not authenticated with gcloud. Please run 'gcloud auth login'."
    exit 1
fi

# Check if the project is set
if ! gcloud config get-value project | grep -q .; then
    echo "The gcloud project is not set. Please run 'gcloud config set project YOUR_PROJECT_ID'."
    exit 1
fi

# --- API Enablement ---
echo "Enabling necessary APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudtasks.googleapis.com \
    aiplatform.googleapis.com \
    bigquery.googleapis.com \
    pubsub.googleapis.com

# --- IAM Permissions ---
echo "Granting IAM permissions..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/cloudtasks.enqueuer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/cloudtasks.queueAdmin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/run.invoker"

gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/pubsub.publisher"

# --- Deployment ---
echo "Deploying 'analyze-volume-images' service..."
gcloud run deploy analyze-volume-images \
    --source . \
    --command="gunicorn","--workers=1","--threads=80","--timeout=0","main:app" \
    --region $REGION \
    --allow-unauthenticated \
    --max-instances=100 \
    --memory=2Gi \
    --timeout=3600 \
    --service-account=$SERVICE_ACCOUNT_EMAIL

SERVICE_URL=$(gcloud run services describe analyze-volume-images --region $REGION --format='value(status.url)')
echo "SERVICE_URL=$SERVICE_URL" > .env

echo "Deploying 'populate-tasks' service..."
gcloud run deploy populate-tasks \
    --source . \
    --command="gunicorn","--workers=1","--threads=80","--timeout=0","populate_with_cloud_run:gunicorn_app" \
    --region $REGION \
    --no-allow-unauthenticated \
    --set-env-vars="SERVICE_URL=$SERVICE_URL" \
    --max-instances=100 \
    --memory=2Gi \
    --timeout=3600 \
    --service-account=$SERVICE_ACCOUNT_EMAIL

POPULATE_SERVICE_URL=$(gcloud run services describe populate-tasks --region $REGION --format='value(status.url)')
echo "POPULATE_SERVICE_URL=$POPULATE_SERVICE_URL" >> .env
echo "REGION=$REGION" >> .env

echo "Deployment complete. Service URLs and region written to .env file."