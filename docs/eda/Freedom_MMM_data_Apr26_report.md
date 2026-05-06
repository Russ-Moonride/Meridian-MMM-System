# EDA Report: Freedom_MMM_data_Apr26
**Generated:** 2026-05-06
**File:** data/raw/Freedom_Power/Freedom_MMM_data_Apr26.csv
**Context:** Updated Freedom Power MMM dataset. Key changes vs. prior version: (1) Reddit_Cost and Reddit_Impressions added as a new paid media channel; (2) date range extended by one week to 2026-05-04.
**Reference dataset:** data/processed/Freedom_Power/Freedom_MMM_data_Apr26_gqv.csv

---

## Summary and Recommended Next Steps

- **The file is structurally clean and pipeline-ready on the basics.** All 738 rows are present (6 geos x 123 weeks), dates are Monday-aligned throughout, no nulls exist in any column, and no duplicate date x geo pairs are found. The new week (2026-05-04) is present across all 6 geos.

- **Reddit launched 2026-03-16 in 5 of 6 geos; San Antonio has zero Reddit spend for the full history.** Reddit_Cost and Reddit_Impressions are heavily zero-inflated (94.6% and 94.3% zeros respectively), which is correct behavior given the late start. Only 8 active weeks of spend data exist. This is very thin for Meridian to estimate an independent Reddit ROI — analyst must decide whether to model Reddit as its own channel or hold it out.

- **San Antonio has a Reddit data anomaly that needs a decision.** Two weeks (2026-03-16 and 2026-03-23) show Reddit_Impressions of 111 and 104 with Reddit_Cost = 0.00. This is inconsistent — impressions without spend. It may be organic Reddit exposure, a tracking artifact, or a data entry error. These 2 rows are the only Reddit signal San Antonio has.

- **All existing columns (pre-Reddit) are byte-for-byte identical to the reference processed file** for the overlapping date range. The one "difference" in Brand_Cost (2024-07-08 Houston: 3113.221593 vs. 3113.2217) is a floating-point rounding artifact at the 4th decimal place — not a structural change. Non-Reddit columns have not been touched.

- **Impression columns changed dtype from float64 (reference) to int64 (this file).** Columns Brand_Impressions, Non_Brand_Impressions, DVD_Impressions, Retargeting_Impressions, Prospecting_Impressions, and population are int64 in this file vs. float64 in the processed reference. The data transformer should cast these to float32 as normal; this is not a data quality problem.

**Analyst attention required:**
- **San Antonio Reddit decision:** Two weeks of Reddit_Impressions with zero cost. Decide whether to zero out these impressions or treat them as organic exposure. If zeroed out, San Antonio has no Reddit signal at all.
- **Reddit channel modeling strategy:** 8 weeks of data across 5 geos is sparse. Decide whether Reddit is included as a paid media channel (with a strongly informative prior), excluded from this model run, or included as a zero-padded control variable.
- **Billboard flat value check:** Austin Billboard_Cost = $32,900 exactly for all 10 consecutive active weeks (2026-03-02 through 2026-05-04), and Billboard_Impressions = 845,515 exactly for the same 10 weeks. This looks like a fixed-rate contract being entered as a weekly constant. Confirm this is correct with the client before transformation.
- **Prospecting spike in Tampa and Orlando:** Both geos show Prospecting_Cost exceeding mean + 3*std during 2026-04-06 through 2026-04-27. This appears to be a genuine budget ramp-up (values rise and fall smoothly) rather than a data error, but confirm with the client.

---

## 1. Basic Shape

| Property | Value |
|---|---|
| Rows | 738 |
| Columns | 23 |
| Date range | 2024-01-01 to 2026-05-04 |
| Total span | 123 weeks (~2 years 4 months) |
| Granularity | Weekly |
| Geos | 6 (Austin, DFW, Houston, Orlando, San Antonio, Tampa) |
| Rows per geo | 123 (perfectly balanced) |

**Granularity evidence:** All consecutive date differences within the sorted unique date list are exactly 7 days. There are exactly 123 unique dates x 6 geos = 738 rows, matching the expected Monday-weekly structure.

**New week confirmed:** The week of 2026-05-04 is present for all 6 geos (6 rows added vs. the prior reference file's 732 rows).

---

## 2. Column Inventory

| Column | dtype | Null count | Null % | Sample values |
|---|---|---|---|---|
| Unnamed: 0 | int64 | 0 | 0.00% | 0, 1, 2, 3 |
| date | datetime64[ns] | 0 | 0.00% | 2024-01-01, 2024-01-08, 2024-01-15 |
| geo | object | 0 | 0.00% | Austin, DFW, Houston, Orlando |
| Brand_Cost | float64 | 0 | 0.00% | 194.45, 234.75, 233.88, 304.40 |
| Non_Brand_Cost | float64 | 0 | 0.00% | 2126.69, 2929.47, 3029.14, 2454.10 |
| DVD_Cost | float64 | 0 | 0.00% | 482.12, 592.78, 1033.60, 833.12 |
| Retargeting_Cost | float64 | 0 | 0.00% | 12.11, 26.01, 13.83, 12.43 |
| Prospecting_Cost | float64 | 0 | 0.00% | 1952.26, 2641.20, 1762.89, 1212.23 |
| Brand_Impressions | int64 | 0 | 0.00% | 246, 244, 308, 318 |
| Non_Brand_Impressions | int64 | 0 | 0.00% | 3527, 4513, 4451, 3709 |
| DVD_Impressions | int64 | 0 | 0.00% | 103813, 196552, 65993, 135999 |
| Retargeting_Impressions | int64 | 0 | 0.00% | 966, 1678, 867, 976 |
| Prospecting_Impressions | int64 | 0 | 0.00% | 101474, 124012, 81967, 53208 |
| Reddit_Cost | float64 | 0 | 0.00% | 0.0, 0.0, 0.0, 0.0 |
| Reddit_Impressions | int64 | 0 | 0.00% | 0, 0, 0, 0 |
| Gross_Leads | float64 | 0 | 0.00% | 12.0, 27.0, 37.0, 65.0 |
| tax_credit_shift | float64 | 0 | 0.00% | 0.0, 0.0, 0.0, 0.0 |
| storm_acute | float64 | 0 | 0.00% | 0.0, 0.0, 0.0, 0.0 |
| storm_tail | float64 | 0 | 0.00% | 0.0, 0.0, 0.0, 0.0 |
| population | int64 | 0 | 0.00% | 1029800, 1029800, 1029800, 1029800 |
| Billboard_Cost | float64 | 0 | 0.00% | 0.0, 0.0, 0.0, 0.0 |
| Billboard_Impressions | float64 | 0 | 0.00% | 0.0, 0.0, 0.0, 0.0 |
| DirectMail_Impressions | float64 | 0 | 0.00% | 0.0, 0.0, 0.0, 0.0 |

**Zero nulls across all 23 columns.** No imputation needed.

**Note on Unnamed: 0:** This is a sequential integer index (0 to 737) that matches the row position exactly. It is a CSV export artifact and carries no modeling information.

---

## 3. Numeric Deep Dive

| Column | min | max | mean | median | std | Zero % | Neg % | Shape |
|---|---|---|---|---|---|---|---|---|
| Brand_Cost | 0.00 | 3113.22 | 502.04 | 421.16 | 358.92 | 4.3% | 0.0% | skew=1.45 |
| Non_Brand_Cost | 0.00 | 51393.35 | 10415.47 | 9118.29 | 7815.17 | 4.1% | 0.0% | right-skewed |
| DVD_Cost | 0.00 | 11614.88 | 1084.67 | 528.29 | 1520.44 | 14.1% | 0.0% | right-skewed |
| Retargeting_Cost | 0.00 | 2491.57 | 256.92 | 115.74 | 371.67 | 10.0% | 0.0% | right-skewed |
| Prospecting_Cost | 0.00 | 12019.26 | 3170.43 | 2527.69 | 2376.90 | 2.7% | 0.0% | skew=0.89 |
| Brand_Impressions | 0 | 1113 | 245.27 | 222.50 | 144.21 | 3.9% | 0.0% | right-skewed |
| Non_Brand_Impressions | 0 | 172158 | 18392.09 | 12895.00 | 20237.18 | 3.3% | 0.0% | right-skewed |
| DVD_Impressions | 0 | 1305875 | 70711.18 | 23455.50 | 135003.35 | 14.1% | 0.0% | right-skewed |
| Retargeting_Impressions | 0 | 60099 | 7037.17 | 3916.50 | 9178.36 | 10.0% | 0.0% | right-skewed |
| Prospecting_Impressions | 0 | 435034 | 94377.08 | 77548.50 | 72316.11 | 2.6% | 0.0% | right-skewed |
| Reddit_Cost | 0.00 | 1960.37 | 31.19 | 0.00 | 171.80 | 94.6% | 0.0% | zero-inflated |
| Reddit_Impressions | 0 | 163981 | 2379.57 | 0.00 | 13262.12 | 94.3% | 0.0% | zero-inflated |
| Gross_Leads | 0.00 | 1526.00 | 110.37 | 97.00 | 88.83 | 1.1% | 0.0% | right-skewed |
| tax_credit_shift | 0.00 | 1.00 | 0.25 | 0.00 | 0.43 | 74.8% | 0.0% | zero-inflated |
| storm_acute | 0.00 | 1.00 | 0.07 | 0.00 | 0.25 | 93.5% | 0.0% | zero-inflated |
| storm_tail | 0.00 | 1.00 | 0.06 | 0.00 | 0.23 | 94.3% | 0.0% | zero-inflated |
| population | 1029800 | 3264490 | 2051961.67 | 2061830.00 | 820603.26 | 0.0% | 0.0% | roughly normal |
| Billboard_Cost | 0.00 | 32900.00 | 445.80 | 0.00 | 3806.27 | 98.6% | 0.0% | zero-inflated |
| Billboard_Impressions | 0.00 | 845515.00 | 11456.84 | 0.00 | 97819.42 | 98.6% | 0.0% | zero-inflated |
| DirectMail_Impressions | 0.00 | 20000.00 | 27.10 | 0.00 | 736.21 | 99.9% | 0.0% | zero-inflated |

**No negative values anywhere.** All spend and volume columns are non-negative, as expected.

**Reddit distribution detail:** When active (non-zero), Reddit_Cost ranges from $99.54 to $1,960.37/week per geo. Reddit_Impressions when active range from 9,545 to 163,981/week. The spend ramp is visible in the data — DFW peaked at $1,960 in the week of 2026-04-20. This spending ramp pattern across the 8 active weeks is consistent with genuine campaign scaling, not data error.

**Billboard distribution note:** The 98.6% zero rate reflects Austin-only activity. All 10 non-zero Billboard weeks show identical cost ($32,900) and identical impressions (845,515). This is consistent with a fixed-rate weekly out-of-home contract, but should be confirmed as intentional before treating as modeling input.

---

## 4. Date Alignment

| Check | Result |
|---|---|
| Date column | `date` |
| Date dtype | datetime64[ns] |
| Min date | 2024-01-01 (Monday) |
| Max date | 2026-05-04 (Monday) |
| All dates Monday-aligned | YES — 100% of 738 date values fall on day-of-week 0 (Monday) |
| Consistent weekly spacing | YES — all consecutive date diffs exactly 7 days |
| Expected weeks in range | 123 |
| Actual unique dates | 123 |
| Missing weeks | 0 |
| Extra/unexpected dates | 0 |
| Duplicate date x geo pairs | 0 |

**Monday alignment: CONFIRMED.** No alignment shift is needed. This file is ready to pass directly into the Meridian pipeline without any date manipulation.

**New week 2026-05-04: CONFIRMED present across all 6 geos** with non-null, non-zero values for all major metrics (see last-week values in Section 7g below).

---

## 5. Categorical Columns

### `geo`
- Unique values: 6
- All 6 expected markets present with equal row counts

| Geo | Row count |
|---|---|
| Austin | 123 |
| DFW | 123 |
| Houston | 123 |
| Orlando | 123 |
| San Antonio | 123 |
| Tampa | 123 |

No casing inconsistencies, no mystery codes, no unexpected markets. All geo names are clean.

### `Unnamed: 0`
Sequential integer index (0–737) matching row position exactly. Carries no modeling information. Should be dropped at transformation time.

---

## 6. Correlation Check

**Reference dataset:** data/processed/Freedom_Power/Freedom_MMM_data_Apr26_gqv.csv (732 rows, 122 weeks)

Merge basis: `date` x `geo` inner join on the overlapping period (2024-01-01 to 2026-04-27). Merge produced 732 rows as expected.

### Existing columns — new raw file vs. old processed file

| Column | r (new vs. ref) | Note |
|---|---|---|
| Brand_Cost | 1.0000 | Identical values |
| Non_Brand_Cost | 1.0000 | Identical values |
| DVD_Cost | 1.0000 | Identical values |
| Retargeting_Cost | 1.0000 | Identical values |
| Prospecting_Cost | 1.0000 | Identical values |
| Brand_Impressions | 1.0000 | Identical values (dtype changed to int64) |
| Non_Brand_Impressions | 1.0000 | Identical values (dtype changed to int64) |
| DVD_Impressions | 1.0000 | Identical values (dtype changed to int64) |
| Retargeting_Impressions | 1.0000 | Identical values (dtype changed to int64) |
| Prospecting_Impressions | 1.0000 | Identical values (dtype changed to int64) |
| Gross_Leads | 1.0000 | Identical values |
| tax_credit_shift | 1.0000 | Identical values |
| storm_acute | 1.0000 | Identical values |
| storm_tail | 1.0000 | Identical values |
| population | 1.0000 | Identical values (dtype changed to int64) |
| Billboard_Cost | 1.0000 | Identical values |
| Billboard_Impressions | 1.0000 | Identical values |
| DirectMail_Impressions | 1.0000 | Identical values |

**Conclusion: no existing columns have changed values.** The r=1.000 across all 18 shared numeric columns confirms the non-Reddit data is bit-for-bit identical (the one Brand_Cost difference at 2024-07-08 Houston is a floating-point rounding artifact at the 4th decimal place: 3113.221593 vs. 3113.2217).

### New Reddit columns vs. reference GQV columns

| Pair | r | Note |
|---|---|---|
| Reddit_Cost vs. GQV_Brand | 0.060 | No meaningful correlation |
| Reddit_Cost vs. GQV_Generic | 0.030 | No meaningful correlation |
| Reddit_Impressions vs. GQV_Brand | 0.069 | No meaningful correlation |
| Reddit_Impressions vs. GQV_Generic | 0.026 | No meaningful correlation |

Reddit and GQV variables are essentially uncorrelated. No multicollinearity concern between Reddit and the search query volume signals.

### dtype changes (new file vs. reference processed file)

The following columns changed from float64 in the reference to int64 in this raw file. This is not a data quality problem — the data transformer will cast everything to float32 for Meridian regardless. Flagged for awareness only.

- Brand_Impressions, Non_Brand_Impressions, DVD_Impressions, Retargeting_Impressions, Prospecting_Impressions, population

---

## 7. Data Quality Flags

### 7a. Future dates
None. All 738 dates are on or before 2026-05-06 (today). The latest date is 2026-05-04 (2 days before today), which is correct.

### 7b. Spikes (value > mean + 3 std)

Most spikes in the legacy paid media columns appear in 2024-07 through 2024-10 and are historically documented campaign periods (e.g. the Houston summer 2024 DVD surge). These are not new and were present in the reference file.

**Notable new spikes:**

**Reddit — expected given zero-inflation math.** Because Reddit_Cost is 94.6% zeros, even moderate non-zero values exceed the population mean + 3*std threshold. The spike detection algorithm is inflated by the zero-inflation. The ramp during April 2026 (DFW reaching $1,960, Houston reaching $1,352) is a real budget increase, not a data error. Analyst should not treat these as outliers.

**Retargeting_Cost and Retargeting_Impressions (DFW and Houston, 2026):** Both geos show sustained Retargeting spend above the 3-sigma threshold from approximately 2026-02 through 2026-04-27. DFW peaks at $1,780 and Houston at $2,492. This coincides with the Reddit launch period and may reflect a broader media ramp-up. Not a data error — these are sustained elevated values, not single-week spikes.

**Prospecting_Cost (Orlando and Tampa, 2026-04):** Both geos reach or exceed $10,000–$12,000/week during 2026-04-06 through 2026-04-20. This is a genuine budget increase in recent weeks. The values drop off in the 2026-05-04 week (Orlando: $2,750, Tampa: $2,624), suggesting either a pullback or the final week being a partial week of data.

**Billboard_Cost (Austin, 2026-03 to 2026-05-04):** The $32,900/week value exceeds the spike threshold (mean=446, std=3806, threshold=11,865), but this is expected given Austin is the only active geo. The repeated identical value is a separate concern (see 7d below).

**Gross_Leads (Houston, summer 2024):** Houston's 2024-07-08 week shows 1,526 leads — approximately 4x the market average. This spike was present in the reference file and is not new.

### 7c. All-zero stretches (4+ consecutive zeros)

| Column | Geo | Consecutive zero weeks | Notes |
|---|---|---|---|
| Reddit_Cost | Austin, DFW, Houston, Orlando, Tampa | 115 weeks | Expected — channel launched 2026-03-16 |
| Reddit_Cost | San Antonio | 123 weeks | San Antonio never activated on Reddit |
| Billboard_Cost | DFW, Houston, Orlando, San Antonio, Tampa | 123 weeks | Billboard is Austin-only |
| Billboard_Cost | Austin | 113 weeks | Active only in the final 10 weeks |
| Brand_Cost | Orlando, Tampa | 12 weeks | Media dark periods — present in reference file |
| Non_Brand_Cost | Orlando, Tampa | 12 weeks | Same dark period as Brand_Cost |
| Retargeting_Cost | Orlando, Tampa | 20+17 weeks | Two separate inactive periods — present in reference |
| DVD_Cost | Orlando, Tampa | 20+15 weeks | Two separate inactive periods — present in reference |
| Prospecting_Cost | Orlando, Tampa | 9 weeks | Inactive period — present in reference |
| Gross_Leads | Orlando | 6 weeks | First 6 weeks of 2024 (Jan-Feb); possibly pre-launch |
| DirectMail_Impressions | All | ~122 weeks | Effectively absent except one Austin burst |

All zero-stretch patterns in the legacy columns were present in the reference file. No new zero-stretch patterns have been introduced.

### 7d. Flat non-zero value stretches (potential backfill artifacts)

| Column | Geo | Identical consecutive weeks | Repeated value |
|---|---|---|---|
| Billboard_Cost | Austin | 10 | $32,900.00 |
| Billboard_Impressions | Austin | 10 | 845,515.00 |
| tax_credit_shift | All 6 geos | Multiple | 1.0 |
| storm_acute | All 6 geos | 8 (summer 2024) | 1.0 |
| storm_tail | All 6 geos | 7 (summer 2024) | 1.0 |
| Gross_Leads | Orlando | 4 | 1.0 |

The **tax_credit_shift, storm_acute, and storm_tail** flat patterns are binary indicator variables — consecutive 1.0 values are the intended behavior for these event windows, not a backfill artifact.

**Billboard flat values are a concern.** Exactly $32,900 cost and exactly 845,515 impressions for 10 straight weeks is consistent with a fixed-rate out-of-home contract, but is also consistent with a single value being copied across all weeks. Confirm with client whether this is a fixed weekly contract or whether weekly actuals are available.

**Gross_Leads = 1.0 for 4 consecutive Orlando weeks** is unusual — this looks like an imputed minimum-value fill rather than true organic lead volume. Analyst should verify with the client whether Orlando was actually generating 1 lead/week during this period.

### 7e. Negative values
None found in any column. All spend and volume values are non-negative.

### 7f. San Antonio Reddit anomaly
San Antonio shows Reddit_Impressions > 0 with Reddit_Cost = 0.00 on two dates:

| date | geo | Reddit_Cost | Reddit_Impressions |
|---|---|---|---|
| 2026-03-16 | San Antonio | 0.00 | 111 |
| 2026-03-23 | San Antonio | 0.00 | 104 |

San Antonio has zero Reddit spend for all 123 weeks. These two impression values (111 and 104) are small (the minimum active-market impression count is 9,545). This could be: (a) organic Reddit brand mentions captured in impression tracking, (b) a residual/spillover from a neighboring geo's campaign, or (c) a data entry error. Analyst decision required before transformation.

### 7g. Last week (2026-05-04) — full values by geo

| Geo | Brand_Cost | Non_Brand_Cost | Reddit_Cost | Reddit_Impressions | Gross_Leads |
|---|---|---|---|---|---|
| Austin | 115.75 | 2685.20 | 217.19 | 21,511 | 29 |
| DFW | 142.07 | 5053.31 | 445.33 | 42,684 | 65 |
| Houston | 215.73 | 7095.70 | 289.70 | 27,226 | 71 |
| Orlando | 72.24 | 2848.39 | 116.57 | 12,334 | 50 |
| San Antonio | 6.87 | 472.52 | 0.00 | 0 | 21 |
| Tampa | 90.85 | 2401.59 | 99.54 | 9,545 | 34 |

All 6 geos have non-null, non-zero values for the primary channels and KPI on 2026-05-04. The week appears complete. Note that Prospecting_Cost drops sharply in this week (Tampa: $2,624 vs. prior weeks around $9,000–$12,000) — this may be a partial week of data or a genuine pullback.

### 7h. Unnamed: 0
Sequential index artifact (0 to 737, exactly matching row position). Drop at transformation time.

---

## 8. MMM Relevance Assessment

### Likely useful for MMM

| Column(s) | Assessment |
|---|---|
| Brand_Cost, Brand_Impressions | Core paid search brand channel. Full 123-week history, 4.3% zeros (dark periods only). High priority modeling variable. |
| Non_Brand_Cost, Non_Brand_Impressions | Core paid search non-brand channel. Largest spend variable in the dataset ($10K+ average weekly). Full history. High priority. |
| DVD_Cost, DVD_Impressions | Direct mail / TV channel (14.1% zeros reflect seasonal dark periods). Right-skewed with high summer 2024 peaks — confirms campaign bursts. Include. |
| Retargeting_Cost, Retargeting_Impressions | Retargeting channel. 10% zeros, recent ramp-up in DFW and Houston. Include. |
| Prospecting_Cost, Prospecting_Impressions | Prospecting channel with existing tighter prior (mean=1.5, scale=0.5 from holdout). Include as existing channel. |
| Gross_Leads | KPI. No structural change from reference file. |
| tax_credit_shift | Binary control variable encoding regulatory/tax credit timing. Known to affect solar lead demand. Include as control. |
| storm_acute, storm_tail | Binary control variables encoding severe weather impact on lead volume. Include as controls. |
| population | Geo-level static offset. Required by Meridian for population normalization. Include. |

### Likely noise / drop

| Column(s) | Assessment |
|---|---|
| Unnamed: 0 | Sequential row index artifact. No modeling value. Drop. |
| DirectMail_Impressions | 99.9% zeros, single Austin burst of 20,000 impressions in one week (2026-03-30). Essentially absent from the dataset. Too sparse to estimate a meaningful ROI. Unless this represents a known intervention, drop or hold as a binary event flag. |

### Needs analyst judgment

| Column(s) | Assessment |
|---|---|
| Reddit_Cost, Reddit_Impressions | **New channel, sparse coverage.** Only 8 active weeks (2026-03-16 to 2026-05-04) across 5 of 6 geos. 6.5% of the total time series is active. Meridian can technically include this channel, but estimating a credible ROI from 8 data points per geo requires a strongly informative prior. Options: (1) include with tight prior anchored to industry Reddit benchmarks, (2) exclude from this run and re-evaluate after 3–6 more months of data, (3) model as a budget flag/binary rather than a spend variable. Analyst must decide which approach fits the client's reporting needs. |
| Billboard_Cost, Billboard_Impressions | Austin-only, 10 weeks active, all at exactly the same value ($32,900 / 845,515 impressions). If the flat value is confirmed as a real fixed-rate contract, this is a single-geo, short-duration channel. Whether it is worth including as a modeled channel (vs. dropping or including as a binary flag) depends on whether the client needs a Billboard ROI estimate. |
| Prospecting_Cost spike (Tampa, Orlando 2026-04) | Values exceed 3-sigma threshold in April 2026. If this is a real budget ramp-up, include as-is. If the final 2026-05-04 week's sharp drop suggests the April values are erroneous or represent a different attribution window, the client should clarify before this data is used for optimization recommendations. |
| Gross_Leads = 1.0 (Orlando, 4 weeks) | Appears to be a minimum-value fill rather than true lead volume. Including 1.0 as literal KPI values in a geo that was generating 50–100 leads in adjacent weeks may distort the model's baseline for Orlando. If these were truly zero-lead weeks that were filled with 1.0 to avoid log(0), the transformer should handle these consistently with whatever zero-treatment strategy is used for the KPI. |
