# prior-sensitivity

## When to use this skill

Invoke when you are asked to:
- Run or interpret a prior sensitivity analysis on a fitted Meridian model
- Check whether model conclusions are prior-driven vs data-driven
- Determine which parameters are identifiable from the data
- Decide whether to tighten or loosen a prior based on evidence

This skill encodes a key finding: **in a well-specified multi-geo Meridian model, adstock_alpha is typically the only parameter at the prior-dependent boundary (~PSI 0.1). ROI posteriors are almost always data-driven (PSI > 0.2).** If ROI posteriors are prior-dependent, the model has a data quality or identifiability problem that must be fixed before results can be trusted.

---

## What prior sensitivity means in Bayesian MMM

Prior sensitivity answers: "If I had used a different prior, would my conclusions change?"

- **Data-driven** (PSI > 0.20): Posterior dominated by likelihood. Prior had little effect. Trustworthy.
- **Prior-dependent** (PSI ~0.10–0.20): Prior and data contribute roughly equally. Results depend on prior quality.
- **Prior-dominated** (PSI < 0.05): Posterior closely mirrors prior. Data has almost no signal for this parameter.

PSI (Population Stability Index):
```
PSI = Σ (posterior_pct_i - prior_pct_i) * ln(posterior_pct_i / prior_pct_i)
```
Computed over binned histogram buckets comparing marginal posterior vs prior distributions.

---

## Step 1 — Sample the prior

```python
from meridian.model import model

mmm = model.Meridian(input_data=data, model_spec=model_spec)

# Sample prior (pure prior predictive — no data used)
mmm.sample_prior(n_draws=1000, seed=42)

# Then sample posterior as usual
mmm.sample_posterior(
    n_chains=cfg["mcmc"]["prod"]["n_chains"],
    n_adapt=cfg["mcmc"]["prod"]["n_adapt"],
    n_burnin=cfg["mcmc"]["prod"]["n_burnin"],
    n_keep=cfg["mcmc"]["prod"]["n_keep"],
    seed=42,
)
```

If the model is already fitted (from pkl), re-sample the prior:
```python
import pickle

with open("outputs/northspore/model.pkl", "rb") as f:
    mmm = pickle.load(f)

mmm.sample_prior(n_draws=1000, seed=42)
# Posterior already in mmm.inference_data.posterior
```

---

## Step 2 — PSI computation utility

```python
import numpy as np

def compute_psi(prior_samples: np.ndarray, posterior_samples: np.ndarray, n_bins: int = 20) -> float:
    """
    Compute Population Stability Index between prior and posterior.

    PSI < 0.05   → prior-dominated  (data has almost no signal)
    PSI 0.05–0.10 → boundary zone   (prior and data roughly equal; normal for alpha_m)
    PSI 0.10–0.20 → prior-dependent (prior matters — scrutinize)
    PSI > 0.20   → data-driven      (posterior dominated by likelihood — good)
    """
    min_val = min(prior_samples.min(), posterior_samples.min())
    max_val = max(prior_samples.max(), posterior_samples.max())
    bins = np.linspace(min_val, max_val, n_bins + 1)

    prior_hist, _ = np.histogram(prior_samples,     bins=bins)
    post_hist,  _ = np.histogram(posterior_samples, bins=bins)

    eps = 1e-8
    prior_pct = prior_hist / (prior_hist.sum() + eps) + eps
    post_pct  = post_hist  / (post_hist.sum()  + eps) + eps

    return float(np.sum((post_pct - prior_pct) * np.log(post_pct / prior_pct)))


def _interpret_psi(psi: float) -> str:
    if psi < 0.05:
        return "prior-dominated"
    elif psi < 0.10:
        return "boundary"
    elif psi < 0.20:
        return "prior-dependent"
    else:
        return "data-driven"
```

---

## Step 3 — Run sensitivity across key parameters

```python
import pandas as pd

# Channel names from model spec
channels = list(mmm.input_data.paid_media_dim)

prior_ds    = mmm.inference_data.prior
posterior_ds = mmm.inference_data.posterior

results = []

# ── ROI (roi_m) — the most important to check ─────────────────────────────────
roi_prior = prior_ds.roi_m.values.reshape(-1, len(channels))
roi_post  = posterior_ds.roi_m.values.reshape(-1, len(channels))

for i, ch in enumerate(channels):
    psi = compute_psi(roi_prior[:, i], roi_post[:, i])
    results.append({"parameter": "roi_m", "channel": ch, "psi": round(psi, 4),
                    "interpretation": _interpret_psi(psi)})

# ── Adstock alpha (alpha_m) — expect PSI ~0.05–0.15 (boundary is normal) ──────
alpha_prior = prior_ds.alpha_m.values.reshape(-1, len(channels))
alpha_post  = posterior_ds.alpha_m.values.reshape(-1, len(channels))

for i, ch in enumerate(channels):
    psi = compute_psi(alpha_prior[:, i], alpha_post[:, i])
    results.append({"parameter": "alpha_m", "channel": ch, "psi": round(psi, 4),
                    "interpretation": _interpret_psi(psi)})

# ── EC half-saturation (ec_m) ─────────────────────────────────────────────────
if hasattr(prior_ds, "ec_m"):
    ec_prior = prior_ds.ec_m.values.reshape(-1, len(channels))
    ec_post  = posterior_ds.ec_m.values.reshape(-1, len(channels))
    for i, ch in enumerate(channels):
        psi = compute_psi(ec_prior[:, i], ec_post[:, i])
        results.append({"parameter": "ec_m", "channel": ch, "psi": round(psi, 4),
                        "interpretation": _interpret_psi(psi)})

psi_df = pd.DataFrame(results).sort_values(["parameter", "psi"])
print(psi_df.to_string(index=False))
```

---

## Step 4 — Expected findings and red flags

### Expected in a well-specified multi-geo model

| Parameter | Expected PSI | Notes |
|---|---|---|
| `roi_m` (all paid channels) | > 0.20 | Data-driven — good. If not, see red flags below. |
| `alpha_m` (adstock decay) | 0.05–0.15 | Boundary is normal. Uniform(0,1) prior is uninformative by design. |
| `ec_m` (half-saturation) | 0.10–0.25 | Partially data-driven; depends on spend variation. |
| `contribution_om` (organic) | < 0.10 | Often prior-dominated — organic signal is weak vs paid. |

**Key finding from Luca Fiaschi's MMM analysis**: In a multi-geo model with ~2 years weekly data, `adstock_alpha` was the **only** parameter at the prior-dependent boundary (~PSI 0.10). All ROI posteriors were data-driven (PSI > 0.20). The 20% ROAS floor was structural (data-driven), not prior-driven.

### Red flags

| Finding | Meaning | Action |
|---|---|---|
| ROI PSI < 0.10 for any channel with meaningful spend | Channel unidentifiable | Merge with related channel or drop. Check for collinearity or >90% zeros. |
| ROI PSI < 0.02 for any channel | Posterior = prior; zero data signal | Must merge or drop before client delivery. |
| `alpha_m` PSI > 0.30 | Data strongly informing decay | Verify alpha posterior isn't stuck at 0 or 1; check max_lag adequacy. |
| `ec_m` PSI < 0.05 | Saturation unidentified | All observed spend is well below saturation — curve is extrapolated, not estimated. Note in report. |

---

## Step 5 — Visual inspection

```python
from meridian.analysis import visualizer
import matplotlib.pyplot as plt

diag_viz = visualizer.ModelDiagnostics(mmm)
diag_viz.plot_prior_and_posterior_distribution()
plt.savefig(f"outputs/{client_id}/prior_posterior_overlay.png", dpi=150)
plt.show()

# Adstock decay: prior vs posterior
media_effects = visualizer.MediaEffects(mmm)
media_effects.plot_adstock_decay()
```

**What to look for:**
- Posterior narrower than prior → data is informative (good)
- Posterior shifted from prior → data contradicts prior (investigate; not inherently bad)
- Posterior ≈ prior in shape and location → data has no signal (channel problem)

---

## Step 6 — Robustness check for prior-dependent parameters

For any parameter flagged as "prior-dependent" (PSI 0.10–0.20), run a perturbation test:

```python
import tensorflow_probability as tfp
from meridian.model import prior_distribution, spec

# Test two alternative alpha priors against the baseline Uniform(0,1)
for label, alpha_prior in [
    ("fast-decay",  tfp.distributions.Beta(1.0, 3.0)),   # mean ~0.25
    ("slow-decay",  tfp.distributions.Beta(3.0, 1.0)),   # mean ~0.75
]:
    alt_prior_dist = prior_distribution.PriorDistribution(
        roi_m=roi_prior,          # hold ROI priors fixed
        alpha_m=alpha_prior,
    )
    alt_spec = spec.ModelSpec(
        prior=alt_prior_dist,
        knots=knots, max_lag=max_lag,
        adstock_decay_spec=adstock,
        media_prior_type="roi",
        media_effects_dist="log_normal",
    )
    mmm_alt = model.Meridian(input_data=data, model_spec=alt_spec)
    mmm_alt.sample_posterior(n_chains=1, n_adapt=200, n_burnin=200, n_keep=200, seed=42)

    alt_roi  = mmm_alt.inference_data.posterior.roi_m.values.reshape(-1, len(channels))
    base_roi = mmm.inference_data.posterior.roi_m.values.reshape(-1, len(channels))

    for i, ch in enumerate(channels):
        diff = abs(np.median(alt_roi[:, i]) - np.median(base_roi[:, i]))
        status = "⚠ SENSITIVE" if diff > 0.30 else "✓ robust"
        print(f"  {label} | {ch:<20} ROI diff = {diff:.3f}  {status}")
```

**If median ROI changes by > 0.30** under an alternative alpha prior, that channel's estimate is sensitive to adstock assumptions. Flag explicitly in the reviewer report and do not present that channel's ROI as a precise estimate.

---

## Step 7 — Report format

```python
# Summary for notebook record
sensitivity_summary = (
    psi_df.groupby("parameter")["psi"]
    .agg(["min", "mean", "max"])
    .round(3)
)
print("Prior Sensitivity Summary (PSI by parameter)")
print(sensitivity_summary)

# Channels at risk
roi_at_risk = psi_df[
    (psi_df["parameter"] == "roi_m") & (psi_df["psi"] < 0.15)
]["channel"].tolist()

if roi_at_risk:
    print(f"\n⚠  ROI posteriors prior-dependent: {roi_at_risk}")
    print("   → Do not report these with confidence intervals to clients.")
    print("   → Consider merging or applying a tighter, experiment-backed prior.")
else:
    print("\n✓  All ROI posteriors are data-driven (PSI > 0.15). Robust to prior specification.")
```

---

## Connection to program.md and reviewer

program.md encodes these PSI thresholds as reviewer criteria:
- ROI PSI < 0.10 → reviewer flags as **WARNING** (prior-dependent; note in client communication)
- ROI PSI < 0.02 → reviewer flags as **CRITICAL** (unidentifiable; block client delivery)
- alpha_m PSI in 0.05–0.15 → reviewer flags as **INFO** (expected; no action needed)

Run this skill after every prod Colab run and document results in the modeling notebook before sharing with clients.
