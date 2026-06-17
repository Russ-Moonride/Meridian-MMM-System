#!/usr/bin/env python3
"""
scripts/eval_freedom_power.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Phases 2–4 evaluation pipeline for Freedom Power MMM.

  Phase 2 — Local dev MCMC with holdout_id set in ModelSpec
  Phase 3 — Prior sensitivity (PSI via analytical prior samples vs posterior)
  Phase 4 — Holdout wCRPS

Key optimisation: prior samples are drawn analytically from the Beta
distribution parameters in the config (not via mmm.sample_prior(), which
triggers an additional slow TF/XLA compilation pass on this machine).

Outputs written to outputs/freedom_power/.
Run the reviewer separately (Phase 5) after this completes.

Usage:
    source .venv/bin/activate
    python -u scripts/eval_freedom_power.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

import numpy as np
import pandas as pd

from meridian.model import model as meridian_model, spec

from src.data_prep import load_config, prepare_data
from src.model_config import build_input_data, build_priors
from src.utils import extract_outputs
from src.crps import holdout_split, compute_crps_holdout

# ── Constants ─────────────────────────────────────────────────────────────────

CONFIG_PATH = REPO_ROOT / "configs" / "Freedom_Power.yaml"
OUT_DIR     = REPO_ROOT / "outputs" / "freedom_power"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CLIENT_ID  = "freedom_power"
DEV_MCMC   = {"n_chains": 1, "n_adapt": 200, "n_burnin": 200, "n_keep": 200}
N_PRIOR    = 1000   # prior draws for PSI (analytical — no TF cost)
RNG        = np.random.default_rng(42)

# ── PSI utilities ─────────────────────────────────────────────────────────────

def compute_psi(prior_s: np.ndarray, post_s: np.ndarray, n_bins: int = 20) -> float:
    """Population Stability Index comparing prior vs posterior marginals."""
    prior_s = np.asarray(prior_s, dtype=np.float64).ravel()
    post_s  = np.asarray(post_s,  dtype=np.float64).ravel()
    lo = min(prior_s.min(), post_s.min())
    hi = max(prior_s.max(), post_s.max())
    if lo >= hi:
        return 0.0
    bins = np.linspace(lo, hi, n_bins + 1)
    ph, _ = np.histogram(prior_s, bins=bins)
    qh, _ = np.histogram(post_s,  bins=bins)
    eps = 1e-8
    p = ph / (ph.sum() + eps) + eps
    q = qh / (qh.sum() + eps) + eps
    return float(np.sum((q - p) * np.log(q / p)))


def _psi_interp(psi: float) -> str:
    if psi < 0.05:   return "prior-dominated"
    if psi < 0.10:   return "boundary"
    if psi < 0.20:   return "prior-dependent"
    return "data-driven"


def _roi_verdict(psi: float) -> str:
    if psi > 0.20:  return "pass"
    if psi > 0.10:  return "warning"
    return "critical"


def _flatten(arr: np.ndarray) -> np.ndarray:
    """Flatten (chain, draw, n_channels) or (draw, n_channels) → (samples, n_channels)."""
    if arr.ndim == 3:
        return arr.reshape(-1, arr.shape[-1])
    return arr


# ── Analytical prior sampling ─────────────────────────────────────────────────

def sample_contribution_priors_analytically(cfg: dict, n_draws: int = 1000) -> np.ndarray:
    """
    Sample contribution_m prior analytically from the Beta distribution
    defined in the config.  This is equivalent to mmm.sample_prior() for the
    contribution_m parameter, but avoids a second TF/XLA compilation pass.

    Returns
    -------
    np.ndarray of shape (n_draws, n_channels)
    """
    channels = cfg["channels"]
    total    = cfg.get("total_media_contribution", 0.60)
    conc_def = cfg.get("concentration_default", 20.0)
    shares   = cfg.get("channel_media_shares", {})

    if shares:
        scale   = total / sum(shares.values())
        targets = {ch: shares.get(ch, total / len(channels)) * scale for ch in channels}
    else:
        targets = {ch: total / len(channels) for ch in channels}

    samples = np.empty((n_draws, len(channels)))
    for i, ch in enumerate(channels):
        mu   = targets[ch]
        conc = cfg.get(f"concentration_{ch.lower()}", conc_def)
        a    = mu * conc
        b    = (1.0 - mu) * conc
        samples[:, i] = RNG.beta(a, b, size=n_draws)

    return samples


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> dict:
    t_total = time.time()

    # ────────────────────────────────────────────────────────────────────────
    # PHASE 2 — LOCAL DEV RUN
    # ────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  PHASE 2 — LOCAL DEV RUN")
    print("=" * 62)

    cfg = load_config(CONFIG_PATH)
    cfg["client_id"] = CLIENT_ID
    print(f"  Config:   {CONFIG_PATH.relative_to(REPO_ROOT)}")
    print(f"  KPI:      {cfg['kpi_column']} ({cfg.get('kpi_type', 'revenue')})")
    print(f"  Channels: {cfg['channels']}")
    print(f"  Organic:  {cfg.get('organic_channels', [])}")
    print(f"  Controls: {cfg.get('controls', [])}")
    sys.stdout.flush()

    t1 = time.time()
    df = prepare_data(cfg)
    n_geos  = df[cfg["geo_column"]].nunique()
    n_weeks = df[cfg["date_column"]].nunique()
    print(f"\n  Data ready: {n_geos} geos × {n_weeks} weeks  ({time.time() - t1:.1f}s)")
    print(f"  Date range: {df[cfg['date_column']].min().date()} → {df[cfg['date_column']].max().date()}")
    sys.stdout.flush()

    # Holdout split
    holdout_dates, holdout_id_1d = holdout_split(
        df=df, cfg=cfg, n_holdout_weeks=8, strategy="interleaved"
    )
    holdout_id = np.tile(holdout_id_1d, (n_geos, 1))  # (n_geos, n_weeks)
    print(f"\n  Holdout ({len(holdout_dates)} weeks interleaved): {holdout_dates[0]} → {holdout_dates[-1]}")
    print(f"  holdout_id shape: {holdout_id.shape}")
    sys.stdout.flush()

    # Build input data + priors
    input_data = build_input_data(df, cfg)
    priors     = build_priors(cfg)

    knots_cfg = cfg.get("knots", 26)
    knots = n_weeks // 2 if str(knots_cfg).lower() == "auto" else int(knots_cfg)
    print(f"  Knots: {knots}  max_lag: {cfg.get('max_lag', 4)}")
    sys.stdout.flush()

    # Build ModelSpec with holdout_id
    model_spec = spec.ModelSpec(
        prior=priors,
        media_prior_type=cfg.get("media_prior_type", "contribution"),
        organic_media_prior_type="contribution",
        knots=knots,
        max_lag=cfg.get("max_lag", 4),
        adstock_decay_spec=cfg.get("adstock_decay_spec", "geometric"),
        media_effects_dist=cfg.get("media_effects_dist", "log_normal"),
        holdout_id=holdout_id,
    )

    print("\n  Building Meridian model (XLA compilation — may take 10-20 min)…")
    sys.stdout.flush()
    t2 = time.time()
    mmm = meridian_model.Meridian(input_data=input_data, model_spec=model_spec)
    print(f"  Model built  ({time.time() - t2:.1f}s)")
    sys.stdout.flush()

    # Dev MCMC
    run_id = f"dev_eval_{pd.Timestamp.now().strftime('%Y-%m-%d_%H%M')}"
    print(f"\n  MCMC dev run  [{run_id}]")
    print(f"  chains={DEV_MCMC['n_chains']}  adapt={DEV_MCMC['n_adapt']}  "
          f"burnin={DEV_MCMC['n_burnin']}  keep={DEV_MCMC['n_keep']}")
    sys.stdout.flush()

    t_mcmc = time.time()
    mmm.sample_posterior(
        n_chains=DEV_MCMC["n_chains"],
        n_adapt=DEV_MCMC["n_adapt"],
        n_burnin=DEV_MCMC["n_burnin"],
        n_keep=DEV_MCMC["n_keep"],
        seed=42,
    )
    print(f"  MCMC complete  ({(time.time() - t_mcmc) / 60:.1f} min)")
    sys.stdout.flush()

    # Extract outputs
    print("\n  Extracting outputs…")
    sys.stdout.flush()
    extract_outputs(mmm, df, cfg, run_id, DEV_MCMC, OUT_DIR)

    print()
    all_ok = True
    for fname in ["diagnostics.json", "contributions.csv", "model.pkl", "status.json"]:
        path = OUT_DIR / fname
        exists = path.exists()
        print(f"  {'✓' if exists else '✗'} {fname}")
        if not exists:
            all_ok = False
    sys.stdout.flush()

    if not all_ok:
        print("\n  ERROR: required output file missing — aborting.")
        sys.exit(1)

    diag = json.loads((OUT_DIR / "diagnostics.json").read_text())
    print(f"\n  rhat_max={diag.get('rhat_max')}  ess_min={diag.get('ess_min')}  "
          f"converged={diag.get('converged')}  model_type={diag.get('model_type')}")
    sys.stdout.flush()

    # ────────────────────────────────────────────────────────────────────────
    # PHASE 3 — PRIOR SENSITIVITY
    # ────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  PHASE 3 — PRIOR SENSITIVITY")
    print("=" * 62)
    sys.stdout.flush()

    channels = cfg["channels"]
    post_ds  = mmm.inference_data.posterior

    # Generate prior samples analytically (fast — no TF needed)
    print(f"\n  Generating {N_PRIOR} analytical prior samples for contribution_m…")
    sys.stdout.flush()
    prior_contrib = sample_contribution_priors_analytically(cfg, n_draws=N_PRIOR)
    print(f"  Prior samples shape: {prior_contrib.shape}")
    sys.stdout.flush()

    # Posterior samples
    has_contrib_m = hasattr(post_ds, "contribution_m")
    has_roi_m     = hasattr(post_ds, "roi_m")
    has_alpha_m   = hasattr(post_ds, "alpha_m")
    has_ec_m      = hasattr(post_ds, "ec_m")

    print(f"  Posterior params — contribution_m:{has_contrib_m}  roi_m:{has_roi_m}  "
          f"alpha_m:{has_alpha_m}  ec_m:{has_ec_m}")
    sys.stdout.flush()

    if has_contrib_m:
        primary_param = "contribution_m"
        post_contrib = _flatten(post_ds.contribution_m.values)
    elif has_roi_m:
        primary_param = "roi_m"
        post_contrib = _flatten(post_ds.roi_m.values)
    else:
        primary_param = None
        post_contrib  = None

    channel_results: list[dict] = []

    # — contribution_m PSI ——
    if primary_param and post_contrib is not None:
        print(f"\n  {primary_param.upper()} PSI  (analytical prior vs posterior)")
        print(f"  {'Channel':<22}  {'PSI':>6}  {'Interpretation':<22}  Verdict")
        print("  " + "-" * 68)
        for i, ch in enumerate(channels):
            psi    = compute_psi(prior_contrib[:, i], post_contrib[:, i])
            interp = _psi_interp(psi)
            verd   = _roi_verdict(psi)
            flag   = " ← CRITICAL" if verd == "critical" else (" ← WARNING" if verd == "warning" else "")
            print(f"  {ch:<22}  {psi:>6.4f}  {interp:<22}  {verd.upper()}{flag}")
            channel_results.append({
                "channel": ch,
                f"{primary_param}_psi": round(psi, 4),
                f"{primary_param}_verdict": verd,
                "notes": "",
            })
        sys.stdout.flush()

    # — alpha_m PSI (adstock decay) ——
    if has_alpha_m:
        a_post = _flatten(post_ds.alpha_m.values)
        # Prior for alpha_m is Uniform(0,1) in Meridian by default
        a_prior = RNG.uniform(0.0, 1.0, size=(N_PRIOR, len(channels)))
        print(f"\n  ALPHA_M PSI  (adstock decay; Uniform(0,1) prior)")
        print(f"  {'Channel':<22}  {'PSI':>6}  Interpretation  (boundary 0.05–0.15 is normal)")
        print("  " + "-" * 58)
        for i, ch in enumerate(channels):
            psi    = compute_psi(a_prior[:, i], a_post[:, i])
            interp = _psi_interp(psi)
            flag   = " ← above expected boundary" if psi > 0.30 else ""
            print(f"  {ch:<22}  {psi:>6.4f}  {interp}{flag}")
            for r in channel_results:
                if r["channel"] == ch:
                    r["alpha_m_psi"] = round(psi, 4)
                    r["alpha_m_interpretation"] = interp
        sys.stdout.flush()

    # — ec_m PSI ——
    if has_ec_m:
        e_post  = _flatten(post_ds.ec_m.values)
        # Prior for ec_m in Meridian is HalfNormal — approximate with uniform for shape
        e_prior = RNG.exponential(scale=1.0, size=(N_PRIOR, len(channels)))
        print(f"\n  EC_M PSI  (half-saturation)")
        print(f"  {'Channel':<22}  {'PSI':>6}  Interpretation")
        print("  " + "-" * 50)
        for i, ch in enumerate(channels):
            psi    = compute_psi(e_prior[:, i], e_post[:, i])
            interp = _psi_interp(psi)
            print(f"  {ch:<22}  {psi:>6.4f}  {interp}")
            for r in channel_results:
                if r["channel"] == ch:
                    r["ec_m_psi"] = round(psi, 4)
        sys.stdout.flush()
    else:
        print("\n  ec_m: not present in posterior (expected for contribution priors)")
        sys.stdout.flush()

    # — Notes and overall verdict ——
    for r in channel_results:
        ch   = r["channel"]
        psi  = r.get(f"{primary_param}_psi") if primary_param else None
        verd = r.get(f"{primary_param}_verdict", "unknown") if primary_param else "unknown"
        parts = []
        if psi is not None:
            parts.append(f"{primary_param} PSI={psi:.4f} ({_psi_interp(psi)})")
        if ch == "Reddit":
            parts.append("sparse channel (~94% zeros, 8 active weeks) — prior-dominated expected")
        elif ch == "Billboard":
            parts.append("sparse channel (Austin only, 9-10 active weeks) — some prior-dominance expected")
        if verd == "critical" and ch not in ("Reddit", "Billboard"):
            parts.append("CRITICAL: data has minimal signal — consider merging or dropping")
        elif verd == "warning":
            parts.append("prior quality important — validate share estimate")
        r["notes"] = "; ".join(parts)

    # Exclude sparse channels from blocking verdict
    critical_channels = [
        r["channel"] for r in channel_results
        if r.get(f"{primary_param}_verdict") == "critical"
        and r["channel"] not in ("Reddit", "Billboard")
    ] if primary_param else []
    warning_channels = [
        r["channel"] for r in channel_results
        if r.get(f"{primary_param}_verdict") == "warning"
    ] if primary_param else []

    if critical_channels:
        overall_psi_verdict = "CRITICAL"
    elif warning_channels:
        overall_psi_verdict = "WARNING"
    else:
        overall_psi_verdict = "PASS"

    print(f"\n  Overall PSI verdict: {overall_psi_verdict}")
    if critical_channels:
        print(f"  Critical (non-sparse): {critical_channels}")
    if warning_channels:
        print(f"  Warning channels:      {warning_channels}")
    sys.stdout.flush()

    sensitivity_report = {
        "client_id": CLIENT_ID,
        "run_id": run_id,
        "primary_parameter": primary_param,
        "prior_sampling_method": "analytical_from_config",
        "overall_verdict": overall_psi_verdict,
        "critical_channels_non_sparse": critical_channels,
        "warning_channels": warning_channels,
        "channels": channel_results,
    }
    report_path = OUT_DIR / "prior_sensitivity_report.json"
    report_path.write_text(json.dumps(sensitivity_report, indent=2))
    print(f"  Written: {report_path.relative_to(REPO_ROOT)}")
    sys.stdout.flush()

    # ────────────────────────────────────────────────────────────────────────
    # PHASE 4 — HOLDOUT CRPS
    # ────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  PHASE 4 — HOLDOUT wCRPS")
    print("=" * 62)
    sys.stdout.flush()

    holdout_df     = df[df[cfg["date_column"]].isin(pd.to_datetime(holdout_dates))]
    holdout_weekly = holdout_df.groupby(cfg["date_column"])[cfg["kpi_column"]].sum()
    kpi_mean       = float(holdout_weekly.mean())
    kpi_std        = float(holdout_weekly.std())

    print(f"  Holdout weeks: {len(holdout_dates)}  ({holdout_dates[0]} → {holdout_dates[-1]})")
    print(f"  KPI ({cfg['kpi_column']}) — mean={kpi_mean:.1f}  std={kpi_std:.1f}")
    sys.stdout.flush()

    crps_score = None
    crps_error = None
    try:
        crps_score = compute_crps_holdout(
            mmm=mmm,
            holdout_dates=holdout_dates,
            df=df,
            cfg=cfg,
            weighted=True,
            aggregate_geos=True,
        )
        print(f"\n  Holdout wCRPS: {crps_score:.5f}")
        if kpi_mean > 0:
            ratio = crps_score / kpi_mean
            print(f"  wCRPS / mean_KPI = {ratio:.4f}")
        print("  Context: first baseline run — no prior runs to compare against.")

        # Anomaly check
        if crps_score < 0.001 * kpi_mean:
            print("  ⚠ wCRPS near zero — possible overfit")
        elif kpi_std > 0 and crps_score > 2 * kpi_std:
            print(f"  ⚠ wCRPS > 2×std — model may be poorly calibrated")
        else:
            print("  ✓ wCRPS in plausible range")

        # Update diagnostics.json
        diag["holdout_wcrps"]    = round(crps_score, 5)
        diag["holdout_n_weeks"]  = len(holdout_dates)
        diag["holdout_strategy"] = "interleaved"
        diag["holdout_kpi_mean"] = round(kpi_mean, 2)
        diag["holdout_kpi_std"]  = round(kpi_std,  2)
        (OUT_DIR / "diagnostics.json").write_text(json.dumps(diag, indent=2))
        print(f"  diagnostics.json updated with holdout_wcrps={crps_score:.5f}")
        sys.stdout.flush()

    except Exception as exc:
        crps_error = str(exc)
        print(f"\n  ERROR computing CRPS: {exc}")
        import traceback; traceback.print_exc()
        sys.stdout.flush()

    # ────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ────────────────────────────────────────────────────────────────────────
    total_min = (time.time() - t_total) / 60
    print("\n" + "=" * 62)
    print("  PHASES 2–4 COMPLETE")
    print("=" * 62)
    print(f"  Wall clock:        {total_min:.1f} min")
    print(f"  run_id:            {run_id}")
    print()
    print(f"  rhat_max:          {diag.get('rhat_max')}")
    print(f"  ess_min:           {diag.get('ess_min')}")
    print(f"  converged:         {diag.get('converged')}")
    print(f"  PSI verdict:       {overall_psi_verdict}")
    if critical_channels:
        print(f"  Critical channels: {critical_channels}")
    if warning_channels:
        print(f"  Warning channels:  {warning_channels}")
    if crps_score is not None:
        print(f"  Holdout wCRPS:     {crps_score:.5f}")
        print(f"  Holdout KPI mean:  {kpi_mean:.1f}")
    elif crps_error:
        print(f"  Holdout wCRPS:     ERROR — {crps_error}")
    print()
    print("  Next: run Phase 5 (reviewer)")
    print("    python agents/reviewer.py --client freedom_power --dry-run")
    print("    python agents/reviewer.py --client freedom_power")
    print("=" * 62)
    sys.stdout.flush()

    return {
        "run_id": run_id,
        "rhat_max": diag.get("rhat_max"),
        "ess_min": diag.get("ess_min"),
        "converged": diag.get("converged"),
        "psi_verdict": overall_psi_verdict,
        "critical_channels": critical_channels,
        "warning_channels": warning_channels,
        "crps_score": crps_score,
    }


if __name__ == "__main__":
    main()
