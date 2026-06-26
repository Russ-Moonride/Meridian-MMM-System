# Janessa Leone — Client Context

**Client:** Janessa Leone  
**KPI:** Revenue (Shopify gross sales)  
**Model type:** National single-series (no geo breakdown)  
**Status:** First prod run complete — first-pass results shared with stakeholders

---

## Data Sources

### Paid media + revenue — BigQuery
Table: `janessa-leone-462017.janessa_leone_segments.full_segments`  
Script: `scripts/refresh_janessa_leone.py --prod`  
Start date: 2024-01-01  
Revenue column: `Gross_Sales__Shopify`

BQ pulls 7 channels via `Type` filter:

| BQ Type value | Column name |
|---|---|
| Brand | Brand |
| Non-Brand | Non_Brand |
| Brand Shopping | Brand_Shopping |
| Prospecting | Prospecting |
| Retargeting | Retargeting |
| Remarketing | Remarketing |
| Pinterest | Pinterest |

### Affiliate — CSVs only (not in BQ)
ShopMy and ShareASale are sourced exclusively from CSV exports — do not pull from BQ.  
Drop new files in `data/raw/janessa_leone/` before running refresh.

| Platform | File pattern | Columns used |
|---|---|---|
| ShopMy | `JL_ShopMy_*.csv` | Date (M/D/YY), Cost, Clicks |
| ShareASale (AWIN) | `JL_ShareASale_*.csv` | Date (YYYY-MM-DD), Cost, Clicks |

Clicks are used as the volume metric (stored in `_Impressions` columns). Spend variability is lower than other channels — treat affiliate ROI estimates as directional.

### Processed dataset
`data/processed/janessa_leone/JL_mmm_data_Jun26.csv`  
GCS: `gs://mmm-pipeline-results/clients/janessa_leone/JL_mmm_data_Jun26.csv`  
130 rows × 21 columns. 2024-01-01 → 2026-06-22.

---

## Channel Configuration

```
channels: Brand, Non_Brand, Brand_Shopping, Prospecting, Retargeting, Remarketing, Pinterest, ShopMy, AWIN
organic_channels: [] (none currently — Social_Organic to be added when data available)
controls: black_friday (pre-computed in refresh script)
```

No geo column. No population column. National model only.

---

## Prior Specification

ROI priors set from last-touch attribution data with directional bias adjustments. All ranges represent the 95% credible interval for a LogNormal prior.

| Channel | LT ROI | Prior range | Rationale |
|---|---|---|---|
| Brand | 10.0 | [1.5, 8.0] | LT over-credits — captures organic intent |
| Non_Brand | 4.0 | [1.5, 7.0] | Reasonable LT signal; symmetric range |
| Brand_Shopping | 5.0 | [1.5, 7.0] | Over-credited; lower anchor |
| Prospecting | 3.08 | [1.5, 7.0] | LT under-credits; used as floor, extended up |
| Retargeting | 2.19 | [0.8, 5.0] | Over-credited + sparse; shifted down |
| Remarketing | 11.18 | [1.5, 8.0] | Heavily over-credited; anchor well below LT |
| Pinterest | 1.5 | [0.3, 4.0] | LT under-credits upper funnel; very low volume |
| ShopMy | 13.32 | [0.5, 6.0] | Last-click meaningless for influencer affiliate |
| AWIN (ShareASale) | 3.29 | [0.5, 4.5] | Affiliate last-click over-credited |

---

## Model Configuration

```yaml
knots: 26
max_lag: 6
adstock_decay_spec: geometric
media_effects_dist: log_normal  # reset to normal by Meridian for national models
prior_roi_mass_percent: 0.95
mcmc dev:  1 chain, 200 adapt/burnin/keep
mcmc prod: 4 chains, 500 adapt/burnin/keep
```

---

## First Prod Run — prod_2026-06-26_1923

**GCS:** `gs://mmm-pipeline-results/clients/janessa_leone/runs/prod_2026-06-26_1923/`  
**Local report:** `outputs/janessa_leone/reports/prod_2026-06-26_1923_report.html`

### Model fit
| Metric | Value |
|---|---|
| R² | 0.845 |
| MAPE | 18.6% |
| Worst week | 2025-11-17 (pre-Black Friday ramp — $115k residual) |
| R-hat max | 1.004 (all channels < 1.01) |
| ESS min | 708 (Prospecting) |

### Attribution
- Paid media: ~50% of modeled revenue
- Baseline: ~50%
- Total modeled revenue: $14.0M over 130 weeks

### ROI results (posterior median, 90% CI)

| Channel | ROI | 90% CI | mROI | Saturation |
|---|---|---|---|---|
| Prospecting | 4.70 | 2.85–6.73 | 2.85 | Headroom |
| Remarketing | 3.66 | 1.82–7.40 | 1.64 | Diminishing |
| Brand | 3.45 | 1.73–6.94 | 1.28 | Diminishing |
| Brand_Shopping | 3.40 | 1.81–6.62 | 1.60 | Diminishing |
| Non_Brand | 3.22 | 1.68–6.44 | 0.83 | Diminishing |
| ShopMy | 2.55 | 0.74–10.75 | 1.17 | Moderate |
| Retargeting | 1.97 | 0.93–4.34 | 0.83 | Diminishing |
| AWIN | 1.48 | 0.58–3.83 | 0.63 | Diminishing |
| Pinterest | 1.10 | 0.37–3.10 | 0.20 | Near saturation |

### Key takeaways
- **Prospecting** is the dominant channel (72% of spend, 81% of paid contribution) and the least saturated — primary candidate for budget reallocation.
- **Google Search** (Brand, Non-Brand, Brand Shopping) are the most stable and consistent channels with tight confidence ranges.
- **Affiliates** — ShopMy CI is very wide (0.74–10.75); ShareASale has low volume. Both directional only.
- **Pinterest** — mROI of 0.20 is below breakeven. Caveat: only two campaign types included in this run.
- **Holiday fit** — model undershoots the pre-Black Friday ramp (Nov 2025). A broader holiday window indicator or additional promo controls would improve this.

---

## Known Gaps / Next Steps

- [ ] Add organic social and paid social channels (expected to add nuance to Prospecting estimate)
- [ ] Include all Pinterest campaign types (awareness, organic) for a complete view
- [ ] Add additional promo/seasonality controls to improve holiday fit
- [ ] Run sensitivity analysis on priors before making budget reallocation recommendations
- [ ] Update GCS data path when next vintage is pulled (`gcs_data_path` in config)
- [ ] R² and MAPE not yet written to `diagnostics.json` — add to `src/utils.py` extraction

---

## Notes on Infrastructure

- `src/data_prep.py` and `src/model_config.py` now support national (no-geo) models — `geo_column` is optional.
- `run_model.py` handles national models cleanly.
- Affiliate CSVs must be manually dropped into `data/raw/janessa_leone/` before each refresh — there is no automated pull for these.
- Config: `configs/Janessa_Leone.yaml`
- Refresh script: `scripts/refresh_janessa_leone.py`
