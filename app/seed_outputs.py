"""
app/seed_outputs.py
~~~~~~~~~~~~~~~~~~~
Generates realistic mock model outputs for Northspore so the Dash app
has data to display before a real Meridian run is complete.

Contributions are derived from actual weekly spend totals in the CSV,
scaled so paid media ≈ 45% of revenue and organic ≈ 5%.
ROI estimates use the geometric midpoints of the prior ranges.
90% CI bounds are set to the prior range bounds (wide, as expected
from a model with limited per-channel data).

Usage (from repo root):
    python app/seed_outputs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.data_prep import load_config, prepare_data

OUT_DIR = ROOT / "outputs" / "northspore"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(42)

# ── Load and prepare Northspore data ─────────────────────────────────────────
cfg = load_config(ROOT / "configs" / "NorthSpore.yaml")
df = prepare_data(cfg)

channels = cfg["channels"]
organic_channels = cfg.get("organic_channels", [])
date_col = cfg["date_column"]
geo_col = cfg["geo_column"]
kpi_col = cfg["kpi_column"]

# Aggregate to weekly totals across all geos
weekly = (
    df.groupby(date_col)
    .agg(
        **{f"{c}_Cost": (f"{c}_Cost", "sum") for c in channels},
        **{f"{c}_Views": (f"{c}_Views", "sum") for c in organic_channels},
        **{kpi_col: (kpi_col, "sum")},
    )
    .reset_index()
    .sort_values(date_col)
)

# ── ROI parameters per channel ────────────────────────────────────────────────
# roi:  geometric midpoint of the prior range — the "true" modelled ROI
# low/high: prior range bounds used directly as 90% CI (appropriately wide)
ROI_PARAMS: dict[str, dict] = {
    "Brand":       {"roi": 3.7,  "low": 1.3, "high": 10.6},
    "Non_Brand":   {"roi": 3.7,  "low": 1.8, "high":  7.7},
    "DVD":         {"roi": 4.0,  "low": 1.3, "high": 12.3},
    "Retargeting": {"roi": 4.0,  "low": 1.3, "high": 12.4},
    "Prospecting": {"roi": 2.2,  "low": 0.8, "high":  6.0},
    "Shopping":    {"roi": 4.0,  "low": 2.0, "high":  7.9},
    "Amazon":      {"roi": 2.4,  "low": 1.2, "high":  4.9},
}

# Organic: scale views → revenue contribution so organic ≈ 5% of total revenue.
# Precompute scale factors from totals.
total_revenue = float(weekly[kpi_col].sum())
organic_target = 0.05 * total_revenue
total_views = {
    ch: float(weekly[f"{ch}_Views"].sum()) for ch in organic_channels
}
organic_scale = {
    ch: (organic_target / len(organic_channels)) / max(total_views[ch], 1)
    for ch in organic_channels
}

# ── Build weekly contributions ────────────────────────────────────────────────
rows: list[dict] = []

for _, row in weekly.iterrows():
    date = row[date_col]
    total_rev = float(row[kpi_col])

    # Paid channel contributions: spend × ROI × small noise
    raw_paid: dict[str, float] = {}
    for ch in channels:
        spend = float(row[f"{ch}_Cost"])
        noise = float(RNG.normal(1.0, 0.07))
        raw_paid[ch] = spend * ROI_PARAMS[ch]["roi"] * max(noise, 0.5)

    # Organic contributions: proportional to views
    raw_organic: dict[str, float] = {
        ch: float(row[f"{ch}_Views"]) * organic_scale[ch]
        for ch in organic_channels
    }

    # Scale paid so total paid ≈ 45% of weekly revenue
    total_raw_paid = sum(raw_paid.values())
    paid_target = 0.45 * total_rev
    scale = paid_target / total_raw_paid if total_raw_paid > 0 else 1.0
    paid_contrib = {ch: v * scale for ch, v in raw_paid.items()}

    total_media = sum(paid_contrib.values()) + sum(raw_organic.values())
    baseline_contrib = max(total_rev - total_media, 0.0)

    # Paid rows
    for ch in channels:
        contrib = paid_contrib[ch]
        spend = float(row[f"{ch}_Cost"])
        p = ROI_PARAMS[ch]
        effective_roi = contrib / spend if spend > 0 else 0.0
        rows.append({
            "date": date,
            "channel": ch,
            "channel_type": "paid",
            "contribution": round(contrib, 2),
            "contribution_pct": round(contrib / total_rev * 100, 3) if total_rev > 0 else 0,
            "roi": round(effective_roi, 3),
            "roi_lower_90": p["low"],
            "roi_upper_90": p["high"],
            "spend": round(spend, 2),
        })

    # Organic rows
    for ch in organic_channels:
        contrib = raw_organic[ch]
        rows.append({
            "date": date,
            "channel": ch,
            "channel_type": "organic",
            "contribution": round(contrib, 2),
            "contribution_pct": round(contrib / total_rev * 100, 3) if total_rev > 0 else 0,
            "roi": None,
            "roi_lower_90": None,
            "roi_upper_90": None,
            "spend": 0.0,
        })

    # Baseline row
    rows.append({
        "date": date,
        "channel": "Baseline",
        "channel_type": "baseline",
        "contribution": round(baseline_contrib, 2),
        "contribution_pct": round(baseline_contrib / total_rev * 100, 3) if total_rev > 0 else 0,
        "roi": None,
        "roi_lower_90": None,
        "roi_upper_90": None,
        "spend": 0.0,
    })

contributions_df = pd.DataFrame(rows)
contributions_path = OUT_DIR / "contributions.csv"
contributions_df.to_csv(contributions_path, index=False)
print(f"✓ contributions.csv  {len(contributions_df):,} rows → {contributions_path}")

# ── diagnostics.json ──────────────────────────────────────────────────────────
diagnostics = {
    "rhat_max": 1.048,
    "rhat_by_channel": {
        "Brand":       1.020,
        "Non_Brand":   1.031,
        "DVD":         1.048,
        "Retargeting": 1.027,
        "Prospecting": 1.019,
        "Shopping":    1.022,
        "Amazon":      1.035,
    },
    "ess_min": 124,
    "ess_by_channel": {
        "Brand":       156,
        "Non_Brand":   143,
        "DVD":         124,
        "Retargeting": 178,
        "Prospecting": 163,
        "Shopping":    149,
        "Amazon":      138,
    },
    "converged": True,
    "runtime_minutes": 17.4,
    "n_chains": 1,
    "n_adapt": 200,
    "n_burnin": 200,
    "n_keep": 200,
    "run_id": "dev_2026-04-15",
    "completed_at": "2026-04-15T10:23:41",
    "model_type": "dev",
}
diag_path = OUT_DIR / "diagnostics.json"
diag_path.write_text(json.dumps(diagnostics, indent=2))
print(f"✓ diagnostics.json            → {diag_path}")

# ── status.json ───────────────────────────────────────────────────────────────
status = {
    "status": "complete",
    "run_id": "dev_2026-04-15",
    "completed_at": "2026-04-15T10:23:41",
    "client_id": "northspore",
    "n_weeks": int(weekly[date_col].nunique()),
    "n_geos": int(df[geo_col].nunique()),
    "n_channels": len(channels),
    "model_type": "dev",
}
status_path = OUT_DIR / "status.json"
status_path.write_text(json.dumps(status, indent=2))
print(f"✓ status.json                 → {status_path}")

# ── Quick sanity check ────────────────────────────────────────────────────────
paid_total = contributions_df[contributions_df["channel_type"] == "paid"]["contribution"].sum()
organic_total = contributions_df[contributions_df["channel_type"] == "organic"]["contribution"].sum()
baseline_total = contributions_df[contributions_df["channel"] == "Baseline"]["contribution"].sum()
grand_total = paid_total + organic_total + baseline_total

print(f"\nAttribution split (should sum to ~$33.8M):")
print(f"  Paid media:   ${paid_total:>12,.0f}  ({paid_total/grand_total*100:.1f}%)")
print(f"  Organic:      ${organic_total:>12,.0f}  ({organic_total/grand_total*100:.1f}%)")
print(f"  Baseline:     ${baseline_total:>12,.0f}  ({baseline_total/grand_total*100:.1f}%)")
print(f"  Grand total:  ${grand_total:>12,.0f}")
print("\nSeed complete. Run: python app/app.py")
