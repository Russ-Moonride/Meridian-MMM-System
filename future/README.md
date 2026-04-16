# future/ — Vertex AI Migration Files

These files set up production model runs on **Vertex AI Custom Jobs** instead of Google Colab.
They are preserved here for when the team migrates off Colab.

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Container image: `python:3.11-slim` + system deps + pip install + repo copy |
| `setup_gcp.sh` | One-time GCP setup: enable APIs, create Artifact Registry repo, grant IAM roles, build + push initial image |
| `build_and_push.sh` | Rebuild and push the container — run whenever `requirements.txt` changes |
| `submit_job.py` | Submit a Vertex AI Custom Job; wraps `scripts/run_model.py` with `--client` / `--mode` / `--no-bq` args |

## When ready to migrate

1. Move these files back to their original locations:
   - `Dockerfile` → repo root
   - `setup_gcp.sh` → `scripts/setup_gcp.sh`
   - `build_and_push.sh` → `scripts/build_and_push.sh`
   - `submit_job.py` → `scripts/submit_job.py`

2. Install dev tooling (kept out of the container image):
   ```bash
   pip install -r scripts/requirements-dev.txt
   ```

3. Run one-time GCP setup (if not already done):
   ```bash
   bash scripts/setup_gcp.sh
   ```

4. Submit jobs:
   ```bash
   python scripts/submit_job.py --client northspore --mode prod
   ```

## Key details
- Machine type: `n1-standard-8` (8 CPU, 30 GB RAM)
- Container image: `us-central1-docker.pkg.dev/moonride-491921/mmm-pipeline/mmm-runner:latest`
- Project: `moonride-491921`, Region: `us-central1`
- `GOOGLE_APPLICATION_CREDENTIALS` is set to `/app/service_account.json` inside the container
