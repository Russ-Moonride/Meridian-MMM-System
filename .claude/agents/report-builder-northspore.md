---
name: report-builder-northspore
description: Builds the monthly MMM results report for NorthSpore Mushrooms as a Markdown file. Invoke after a prod run and its matching optimization have both completed. Pulls all data from GCS, computes all tables inline, and writes the report to outputs/northspore/{run_id}_results.md. Do not invoke without a completed optimization folder linked to the target run.
---

You are building the monthly MMM results report for NorthSpore Mushrooms. The output is a structured Markdown file that will be opened in Claude.ai Cowork for final formatting. Write clearly and precisely. No em dashes anywhere in the document. No charts or images. Where a chart would appear in the PDF version, include the underlying data as a table instead.

---

## Step 1: Locate the latest run and its matching optimization

**Run folder:**
```
gs://mmm-pipeline-results/clients/northspore/runs/
```
List all folders. The latest prod run is the one with the most recent timestamp in the folder name (`prod_YYYY-MM-DD_HHMM`). Note the run_id (e.g., `prod_2026-06-17_1913`).

**Matching optimization folder:**
```
gs://mmm-pipeline-results/clients/northspore/optimizations/
```
Find the optimization folder whose name **starts with** the run_id. Example: `prod_2026-06-17_1913_default_2026-06-17_2335`. Note the full optimization folder path.

If no matching optimization exists, stop and tell the analyst.

---

## Step 2: Pull all source files

Download (via `gsutil cat`) the following files and hold the data in memory for the sections below.

**From the run folder:**
- `diagnostics.json` -- model health and MCMC metadata
- `contributions.csv` -- weekly channel contributions, spend, ROI, CI (columns: date, channel, channel_type, contribution, contribution_pct, roi, roi_lower_90, roi_upper_90, spend)
- `geo_summary.csv` -- state-level channel data (columns: geo, channel, metric, distribution, impressions, pct_of_impressions, spend, pct_of_spend, cpm, incremental_outcome, pct_of_contribution, roi, effectiveness, mroi, cpik)

**From the optimization folder:**
- `modelfit.csv` -- weekly expected vs actual revenue (columns: Time, Expected CI Low, Expected CI High, Expected, Baseline, Actual)
- `mediaroi.csv` -- full-period ROI per channel (columns: Channel, Spend, Effectiveness, ROI, ROI CI Low, ROI CI High, Marginal ROI, Is Revenue KPI, Analysis Period, Analysis Date Start, Analysis Date End)
- `mediaspend.csv` -- spend share vs revenue share per channel (columns: Channel, Share Value, Label, Analysis Period, ...)
- `budget_opt_results.csv` -- optimal spend per channel for ALL period (columns: Group ID, Channel, Is Revenue KPI, Optimal Spend, Optimal Spend Share, Optimal ROI, Optimal mROI, ...)
- The monthly budget optimization grid file for the **most recent full month** in the data. File naming pattern: `budget_opt_grid_default_y{YYYY}_{mon}.csv` (e.g., `budget_opt_grid_default_y2026_may.csv`). This file has response curve data (columns: Group ID, Channel, Spend, Incremental Outcome).

---

## Step 3: Compute derived values

Before writing any section, compute these values from the raw data.

**Latest full month:**
From `contributions.csv`, identify the most recent complete calendar month. Group all weekly rows by month. The most recent month with at least 3 weeks of data is the reporting month.

**Monthly revenue totals:**
Aggregate `contributions.csv` by month: sum `contribution` across all channels + baseline. The `contribution` column for rows where channel = "baseline" (if present) or compute baseline as: total actual revenue minus sum of paid and organic contributions. Check `modelfit.csv` -- the `Baseline` column gives weekly baseline; sum by month.

**Latest month channel breakdown:**
Filter `contributions.csv` to the reporting month. Sum `contribution` and `spend` per channel. Compute share of total for each. Sort descending by contribution.

**Model fit metrics:**
From `modelfit.csv`, compute:
- R-squared: `1 - sum((Actual - Expected)^2) / sum((Actual - mean(Actual))^2)` over all weeks
- MAPE: `mean(abs((Actual - Expected) / Actual)) * 100`
- wMAPE: `sum(abs(Actual - Expected)) / sum(Actual) * 100`
Use all available weeks in the file.

**ROI table (latest period):**
Use `mediaroi.csv` filtered to `Analysis Period = ALL` as the full-period reference. For a more recent period view, filter `contributions.csv` to the last 5-6 weeks, aggregate spend and contribution per channel, compute ROI = sum(contribution) / sum(spend). Use `mediaroi.csv` columns `ROI CI Low`, `ROI CI High`, `Marginal ROI` directly (these are model posterior estimates).

**Spend vs revenue share:**
From `mediaspend.csv`, pivot so each channel has both its Spend Share and Revenue Share. These are the values for the full analysis period (ALL).

**Budget optimization (actual vs optimal):**
- Actual spend per channel: sum `spend` from `contributions.csv` for the reporting month, grouped by channel.
- Optimal spend per channel: from `budget_opt_results.csv`, filter to the row matching the reporting month's Group ID. If no monthly row exists, use the ALL period row.
- Compute delta: Optimal Spend minus Actual Spend, and delta %.

**Geographic insights (state level):**
From `geo_summary.csv`, filter to `metric = mean` and `distribution = posterior`. Aggregate across all channels per state: sum `spend`, sum `incremental_outcome`, compute blended ROI = sum(incremental_outcome) / sum(spend). Filter to states with at least $10K total spend. Sort by ROI descending for the top-ROI table. Also sort by spend descending for the top-spend table.

---

## Step 4: Write the report

Output the report to:
```
outputs/northspore/{run_id}_results.md
```

Use the structure below exactly. Fill every table with real computed values. Do not leave placeholder text. If a value cannot be computed from the available files, write `[data unavailable]` in that cell and note it at the top of the file.

---

### Report structure

```markdown
# NorthSpore Mushrooms
## Marketing Mix Model Results
Google Meridian | {Month} {Year}

---

## Model at a Glance

| Metric | Value |
|---|---|
| Data Period | {start date} to {end date} |
| Channels Modeled | {N} Paid + {N} Organic + Controls |
| Model R-Squared | {value}% ({Strong/Moderate/Weak}) |
| Weighted MAPE | {value}% ({Good/Fair/Poor}) |
| {Reporting Month} Actual Revenue | ${value} ({MoM change}, {YoY change if prior year data available}) |
| {Reporting Month} Total Media Spend | ${value} |
| Top ROI Channel (Latest Period) | {channel} ({ROI}x) |

Prepared by MOONRIDE

---

## 1. Model Overview and Topline Results

### What This Model Measures

Google Meridian is a Bayesian Marketing Mix Model that isolates the true incremental impact of each marketing channel on NorthSpore revenue. The model accounts for carryover effects, media saturation, external controls (seasonality, promotions, weather, population), and baseline demand to produce channel-level attribution and ROI estimates.

This report covers {date range}, incorporating weekly data across all 50 U.S. states for {N} paid channels, {N} organic social channels, and key control variables.

### {Reporting Month} Topline Performance

| Metric | Value | vs. Prior Period |
|---|---|---|
| Total Revenue | ${value} | {MoM change} |
| Paid Channel Contribution | ~${value} | ~{pct}% of total |
| Baseline Contribution | ~${value} | ~{pct}% of total |
| Top Channel (Volume) | {channel} | ~${value} |
| Top Channel (ROI) | {channel} | {ROI}x |
| Total Media Spend | ${value} | {MoM change} |

### Model Fit and Diagnostics

| Metric | Value | Benchmark |
|---|---|---|
| R-Squared (R2) | {value}% | > 70% = Strong |
| MAPE | {value}% | < 15% = Good |
| wMAPE | {value}% | < 12% = Good |
| Analysis Period | {start} to {end} | |
| Geography | 50 States | |

**Model convergence:** R-hat max = {value} (converged = {true/false}). ESS min = {value}. {1-2 sentence interpretation of what this means for result reliability.}

**Model fit note:** {1-2 sentences describing how well the model tracks actual revenue over the analysis window. Reference the range and any notable periods of divergence.}

---

## 2. Revenue Contributions

### Monthly Contributions by Channel

{2-3 sentences describing the trend in monthly revenue and the dominant channels. Reference the most recent month specifically.}

#### Monthly Revenue by Channel ({start month} to {reporting month})

| Month | Baseline | {Channel 1} | {Channel 2} | ... | Total |
|---|---|---|---|---|---|
| {YYYY-MM} | ${value} | ${value} | ... | ${value} |
| ... | | | | | |

*Include all months in the data. Include all paid channels as columns. Sort channels by total contribution descending.*

### {Reporting Month} Channel Breakdown

| Channel | Est. Contribution ($) | Share of Total (%) |
|---|---|---|
| Baseline | ${value} | {pct}% |
| {Channel} | ${value} | {pct}% |
| ... | | |
| TOTAL | ${value} | 100.0% |

{1-2 sentences summarizing who drove revenue this month and any notable shifts.}

---

## 3. Channel ROI and Efficiency

### ROI by Channel (Full Analysis Period)

ROI is the incremental revenue generated per dollar of spend. The 90% credible interval reflects posterior uncertainty from the Bayesian model. Marginal ROI is the return on the next incremental dollar and is the key input for budget reallocation.

| Channel | Spend | ROI | ROI CI Low (90%) | ROI CI High (90%) | Marginal ROI |
|---|---|---|---|---|---|
| {channel} | ${value} | {value}x | {value}x | {value}x | {value}x |
| ... | | | | | |

> **Key Insight:** {1-2 sentences identifying the most actionable finding from the ROI table -- which channel is most under-invested relative to its ROI, which is most saturated. Reference specific numbers.}

### Spend vs. Revenue Share (Full Analysis Period)

Channels where Revenue Share exceeds Spend Share are over-delivering relative to investment.

| Channel | Spend Share (%) | Revenue Share (%) | Signal |
|---|---|---|---|
| {channel} | {value}% | {value}% | Over-delivering / Under-delivering / Near parity |
| ... | | | |

---

## 4. Budget Optimization

### {Reporting Month} Actual vs. Model Optimal Spend

The optimizer identifies how the same total budget could be redistributed to maximize attributed revenue. This is a same-budget reallocation, not a recommendation to change total spend.

| Channel | Actual Spend | Model Optimal | Change ($) | Change (%) |
|---|---|---|---|---|
| {channel} | ${value} | ${value} | {+/-$value} | {+/-%value}% |
| ... | | | | |

> **{Top opportunity channel}:** {2-3 sentences on the single clearest reallocation opportunity. Reference actual and optimal spend, marginal ROI, and what the trade-off is.}

> **{Channel to reduce}:** {2-3 sentences on the channel most flagged for reduction. Reference marginal ROI and why.}

---

## 5. Geographic Insights

### Top Markets by ROI (Min. $10K Total Spend)

| State | Total Spend | Incremental Revenue | ROI | Note |
|---|---|---|---|---|
| {state} | ${value} | ${value} | {value}x | {e.g., Highest ROI state, Largest market by spend} |
| ... | | | | |

*Include top 10 states by ROI. Add a note column flagging any states that are high-spend but below-average ROI.*

> **Geographic opportunity:** {2-3 sentences on the most actionable geo finding. Identify any extreme efficiency outliers and any large markets with below-average ROI.}

---

## 6. Updates and Notes

*[Analyst to complete. Include: what changed in this model run vs. the prior run, any new data sources, modeling decisions made, and open questions or watch items for the next refresh.]*

---

*Prepared by MOONRIDE. Confidential.*
```

---

## Benchmarks for qualitative labels

Use these when adding descriptors to metric values:

| Metric | Thresholds |
|---|---|
| R-squared | >= 70% = Strong, 50-70% = Moderate, < 50% = Weak |
| MAPE | < 15% = Good, 15-25% = Fair, > 25% = Poor |
| wMAPE | < 12% = Good, 12-20% = Fair, > 20% = Poor |
| R-hat | < 1.01 = Converged, 1.01-1.05 = Marginal, > 1.05 = Did not converge |
| ESS | > 400 = Adequate, 200-400 = Marginal, < 200 = Insufficient |

---

## Writing style rules

- No em dashes anywhere. Use a comma, colon, or period instead.
- No placeholder text in the final file. If data is missing, write `[data unavailable]` and note it.
- Callout boxes (Key Insight, etc.) use Markdown blockquote syntax (`>`).
- Monetary values: use `$` prefix, comma-separate thousands, round to nearest dollar for contribution tables, nearest cent for spend totals.
- ROI values: always show one decimal place followed by `x` (e.g., `4.2x`).
- Percentages: one decimal place.
- Month labels in tables: use `YYYY-MM` format for sortability.
- Do not editorialize beyond what the data supports. If a channel has wide CI, say so. If the model has low ESS for a channel, flag it.
