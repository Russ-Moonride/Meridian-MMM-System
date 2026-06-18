---
name: report-builder-freedom
description: Builds the monthly MMM results report for Freedom Power as a Markdown file. Invoke after a prod run and its matching optimization have both completed. Pulls all data from GCS, computes all tables inline, and writes the report to outputs/Freedom_Power/{run_id}_results.md. Freedom Power KPI is incremental gross leads, not revenue. CPL (cost per incremental lead) is the primary efficiency metric. Do not invoke without a completed optimization folder linked to the target run.
---

You are building the monthly MMM results report for Freedom Power. The output is a structured Markdown file that will be opened in Claude.ai Cowork for final formatting. Write clearly and precisely. No em dashes anywhere in the document. No charts or images. Where a chart would appear in the PDF version, include the underlying data as a table instead.

**Critical distinction:** Freedom Power's KPI is gross leads, not revenue. ROI values in the raw files are leads-per-dollar (very small decimals, e.g., 0.049). The report should express efficiency as **Cost Per Incremental Lead (CPL)** in dollars, computed as: `CPL = total spend / total incremental leads`. Do not display raw ROI decimals to the client. The optimizer optimal spend is still in dollars and is directly usable.

---

## Step 1: Locate the latest run and its matching optimization

**Run folder:**
```
gs://mmm-pipeline-results/clients/freedom/runs/
```
List all folders. The latest prod run is the folder with the most recent timestamp (`prod_YYYY-MM-DD_HHMM`). Note the run_id.

**Matching optimization folder:**
```
gs://mmm-pipeline-results/clients/freedom/optimizations/
```
Find the optimization folder whose name **starts with** the run_id. If multiple exist, take the most recent. If no match exists, stop and tell the analyst.

---

## Step 2: Pull all source files

Download (via `gsutil cat`) the following files.

**From the run folder:**
- `diagnostics.json` -- model health and MCMC metadata (rhat_max, ess_min, converged, rhat_by_channel, ess_by_channel)
- `contributions.csv` -- weekly channel contributions and spend (columns: date, channel, channel_type, contribution, contribution_pct, roi, roi_lower_90, roi_upper_90, spend). Contribution here = incremental gross leads.
- `geo_summary.csv` -- DMA-level channel data (columns: geo, channel, metric, distribution, impressions, pct_of_impressions, spend, pct_of_spend, cpm, incremental_outcome, pct_of_contribution, roi, effectiveness, mroi, cpik). The `geo` column contains DMA names: Austin, DFW, Houston, Orlando, San Antonio, Tampa.

**From the optimization folder:**
- `modelfit.csv` -- weekly expected vs actual leads (columns: Time, Expected CI Low, Expected CI High, Expected, Baseline, Actual)
- `mediaroi.csv` -- full-period metrics per channel (columns: Channel, Spend, Effectiveness, ROI, ROI CI Low, ROI CI High, Marginal ROI, Is Revenue KPI, Analysis Period, Analysis Date Start, Analysis Date End)
- `budget_opt_results.csv` -- optimal spend per channel (columns: Group ID, Channel, Is Revenue KPI, Optimal Spend, Optimal Spend Share, Optimal ROI, Optimal mROI, ...)
- The monthly budget optimization grid file for the most recent full month: `budget_opt_grid_default_y{YYYY}_{mon}.csv`

---

## Step 3: Compute derived values

**Latest full month:**
From `contributions.csv`, identify the most recent complete calendar month (at least 3 weeks of data). This is the reporting month.

**Monthly lead totals:**
Aggregate `contributions.csv` by month: sum `contribution` per channel. Baseline leads: from `modelfit.csv`, sum `Baseline` by month.

**Reporting month channel breakdown:**
Filter `contributions.csv` to the reporting month. Sum `contribution` (leads) and `spend` per channel. Compute:
- Lead share = channel leads / total leads (including baseline)
- CPL = channel spend / channel incremental leads
Sort by incremental leads descending.

**Model fit metrics:**
From `modelfit.csv`, compute over all available weeks:
- R-squared: `1 - sum((Actual - Expected)^2) / sum((Actual - mean(Actual))^2)`
- MAPE: `mean(abs((Actual - Expected) / Actual)) * 100`
- wMAPE: `sum(abs(Actual - Expected)) / sum(Actual) * 100`

**CPL trend by channel:**
From `contributions.csv`, compute CPL per channel for the reporting month and the prior month. Express direction as: Up, Down, or Stable (less than 5% change).

**Budget optimization (actual vs optimal):**
- Actual spend: sum `spend` from `contributions.csv` for the reporting month, grouped by channel.
- Optimal spend: from `budget_opt_results.csv`, use rows matching the reporting month's Group ID, or ALL period if monthly rows are unavailable.
- Compute: delta in dollars and delta %.

**Geo breakdown per DMA:**
From `geo_summary.csv`, filter to `metric = mean` and `distribution = posterior`. For each DMA, compute per channel:
- Spend share = channel spend / total DMA spend
- Contribution share = channel incremental_outcome / total DMA incremental_outcome
- Incremental leads = sum of incremental_outcome across the full window
- CPL = total channel spend / total channel incremental_outcome
- Budget signal: compare spend share to contribution share (see signal legend below)

**Geo budget signals:**
- Contribution share >= 2x spend share: Severely under-invested
- Contribution share >= 1.3x spend share: Under-invested
- Within 15% of each other: Near parity
- Spend share >= 1.3x contribution share: Over-allocated
- Spend share >= 2x contribution share: Significantly over-allocated

---

## Step 4: Write the report

Output the report to:
```
outputs/Freedom_Power/{run_id}_results.md
```

Use the structure below exactly. Fill every table with real computed values. Do not leave placeholder text. If a value cannot be computed, write `[data unavailable]` and note it.

---

### Report structure

```markdown
# Freedom Power
## Marketing Mix Model -- {Month} {Year} Refresh
Google Meridian | {Month} {Year}

---

## Model at a Glance

| Metric | Value |
|---|---|
| Data Period | {start date} to {end date} |
| Modeled Markets | Austin, DFW, Houston, Orlando, San Antonio, Tampa |
| Channels Modeled | {list all channels} |
| Model R-Squared | {value} ({Strong/Moderate/Weak} -- explains {pct}% of weekly lead variance) |
| MAPE / wMAPE | {value}% / {value}% ({Good/Fair/Poor} Accuracy) |
| Total Incremental Leads (paid) | {value} across full window |
| Baseline Share | {value}% of total leads |

---

## What Changed in This Update

*[Analyst to complete. Note any new data sources added, channels added or removed, modeling decisions made this refresh, and anything unusual about this run compared to the prior one.]*

---

## 1. Recent Performance: {Reporting Month}

{2-3 sentences on the reporting month: total observed gross leads, how it compares to the prior month, and any notable context about spend levels or campaign changes.}

### Incremental Leads by Channel -- {Reporting Month}

| Channel | Incr. Leads | Lead Share | Actual Spend | Optimal Spend |
|---|---|---|---|---|
| {channel} | {value} | {pct}% | ${value} | ${value} |
| ... | | | | |
| Baseline | {value} | {pct}% | -- | -- |
| TOTAL | {value} | 100% | ${value} | ${value} |

*Sort by incremental leads descending. Baseline rows do not have spend or optimal spend.*

### Cost Per Incremental Lead -- {Reporting Month}

| Channel | CPL | Trend | Notes |
|---|---|---|---|
| {channel} | ${value} | {Up/Down/Stable} | {1 sentence on efficiency signal} |
| ... | | | |

*Sort by CPL ascending (most efficient first). Do not include Baseline. Add a brief note for any channel where CPL is notably high or has moved significantly.*

### Monthly Incremental Lead Contribution by Channel

{1-2 sentences describing the overall trend in paid lead volume over the data window.}

| Month | {Channel 1} | {Channel 2} | ... | Baseline | Total |
|---|---|---|---|---|---|
| {YYYY-MM} | {leads} | {leads} | ... | {leads} | {leads} |
| ... | | | | | |

*Include all months in the data. Baseline excluded from the chart in the PDF but included here for completeness. Sort channels by total leads descending.*

---

## 2. Billboard and Direct Mail Performance Note

*[Analyst to complete if Billboard or Direct Mail is active. Describe whether the model is attributing contribution to these channels, what the trend looks like in the billboard markets, and any caveats about signal quality due to static spend or limited data window.]*

*If neither channel is active or relevant this refresh, remove this section.*

---

## 3. Budget Optimization Recommendations

Optimization outputs represent the model's recommended allocation for the **same total budget**. The optimizer maximizes gross leads by balancing marginal returns across channels.

### Optimization Summary -- {Reporting Month}

| Channel | Actual Spend | Optimal Spend | Delta | Directional Signal |
|---|---|---|---|---|
| {channel} | ${value} | ${value} | {+/-$value} | {signal description} |
| ... | | | | |

*Flag Billboard and Reddit rows with a note if their optimal is $0 or near zero.*

> **Optimization Takeaways:** {3-5 sentences on the overall pattern. What is the single largest reallocation opportunity? What should be funded by what reduction? What channels remain consistently under-invested? Reference specific numbers.}

Key caveats:
- Optimization signals are directional. Shifts should be made gradually, not in a single budget cycle.
- Marginal returns diminish as any channel scales. Efficiency metrics will compress as recommended allocations are approached.
- Channels with static or near-zero spend (Billboard, Direct Mail) are low-confidence and will firm up with more data.

### Geo-Level Reallocation Signals

| Channel | Austin | DFW | Houston | Orlando | San Antonio | Tampa |
|---|---|---|---|---|---|---|
| {channel} | {signal} | {signal} | {signal} | {signal} | {signal} | {signal} |
| ... | | | | | | |

Signal legend: up up = materially under-invested, up = room to grow, approx = near parity, down = over-allocated, down down = significantly over-allocated, -- = no spend in market.

*Use arrows or text abbreviations since this is Markdown: "Scale++", "Scale", "Hold", "Reduce", "Reduce++" or similar.*

---

## 4. Geo Level Breakdown (Full Window Totals)

One table per DMA. Each table shows per-channel spend share, contribution share, incremental leads, CPL, and budget signal for the full analysis window. Below each table add 1-2 sentence takeaways flagging the single most important reallocation signal in that market.

### Austin

| Channel | Spend Share | Contrib. Share | Incr. Leads | CPL | Budget Signal |
|---|---|---|---|---|---|
| {channel} | {pct}% | {pct}% | {value} | ${value} | {signal} |
| ... | | | | | |

*Takeaway: {1-2 sentences on the clearest signal in this market, referencing specific channel names and CPL values.}*

### DFW

[same structure]

### Houston

[same structure]

### Orlando

[same structure]

### San Antonio

[same structure]

### Tampa

[same structure]

---

## 5. Notes and Next Steps

*[Analyst to complete. Include: what to watch in the next refresh, any spend-level decisions pending (e.g., cut or scale Reddit), any geo experiment results expected, and model changes planned for the next run.]*

---

*Prepared by MOONRIDE. Confidential.*
```

---

## Benchmarks for qualitative labels

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
- No placeholder text in the final file. Every table cell must have a real value or `[data unavailable]`.
- Callout boxes (key insight, optimization takeaways) use Markdown blockquote syntax (`>`).
- CPL values: use `$` prefix, round to nearest dollar. Example: `$26`.
- Spend values: use `$` prefix, comma-separate thousands.
- Percentages: one decimal place.
- Month labels in tables: use `YYYY-MM` format.
- Lead counts: round to nearest whole number, no decimal places.
- Do not editorialize beyond what the data supports. If a channel has near-zero attribution, say so plainly without overclaiming. If the model has low confidence in a channel (wide CI or low ESS), flag it.
- The geo tables cover the full analysis window, not just the reporting month. Make this clear in the section header.
