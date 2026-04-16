#!/usr/bin/env bash
# scripts/build_and_push.sh
# Rebuild and push the container image after requirements.txt changes.
# Run from the repo root: bash scripts/build_and_push.sh
set -euo pipefail

IMAGE="us-central1-docker.pkg.dev/moonride-491921/mmm-pipeline/mmm-runner"

docker build -t "$IMAGE:latest" .
docker push "$IMAGE:latest"

echo "Pushed: $IMAGE:latest"
