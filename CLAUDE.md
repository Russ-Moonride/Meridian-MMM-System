# CLAUDE.md

This file provides guidance to Claude Code when working in this repository. Read this fully before taking any action.

---

## Project overview

This is a **Bayesian Marketing Mix Modeling (MMM) workbench** built on Google's Meridian library. The goal is not a fully automated pipeline — it is a coherent system that makes the analyst (Russ) faster, more organized, and able to serve more clients without losing the judgment and stakeholder collaboration that makes MMM valuable.

The current client is **Northspore**, a mushroom cultivation company. The system is designed to scale to multiple clients using per-client config files.

---

## What this system is and is not

**It is:**
- A workbench for running, evaluating, and presenting MMM results
- A config-driven system where each client has their own settings, priors, and data paths
- A place where Claude Code is used heavily for EDA, model evaluation, iteration, and refactoring
- An app-first system — results live in a Dash app, not scattered plot files

**It is not:**
- A fully automated pipeline that runs without human involvement
- A system that makes modeling decisions autonomously
- Production infrastructure — this is an internal analyst tool

---

## Current state of the repo

```
mmm-workspace/
  configs/
    Freedom_Power.yaml        ← EMPTY — needs to be filled in
  notebooks/
    modeling/
      NorthSpore/
        northspore_model.ipynb   ← main working notebook (Northspore)
      Freedom_Power/
        Freedom_Power_model.ipynb ← second client notebook
    eda/
      Freedom_Power/           ← empty, EDA not started
  data/
    raw/
      northspore/              ← NS_mmm_data_Mar26.csv (gitignored)
      Freedom_Power/           ← Freedom_MMM_data_Mar26.csv (gitignored)
    processed/
      Freedom_Power/           ← empty
  src/
    data_prep.py              ← EMPTY placeholder — needs refactoring from notebook
    model_config.py           ← EMPTY placeholder — needs refactoring from notebook
    utils.py                  ← EMPTY placeholder — needs refactoring from notebook
  outputs/
    northspore/               ← gitignored
    Freedom_Power/            ← gitignored
  CLAUDE.md                   ← this file
  requirements.txt            ← needs cleanup (currently a full Anaconda dump, 456 lines)
```

**Immediate priorities:**
1. Fill in `configs/Freedom_Power.yaml` with the Freedom Power client config
2. Refactor `src/` modules — extract logic from the notebook into working Python modules
3. Clean up `requirements.txt` to a lean, minimal file
4. Build the Dash app skeleton with real Northspore data
5. Wire up BigQuery for run history and results storage

---

## Environment setup

- Python 3.11.15 (Homebrew), venv at `.venv/`
- Activate: `source .venv/bin/activate`
- Install: `pip install -r requirements.txt`
- Key dependencies: TensorFlow 2.14+, tensorflow-probability (nightly), pandas, arviz 0.19+, plotly, dash, google-cloud-bigquery, anthropic, papermill

```bash
# Launch the Northspore modeling notebook
jupyter notebook notebooks/modeling/NorthSpore/northspore_model.ipynb

# Launch the Freedom Power modeling notebook
jupyter notebook notebooks/modeling/Freedom_Power/Freedom_Power_model.ipynb
```

GPU is intentionally disabled (`CUDA_VISIBLE_DEVICES=""`). Meridian runs on CPU via MCMC.

---

## Modeling pipeline — Northspore

**Data:** `data/raw/northspore/NS_mmm_data_Mar26.csv`
- Weekly rows, Monday-aligned dates, 2024-01-01 → 2026-03-31
- Multiple US states as `geo` column

**Freedom Power data:** `data/raw/Freedom_Power/Freedom_MMM_data_Mar26.csv`
- Same weekly structure; config in `configs/Freedom_Power.yaml` (currently empty — needs populating)

**Pipeline steps:**
1. Load CSV → align dates to Monday-start weeks → fill multi-geo gaps
2. Feature engineering: Black Friday indicator, float32 casting
3. `DataFrameInputDataBuilder` assembles Meridian inputs:
   - KPI: `Revenue`
   - Paid media (7 channels): Brand, Non-Brand, DVD, Retargeting, Prospecting, Shopping, Amazon — each with `_Cost` and `_Impressions`
   - Organic (3 channels): `Facebook_Views`, `Instagram_Views`, `YouTube_Views`
   - Controls: `black_friday`, `Promo Intensity`, `weekly_average_temp`, `weekly_rainfall`
   - Population: geo-level `population`
4. Priors: `LogNormal` ROI per channel. Prospecting has tighter prior (mean=1.5, scale=0.5) based on holdout test
5. ModelSpec: 26 knots for baseline trend, 6-week max lag, geometric adstock decay
6. Inference: MCMC via TensorFlow Probability
7. Outputs: ROI estimates, geo maps (PNG + HTML), budget optimization tables → `outputs/northspore/`

**Naming conventions:**
- Media spend/impressions: `{Channel}_Cost` / `{Channel}_Impressions`
- Dates must be Monday-aligned before passing to Meridian
- All tensors cast to `float32`

---

## Development workflow

**Standard workflow — follow this every time:**
1. Experiment in the modeling notebook — test priors, inspect diagnostics, iterate on model spec
2. Run the "Save settings" cell at the bottom of the notebook to write params to `configs/{client}.yaml`
3. `git push` — Colab always clones fresh from `main`; unpushed changes are silently ignored
4. Open `notebooks/colab_runner.ipynb` in Colab → edit Cell 5 (`CLIENT`, `MODE`) → Runtime → Run All
5. Results write to `outputs/{client}/` and BigQuery automatically
6. App reads from BigQuery

**Modeling notebooks** (experimentation only — no production output writing):
- Northspore: `notebooks/modeling/NorthSpore/northspore_model.ipynb`
- Freedom Power: `notebooks/modeling/Freedom_Power/Freedom_Power_model.ipynb`

**Running `run_model.py` locally is for debugging only**, not normal workflow. Production runs go through Colab.

See `docs/COLAB_SETUP.md` for full setup and one-time credential instructions.

Never commit data files or model outputs (see `.gitignore`).

---

## New data source onboarding workflow

When adding a new raw data source (e.g. Google Search Query volume, weather, promo calendars) to an existing client model, follow this sequence. Each step has a dedicated Claude Code agent.

**Step-by-step:**
1. Drop the raw file in `data/raw/{client_id}/`
2. Run the **eda-analyst** agent with the file path and a description of what the data is
3. Review the EDA report at `docs/eda/{filename}_report.md` — look at the "Analyst attention required" section and the data quality flags before proceeding
4. Run the **data-transformer** agent with the raw file path, client ID, and source name
5. Review the transform log at `docs/eda/{filename}_transform_log.md` — check the "Analyst Review Required" section for anything that required assumptions
6. Run the **config-updater** agent with the client ID and source name
7. Review the proposed config at `configs/{client_id}_proposed.yaml` and work through the Analyst Review Checklist
8. When satisfied: `cp configs/{client_id}_proposed.yaml configs/{client_id}.yaml`
9. Push to GitHub → trigger Colab run as normal

**Agents (in `.claude/agents/`):**

| Agent | File | Purpose |
|---|---|---|
| `eda-analyst` | `.claude/agents/eda-analyst.md` | Analyzes a raw data file and produces a quality report |
| `data-transformer` | `.claude/agents/data-transformer.md` | Transforms raw data to pipeline-ready format with a full decision log |
| `config-updater` | `.claude/agents/config-updater.md` | Proposes config changes for new data; writes to `_proposed.yaml` only |
| `config-builder` | `.claude/agents/config-builder.md` | Drafts a full config for a new client from scratch |

**Key directories for this workflow:**
- `data/raw/{client_id}/` — drop raw files here (gitignored)
- `data/processed/` — output from data-transformer (gitignored, `.gitkeep` keeps the dir)
- `docs/eda/` — EDA reports and transform logs (committed — these are analyst artifacts)
- `src/transforms/` — repeatable transformation scripts (committed)
- `configs/{client_id}_proposed.yaml` — staging area for config changes (committed for review; rename to live when ready)

---

## Colab execution

`notebooks/colab_runner.ipynb` clones the repo, installs dependencies, mounts credentials from Google Drive, and executes `scripts/run_model.py` unchanged. It is the only sanctioned way to run production model jobs.

**MCMC modes:**

| Mode | Chains | Adapt | Burnin | Keep | Typical runtime |
|---|---|---|---|---|---|
| `dev` | 1 | 200 | 200 | 200 | ~5 min |
| `prod` | 4 | 500 | 500 | 500 | ~30–45 min |

**Future migration:** `future/` contains Vertex AI Custom Job files (Dockerfile, submit_job.py, setup scripts) for when the team moves off Colab. See `future/README.md`.

---

## System architecture

### Layers

**1. Workbench (local — VS Code + Claude Code)**
- Where all development happens
- `orchestrator.py` (to be built): reads client queue, triggers runs
- Per-client `configs/{client_id}.json`: single source of truth per client
- Claude Code used for: EDA, model evaluation, refactoring, iteration

**2. Compute (Google Colab)**
- Meridian fitting runs on Colab using company GPU allocation
- `notebooks/colab_runner.ipynb` clones the repo and executes `scripts/run_model.py`
- Config is locked in `configs/{client}.yaml` before each run via the notebook's save-to-config cell
- PyMC as a second framework is a **future item** — not in scope now
- Last-touch attribution comparison is a **future item** — not in scope now

**3. Storage (GCP)**
- **GCS bucket:** raw model artifacts per run (posteriors `.nc`, `contributions.csv`, `diagnostics.json`, `status.json`)
- **BigQuery:** structured run history, ROI estimates, reviewer verdicts, diagnostics — used for querying across clients and runs

**4. AI evaluation (Claude API)**
- `agents/reviewer.py` calls the Anthropic API
- System prompt is loaded from `program.md` — your encoded expert judgment about what good looks like
- Returns structured JSON: `overall_verdict`, `flags`, `framework_agreement`, `client_ready`, `summary`

**5. App layer (Dash)**
- Reads from BigQuery + GCS
- Four core screens: client list, results view (charts/ROI/curves), diagnostics (RHAT/ESS/flags), config editor
- Designed for internal use and screen-sharing with clients — not a public-facing product yet
- Streamlit is acceptable for early POC; Dash is the target

### Artifact schema (per run)
```
gs://mmm-pipeline-results/
  clients/{client_id}/
    runs/{run_id}/
      meridian/
        inference_data.nc
        diagnostics.json      ← {rhat_max, rhat_by_channel, ess_min, converged, runtime_minutes}
        contributions.csv     ← {date, channel, contribution, contribution_pct, roi, roi_lower_90, roi_upper_90}
        status.json           ← {status: complete|failed, run_id, error?}
      reviewer_report.json    ← Claude's structured verdict
```

### Client config schema

Configs are YAML files at `configs/{client_id}.yaml`. Example:

```yaml
client_id: northspore
data_path: gs://mmm-pipeline-results/clients/northspore/data.csv
output_path: gs://mmm-pipeline-results/clients/northspore/runs/
channels:
  - Brand
  - Non-Brand
  - DVD
  - Retargeting
  - Prospecting
  - Shopping
  - Amazon
organic_channels:
  - Facebook_Views
  - Instagram_Views
  - YouTube_Views
date_column: date
kpi_column: Revenue
prior_expected_roi:
  Brand: [0.8, 3.0]
  Prospecting: [1.5, 0.5]
mcmc_samples: 500
mcmc_chains: 4
max_runtime_minutes: 45
```

---

## Key architectural decisions (do not re-litigate)

These were deliberate choices — don't suggest alternatives unless asked:

- **No full automation.** The system supports the analyst, it doesn't replace them. Human review and stakeholder involvement are intentional parts of the workflow.
- **Dash over Streamlit** for the app (Streamlit acceptable for early POC only).
- **BigQuery over SQLite/Postgres** — analyst already manages large BQ datasets and is skilled with it. Fits the GCP stack.
- **GCS for artifacts** — keeps everything in one GCP ecosystem alongside Colab and BigQuery.
- **Colab compute** — company has existing GPU allocation; no need for Modal or external compute costs.
- **Meridian only for now** — PyMC is a future validation framework, not current scope.
- **Claude API for reviewer agent** — not a rules-based evaluator; Claude reads `program.md` and applies judgment.
- **Two active clients** — Northspore (primary, further along) and Freedom Power (data + notebook exist, config not yet filled in). Build Northspore end to end first; Freedom Power follows the same pattern.

---

## program.md

`program.md` (to be created at repo root) is the system prompt for the reviewer agent. It encodes the analyst's expert judgment: convergence thresholds, ROI plausibility ranges by channel type, cross-framework agreement rules, and red flags for non-technical client communication. When building or editing the reviewer agent, always load this file as the system prompt — never hardcode evaluation logic in the Python code itself.

---

## Files never to commit
- `data/` — all raw and processed data
- `outputs/` — model artifacts and plots
- `.env` — API keys (ANTHROPIC_API_KEY, GCS credentials)
- `*.nc` — InferenceData posteriors
- Any file matching patterns in `.gitignore`
