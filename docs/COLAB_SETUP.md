# Running MMM on Google Colab

## Workflow overview

1. **Experiment locally** — iterate on priors, model spec, and diagnostics in the modeling notebook
2. **Save to config** — when happy, run the "Save settings" cell to write params to `configs/{client}.yaml`
3. **Push to GitHub** — Colab always clones fresh; unpushed changes will not be included
4. **Run on Colab** — open `notebooks/colab_runner.ipynb`, edit Cell 5, hit Run All
5. **Check results** — outputs land in BigQuery `mmm_results` dataset (project `moonride-491921`)

---

## One-time setup

Save your service account JSON to Google Drive at exactly this path:

```
MyDrive/mmm_secrets/service_account.json
```

Cell 3 of the runner notebook copies it from there into the cloned repo. You only need to do this once per Google account.

---

## Step 1 — Experiment in the modeling notebook

Work in the appropriate notebook:
- **Northspore:** `notebooks/modeling/NorthSpore/northspore_model.ipynb`
- **Freedom Power:** `notebooks/modeling/Freedom_Power/Freedom_Power_model.ipynb`

Test priors, inspect convergence diagnostics, and iterate on the model spec here. Do not write production outputs from these notebooks — that's `scripts/run_model.py`'s job.

---

## Step 2 — Run the save-to-config cell

When you're satisfied with the model configuration, scroll to the bottom of the modeling notebook and run the **"Save settings to configs/{client}.yaml"** cell. It captures:

- MCMC settings (chains, adapt, burnin, keep) for both dev and prod modes
- Prior parameters per channel (ROI ranges or contribution targets)
- ModelSpec parameters (knots, max_lag, adstock, media_effects_dist)
- Control variables

It writes these to `configs/{client}.yaml` and prints a confirmation.

---

## Step 3 — Push to GitHub

```bash
git add configs/NorthSpore.yaml   # or Freedom_Power.yaml
git commit -m "update northspore config"
git push
```

Colab clones fresh from `main` on every run. If you skip the push, the Colab run uses the previous config.

---

## Step 4 — Open colab_runner.ipynb in Colab

**Option A — from GitHub (recommended):**
1. Go to [colab.research.google.com](https://colab.research.google.com)
2. File → Open notebook → GitHub tab
3. Paste: `https://github.com/Russ-Moonride/Meridian-MMM-System`
4. Select `notebooks/colab_runner.ipynb`

**Option B — upload to Drive:**
1. Upload `notebooks/colab_runner.ipynb` to your Google Drive
2. Double-click it — Colab opens automatically

**Edit Cell 5** with the target client and mode:
```python
CLIENT = "northspore"   # matches a file in configs/
MODE = "prod"           # "dev" for fast iteration, "prod" for full sampling
```

Then: **Runtime → Run all** (Ctrl+F9)

---

## Monitoring the run

- Cell 5 streams `run_model.py` stdout directly in the notebook output.
- MCMC progress is printed per chain. A full `prod` run takes ~30–45 minutes.
- Do not close the Colab tab during the run — the runtime will disconnect.
- To run unattended, keep the browser tab open, or enable Colab Pro background execution.

---

## After the run

- Cell 6 lists files written to `outputs/{CLIENT}/` and confirms the BigQuery write.
- Results land in BigQuery dataset `mmm_results` (project `moonride-491921`).
- If BigQuery write fails, outputs are still on Colab disk — download before the session expires.

---

## MCMC settings reference

| Mode | Chains | Adapt | Burnin | Keep | Typical runtime |
|---|---|---|---|---|---|
| `dev` | 1 | 200 | 200 | 200 | ~5 min |
| `prod` | 4 | 500 | 500 | 500 | ~30–45 min |

Settings are written to `configs/{client}.yaml` by the save-to-config cell — override them there.

---

## Local runs (debugging only)

Running `run_model.py` locally is only for debugging the script itself, not for normal workflow:

```bash
python scripts/run_model.py --client northspore --mode dev --no-bq
```
