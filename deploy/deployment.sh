#!/usr/bin/env bash

# Exit immediately on error, treat unset variables as errors, and fail on pipe errors
set -euo pipefail

# ==============================================================================
# CONFIGURATION & VARIABLES
# (Override these by setting environment variables before running the script)
# ==============================================================================

# Google Cloud Base Config
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-europe-west1}"

# Repository & Job Details
REPO="${REPO:-automated-booking-system}"
JOB="${JOB:-automated-booking-job}"
UPDATE_DESC="${UPDATE_DESC:-Automated booking system repository}"

# Service Account & Compute Resources
SA_EMAIL="${SA_EMAIL:-your-service-account@${PROJECT_ID}.iam.gserviceaccount.com}"
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-2}"
MAX_RETRIES="${MAX_RETRIES:-1}"
TASK_TIMEOUT="${TASK_TIMEOUT:-900s}"

# Image Construction
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${JOB}:${IMAGE_TAG}"

# ==============================================================================
# VALIDATION & PRE-FLIGHT
# ==============================================================================

if [[ -z "${PROJECT_ID}" ]]; then
  echo "[ERROR] PROJECT_ID is not set and could not be detected from gcloud config." >&2
  exit 1
fi

echo "=================================================="
echo " Starting Cloud Run Job Build & Deployment"
echo " Project ID:      ${PROJECT_ID}"
echo " Region:          ${REGION}"
echo " Repository:      ${REPO}"
echo " Job Name:        ${JOB}"
echo " Service Account: ${SA_EMAIL}"
echo " Image Target:    ${IMAGE}"
echo "=================================================="

# ==============================================================================
# EXECUTION STEPS
# ==============================================================================

echo -e "\n--> [1/3] Updating Artifact Registry description..."
gcloud artifacts repositories update "${REPO}" \
  --project="${PROJECT_ID}" \
  --location="${REGION}" \
  --description="${UPDATE_DESC}"

echo -e "\n--> [2/3] Building and pushing container image via Cloud Build..."
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --tag="${IMAGE}" .

echo -e "\n--> [3/3] Deploying Cloud Run Job..."
gcloud run jobs deploy "${JOB}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --service-account="${SA_EMAIL}" \
  --memory="${MEMORY}" \
  --cpu="${CPU}" \
  --max-retries="${MAX_RETRIES}" \
  --task-timeout="${TASK_TIMEOUT}"

echo -e "\n=================================================="
echo " Success! Cloud Run Job '${JOB}' successfully deployed."
echo "=================================================="