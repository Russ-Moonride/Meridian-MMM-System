# meridian-mmm

## When to use this skill

Invoke whenever you are asked to:
- Build or iterate on a Meridian MMM model
- Set or adjust priors for any client
- Interpret convergence diagnostics (r-hat, ESS, PPP)
- Debug a model that failed to converge or produced implausible ROIs
- Extract contributions, ROI, baseline from a fitted model
- Run or interpret budget optimization
- Propose ModelSpec changes (knots, max_lag, adstock decay)
- Assess prior-posterior shift for any channel

This skill takes agent correctness from ~0% to ~70% on hard Bayesian modeling problems. Read it fully before writing a single line of model code.

---

## Environment invariants — never change these

```python
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # CPU-only; Meridian runs on CPU via MCMC

import tensorflow as tf
tf.get_logger().setLevel("ERROR")
```

All tensors must be **float32** before passing to Meridian. Use `df = df.astype({col: "float32"})` on all numeric columns.

---

## Step 1 — Data preparation

### Monday alignment (mandatory)
Meridian requires dates to be Monday-aligned. If dates are not already Monday-aligned, shift them:

```python
import pandas as pd

df["date"] = pd.to_datetime(df["date"])
df["date"] = df["date"] - pd.to_timedelta(df["date"].dt.dayofweek, unit="D")
assert (df["date"].dt.dayofweek == 0).all(), "Dates must be Monday-aligned"
```

### Gap filling for multi-geo data
After filtering to active geos, fill missing weeks per geo with zeros for media columns and forward-fill for controls:

```python
all_dates = pd.date_range(df["date"].min(), df["date"].max(), freq="W-MON")
all_geos = df["geo"].unique()
full_index = pd.MultiIndex.from_product([all_geos, all_dates], names=["geo", "date"])
df = df.set_index(["geo", "date"]).reindex(full_index).reset_index()

media_cols = [c for c in df.columns if c.endswith("_Cost") or c.endswith("_Impressions")]
df[media_cols] = df[media_cols].fillna(0)

control_cols = ["weekly_average_temp", "weekly_rainfall", "Promo Intensity", "population"]
df[control_cols] = df.groupby("geo")[control_cols].transform(lambda x: x.ffill().bfill())
```

### Feature engineering
```python
# Black Friday indicator — applies to week containing the 4th Thursday of November
def black_friday_indicator(date_series):
    flags = []
    for d in date_series:
        d = pd.Timestamp(d)
        nov = pd.date_range(f"{d.year}-11-01", f"{d.year}-11-30", freq="D")
        thursdays = nov[nov.dayofweek == 3]
        bf = thursdays[3]  # 4th Thursday
        week_start = bf - pd.Timedelta(days=bf.dayofweek)
        flags.append(1 if week_start == d else 0)
    return flags

df["black_friday"] = black_friday_indicator(df["date"])
```

### Cast to float32 (mandatory)
```python
numeric_cols = df.select_dtypes("number").columns.tolist()
df[numeric_cols] = df[numeric_cols].astype("float32")
```

---

## Step 2 — Build InputData via DataFrameInputDataBuilder

Meridian's `DataFrameInputDataBuilder` is the only sanctioned way to construct `InputData` from a DataFrame. Read config from `configs/{client_id}.yaml` before building.

```python
from meridian.data.builder import DataFrameInputDataBuilder
import yaml

with open(f"configs/{client_id}.yaml") as f:
    cfg = yaml.safe_load(f)

channels    = cfg["channels"]
organic_chs = cfg.get("organic_channels", [])
controls    = cfg["controls"]
kpi_col     = cfg["kpi_column"]
date_col    = cfg["date_column"]
geo_col     = cfg["geo_column"]
pop_col     = cfg["population_column"]

# Date filter
if "start_date" in cfg:
    df = df[df[date_col] >= cfg["start_date"]]
if "end_date" in cfg:
    df = df[df[date_col] <= cfg["end_date"]]

# Drop inactive geos
if cfg.get("geos_to_drop"):
    df = df[~df[geo_col].isin(cfg["geos_to_drop"])]

# Organic column naming — default is {channel}_Views; override via organic_cols in config
organic_media_cols = [
    cfg.get("organic_cols", {}).get(c, f"{c}_Views") for c in organic_chs
]

builder = DataFrameInputDataBuilder(
    df=df,
    kpi_col=kpi_col,
    date_col=date_col,
    geo_col=geo_col,
    population_col=pop_col,
    paid_media_cols=[f"{c}_Impressions" for c in channels],  # impressions NOT spend
    paid_media_spend_cols=[f"{c}_Cost" for c in channels],   # spend alongside
    organic_media_cols=organic_media_cols,
    controls_cols=controls,
)
data = builder.build()
```

**Critical naming rule**: `paid_media_cols` takes **impressions**, `paid_media_spend_cols` takes **cost**. Swapping these is a silent error that produces nonsensical ROI.

**Population scaling**: Meridian automatically applies geo-level population scaling to the KPI using `population_col`. The population column must be constant per geo across time.

**Automated data checks on `builder.build()`:**
- Pairwise correlation > 0.999 between any two media channels → **ERROR** (collinearity)
- VIF > 1000 for any predictor → **ERROR** (multicollinearity)

If you hit either error, merge offending channels or drop the weaker one. Never proceed past a collinearity error.

---

## Step 3 — Prior specification

Prior type is set in `configs/{client_id}.yaml` under `prior_type`. Two patterns:

### Pattern A: ROI priors (Northspore — revenue KPI)

Use `lognormal_dist_from_range(low, high, mass_percent)` to convert a 95% CI range into a LogNormal distribution.

```python
import tensorflow_probability as tfp
from meridian.model import prior_distribution, spec

roi_ranges = cfg["prior_roi_ranges"]       # dict: {channel: [low, high]}
mass_pct   = cfg.get("prior_roi_mass_percent", 0.95)

lows  = [roi_ranges[ch][0] for ch in channels]
highs = [roi_ranges[ch][1] for ch in channels]

roi_prior = prior_distribution.lognormal_dist_from_range(
    low=lows, high=highs, mass_percent=mass_pct
)
prior = prior_distribution.PriorDistribution(roi_m=roi_prior)
```

**Channel archetype ROI range reference (95% CI):**

| Channel type | Low | High | Notes |
|---|---|---|---|
| Brand search | 1.3 | 10.6 | High ROI, branded intent |
| Non-brand search | 1.8 | 7.7 | Moderate; competitive |
| Retargeting | 1.3 | 12.4 | Highly variable |
| Prospecting | 0.8 | 6.0 | Widest uncertainty; lower floor |
| Shopping | 2.0 | 7.9 | Product-feed driven |
| Performance Max | 1.0 | 6.0 | Opaque; weakly informative |
| TikTok / social | 2.0 | 4.5 | Tight if sporadic spend |
| DVD / direct mail | 1.3 | 12.3 | Long tail; can be high |

**Negative baseline guard**: The 90th percentile ROI prior for any channel must NOT imply that channel drives >100% of total revenue. Check:
```python
# For each channel ch:
roi_90pct = prior_distribution.lognormal_dist_from_range(low, high, 0.95).quantile(0.90)
channel_spend = df[f"{ch}_Cost"].sum()
total_revenue = df[kpi_col].sum()
assert roi_90pct * channel_spend / total_revenue < 1.0, f"{ch} prior too wide — implies >100% revenue"
```

### Pattern B: Contribution priors (Freedom Power — non-revenue KPI, no holdouts)

Use when KPI is not revenue AND you lack channel-level ROAS holdout tests.

```python
total_contrib = cfg["total_media_contribution"]   # e.g. 0.60
shares        = cfg["channel_media_shares"]        # dict: {channel: share}
conc_default  = cfg.get("concentration_default", 20.0)

scale_factor = total_contrib / sum(shares.values())

concentration1_list = []
concentration0_list = []
for ch in channels:
    share = shares.get(ch, 0.01)
    mean_contrib = share * scale_factor
    conc_key = f"concentration_{ch.lower()}"
    concentration = cfg.get(conc_key, conc_default)
    alpha = mean_contrib * concentration
    beta  = (1.0 - mean_contrib) * concentration
    concentration1_list.append(alpha)
    concentration0_list.append(beta)

contribution_prior = tfp.distributions.Beta(
    concentration1=concentration1_list,
    concentration0=concentration0_list,
)
prior = prior_distribution.PriorDistribution(contribution_m=contribution_prior)
```

**When to use contribution vs ROI priors:**
- Revenue KPI + holdout data → ROI priors (LogNormal from range)
- Revenue KPI + no holdouts → ROI priors with archetype defaults
- Non-revenue KPI + no holdouts → Contribution priors (Beta mode)
- Non-revenue KPI + `revenue_per_kpi` known → Pass to InputData, then use ROI priors

**Never mix** `media_prior_type='roi'` with `contribution_m` in the same PriorDistribution — the non-matching argument is silently ignored.

### Organic channel priors

Default Beta(1, 99) = 1% mean. Loosen if organics are a known major driver:

```python
organic_prior = tfp.distributions.Beta(
    concentration1=[3.0] * len(organic_chs),
    concentration0=[97.0] * len(organic_chs),
)
prior = prior_distribution.PriorDistribution(
    roi_m=roi_prior,
    contribution_om=organic_prior,
)
```

---

## Step 4 — ModelSpec

```python
from meridian.model import spec

# Resolve 'auto' knots
n_times = int(df[date_col].nunique())
knots_cfg = cfg.get("knots", 26)
knots = (n_times // 2) if knots_cfg == "auto" else int(knots_cfg)

max_lag = cfg.get("max_lag", 6)
adstock  = cfg.get("adstock_decay_spec", "geometric")
prior_type = cfg.get("media_prior_type", "roi")

model_spec = spec.ModelSpec(
    prior=prior,
    knots=knots,
    max_lag=max_lag,
    adstock_decay_spec=adstock,
    media_prior_type=prior_type,          # 'roi' | 'mroi' | 'contribution' | 'coefficient'
    rf_prior_type=prior_type,             # match paid type
    organic_media_prior_type="contribution",  # always contribution for organic
    media_effects_dist="log_normal",      # do not change
)
```

### Knot selection rules

| Model type | Start | When to reduce |
|---|---|---|
| Geo-level (G > 1) | `n_times` (one per week) | Overfitting evident; few geos per time period |
| National (G = 1) | 1 | Increase until estimates become unrealistic |

Northspore: `knots=26` ≈ one every 4 weeks for a 2-year series — good balance.
Freedom Power: `knots='auto'` → `n_weeks // 2` is reasonable.

**Do NOT use `enable_aks=True` together with an explicit `knots` argument** — mutually exclusive.

### max_lag rules

| Adstock | Range | Notes |
|---|---|---|
| `geometric` | 2–10 weeks | Decays fast; 6 is good default for digital |
| `binomial` | 4–20 weeks | Use when effects persist into latter half of window |

Northspore: `max_lag=6` (geometric). Freedom Power: `max_lag=4` (digital-heavy).

If carryover plots still show heavy tail at `max_lag`, bump by 2 and re-run.

### Per-channel adstock override

```python
adstock_spec = {
    "Brand":     "geometric",
    "Non_Brand": "geometric",
    "DVD":       "binomial",   # direct mail; longer tail
}
model_spec = spec.ModelSpec(..., adstock_decay_spec=adstock_spec)
```

---

## Step 5 — Fit the model

```python
from meridian.model import model

mmm = model.Meridian(input_data=data, model_spec=model_spec)

mode = "dev"  # "dev" for iteration; "prod" for client delivery
mcmc_cfg = cfg["mcmc"][mode]

mmm.sample_posterior(
    n_chains=mcmc_cfg["n_chains"],
    n_adapt=mcmc_cfg["n_adapt"],
    n_burnin=mcmc_cfg["n_burnin"],
    n_keep=mcmc_cfg["n_keep"],
    seed=42,
)
```

**Dev mode** (1 chain, 200/200/200): ~5 min. `converged=False` is expected. Do not report dev results to clients.

**Prod mode** (4 chains, 500/500/500): 30–45 min on Colab. Only prod runs generate trustworthy r-hat.

Production runs happen via Colab (`notebooks/colab_runner.ipynb`), not locally.

---

## Step 6 — Post-modeling diagnostics

### 6a. Convergence (r-hat and ESS)

```python
import arviz as az
import numpy as np

# Check beta_m (media coefficients) and roi_m
diag_sum = az.summary(mmm.inference_data, var_names=["roi_m", "beta_m"], round_to=4)
rhat_max  = diag_sum["r_hat"].max()
ess_min   = diag_sum["ess_bulk"].min()

print(f"max r-hat: {rhat_max:.4f}  |  min ESS: {ess_min:.0f}")
```

**Thresholds:**

| Metric | Pass | Warning | Fail — block client delivery |
|---|---|---|---|
| max r-hat | < 1.01 | 1.01–1.05 | > 1.10 |
| min ESS bulk | ≥ 400 | 200–399 | < 100 |

Meridian's own `ModelReviewer` uses r-hat < 1.2. This repo targets r-hat < 1.05 before client delivery.

**Fix convergence failures in this order:**
1. Check collinearity (`VIF`, pairwise correlation) — #1 cause
2. Increase `n_adapt + n_burnin` (try 1000/1000)
3. Tighten priors on sparse channels
4. Reduce `knots` (too many → weak identifiability with few geos)
5. Check for channels with >90% zeros — merge or drop

### 6b. Automated quality checks

```python
from meridian.analysis.review import reviewer

report = reviewer.ModelReviewer(mmm).run()
```

| Check | Pass | Review | Fail |
|---|---|---|---|
| Convergence (max r-hat) | < 1.2 | — | ≥ 1.2 |
| Negative baseline prob | < 0.2 | 0.2–0.8 | > 0.8 |
| Bayesian PPP | ≥ 0.05 | — | < 0.05 |
| R-squared | > 0 | ≤ 0 | — |
| Prior-posterior shift | All shifted | Any channel no shift | — |
| ROI consistency | Within 1st–99th pct | Outside 1st/99th pct | — |

**Negative baseline > 0.8 (FAIL):** Media over-credited. Fix:
- Tighten ROI prior upper bounds
- Add missing confounders as controls
- Increase `knots` to capture organic time trend (prevents media absorbing it)

**PPP < 0.05 (FAIL):** Fundamental misspecification. Check:
- Missing confounder (GQV for paid search; temperature for seasonal products)
- Wrong adstock function
- Data anomaly not caught by EDA (spike, structural break)

**No prior-posterior shift (REVIEW):** Channel unidentified by data. Options:
- Accept (prior is doing its job; reasonable if prior is well-founded)
- Merge sparse channel with a related one
- Drop as last resort

**ROI outside prior tails (REVIEW):** Data contradicts prior. Investigate channel mapping, data anomalies, or prior miscalibration.

### 6c. Visual diagnostics

```python
from meridian.analysis import visualizer

diag_viz = visualizer.ModelDiagnostics(mmm)

# Prior vs posterior overlay for each channel
diag_viz.plot_prior_and_posterior_distribution()

# Adstock decay curves (prior vs posterior)
media_effects = visualizer.MediaEffects(mmm)
media_effects.plot_adstock_decay()

# Hill saturation curves
media_effects.plot_hill_curves()
```

Always run `plot_prior_and_posterior_distribution()` after every prod fit. Channels where posterior ≈ prior are unidentified.

### 6d. Raw posterior access

```python
# Adstock decay alpha per channel — posterior mean
alpha_mean = np.mean(mmm.inference_data.posterior.alpha_m, axis=(0, 1))

# ROI probability > 1.0 per channel
roi_m = mmm.inference_data.posterior.roi_m
prob_roi_gt1 = (roi_m >= 1.0).mean(dim=("chain", "draw"))

# 90th percentile CI for any parameter
from meridian.analysis import analyzer
ci = analyzer.Analyzer.get_central_tendency_and_ci(
    mmm.inference_data.posterior.roi_m, 0.90
)
```

---

## Step 7 — Extract outputs via Analyzer

Use `src/utils.py::extract_outputs()` — do not reinvent this. It correctly calls `Analyzer` and writes `contributions.csv`, `diagnostics.json`, `status.json`, `geo_summary.csv`, `model.pkl`.

```python
import yaml
from pathlib import Path
from src.utils import extract_outputs

with open(f"configs/{client_id}.yaml") as f:
    cfg = yaml.safe_load(f)

mode = "prod"
mcmc_cfg = cfg["mcmc"][mode]
run_id = f"{mode}_{pd.Timestamp.now().strftime('%Y-%m-%d')}"
out_dir = Path(cfg["output_path"])

results = extract_outputs(
    mmm=mmm, df=df, config=cfg,
    run_id=run_id, mcmc=mcmc_cfg, out_dir=out_dir,
)
contributions_df = results["contributions_df"]
diagnostics      = results["diagnostics"]
```

### Direct Analyzer calls (ad-hoc analysis)

```python
from meridian.analysis import analyzer

m_analyzer = analyzer.Analyzer(mmm)

# Aggregate ROI summary (all geos + time)
agg = m_analyzer.summary_metrics(
    aggregate_geos=True, aggregate_times=True, use_kpi=True
)
agg_df = agg.to_dataframe().reset_index()
# Key cols: channel, metric (median/ci_lo/ci_hi), distribution (posterior), roi, incremental_outcome

# Time-series by channel
ts = m_analyzer.summary_metrics(
    aggregate_geos=True, aggregate_times=False,
    use_kpi=True, include_non_paid_channels=True,
)
brand_weekly = ts["incremental_outcome"].sel(
    channel="Brand", metric="median", distribution="posterior"
).values

# Baseline time series
eva = m_analyzer.expected_vs_actual_data(
    aggregate_geos=True, aggregate_times=False, use_kpi=True
)
baseline_vals = eva["baseline"].sel(metric="mean").values

# Negative baseline probability
neg_prob = m_analyzer.negative_baseline_probability()

# Fit metrics
fit_metrics = m_analyzer.predictive_accuracy()   # R2, MAPE, wMAPE

# Response curves
rc = m_analyzer.response_curves()

# Marginal ROI
mroi = m_analyzer.marginal_roi(aggregate_geos=True, aggregate_times=True, use_kpi=True)

# Geo-level summary
geo_metrics = m_analyzer.summary_metrics(aggregate_geos=False, use_kpi=True)
geo_df = geo_metrics.to_dataframe().reset_index()
```

---

## Step 8 — Budget optimization

```python
from meridian.analysis import optimizer as opt

budget_optimizer = opt.BudgetOptimizer(mmm)

# Fixed budget scenario
current_spend = df[[f"{c}_Cost" for c in channels]].sum().sum()

optimized = budget_optimizer.optimize(
    budget=current_spend,
    target_roi=None,    # None = maximize revenue at fixed budget
)
opt_df = optimized.to_dataframe()
print(opt_df[["channel", "optimized_spend", "optimized_pct_of_budget", "optimized_incremental_outcome"]])

# Flexible budget (target ROI)
optimized = budget_optimizer.optimize(target_roi=2.0)

# Per-channel constraints
budget_range = {
    "Brand": (0.5, 1.5),     # 50%–150% of historical spend
    "DVD":   (0.8, 1.0),
}
optimized = budget_optimizer.optimize(budget=current_spend, budget_range=budget_range)
```

**When to trust optimization:**
- r-hat < 1.05 on all channels ✓
- Negative baseline probability < 0.2 ✓
- No prior-posterior collapse on major channels ✓
- Response curves are concave (guaranteed when `slope_m = Deterministic(1)`, the default)

**Block optimization output when:**
- Dev run (1 chain)
- Any FAIL on convergence or negative baseline
- Freedom Power: until first full prod run completes

---

## Step 9 — Iteration guide

After a dev run, work through this checklist before requesting a prod Colab run:

**Convergence:**
- [ ] r-hat > 1.05 on any channel → tighten that channel's prior or reduce knots
- [ ] ESS < 200 → increase n_burnin to 500 minimum
- [ ] r-hat > 1.2 → block prod run; fix first

**Attribution sanity:**
- [ ] Baseline < 30% → paid media over-credited; tighten priors or add controls
- [ ] Baseline > 75% → paid media under-credited; widen priors or check for missing channels
- [ ] Any channel ROI posterior median > 20 → implausible; tighten upper bound of prior range
- [ ] Any single channel contribution_pct > 40% → verify with client spend data

**Client-specific expected ranges:**

Northspore (revenue KPI):
- Baseline: 35–60%
- Shopping + Non_Brand typically highest ROI channels
- DVD: high uncertainty, wide CI acceptable
- Prospecting: ROI likely below Brand/Non_Brand based on holdout

Freedom Power (lead KPI):
- Baseline: 40–60%
- Prospecting + Non_Brand highest contribution shares (~16% + ~15%)
- Billboard and Reddit likely unidentified in first runs (check prior-posterior overlap)
- If Reddit posterior ≈ prior, note in diagnostic report — do not report Reddit ROI to client

**Prior adjustment workflow:**
1. Posterior median > prior 99th pct → data wants higher value; widen the prior range upper bound
2. Posterior ≈ prior → no data signal; leave prior in place
3. Posterior median < prior 1st pct → data wants lower value; lower the prior mean

---

## Step 10 — Committing results for Colab run

```python
# "Save settings" cell at bottom of modeling notebook
import yaml, copy

current_config = copy.deepcopy(cfg)
current_config["knots"] = knots              # update if changed interactively
current_config["max_lag"] = max_lag
# Update prior ranges if adjusted:
# current_config["prior_roi_ranges"] = roi_ranges

with open(f"configs/{client_id}.yaml", "w") as f:
    yaml.dump(current_config, f, default_flow_style=False, sort_keys=False)

print(f"Config saved → commit and push before triggering Colab run")
```

Then: `git push` → open `notebooks/colab_runner.ipynb` → set `CLIENT` and `MODE` → Run All.

**Never** run `scripts/run_model.py` locally for production. Always use Colab.

---

## Common errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `ValueError: Pairwise correlation > 0.999` | Two channels near-identical | Merge or drop weaker channel |
| `MCMC chain divergence` | Prior too uninformative or data too sparse | Tighten prior; check for 100% zeros |
| Negative baseline probability > 0.8 | Media over-credited | Tighten ROI upper bounds; add confounders |
| ROI posterior = prior (no shift) | Sparse channel | Accept, or merge channel |
| `sample_posterior` hangs > 60 min on Colab | Too many knots or max_lag | Reduce knots; reduce max_lag; use geometric |
| `InvalidArgumentError: NaN` during MCMC | Float64 tensor in graph | Ensure all numeric cols are `float32` |
| `AttributeError: NoneType has no .values` on Analyzer | `use_kpi=True` without `revenue_per_kpi` | Use `use_kpi=False` or pass `revenue_per_kpi` to InputData |

---

## Out of scope for this skill

- PyMC-Marketing (different framework; future scope)
- Reach and frequency channels (neither client has R&F data currently)
- Optuna hyperparameter optimization for knots/max_lag (see Luca Fiaschi blog post — future)
- Vertex AI compute migration (see `future/README.md`)
- Last-touch attribution comparison (future item)

For Dash app, BigQuery writes, and GCS upload, see `scripts/run_model.py` and `src/utils.py`.
