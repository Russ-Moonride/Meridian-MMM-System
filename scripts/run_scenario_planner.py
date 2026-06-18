#!/usr/bin/env python3
"""
scripts/run_scenario_planner.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Budget optimization & scenario planning for a trained Meridian model.

Loads model.pkl from an existing run in GCS, generates optimization dataframes,
and uploads CSVs to GCS under clients/{client_id}/optimizations/{opt_id}/.

Usage
-----
    python scripts/run_scenario_planner.py \
        --client northspore \
        --run-id prod_2026-05-04_1430 \
        [--filter-start 2024-01-01] \
        [--monthly] [--no-monthly] \
        [--quarterly] [--yearly] \
        [--min-spend-shift 0.5] [--max-spend-shift 2.0] \
        [--optimization-name default]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.data_prep import load_config  # noqa: E402

from meridian.model import model  # noqa: E402
from meridian.schema.processors import (  # noqa: E402
    budget_optimization_processor,
    marketing_processor,
    model_fit_processor,
)
from meridian.schema.utils import date_range_bucketing  # noqa: E402
from scenarioplanner.converters.dataframe import dataframe_model_converter  # noqa: E402
from scenarioplanner import mmm_ui_proto_generator as mmm_ui_gen  # noqa: E402

from google.cloud import storage  # noqa: E402
import pandas as pd  # noqa: E402


def _patch_batch_size() -> None:
    """
    Workaround for a packaging bug in google-meridian where
    budget_optimization_processor.py references a `batch_size` field that
    is absent from the shipped protobuf-generated class.
    Dynamically strips any `batch_size` line from to_proto() so the proto
    constructor call succeeds.
    """
    import inspect, textwrap
    import meridian.schema.processors.budget_optimization_processor as _bop

    # Find budget_pb from the processor module's own namespace — avoids
    # hardcoding the import path which differs between meridian versions.
    _bpb = vars(_bop).get('budget_pb')
    if _bpb is None:
        print("  [patch] budget_pb not found in processor module — skipping")
        return

    proto_fields = {f.name for f in _bpb.BudgetOptimizationSpec.DESCRIPTOR.fields}
    if 'batch_size' in proto_fields:
        return  # no patch needed — versions are in sync

    src = inspect.getsource(_bop.BudgetOptimizationSpec.to_proto)
    filtered = '\n'.join(l for l in src.splitlines() if 'batch_size' not in l)
    patched_src = textwrap.dedent(filtered)
    local_ns: dict = {}
    exec(compile(patched_src, '<patched_to_proto>', 'exec'), vars(_bop), local_ns)  # noqa: S102
    _bop.BudgetOptimizationSpec.to_proto = local_ns['to_proto']
    print("  [patch] batch_size removed from BudgetOptimizationSpec.to_proto")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run Meridian scenario planner from a completed model run."
    )
    p.add_argument("--client", required=True, help="Client ID matching configs/{id}.yaml")
    p.add_argument(
        "--run-id", required=True,
        help="Run ID to source model.pkl from (e.g. prod_2026-05-04_1430)",
    )
    p.add_argument(
        "--filter-start", default=None,
        help="Only include data from this date onwards (YYYY-MM-DD). "
             "Defaults to no filtering.",
    )
    p.add_argument("--monthly", action=argparse.BooleanOptionalAction, default=True,
                   help="Include monthly time breakdowns (default: on)")
    p.add_argument("--quarterly", action="store_true", default=False)
    p.add_argument("--yearly", action="store_true", default=False)
    p.add_argument(
        "--min-spend-shift", type=float, default=1.0,
        help="Lower bound multiplier on channel spend (1.0 = can't decrease below historical)",
    )
    p.add_argument(
        "--max-spend-shift", type=float, default=1.0,
        help="Upper bound multiplier on channel spend (1.0 = can't increase above historical)",
    )
    p.add_argument("--optimization-name", default="default",
                   help="Label for this optimization scenario")
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


def _parse_gcs_path(gs_uri: str) -> tuple[str, str]:
    without_scheme = gs_uri[len("gs://"):]
    bucket, _, prefix = without_scheme.partition("/")
    return bucket, prefix.rstrip("/")


def download_model_from_gcs(gcs_runs_base: str, run_id: str, dest: Path) -> Path:
    model_uri = f"{gcs_runs_base.rstrip('/')}/{run_id}/model.pkl"
    bucket_name, blob_path = _parse_gcs_path(model_uri)
    gcs_client = storage.Client()
    blob = gcs_client.bucket(bucket_name).blob(blob_path)
    local_path = dest / "model.pkl"
    try:
        blob.download_to_filename(str(local_path))
    except Exception:
        # List what files actually exist in this run folder so the user knows what's there
        run_prefix = f"{_parse_gcs_path(gcs_runs_base.rstrip('/'))[1]}/{run_id}/"
        existing = [
            b.name.split("/")[-1]
            for b in gcs_client.list_blobs(bucket_name, prefix=run_prefix)
        ]
        if existing:
            print(f"\nERROR: model.pkl not found. Files present in this run folder:")
            for f in existing:
                print(f"  {f}")
            print("\nmodel.pkl was likely not uploaded when this run completed.")
        else:
            # List available runs for this client so user can pick a valid one
            client_prefix = _parse_gcs_path(gcs_runs_base.rstrip('/'))[1] + "/"
            runs = sorted({
                b.name[len(client_prefix):].split("/")[0]
                for b in gcs_client.list_blobs(bucket_name, prefix=client_prefix)
            }, reverse=True)
            print(f"\nERROR: Run folder '{run_id}' not found in GCS.")
            print(f"Available runs for this client:")
            for r in runs:
                print(f"  {r}")
        sys.exit(1)
    print(f"  ✓ Downloaded gs://{bucket_name}/{blob_path}")
    return local_path


def filter_dataframes(
    dataframes: dict[str, pd.DataFrame],
    filter_start: str | None,
) -> dict[str, pd.DataFrame]:
    """
    Drop rows before filter_start from time-series sheets, and remove
    budget optimization grids for years before filter_start.
    """
    if not filter_start:
        return dataframes

    cutoff = pd.to_datetime(filter_start)
    TIME_SERIES_KEYS = {"ModelFit", "ScenarioBudget", "ScenarioOutcomes", "MarketingAnalysis"}
    result = {}

    for key, df in dataframes.items():
        if key.startswith("budget_opt_grid_"):
            try:
                year_str = key.split("_Y")[1][:4]
                if int(year_str) < cutoff.year:
                    print(f"  Skipping {key} (before {cutoff.year})")
                    continue
            except (IndexError, ValueError):
                pass

        date_col = next((c for c in ("Time", "Date") if c in df.columns), None)
        if key in TIME_SERIES_KEYS and date_col:
            df[date_col] = pd.to_datetime(df[date_col])
            filtered = df[df[date_col] >= cutoff].copy()
            filtered[date_col] = filtered[date_col].apply(lambda x: x.isoformat())
            print(f"  {key}: {len(df):,} → {len(filtered):,} rows")
            result[key] = filtered
        else:
            result[key] = df

    return result


def upload_to_gcs(
    dataframes: dict[str, pd.DataFrame],
    gcs_opt_path: str,
    manifest: dict,
) -> None:
    bucket_name, prefix = _parse_gcs_path(gcs_opt_path)
    gcs_client = storage.Client()
    bucket = gcs_client.bucket(bucket_name)
    uploaded = []

    for key, df in dataframes.items():
        fname = key.lower().replace(" ", "_") + ".csv"
        blob_path = f"{prefix}/{fname}"
        bucket.blob(blob_path).upload_from_string(
            df.to_csv(index=False).encode(), content_type="text/csv"
        )
        print(f"  ✓ gs://{bucket_name}/{blob_path}  ({len(df):,} rows)")
        uploaded.append(fname)

    manifest["files"] = sorted(uploaded)
    blob_path = f"{prefix}/manifest.json"
    bucket.blob(blob_path).upload_from_string(
        json.dumps(manifest, indent=2).encode(), content_type="application/json"
    )
    print(f"  ✓ gs://{bucket_name}/{blob_path}")


def main() -> None:
    _patch_batch_size()

    args = parse_args()
    t_start = time.time()

    config_path = _resolve_config(args.client)
    config = load_config(config_path)
    client_id = config["client_id"]

    gcs_runs_base = config.get("gcs_output_path", "").rstrip("/")
    if not gcs_runs_base:
        print("ERROR: gcs_output_path not set in config")
        sys.exit(1)

    # Derive optimizations path: .../runs → .../optimizations
    gcs_opt_base = gcs_runs_base.replace("/runs", "/optimizations")
    opt_id = f"{args.run_id}_{args.optimization_name}_{datetime.now().strftime('%Y-%m-%d_%H%M')}"
    gcs_opt_path = f"{gcs_opt_base}/{opt_id}"

    print(f"{'='*60}")
    print(f"  Scenario Planner — {client_id}")
    print(f"  source run  : {args.run_id}")
    print(f"  opt_id      : {opt_id}")
    print(f"  output      : {gcs_opt_path}/")
    print(f"{'='*60}\n")

    # ── 1. Download model from GCS ────────────────────────────────────────────
    print("1/4  Downloading model.pkl from GCS …")
    t1 = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = download_model_from_gcs(gcs_runs_base, args.run_id, Path(tmpdir))
        print(f"     ({time.time() - t1:.1f}s)\n")

        # ── 2. Load model ─────────────────────────────────────────────────────
        print("2/4  Loading model …")
        t2 = time.time()
        mmm_raw = model.load_mmm(str(model_path))
        mmm = model.Meridian(
            input_data=mmm_raw.input_data,
            model_spec=mmm_raw.model_spec,
            inference_data=mmm_raw.inference_data,
        )
        print(f"     ({time.time() - t2:.1f}s)\n")

        # ── 3. Generate scenario dataframes ───────────────────────────────────
        print("3/4  Generating scenario data …")
        t3 = time.time()

        time_breakdown_generators = []
        if args.yearly:
            time_breakdown_generators.append(date_range_bucketing.YearlyDateRangeGenerator)
        if args.quarterly:
            time_breakdown_generators.append(date_range_bucketing.QuarterlyDateRangeGenerator)
        if args.monthly:
            time_breakdown_generators.append(date_range_bucketing.MonthlyDateRangeGenerator)

        fixed_channels = set(config.get("fixed_channels", []))
        channel_constraints = [
            budget_optimization_processor.ChannelConstraintRel(
                channel_name=ch,
                spend_constraint_lower=1.0 if ch in fixed_channels else args.min_spend_shift,
                spend_constraint_upper=1.0 if ch in fixed_channels else args.max_spend_shift,
            )
            for ch in mmm.input_data.get_all_paid_channels()
        ]

        budget_spec = budget_optimization_processor.BudgetOptimizationSpec(
            optimization_name=args.optimization_name,
            grid_name="-".join(args.optimization_name.lower().split()),
            constraints=channel_constraints,
        )

        mmm_proto = mmm_ui_gen.create_mmm_ui_data_proto(
            mmm=mmm,
            specs=[
                model_fit_processor.ModelFitSpec(),
                marketing_processor.MarketingAnalysisSpec(
                    media_summary_spec=marketing_processor.MediaSummarySpec(
                        include_non_paid_channels=True,
                    ),
                ),
                budget_spec,
            ],
            time_breakdown_generators=time_breakdown_generators,
        )

        dataframes = dataframe_model_converter.DataFrameModelConverter(mmm_proto)()
        print(f"     {len(dataframes)} dataframes generated  ({(time.time() - t3) / 60:.1f} min)\n")

        # ── 4. Filter + upload to GCS ─────────────────────────────────────────
        print("4/4  Filtering and uploading to GCS …")
        filtered = filter_dataframes(dataframes, args.filter_start)

        manifest = {
            "client_id": client_id,
            "run_id": args.run_id,
            "optimization_id": opt_id,
            "optimization_name": args.optimization_name,
            "created_at": datetime.now().isoformat(),
            "filter_start": args.filter_start,
            "time_breakdowns": {
                "monthly": args.monthly,
                "quarterly": args.quarterly,
                "yearly": args.yearly,
            },
            "spend_shift": {
                "min": args.min_spend_shift,
                "max": args.max_spend_shift,
            },
            "gcs_path": gcs_opt_path,
        }

        upload_to_gcs(filtered, gcs_opt_path, manifest)

    total_min = (time.time() - t_start) / 60
    print(f"\n{'='*60}")
    print(f"  Done in {total_min:.1f} min  |  opt_id: {opt_id}")
    print(f"  GCS: {gcs_opt_path}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
