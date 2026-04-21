"""
app/data.py
~~~~~~~~~~~
Data layer for the Dash app.

Primary source: BigQuery (mmm_results.contributions, mmm_results.diagnostics, mmm_results.runs).
Fallback:       Local files in outputs/{client_id}/ when BQ credentials are absent.

All local paths resolve relative to the repository root regardless of working directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

_BQ_PROJECT = "moonride-491921"
_BQ_DATASET = "mmm_results"

REPO_ROOT = Path(__file__).parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"

# Channel color palette — shared across all pages
CHANNEL_COLORS: dict[str, str] = {
    "Baseline":   "#ADB5BD",
    "Brand":      "#4C72B0",
    "Non_Brand":  "#55A868",
    "DVD":        "#C44E52",
    "Retargeting": "#8172B2",
    "Prospecting": "#CCB974",
    "Shopping":   "#64B5CD",
    "Amazon":     "#FF7F0E",
    "Facebook":   "#3B5998",
    "Instagram":  "#E1306C",
    "YouTube":    "#CC0000",
}


# ── Internal ──────────────────────────────────────────────────────────────────

def _all_configs() -> dict[str, tuple[dict, Path]]:
    """Scan configs/ and return {client_id: (config_dict, yaml_path)}."""
    result: dict[str, tuple[dict, Path]] = {}
    for path in sorted(CONFIGS_DIR.glob("*.yaml")):
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f)
            if cfg and "client_id" in cfg:
                result[cfg["client_id"]] = (cfg, path)
        except Exception:
            pass
    return result


def _output_dir(client_id: str) -> Path:
    """Resolve the output directory for a client from its config."""
    configs = _all_configs()
    if client_id in configs:
        cfg, _ = configs[client_id]
        return REPO_ROOT / cfg.get("output_path", f"outputs/{client_id}")
    return REPO_ROOT / "outputs" / client_id


# ── Public API ────────────────────────────────────────────────────────────────

def list_clients() -> list[dict[str, Any]]:
    """Return all configured clients with their status info."""
    clients = []
    for client_id, (cfg, _) in _all_configs().items():
        clients.append({
            "client_id": client_id,
            "config": cfg,
            "status": get_status(client_id),
        })
    return clients


def get_status(client_id: str) -> dict[str, Any]:
    """Load run status — BigQuery first, local file fallback."""
    if _has_bq_credentials():
        result = get_status_bq(client_id)
        if result is not None:
            return result
    path = _output_dir(client_id) / "status.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"status": "no_run", "client_id": client_id}


def load_contributions_bq(client_id: str) -> pd.DataFrame | None:
    """Query mmm.contributions for the most recent complete run for this client.

    Prefers runs with status='complete' in the runs table; falls back to the
    latest run_id found directly in contributions if the runs table has no
    matching complete row (handles mismatched run_ids or non-'complete' status).
    """
    try:
        from google.cloud import bigquery
        bq = bigquery.Client(project=_BQ_PROJECT)
        query = f"""
            WITH latest_complete AS (
              SELECT run_id FROM `{_BQ_PROJECT}.{_BQ_DATASET}.runs`
              WHERE client_id = @client_id AND status = 'complete'
              ORDER BY completed_at DESC
              LIMIT 1
            ),
            latest_any AS (
              SELECT run_id FROM `{_BQ_PROJECT}.{_BQ_DATASET}.contributions`
              WHERE client_id = @client_id
              ORDER BY run_id DESC
              LIMIT 1
            )
            SELECT c.*
            FROM `{_BQ_PROJECT}.{_BQ_DATASET}.contributions` c
            WHERE c.client_id = @client_id
              AND c.run_id = COALESCE(
                (SELECT run_id FROM latest_complete),
                (SELECT run_id FROM latest_any)
              )
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("client_id", "STRING", client_id)]
        )
        rows = list(bq.query(query, job_config=job_config).result())
        if not rows:
            return None
        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return None


def load_diagnostics_bq(client_id: str) -> dict | None:
    """Query mmm.runs + mmm.diagnostics for the most recent complete run."""
    try:
        from google.cloud import bigquery
        bq = bigquery.Client(project=_BQ_PROJECT)

        runs_query = f"""
            SELECT run_id, completed_at, model_type, rhat_max, ess_min, converged,
                   runtime_minutes, n_chains, n_adapt, n_burnin, n_keep,
                   n_weeks, n_geos, n_channels
            FROM `{_BQ_PROJECT}.{_BQ_DATASET}.runs`
            WHERE client_id = @client_id AND status = 'complete'
            ORDER BY completed_at DESC
            LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("client_id", "STRING", client_id)]
        )
        runs_rows = list(bq.query(runs_query, job_config=job_config).result())
        if not runs_rows:
            return None
        run = dict(runs_rows[0])
        run_id = run["run_id"]

        diag_query = f"""
            SELECT channel, rhat, ess_bulk
            FROM `{_BQ_PROJECT}.{_BQ_DATASET}.diagnostics`
            WHERE run_id = @run_id
        """
        diag_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
        )
        diag_rows = list(bq.query(diag_query, job_config=diag_config).result())

        return {
            "run_id":           run_id,
            "client_id":        client_id,
            "completed_at":     str(run.get("completed_at", "")),
            "model_type":       run.get("model_type"),
            "rhat_max":         run.get("rhat_max"),
            "rhat_by_channel":  {r["channel"]: r["rhat"] for r in diag_rows},
            "ess_min":          run.get("ess_min"),
            "ess_by_channel":   {r["channel"]: r["ess_bulk"] for r in diag_rows},
            "converged":        run.get("converged"),
            "runtime_minutes":  run.get("runtime_minutes"),
            "n_chains":         run.get("n_chains"),
            "n_adapt":          run.get("n_adapt"),
            "n_burnin":         run.get("n_burnin"),
            "n_keep":           run.get("n_keep"),
        }
    except Exception:
        return None


def _has_bq_credentials() -> bool:
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    # Auto-detect service_account.json at repo root (gitignored, for local dev)
    local_sa = REPO_ROOT / "service_account.json"
    if local_sa.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(local_sa)
        return True
    return False


def get_status_bq(client_id: str) -> dict[str, Any] | None:
    """Query mmm_results.runs for the most recent complete run for this client."""
    try:
        from google.cloud import bigquery
        bq = bigquery.Client(project=_BQ_PROJECT)
        query = f"""
            SELECT run_id, status, completed_at, model_type,
                   n_weeks, n_geos, n_channels
            FROM `{_BQ_PROJECT}.{_BQ_DATASET}.runs`
            WHERE client_id = @client_id
            ORDER BY completed_at DESC
            LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("client_id", "STRING", client_id)]
        )
        rows = list(bq.query(query, job_config=job_config).result())
        if not rows:
            return None
        row = dict(rows[0])
        return {
            "status":       row.get("status", "complete"),
            "run_id":       row.get("run_id"),
            "client_id":    client_id,
            "completed_at": str(row.get("completed_at", "")),
            "model_type":   row.get("model_type"),
            "n_weeks":      row.get("n_weeks"),
            "n_geos":       row.get("n_geos"),
            "n_channels":   row.get("n_channels"),
        }
    except Exception:
        return None


def get_contributions(client_id: str) -> pd.DataFrame | None:
    """Load contributions — BigQuery first, local file fallback."""
    if _has_bq_credentials():
        result = load_contributions_bq(client_id)
        if result is not None:
            return result
    path = _output_dir(client_id) / "contributions.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, parse_dates=["date"])


def get_diagnostics(client_id: str) -> dict | None:
    """Load diagnostics — BigQuery first, local file fallback."""
    if _has_bq_credentials():
        result = load_diagnostics_bq(client_id)
        if result is not None:
            return result
    path = _output_dir(client_id) / "diagnostics.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def get_config(client_id: str) -> dict[str, Any]:
    """Return the parsed config dict for a client."""
    configs = _all_configs()
    if client_id not in configs:
        raise KeyError(f"No config found for client_id: {client_id!r}")
    return configs[client_id][0]


def get_config_raw(client_id: str) -> str:
    """Return the raw YAML string for display / editing."""
    configs = _all_configs()
    if client_id not in configs:
        raise KeyError(f"No config found for client_id: {client_id!r}")
    _, path = configs[client_id]
    return path.read_text()


def save_config(client_id: str, yaml_str: str) -> None:
    """Validate YAML syntax and write back to the config file on disk."""
    yaml.safe_load(yaml_str)          # raises yaml.YAMLError on bad syntax
    configs = _all_configs()
    if client_id not in configs:
        raise KeyError(f"No config found for client_id: {client_id!r}")
    _, path = configs[client_id]
    path.write_text(yaml_str)
