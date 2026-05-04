"""
src/utils.py
~~~~~~~~~~~~
Shared utilities for extracting Meridian model outputs to disk.

Public API
----------
extract_outputs(mmm, df, config, run_id, mcmc, out_dir) → dict
"""
from __future__ import annotations

import json
import pickle
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import arviz as az
import numpy as np
import pandas as pd
from meridian.analysis import analyzer


def extract_outputs(
    mmm,
    df: pd.DataFrame,
    config: dict[str, Any],
    run_id: str,
    mcmc: dict[str, int],
    out_dir: Path,
) -> dict[str, Any]:
    """
    Extract contributions, diagnostics, and status from a fitted Meridian model
    and write them to out_dir as contributions.csv, diagnostics.json, status.json.

    Parameters
    ----------
    mmm       : fitted meridian.model.model.Meridian
    df        : prepared DataFrame (same one used to build the model)
    config    : client config dict
    run_id    : string identifier, e.g. "prod_2026-04-16"
    mcmc      : dict with n_chains, n_adapt, n_burnin, n_keep
    out_dir   : Path to write output files

    Returns
    -------
    dict with keys: contributions_df, diagnostics, status
    """
    t0 = _time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    channels     = config["channels"]
    organic_chs  = config.get("organic_channels", [])
    date_col     = config["date_column"]
    kpi_col      = config["kpi_column"]
    client_id    = config["client_id"]
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    n_chains = mcmc.get("n_chains", 1)
    n_adapt  = mcmc.get("n_adapt",  200)
    n_burnin = mcmc.get("n_burnin", 200)
    n_keep   = mcmc.get("n_keep",   200)

    m_analyzer = analyzer.Analyzer(mmm)

    # ── Weekly spend and KPI summed across all geos ───────────────────────────
    weekly_spend = (
        df.groupby(date_col)[[f"{c}_Cost" for c in channels]]
        .sum()
        .rename(columns={f"{c}_Cost": c for c in channels})
        .reset_index()
    )
    weekly_spend[date_col] = pd.to_datetime(weekly_spend[date_col])

    weekly_kpi = (
        df.groupby(date_col)[kpi_col]
        .sum()
        .reset_index()
        .rename(columns={kpi_col: "total_revenue"})
    )
    weekly_kpi[date_col] = pd.to_datetime(weekly_kpi[date_col])

    # ── Aggregate ROI with 90% CI per paid channel ────────────────────────────
    agg    = m_analyzer.summary_metrics(aggregate_geos=True, aggregate_times=True, use_kpi=True)
    agg_df = agg.to_dataframe().reset_index()

    def _roi(ch: str, metric: str, dist: str = "posterior") -> float:
        mask = (
            (agg_df["channel"] == ch) &
            (agg_df["metric"] == metric) &
            (agg_df["distribution"] == dist)
        )
        vals = agg_df.loc[mask, "roi"]
        return float(vals.values[0]) if len(vals) else float("nan")

    roi_median = {ch: _roi(ch, "median") for ch in channels}
    roi_lo     = {ch: _roi(ch, "ci_lo")  for ch in channels}
    roi_hi     = {ch: _roi(ch, "ci_hi")  for ch in channels}

    # ── Weekly incremental contributions — paid and organic ───────────────────
    ts = m_analyzer.summary_metrics(
        aggregate_geos=True, aggregate_times=False, use_kpi=True,
        include_non_paid_channels=True,
    )
    ts_dates = pd.to_datetime(ts.coords["time"].values)

    paid_weekly = {
        ch: ts["incremental_outcome"]
            .sel(channel=ch, metric="median", distribution="posterior")
            .values.astype(float)
        for ch in channels
    }
    org_weekly = {
        ch: ts["incremental_outcome"]
            .sel(channel=ch, metric="median", distribution="posterior")
            .values.astype(float)
        for ch in organic_chs
    }

    # ── Baseline time series ──────────────────────────────────────────────────
    eva = m_analyzer.expected_vs_actual_data(
        aggregate_geos=True, aggregate_times=False, use_kpi=True
    )
    baseline_vals = eva["baseline"].sel(metric="mean").values.astype(float)

    # ── Build contributions DataFrame ─────────────────────────────────────────
    rows = []
    for i, ts_date in enumerate(ts_dates):
        date_str  = pd.Timestamp(ts_date).strftime("%Y-%m-%d")
        date_key  = pd.Timestamp(ts_date)
        total_rev = float(
            weekly_kpi.loc[weekly_kpi[date_col] == date_key, "total_revenue"].iloc[0]
        )

        for ch in channels:
            contrib = float(paid_weekly[ch][i])
            spend   = float(weekly_spend.loc[weekly_spend[date_col] == date_key, ch].iloc[0])
            rows.append({
                "date":             date_str,
                "channel":          ch,
                "channel_type":     "paid",
                "contribution":     round(contrib, 2),
                "contribution_pct": round(contrib / total_rev * 100, 3) if total_rev > 0 else 0.0,
                "roi":              round(roi_median[ch], 3),
                "roi_lower_90":     round(roi_lo[ch], 3),
                "roi_upper_90":     round(roi_hi[ch], 3),
                "spend":            round(spend, 2),
            })

        for ch in organic_chs:
            contrib = float(org_weekly[ch][i])
            rows.append({
                "date":             date_str,
                "channel":          ch,
                "channel_type":     "organic",
                "contribution":     round(contrib, 2),
                "contribution_pct": round(contrib / total_rev * 100, 3) if total_rev > 0 else 0.0,
                "roi":              None,
                "roi_lower_90":     None,
                "roi_upper_90":     None,
                "spend":            0.0,
            })

        bl = float(baseline_vals[i])
        rows.append({
            "date":             date_str,
            "channel":          "Baseline",
            "channel_type":     "baseline",
            "contribution":     round(bl, 2),
            "contribution_pct": round(bl / total_rev * 100, 3) if total_rev > 0 else 0.0,
            "roi":              None,
            "roi_lower_90":     None,
            "roi_upper_90":     None,
            "spend":            0.0,
        })

    contributions_df = pd.DataFrame(rows)
    contributions_df.to_csv(out_dir / "contributions.csv", index=False)

    # ── Geo-level summary ─────────────────────────────────────────────────────
    geo_metrics = m_analyzer.summary_metrics(aggregate_geos=False, use_kpi=True)
    geo_df = geo_metrics.to_dataframe().reset_index()
    geo_df.to_csv(out_dir / "geo_summary.csv", index=False)

    # ── diagnostics.json — rhat and ESS via arviz ─────────────────────────────
    diag_sum = az.summary(mmm.inference_data, var_names=["beta_m"], round_to=4)

    rhat_by_ch: dict[str, float | None] = {}
    ess_by_ch:  dict[str, int]          = {}
    for ch in channels:
        label = f"beta_m[{ch}]"
        if label in diag_sum.index:
            r = diag_sum.loc[label, "r_hat"]
            e = diag_sum.loc[label, "ess_bulk"]
            rhat_by_ch[ch] = None if (isinstance(r, float) and np.isnan(r)) else round(float(r), 4)
            ess_by_ch[ch]  = int(e)

    all_rhat = [v for v in rhat_by_ch.values() if v is not None]
    all_ess  = list(ess_by_ch.values())
    rhat_max  = float(max(all_rhat)) if all_rhat else None
    ess_min   = int(min(all_ess)) if all_ess else None
    converged = (rhat_max < 1.2) if rhat_max is not None else (ess_min is not None and ess_min >= 50)
    model_type = "prod" if n_chains >= 4 else "dev"

    diagnostics = {
        "run_id":           run_id,
        "client_id":        client_id,
        "completed_at":     completed_at,
        "model_type":       model_type,
        "rhat_max":         rhat_max,
        "rhat_by_channel":  rhat_by_ch,
        "ess_min":          ess_min,
        "ess_by_channel":   ess_by_ch,
        "converged":        bool(converged),
        "runtime_minutes":  round((_time.time() - t0) / 60, 2),
        "n_chains":         n_chains,
        "n_adapt":          n_adapt,
        "n_burnin":         n_burnin,
        "n_keep":           n_keep,
    }
    (out_dir / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2))

    # ── status.json ───────────────────────────────────────────────────────────
    status = {
        "status":       "complete",
        "run_id":       run_id,
        "completed_at": completed_at,
        "client_id":    client_id,
        "n_weeks":      int(df[date_col].nunique()),
        "n_geos":       int(df[config["geo_column"]].nunique()),
        "n_channels":   len(channels),
        "model_type":   model_type,
    }
    (out_dir / "status.json").write_text(json.dumps(status, indent=2))

    # ── Model pickle ──────────────────────────────────────────────────────────
    with open(out_dir / "model.pkl", "wb") as _fh:
        pickle.dump(mmm, _fh)

    # ── Print summary ─────────────────────────────────────────────────────────
    paid_t    = contributions_df[contributions_df["channel_type"] == "paid"]["contribution"].sum()
    organic_t = contributions_df[contributions_df["channel_type"] == "organic"]["contribution"].sum()
    base_t    = contributions_df[contributions_df["channel"] == "Baseline"]["contribution"].sum()
    grand     = paid_t + organic_t + base_t

    print(f"  contributions.csv   {len(contributions_df):,} rows  → {out_dir / 'contributions.csv'}")
    print(f"  geo_summary.csv     {len(geo_df):,} rows  → {out_dir / 'geo_summary.csv'}")
    print(f"  diagnostics.json                     → {out_dir / 'diagnostics.json'}")
    print(f"  status.json                          → {out_dir / 'status.json'}")
    print(f"  model.pkl                            → {out_dir / 'model.pkl'}")
    print(f"\n  Attribution split:")
    print(f"    Paid:     ${paid_t:>12,.0f}  ({paid_t / grand * 100:.1f}%)")
    print(f"    Organic:  ${organic_t:>12,.0f}  ({organic_t / grand * 100:.1f}%)")
    print(f"    Baseline: ${base_t:>12,.0f}  ({base_t / grand * 100:.1f}%)")
    print(f"    Total:    ${grand:>12,.0f}")
    print(f"\n  Diagnostics: rhat_max={rhat_max}, ess_min={ess_min}, converged={converged}")

    return {
        "contributions_df": contributions_df,
        "geo_df":           geo_df,
        "diagnostics":      diagnostics,
        "status":           status,
    }
