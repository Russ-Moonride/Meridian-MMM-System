"""
src/bq_writer.py
~~~~~~~~~~~~~~~~
Write MMM run outputs to BigQuery.

Public API
----------
write_run(client_id, run_id, outputs_dir)

Tables written (project=meridian-system-493519, dataset=mmm):
  mmm.runs          — one row per run
  mmm.diagnostics   — one row per paid channel per run
  mmm.contributions — one row per channel per week per run

Tables are created automatically on first write if they don't exist.
Authentication uses GOOGLE_APPLICATION_CREDENTIALS env variable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from google.cloud import bigquery

PROJECT = "meridian-system-493519"
DATASET = "mmm"

# ── Table schemas ─────────────────────────────────────────────────────────────

_RUNS_SCHEMA = [
    bigquery.SchemaField("run_id",          "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("client_id",       "STRING"),
    bigquery.SchemaField("completed_at",    "TIMESTAMP"),
    bigquery.SchemaField("status",          "STRING"),
    bigquery.SchemaField("model_type",      "STRING"),
    bigquery.SchemaField("n_weeks",         "INTEGER"),
    bigquery.SchemaField("n_geos",          "INTEGER"),
    bigquery.SchemaField("n_channels",      "INTEGER"),
    bigquery.SchemaField("n_chains",        "INTEGER"),
    bigquery.SchemaField("n_adapt",         "INTEGER"),
    bigquery.SchemaField("n_burnin",        "INTEGER"),
    bigquery.SchemaField("n_keep",          "INTEGER"),
    bigquery.SchemaField("rhat_max",        "FLOAT"),
    bigquery.SchemaField("ess_min",         "INTEGER"),
    bigquery.SchemaField("converged",       "BOOLEAN"),
    bigquery.SchemaField("runtime_minutes", "FLOAT"),
]

_DIAGNOSTICS_SCHEMA = [
    bigquery.SchemaField("run_id",    "STRING", mode="REQUIRED"),
    bigquery.SchemaField("client_id", "STRING"),
    bigquery.SchemaField("channel",   "STRING"),
    bigquery.SchemaField("rhat",      "FLOAT"),
    bigquery.SchemaField("ess_bulk",  "INTEGER"),
]

_CONTRIBUTIONS_SCHEMA = [
    bigquery.SchemaField("run_id",           "STRING", mode="REQUIRED"),
    bigquery.SchemaField("client_id",        "STRING"),
    bigquery.SchemaField("date",             "DATE"),
    bigquery.SchemaField("channel",          "STRING"),
    bigquery.SchemaField("channel_type",     "STRING"),
    bigquery.SchemaField("contribution",     "FLOAT"),
    bigquery.SchemaField("contribution_pct", "FLOAT"),
    bigquery.SchemaField("roi",              "FLOAT"),
    bigquery.SchemaField("roi_lower_90",     "FLOAT"),
    bigquery.SchemaField("roi_upper_90",     "FLOAT"),
    bigquery.SchemaField("spend",            "FLOAT"),
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT)


def _ensure_tables(bq: bigquery.Client) -> None:
    """Create mmm tables with defined schemas if they don't already exist."""
    dataset_ref = bigquery.DatasetReference(PROJECT, DATASET)
    for name, schema in [
        ("runs",          _RUNS_SCHEMA),
        ("diagnostics",   _DIAGNOSTICS_SCHEMA),
        ("contributions", _CONTRIBUTIONS_SCHEMA),
    ]:
        table_ref = bigquery.Table(dataset_ref.table(name), schema=schema)
        try:
            bq.get_table(table_ref)
        except Exception:
            bq.create_table(table_ref)
            print(f"  Created table {DATASET}.{name}")


def _run_exists(bq: bigquery.Client, run_id: str) -> bool:
    query = f"""
        SELECT 1 FROM `{PROJECT}.{DATASET}.runs`
        WHERE run_id = @run_id
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    result = bq.query(query, job_config=job_config).result()
    return result.total_rows > 0


def _insert(bq: bigquery.Client, table_id: str, rows: list[dict]) -> None:
    errors = bq.insert_rows_json(f"{PROJECT}.{DATASET}.{table_id}", rows)
    if errors:
        raise RuntimeError(f"BigQuery insert failed for {table_id}: {errors}")


# ── Public API ────────────────────────────────────────────────────────────────

def write_run(client_id: str, run_id: str, outputs_dir: str | Path) -> None:
    """
    Read contributions.csv, diagnostics.json, and status.json from outputs_dir
    and write them to BigQuery. Skips if run_id already exists in mmm.runs.

    Parameters
    ----------
    client_id   : e.g. "northspore"
    run_id      : e.g. "prod_2026-04-16"
    outputs_dir : directory containing contributions.csv, diagnostics.json, status.json
    """
    outputs_dir = Path(outputs_dir)

    for fname in ["contributions.csv", "diagnostics.json", "status.json"]:
        p = outputs_dir / fname
        if not p.exists():
            raise FileNotFoundError(f"Required output file not found: {p}")

    contribs_df = pd.read_csv(outputs_dir / "contributions.csv")
    diagnostics  = json.loads((outputs_dir / "diagnostics.json").read_text())
    status       = json.loads((outputs_dir / "status.json").read_text())

    bq = _bq_client()
    _ensure_tables(bq)

    if _run_exists(bq, run_id):
        print(f"run_id '{run_id}' already exists in {DATASET}.runs — skipping BigQuery write.")
        return

    # ── mmm.runs ──────────────────────────────────────────────────────────────
    runs_row: dict[str, Any] = {
        "run_id":           run_id,
        "client_id":        client_id,
        "completed_at":     diagnostics.get("completed_at"),
        "status":           status.get("status", "complete"),
        "model_type":       diagnostics.get("model_type", "dev"),
        "n_weeks":          status.get("n_weeks"),
        "n_geos":           status.get("n_geos"),
        "n_channels":       status.get("n_channels"),
        "n_chains":         diagnostics.get("n_chains"),
        "n_adapt":          diagnostics.get("n_adapt"),
        "n_burnin":         diagnostics.get("n_burnin"),
        "n_keep":           diagnostics.get("n_keep"),
        "rhat_max":         diagnostics.get("rhat_max"),
        "ess_min":          diagnostics.get("ess_min"),
        "converged":        diagnostics.get("converged"),
        "runtime_minutes":  diagnostics.get("runtime_minutes"),
    }
    _insert(bq, "runs", [runs_row])
    print(f"  ✓ {DATASET}.runs          1 row")

    # ── mmm.diagnostics ───────────────────────────────────────────────────────
    rhat_by_ch = diagnostics.get("rhat_by_channel", {})
    ess_by_ch  = diagnostics.get("ess_by_channel", {})
    diag_rows = [
        {
            "run_id":    run_id,
            "client_id": client_id,
            "channel":   ch,
            "rhat":      rhat_by_ch.get(ch),
            "ess_bulk":  ess_by_ch.get(ch),
        }
        for ch in rhat_by_ch
    ]
    if diag_rows:
        _insert(bq, "diagnostics", diag_rows)
        print(f"  ✓ {DATASET}.diagnostics   {len(diag_rows)} rows")

    # ── mmm.contributions ─────────────────────────────────────────────────────
    contribs_df["run_id"]    = run_id
    contribs_df["client_id"] = client_id
    # Replace NaN with None so BigQuery accepts nullable FLOAT fields
    contribs_rows = contribs_df.where(pd.notnull(contribs_df), None).to_dict(orient="records")
    _insert(bq, "contributions", contribs_rows)
    print(f"  ✓ {DATASET}.contributions  {len(contribs_rows)} rows")
