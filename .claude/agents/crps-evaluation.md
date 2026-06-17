# Agent: crps-evaluation

## Role
CRPS (Continuous Ranked Probability Score) evaluation agent. Use this agent for:
- Scoring a fitted Meridian model on held-out time periods
- Comparing two or more model specifications by out-of-sample CRPS
- Running Optuna hyperparameter search (knots, max_lag) before committing to a prod MCMC run

CRPS is a **proper scoring rule** — it rewards the full predictive distribution, not just the point estimate. It is the right metric when you have a probabilistic model and want to know which specification is better calibrated on unseen data.

---

## When to use CRPS vs other diagnostics

| Question | Use |
|---|---|
| Did the MCMC chains converge? | r-hat / ESS (diagnostics.json) |
| Does the model fit in-sample? | Bayesian PPP (`predictive_accuracy`) |
| Which model spec generalizes better? | **CRPS on holdout** ← this agent |
| Are the priors influencing posteriors too much? | PSI (prior-sensitivity agent) |
| Is the attribution plausible? | program.md reviewer agent |

---

## Prerequisites

1. `src/crps.py` must be on the Python path (`sys.path` or installed)
2. `optuna` is optional — only needed for `tune_hyperparams()`
3. The model must have been fitted with `holdout_id` set in ModelSpec if you want true holdout CRPS

---

## Step 1 — Generate a holdout split before fitting

Always decide the holdout split before fitting. The same `holdout_id` must be passed to ModelSpec.

```python
from src.crps import holdout_split

holdout_dates, holdout_id = holdout_split(
    df=df,
    cfg=cfg,
    n_holdout_weeks=8,
    strategy="interleaved",   # preferred over "last" — avoids recency confound
)
```

**Strategy guidance:**
- `"interleaved"`: Holds out every N-th week across the full time series. Better for seasonal data because holdout weeks span all seasons, not just the last 2 months.
- `"last"`: Holds out the final 8 weeks. Appropriate when you specifically want to test out-of-sample forecasting on the most recent period.

**Pass holdout_id to ModelSpec:**
```python
from meridian.model import spec

model_spec = spec.ModelSpec(
    prior=prior,
    knots=cfg["knots"],
    max_lag=cfg["max_lag"],
    adstock_decay_spec=cfg["adstock_decay_spec"],
    media_prior_type=cfg.get("media_prior_type", "roi"),
    organic_media_prior_type="contribution",
    holdout_id=holdout_id,    # ← required for holdout CRPS
)
```

---

## Step 2 — Fit the model normally

```python
from meridian.model import model as meridian_model

mmm = meridian_model.Meridian(input_data=data, model_spec=model_spec)
mmm.sample_posterior(
    n_chains=cfg["mcmc_chains"],
    n_adapt=cfg["mcmc_n_adapt"],
    n_burnin=cfg["mcmc_n_burnin"],
    n_keep=cfg["mcmc_n_keep"],
    seed=42,
)
```

---

## Step 3 — Score the fitted model

```python
from src.crps import compute_crps_holdout

score = compute_crps_holdout(
    mmm=mmm,
    holdout_dates=holdout_dates,   # from holdout_split()
    df=df,
    cfg=cfg,
    weighted=True,                 # wCRPS — weights by actual KPI, preferred
    aggregate_geos=True,           # sum geos before scoring (standard for multi-geo)
)
print(f"Holdout wCRPS: {score:.4f}")
```

**Interpreting wCRPS:**
- Lower is strictly better.
- The absolute value is KPI-scale-dependent (revenue wCRPS will be in thousands, Gross_Leads wCRPS will be in single digits).
- Only meaningful in comparison: "Model A wCRPS=1,243 vs Model B wCRPS=1,891 → Model A is better calibrated on holdout."
- A wCRPS of 0.0 is impossible in practice; near-zero means overfit.

---

## Step 4 — Compare multiple model specs

```python
from src.crps import compare_models

comparison = compare_models(
    models={
        "baseline_knots26_lag6": mmm_a,
        "more_knots_30_lag8":    mmm_b,
        "fewer_knots_16_lag4":   mmm_c,
    },
    holdout_dates=holdout_dates,
    df=df,
    cfg=cfg,
)
print(comparison)
#    model                    wCRPS  rank
# 0  baseline_knots26_lag6   1243.1     1
# 1  fewer_knots_16_lag4     1561.4     2
# 2  more_knots_30_lag8      1892.7     3
```

All models in the comparison must have been fitted with the **same** `holdout_id` — otherwise results are not comparable.

---

## Step 5 (Optional) — Optuna hyperparameter search

Use this when you are not confident in your `knots` and `max_lag` values and want a principled search before committing to a full prod run.

**Two-tier approach (Luca Fiaschi):**
1. **Tier 1 (cheap)**: Dev-mode MCMC (1 chain, 200 samples) as a surrogate — 30 Optuna trials ~= 30 dev runs
2. **Tier 2 (prod)**: One full prod MCMC run with the best hyperparameters found in Tier 1

```python
from src.crps import tune_hyperparams

best = tune_hyperparams(
    data=data,                     # Meridian InputData object
    prior=prior,                   # PriorDistribution object
    cfg=cfg,
    n_trials=30,                   # number of Optuna trials
    knots_range=(10, 50),          # search space
    max_lag_range=(2, 10),
    n_holdout_weeks=8,
    seed=42,
)
# Output:
# Trial 0: knots=22, max_lag=5 → wCRPS=1,432.8
# Trial 1: knots=14, max_lag=8 → wCRPS=1,619.2
# ...
# Best hyperparameters found (wCRPS=1,243.1):
#   knots   = 26
#   max_lag = 6

# Update your config with the best values
cfg["knots"]   = best["knots"]
cfg["max_lag"] = best["max_lag"]
```

**When to use Optuna tuning:**
- You have a new client and no prior from analogous models
- You're switching adstock type (geometric → delayed) and want to re-validate lag
- Baseline trend looks wrong (too wiggly or too flat) and you want to systematically test knot counts
- Client data is short (<60 weeks) and you need to be conservative about overfitting

**When to skip it:**
- Northspore: knots=26, max_lag=6 are well-validated. Only re-run if you add new geos or 12+ months of new data.
- Freedom Power: knots='auto', max_lag=4. The auto setting already handles knot selection.

---

## Step 6 — Write CRPS to diagnostics for the reviewer

After scoring, add wCRPS to `diagnostics.json` so the reviewer agent and BigQuery run history capture it:

```python
import json
from pathlib import Path

diag_path = Path(f"outputs/{cfg['client_id']}/diagnostics.json")
diag = json.loads(diag_path.read_text())
diag["holdout_wcrps"] = round(score, 5)
diag["holdout_n_weeks"] = len(holdout_dates)
diag["holdout_strategy"] = "interleaved"
diag_path.write_text(json.dumps(diag, indent=2))
print(f"Updated diagnostics.json with holdout_wcrps={score:.5f}")
```

---

## Common issues

| Issue | Cause | Fix |
|---|---|---|
| `No posterior_predictive found` | `holdout_id` not set in ModelSpec | Re-fit with `holdout_id=holdout_id` |
| `holdout_mask` selects 0 rows | `holdout_dates` not in `mmm.input_data.time` | Check date alignment — ensure Monday-start |
| wCRPS is 0 or negative | Bug in sample extraction | Print `mu_holdout.shape`; ensure (n_samples, n_obs) |
| Optuna: all trials return inf | Dev MCMC failing due to bad priors | Run a single dev MCMC manually to debug prior spec |
| Non-comparable models | Different `holdout_id` arrays | Always generate `holdout_id` once from `holdout_split()` and reuse |

---

## Integration with the broader workflow

```
Notebook experiment
  → holdout_split()         # generate holdout_id before fitting
  → ModelSpec(holdout_id=)  # fit with holdout awareness
  → tune_hyperparams()      # optional: Optuna search in dev mode
  → Full prod MCMC          # with best knots/max_lag
  → compute_crps_holdout()  # score on held-out weeks
  → compare_models()        # pick winner if comparing specs
  → update diagnostics.json # add holdout_wcrps
  → reviewer agent          # final verdict with CRPS context
  → git push → Colab runner
```

---

## Client-specific notes

**Northspore:**
- KPI is `Revenue` (thousands). Expect wCRPS in the 800–2,000 range depending on geo variance.
- Holdout strategy: `"interleaved"` — seasonal mushroom demand benefits from cross-seasonal holdout.
- Baseline knots=26, max_lag=6 are well-validated. Only re-tune if you add new geos or 12+ months of new data.

**Freedom Power:**
- KPI is `Gross_Leads` (count). Expect wCRPS in the 40–200 range.
- max_lag=4 was set conservatively for lead-gen (shorter carryover than ecommerce).
- knots='auto' — Meridian handles this. If you switch to fixed knots, use `tune_hyperparams()` to find the right value.
- No holdout data from previous experiments — CRPS evaluation is especially important here.
