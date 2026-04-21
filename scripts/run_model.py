#!/usr/bin/env python3
"""
scripts/run_model.py
~~~~~~~~~~~~~~~~~~~~
Standalone Meridian model runner.

Usage
-----
    python scripts/run_model.py --client northspore [--mode dev|prod] [--no-bq]

Steps
-----
  1. Load config from configs/{client_id}.yaml
  2. Prepare data via src/data_prep.py
  3. Build model via src/model_config.py
  4. Fit with MCMC (settings from config[mcmc][mode])
  5. Extract outputs to outputs/{client_id}/ via src/utils.py
  6. Write to BigQuery via src/bq_writer.py (skipped if --no-bq or no credentials)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Repo-relative imports ─────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from src.data_prep import load_config, prepare_data          # noqa: E402
from src.model_config import build_model                     # noqa: E402
from src.utils import extract_outputs                        # noqa: E402
from src.bq_writer import write_run                          # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Meridian MMM for a client.")
    p.add_argument(
        "--client", required=True,
        help="Client ID matching a configs/{id}.yaml file (case-insensitive).",
    )
    p.add_argument(
        "--mode", choices=["dev", "prod"], default="prod",
        help="MCMC mode: dev (1 chain, 200 steps) or prod (4 chains, 500 steps). Default: prod",
    )
    p.add_argument(
        "--no-bq", action="store_true",
        help="Skip BigQuery write even if GOOGLE_APPLICATION_CREDENTIALS is set.",
    )
    return p.parse_args()


def _resolve_config(client_arg: str) -> Path:
    configs_dir = REPO_ROOT / "configs"
    exact = configs_dir / f"{client_arg}.yaml"
    if exact.exists():
        return exact
    for path in configs_dir.glob("*.yaml"):
        if path.stem.lower() == client_arg.lower():
            return path
    print(f"ERROR: No config found for client '{client_arg}' in {configs_dir}/")
    sys.exit(1)


def main() -> None:
    args      = parse_args()
    mode      = args.mode
    t_start   = time.time()

    config_path = _resolve_config(args.client)
    config      = load_config(config_path)
    client_id   = config["client_id"]

    # ── MCMC settings from config ─────────────────────────────────────────────
    mcmc_cfg = config.get("mcmc", {}).get(mode, {})
    mcmc = {
        "n_chains": mcmc_cfg.get("n_chains", 4 if mode == "prod" else 1),
        "n_adapt":  mcmc_cfg.get("n_adapt",  500 if mode == "prod" else 200),
        "n_burnin": mcmc_cfg.get("n_burnin", 500 if mode == "prod" else 200),
        "n_keep":   mcmc_cfg.get("n_keep",   500 if mode == "prod" else 200),
    }

    run_id  = f"{mode}_{datetime.now().strftime('%Y-%m-%d_%H%M')}"
    out_dir = REPO_ROOT / config.get("output_path", f"outputs/{client_id}")

    print(f"{'='*60}")
    print(f"  MMM Run — {client_id}  [{mode}]")
    print(f"  run_id  : {run_id}")
    print(f"  config  : {config_path.relative_to(REPO_ROOT)}")
    print(f"  MCMC    : chains={mcmc['n_chains']}  adapt={mcmc['n_adapt']}  "
          f"burnin={mcmc['n_burnin']}  keep={mcmc['n_keep']}")
    print(f"  output  : {out_dir.relative_to(REPO_ROOT)}")
    print(f"{'='*60}\n")

    # ── 1. Data prep ──────────────────────────────────────────────────────────
    print("1/4  Preparing data …")
    t1 = time.time()
    df = prepare_data(config)
    n_geos  = df[config["geo_column"]].nunique()
    n_weeks = df[config["date_column"]].nunique()
    print(f"     {n_geos} geos × {n_weeks} weeks  ({time.time() - t1:.1f}s)\n")

    # ── 2. Build model ────────────────────────────────────────────────────────
    print("2/4  Building model …")
    t2 = time.time()
    mmm = build_model(df, config)
    print(f"     Model built  ({time.time() - t2:.1f}s)\n")

    # ── 3. Fit ────────────────────────────────────────────────────────────────
    print("3/4  Running MCMC …")
    t3 = time.time()
    mmm.sample_prior(500)
    mmm.sample_posterior(
        n_chains=mcmc["n_chains"],
        n_adapt=mcmc["n_adapt"],
        n_burnin=mcmc["n_burnin"],
        n_keep=mcmc["n_keep"],
    )
    print(f"     MCMC complete  ({(time.time() - t3) / 60:.1f} min)\n")

    # ── 4. Extract outputs ────────────────────────────────────────────────────
    print("4/4  Extracting outputs …")
    extract_outputs(mmm, df, config, run_id, mcmc, out_dir)
    print()

    # ── BigQuery ──────────────────────────────────────────────────────────────
    if args.no_bq:
        print("BigQuery write skipped (--no-bq).")
    elif not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        print("BigQuery write skipped (GOOGLE_APPLICATION_CREDENTIALS not set).")
    else:
        print("Writing to BigQuery …")
        try:
            write_run(client_id, run_id, out_dir)
        except Exception as exc:
            print(f"WARNING: BigQuery write failed: {exc}")
            print("  Outputs are still on disk — run is otherwise complete.")

    total_min = (time.time() - t_start) / 60
    print(f"\n{'='*60}")
    print(f"  Done in {total_min:.1f} min  |  run_id: {run_id}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
