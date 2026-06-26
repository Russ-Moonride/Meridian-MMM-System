"""
Local dev run for Janessa Leone.

Loads data/processed/janessa_leone/JL_mmm_data_Jun26.csv, runs Meridian in
dev mode (1 chain, 200 adapt/burnin/keep), prints diagnostics, and saves
the InferenceData to outputs/janessa_leone/.

Usage:
    source .venv/bin/activate
    python scripts/run_jl_local.py
"""

import os
import sys
import time
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import tensorflow as tf
import tensorflow_probability as tfp
import yaml

from meridian.data import data_frame_input_data_builder
from meridian.model import model, prior_distribution, spec

tfd = tfp.distributions

# ── Config ────────────────────────────────────────────────────────────────────

with open(ROOT / "configs" / "Janessa_Leone.yaml") as fh:
    cfg = yaml.safe_load(fh)

channels   = cfg["channels"]
roi_ranges = cfg["prior_roi_ranges"]
mass_pct   = cfg.get("prior_roi_mass_percent", 0.95)

OUT_DIR = ROOT / "outputs" / "janessa_leone"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Load & prepare data ────────────────────────────────────────────────────────

print("[1/6] Loading data ...")
data_path = ROOT / cfg["data_path"]
df = pd.read_csv(data_path, parse_dates=["date"])
df = df.sort_values("date").reset_index(drop=True)

print(f"      {len(df)} rows | {df['date'].min().date()} → {df['date'].max().date()}")

# Float32 casting
df["Revenue"]      = df["Revenue"].astype(np.float32)
df["black_friday"] = df["black_friday"].astype(np.float32)
for ch in channels:
    df[f"{ch}_Cost"]        = df[f"{ch}_Cost"].astype(np.float32)
    df[f"{ch}_Impressions"] = df[f"{ch}_Impressions"].astype(np.float32)

# Quick spend summary
print("\n      Channel spend summary:")
for ch in channels:
    total   = float(df[f"{ch}_Cost"].sum())
    nonzero = int((df[f"{ch}_Cost"] > 0).sum())
    print(f"        {ch:<20} ${total:>12,.0f}  ({nonzero}/{len(df)} non-zero weeks)")

# ── Build InputData ────────────────────────────────────────────────────────────

print("\n[2/6] Building InputData (national — no geo) ...")
builder = data_frame_input_data_builder.DataFrameInputDataBuilder(kpi_type="revenue")
builder = builder.with_kpi(df, kpi_col="Revenue", time_col="date")
builder = builder.with_media(
    df,
    media_channels=channels,
    media_spend_cols=[f"{c}_Cost" for c in channels],
    media_cols=[f"{c}_Impressions" for c in channels],
    time_col="date",
)
builder = builder.with_controls(df, control_cols=["black_friday"], time_col="date")
input_data = builder.build()
print("      InputData built.")

# ── Priors ────────────────────────────────────────────────────────────────────

print("\n[3/6] Building priors ...")
roi_dists = []
for ch in channels:
    lo, hi = roi_ranges[ch]
    d = prior_distribution.lognormal_dist_from_range(
        low=lo, high=hi, mass_percent=mass_pct
    )
    roi_dists.append(d)
    print(f"      {ch:<20} ROI [{lo}, {hi}]  → LogNormal(loc={d.loc:.3f}, scale={d.scale:.3f})")

roi_loc   = tf.cast([d.loc   for d in roi_dists], tf.float32)
roi_scale = tf.cast([d.scale for d in roi_dists], tf.float32)
priors = prior_distribution.PriorDistribution(
    roi_m=tfd.LogNormal(loc=roi_loc, scale=roi_scale)
)

# ── ModelSpec ─────────────────────────────────────────────────────────────────

print("\n[4/6] Building ModelSpec ...")
n_weeks = df["date"].nunique()
knots   = cfg.get("knots", 26)
model_spec = spec.ModelSpec(
    prior=priors,
    media_prior_type="roi",
    knots=knots,
    max_lag=cfg.get("max_lag", 6),
    adstock_decay_spec=cfg.get("adstock_decay_spec", "geometric"),
    media_effects_dist=cfg.get("media_effects_dist", "log_normal"),
)
mmm = model.Meridian(input_data=input_data, model_spec=model_spec)
print(f"      Knots={knots}, max_lag={cfg.get('max_lag', 6)}, {n_weeks} time points")

# ── Prior predictive ──────────────────────────────────────────────────────────

print("\n[5/6] Sampling prior (500 draws) ...")
t0 = time.time()
mmm.sample_prior(500, seed=42)
print(f"      Done in {time.time()-t0:.1f}s")

# ── MCMC (dev mode) ───────────────────────────────────────────────────────────

print("\n[6/6] Running MCMC — dev mode (1 chain, 200 adapt / 200 burnin / 200 keep) ...")
t0 = time.time()
mmm.sample_posterior(n_chains=1, n_adapt=200, n_burnin=200, n_keep=200, seed=42)
elapsed = time.time() - t0
print(f"      Done in {elapsed/60:.1f} min")

# ── Diagnostics ───────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("DIAGNOSTICS")
print("="*60)

idata = mmm.inference_data

# R-hat
try:
    import arviz as az
    summary = az.summary(idata, var_names=["roi_m"], round_to=3)
    print("\nROI posterior (roi_m):")
    print(summary[["mean", "sd", "hdi_3%", "hdi_97%", "r_hat", "ess_bulk"]].to_string())

    # Overall convergence
    rhats = summary["r_hat"].dropna()
    max_rhat = float(rhats.max())
    n_diverged = int((rhats > 1.1).sum())
    print(f"\nMax R-hat:          {max_rhat:.4f}  {'✓ CONVERGED' if max_rhat < 1.1 else '⚠ WARNING'}")
    print(f"Channels R-hat>1.1: {n_diverged}/{len(rhats)}")

    min_ess = float(summary["ess_bulk"].min())
    print(f"Min ESS (bulk):     {min_ess:.0f}  {'✓' if min_ess >= 100 else '⚠ low'}")
except Exception as e:
    print(f"ArviZ summary failed: {e}")

# ROI medians from posterior
print("\nChannel ROI medians (posterior):")
try:
    roi_samples = idata.posterior["roi_m"].values  # (chains, draws, channels)
    roi_flat    = roi_samples.reshape(-1, len(channels))
    for i, ch in enumerate(channels):
        med  = float(np.median(roi_flat[:, i]))
        p5   = float(np.percentile(roi_flat[:, i], 5))
        p95  = float(np.percentile(roi_flat[:, i], 95))
        lo, hi = roi_ranges[ch]
        print(f"  {ch:<20}  median={med:.2f}  [p5={p5:.2f}, p95={p95:.2f}]  prior=[{lo},{hi}]")
except Exception as e:
    print(f"  ROI extraction failed: {e}")

# ── Save InferenceData ────────────────────────────────────────────────────────

out_nc = OUT_DIR / "dev_run_inference_data.nc"
try:
    idata.to_netcdf(str(out_nc))
    print(f"\nInferenceData saved → {out_nc.relative_to(ROOT)}")
except Exception as e:
    print(f"\nSave failed: {e}")

print("\nDone.")
