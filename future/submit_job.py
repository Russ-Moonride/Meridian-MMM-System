#!/usr/bin/env python3
"""
scripts/submit_job.py
~~~~~~~~~~~~~~~~~~~~~
Submit a Vertex AI custom job to run scripts/run_model.py on Google Cloud.

Usage
-----
    python scripts/submit_job.py --client northspore [--mode dev|prod] [--no-bq]

Requirements
------------
    pip install google-cloud-aiplatform  (see scripts/requirements-dev.txt)
"""
import argparse

from google.cloud import aiplatform

PROJECT = "moonride-491921"
REGION = "us-central1"
IMAGE = "us-central1-docker.pkg.dev/moonride-491921/mmm-pipeline/mmm-runner:latest"
MACHINE_TYPE = "n1-standard-8"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Submit Vertex AI custom job for MMM.")
    p.add_argument("--client", required=True, help="Client ID matching a configs/{id}.yaml file.")
    p.add_argument("--mode", choices=["dev", "prod"], default="prod",
                   help="MCMC mode: dev (1 chain, 200 steps) or prod (4 chains, 500 steps).")
    p.add_argument("--no-bq", action="store_true", help="Pass --no-bq to run_model.py.")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    cmd = ["python", "scripts/run_model.py", "--client", args.client, "--mode", args.mode]
    if args.no_bq:
        cmd.append("--no-bq")

    aiplatform.init(project=PROJECT, location=REGION)

    job = aiplatform.CustomJob(
        display_name=f"mmm-{args.client}-{args.mode}",
        worker_pool_specs=[
            {
                "machine_spec": {"machine_type": MACHINE_TYPE},
                "replica_count": 1,
                "container_spec": {
                    "image_uri": IMAGE,
                    "command": cmd,
                    "env": [
                        {
                            "name": "GOOGLE_APPLICATION_CREDENTIALS",
                            "value": "/app/service_account.json",
                        }
                    ],
                },
            }
        ],
    )

    job.submit()

    print(f"\nJob submitted:  {job.display_name}")
    print(f"Job resource:   {job.name}")
    print(f"Monitor at:     https://console.cloud.google.com/vertex-ai/training/custom-jobs?project={PROJECT}")


if __name__ == "__main__":
    main()
