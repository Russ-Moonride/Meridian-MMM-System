"""
src/gcs_writer.py
~~~~~~~~~~~~~~~~~
Upload a completed MMM run's local artifacts to GCS.

Public API
----------
upload_run_to_gcs(out_dir, gcs_run_path)

Files uploaded (all in out_dir):
  model.pkl         — pickled fitted Meridian model
  geo_summary.csv   — geo-level ROI / contribution summary
  contributions.csv — weekly channel contributions
  diagnostics.json  — rhat, ESS, convergence
  status.json       — run metadata

Usage
-----
    gcs_run_path = "gs://mmm-pipeline-results/clients/northspore/runs/prod_2026-05-04/"
    upload_run_to_gcs("outputs/northspore", gcs_run_path)
"""
from __future__ import annotations

from pathlib import Path

from google.cloud import storage


_UPLOAD_FILES = [
    "model.pkl",
    "geo_summary.csv",
    "contributions.csv",
    "diagnostics.json",
    "status.json",
]


def _parse_gcs_path(gs_uri: str) -> tuple[str, str]:
    """Return (bucket_name, prefix) from a gs://bucket/prefix URI."""
    if not gs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {gs_uri!r}")
    without_scheme = gs_uri[len("gs://"):]
    bucket, _, prefix = without_scheme.partition("/")
    return bucket, prefix.rstrip("/")


def upload_run_to_gcs(out_dir: str | Path, gcs_run_path: str) -> None:
    """
    Upload run artifacts from out_dir to gcs_run_path.

    Parameters
    ----------
    out_dir      : local directory containing the run's output files
    gcs_run_path : destination GCS prefix, e.g.
                   "gs://mmm-pipeline-results/clients/northspore/runs/prod_2026-05-04"
    """
    out_dir = Path(out_dir)
    bucket_name, prefix = _parse_gcs_path(gcs_run_path)
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    for fname in _UPLOAD_FILES:
        local = out_dir / fname
        if not local.exists():
            print(f"  GCS upload skipped (not found): {fname}")
            continue
        blob_path = f"{prefix}/{fname}" if prefix else fname
        blob = bucket.blob(blob_path)
        blob.upload_from_filename(str(local))
        print(f"  ✓ gs://{bucket_name}/{blob_path}")
