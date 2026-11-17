#!/bin/bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-${PROJECT_ID:-}}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-streetview-imagery-insights-mcp}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-}"
ALLOWED_GCS_PREFIX="${ALLOWED_GCS_PREFIX:-}"
ALLOWED_CALLER_EMAILS="${ALLOWED_CALLER_EMAILS:-}"

if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "YOUR_PROJECT_ID" ]]; then
  echo "Error: Set PROJECT_ID or GOOGLE_CLOUD_PROJECT to your GCP project ID." >&2
  exit 1
fi

if [[ -z "${SERVICE_ACCOUNT_EMAIL}" ]]; then
  echo "Error: Set SERVICE_ACCOUNT_EMAIL to a least-privilege Cloud Run service account." >&2
  exit 1
fi

if [[ "${ALLOWED_GCS_PREFIX}" != gs://* || "${ALLOWED_GCS_PREFIX}" == "gs://your-allowed-imagery-bucket"* ]]; then
  echo "Error: Set ALLOWED_GCS_PREFIX to your Street View Insights gs:// bucket prefix." >&2
  exit 1
fi

IMAGE_TAG="${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/${SERVICE_NAME}:latest"

echo "Building container image using Cloud Build..."
CLOUDSDK_CORE_INTERACTIVE_UX_STYLE=OFF gcloud builds submit . \
  --tag="${IMAGE_TAG}" \
  --project="${PROJECT_ID}" \
  --quiet

echo "Deploying authenticated Cloud Run service: ${SERVICE_NAME}..."
CLOUDSDK_CORE_INTERACTIVE_UX_STYLE=OFF gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_TAG}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --no-allow-unauthenticated \
  --service-account="${SERVICE_ACCOUNT_EMAIL}" \
  --set-env-vars="PROJECT_ID=${PROJECT_ID},GEMINI_LOCATION=global,ALLOWED_GCS_PREFIX=${ALLOWED_GCS_PREFIX},ALLOWED_CALLER_EMAILS=${ALLOWED_CALLER_EMAILS}" \
  --port=8080 \
  --quiet

MCP_SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --format="value(status.url)" \
  --quiet)

CLOUDSDK_CORE_INTERACTIVE_UX_STYLE=OFF gcloud run services update "${SERVICE_NAME}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --update-env-vars="MCP_SERVICE_URL=${MCP_SERVICE_URL}" \
  --quiet

echo "Deployment complete (authenticated access enforced): ${MCP_SERVICE_URL}"
