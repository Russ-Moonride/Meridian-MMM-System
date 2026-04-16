#!/usr/bin/env bash
# scripts/setup_gcp.sh
# One-time setup: enable APIs, create Artifact Registry repo, grant IAM roles,
# build and push the initial Docker image.
# Run from the repo root: bash scripts/setup_gcp.sh
set -euo pipefail

PROJECT="moonride-491921"
REGION="us-central1"
REPO="mmm-pipeline"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/mmm-runner"

# Resolve service account email from the local service_account.json
SA_EMAIL=$(python3 -c "import json; print(json.load(open('service_account.json'))['client_email'])")
echo "Service account: $SA_EMAIL"
echo ""

# ── Enable APIs ───────────────────────────────────────────────────────────────
echo "Enabling GCP APIs..."
gcloud services enable \
    aiplatform.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    --project "$PROJECT"
echo "  APIs enabled."
echo ""

# ── Artifact Registry repository ─────────────────────────────────────────────
echo "Creating Artifact Registry repository '$REPO'..."
gcloud artifacts repositories create "$REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT" \
    --description="MMM pipeline Docker images" \
    2>/dev/null || echo "  Repository already exists — skipping."
echo ""

# ── IAM roles ─────────────────────────────────────────────────────────────────
echo "Granting IAM roles to $SA_EMAIL..."
for ROLE in \
    roles/aiplatform.user \
    roles/storage.objectViewer \
    roles/bigquery.dataEditor \
    roles/bigquery.jobUser
do
    gcloud projects add-iam-policy-binding "$PROJECT" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="$ROLE" \
        --quiet
    echo "  Granted $ROLE"
done
echo ""

# ── Docker auth + build + push ────────────────────────────────────────────────
echo "Configuring Docker for Artifact Registry..."
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

echo "Building Docker image..."
docker build -t "$IMAGE:latest" .

echo "Pushing to Artifact Registry..."
docker push "$IMAGE:latest"

echo ""
echo "Done. Image available at: $IMAGE:latest"
