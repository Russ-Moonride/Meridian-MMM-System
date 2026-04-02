# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Bayesian Marketing Mix Modeling (MMM)** project for Northspore (a mushroom cultivation company), built on Google's **Meridian** library. The goal is to estimate channel-level ROI across paid and organic marketing channels and provide budget reallocation recommendations to maximize revenue.

## Environment Setup

- Python 3.11.15 (Homebrew), venv at `.venv/`
- Activate: `source .venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`
- Key dependencies: TensorFlow 2.20.0, tfp-nightly, pandas 2.3.3, arviz 0.19.0

```bash
# Launch the main modeling notebook
jupyter notebook notebooks/modeling/northspore_model.ipynb
```

GPU is intentionally disabled in the notebook (`CUDA_VISIBLE_DEVICES=""`); Meridian runs on CPU via MCMC sampling.

## Architecture

All functional code currently lives in `notebooks/modeling/northspore_model.ipynb`. The `src/` modules (`data_prep.py`, `model_config.py`, `utils.py`) are empty placeholders intended for future refactoring.

**Modeling pipeline:**
1. **Data ingestion** — load `data/raw/northspore/NS_mmm_data_Mar26.csv` (weekly, multi-geo)
2. **Data alignment** — build a complete date × geo multi-index to fill gaps
3. **Feature engineering** — Black Friday indicator, weekly aggregation, float32 casting
4. **Meridian input builder** — `DataFrameInputDataBuilder` assembles:
   - KPI: `Revenue`
   - Paid media channels (7): Brand, Non-Brand, DVD, Retargeting, Prospecting, Shopping, Amazon — with both `_Cost` and `_Impressions` columns
   - Organic channels (3): `Facebook_Views`, `Instagram_Views`, `YouTube_Views`
   - Controls: `black_friday`, `Promo Intensity`, `weekly_average_temp`, `weekly_rainfall`
   - Population: geo-level `population`
5. **Priors** — `LogNormal` ROI priors per channel; Prospecting has a tighter prior (mean=1.5, scale=0.5) based on a holdout test
6. **ModelSpec** — 26 knots for baseline trend, 6-week max lag, geometric adstock decay
7. **Inference** — Meridian runs MCMC (TensorFlow Probability)
8. **Outputs** — ROI estimates, geo-level maps (PNG + interactive HTML), budget optimization tables

## Data

- **Raw data:** `data/raw/northspore/NS_mmm_data_Mar26.csv`
  - Weekly rows, Monday-aligned dates, 2024-01-01 → 2026-03-31
  - Multiple US states as `geo` column
- Data and output files are in `.gitignore` — do not commit them

## Key Conventions

- All media spend/impression columns follow `{Channel}_Cost` / `{Channel}_Impressions` naming
- Dates must be aligned to Monday-start weeks before passing to Meridian
- All tensors cast to `float32` for TF compatibility
- Outputs go to `outputs/northspore/`; configs go to `configs/`

## Development workflow

- **Local dev:** Run notebook with reduced sampling for fast iteration
  - `n_chains=1, n_adapt=200, n_burnin=200, n_keep=200`
- **Production:** Push to Colab for full sampling
  - `n_chains=4, n_adapt=500, n_burnin=500, n_keep=500`
- Never commit data files or model outputs (see .gitignore)