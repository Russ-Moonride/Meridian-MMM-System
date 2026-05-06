# Transform Log: freedom_power / gsq
**Script:** `src/transforms/freedom_power_gsq.py`
**Input (GQV):** `data/raw/Freedom_Power/Freedom-GQVdata-Mar26.csv`
**Input (base):** `data/raw/Freedom_Power/Freedom_MMM_data_Apr26.csv`
**Output:** `data/processed/Freedom_Power/Freedom_MMM_data_Apr26_gqv.csv`

**EDA report:** `docs/eda/Freedom_MMM_data_Apr26_report.md`
**Date:** 2026-05-06 (updated; originally 2026-04-21)

---

## Summary

Google Search Query Volume (BRAND and GENERIC labels) was filtered to the 6 active Freedom Power DMA markets, pivoted from long to wide format, and left-joined to the Freedom Power MMM dataset (Apr26 vintage). The result is a drop-in replacement for the raw MMM CSV with two new control columns appended: `GQV_Brand` and `GQV_Generic`. The output preserves the full MMM date/geo scope (738 rows, 123 weeks × 6 geos, 2024-01-01 through 2026-05-04) with zero rows added or removed.

**Updated 2026-05-06:** Base frame updated to Apr26 data (738 rows, extended through 2026-05-04). Reddit channel added to base frame (Reddit_Cost and Reddit_Impressions). San Antonio data artifact corrected. YoY estimation extended by one additional week (2026-05-04 → 2025-05-05).

---

## Decisions Made

| # | Decision | What | Why |
|---|---|---|---|
| 1 | GeoType filter | Kept `DMA_REGION` only; dropped `STATE` rows | The Freedom Power model operates at DMA level. STATE-level aggregations represent a different geographic scope and would not align to the model's geo dimension. |
| 2 | Non-model DMA filter | Kept only 6 model geos; dropped all other DMA rows | The GQV file covers 185 DMAs nationwide. Only the 6 active Freedom Power markets are relevant. Dropping unused geos is not a data loss — they were never part of the model frame. |
| 3 | QueryLabel pivot | Pivoted from long (one row per label) to wide (one column per label) | Pipeline expects one row per date × geo. The two labels (BRAND, GENERIC) become `GQV_Brand` and `GQV_Generic` columns. |
| 4 | Date rename | `ReportDate` → `date` | Matches the `date_column` in `configs/Freedom_Power.yaml`. |
| 5 | Geo name mapping | GQV `GeoName` strings → MMM `geo` short names (6 exact mappings) | MMM uses short names (e.g. `DFW`); GQV uses full DMA strings (e.g. `Dallas-Ft. Worth, TX`). Deterministic mapping, no ambiguity. |
| 6 | Join type | Left join on MMM base frame | MMM data is the authoritative date/geo scope. All 738 MMM rows are preserved. GQV provides the supplementary signal. |
| 7 | YoY estimation for 5 trailing weeks | Estimated `GQV_Brand` and `GQV_Generic` for 5 missing Apr–May 2026 weeks using YoY adjustment | GQV data ends 2026-03-30; MMM data extends to 2026-05-04. The 5 missing weeks × 6 geos = 30 rows estimated as: `GQV[2025 same-week] × ratio_Q1[geo, label]`, where `ratio_Q1 = mean(Q1-2026) / mean(Q1-2025)`. See Analyst Review Required. |
| 8 | Week mapping for 2026-05-04 | Mapped 2026-05-04 → 2025-05-05 | Added with the Apr26 data update. Verified that 2025-05-05 has observations for all 6 model geos in the GQV file. |
| 9 | San Antonio Reddit_Impressions zeroed | Set Reddit_Impressions = 0 for San Antonio on 2026-03-16 and 2026-03-23 | These 2 rows had Reddit_Impressions > 0 but Reddit_Cost = $0. No spend was placed in San Antonio in those weeks; the impressions are a data artifact (likely misattributed geo). Zeroing is consistent with how zero-spend weeks are represented throughout the dataset. |
| 10 | No lag applied | GQV values used contemporaneously | Analyst confirmed: Meridian does not apply adstock to controls, and no manual lag is needed at this stage. |
| 11 | No scaling applied | Raw indexed values preserved | BRAND (~0.0006 scale) and GENERIC (~0.5 scale) kept as-is. Meridian will fit separate coefficients to each. Monitor coefficient magnitudes after first dev run. |
| 12 | Column order | MMM columns preserved in original order, GQV columns appended at end | Minimises disruption to any downstream code that references columns positionally. |

---

## Column Rename Map

| Original column | Renamed to | Notes |
|---|---|---|
| `ReportDate` | `date` | Matches config `date_column` |
| `IndexedQueryVolume` (BRAND rows) | `GQV_Brand` | After pivot |
| `IndexedQueryVolume` (GENERIC rows) | `GQV_Generic` | After pivot |
| `GeoName` | *(dropped)* | Replaced by mapped `geo` column |
| `TimeGranularity` | *(dropped)* | Constant column (`WEEKLY_MONDAY`) — zero information |
| `GeoCriteriaId` | *(dropped)* | Google internal numeric ID — not used in pipeline |
| `GeoType` | *(dropped)* | Used for filtering only; not needed in output |
| `QueryLabel` | *(dropped)* | Replaced by pivot into two columns |

---

## Rows Removed

| Filter step | Rows before | Rows after | Rows removed | Reason |
|---|---|---|---|---|
| GeoType = DMA_REGION | 50,823 | 38,452 | 12,371 | STATE rows — wrong geographic aggregation level |
| Model geos only | 38,452 | 1,584 | 36,868 | Non-model DMAs (179 geos) — not in Freedom Power model |
| **Total GQV rows dropped** | 50,823 | 1,584 | **49,239** | |

No rows were dropped from the MMM base frame. Output retains all 738 MMM rows.

**Values zeroed (not dropped):** Reddit_Impressions set to 0 for 2 San Antonio rows (2026-03-16, 2026-03-23) where Reddit_Cost = $0. These rows are retained; only the Impressions value was corrected.

---

## Nulls Handled

| Column | Null count (pre-fill) | Approach | Flagged assumption? |
|---|---|---|---|
| `GQV_Brand` | 30 rows (5 missing weeks × 6 geos) | YoY-adjusted estimation from 2025 same-week observations | Yes — see below |
| `GQV_Generic` | 30 rows (5 missing weeks × 6 geos) | YoY-adjusted estimation from 2025 same-week observations | Yes — see below |

All other columns: 0 nulls (inherited from MMM base frame, which had no nulls).

Note: The Apr26 update increased the null count from 24 (4 missing weeks) to 30 (5 missing weeks) before estimation. The estimation method is unchanged.

---

## Analyst Review Required

**YoY estimation for 5 trailing Apr–May 2026 weeks**

The GQV export ends 2026-03-30. The MMM modeling data now extends through 2026-05-04, leaving weeks 2026-04-06, 2026-04-13, 2026-04-20, 2026-04-27, and 2026-05-04 without observed GQV data. These 5 weeks × 6 geos = 30 rows were estimated using the YoY adjustment method: `GQV[2026 estimate] = GQV[2025 same-week] × ratio_Q1[geo, label]`.

This is a stronger estimate than the prior forward-fill approach — it uses the actual same-calendar-week signal from 2025, adjusted for the Q1-2026/Q1-2025 trend per geo and label. However, it is still an assumption. The true Apr–May 2026 GQV values may differ if there was unusual search activity in those weeks.

YoY ratios for reference (Q1-2026 / Q1-2025):
- Austin BRAND: 1.69, Austin GENERIC: 0.96
- DFW BRAND: 0.82, DFW GENERIC: 0.94
- Houston BRAND: 1.48, Houston GENERIC: 0.96
- Orlando BRAND: 0.67, Orlando GENERIC: 0.97
- San Antonio BRAND: 0.79, San Antonio GENERIC: 0.99
- Tampa BRAND: 0.75, Tampa GENERIC: 0.99

**Options if this assumption is not acceptable:**
1. Pull a fresher GQV export from Google Ads that covers Apr–May 2026, re-run this script (preferred)
2. Leave as NaN (Meridian handles missing control values, but confirm for the version in use)
3. Accept the YoY estimates and note it in the model run log

**San Antonio Reddit_Impressions zero-out**

2 rows (2026-03-16 and 2026-03-23) had Reddit_Impressions > 0 with Reddit_Cost = $0. This was treated as a data artifact and the Impressions values were zeroed in the script. If Reddit did run in San Antonio in those weeks with no measurable spend (e.g. organic/earned impressions counted against the campaign), this zeroing would be incorrect. Confirm with media team before the next production run.

---

## Output Schema

```
738 rows × 24 columns
```

| Column | Type | Source | Notes |
|---|---|---|---|
| `date` | datetime64 | MMM base | Monday-aligned weekly dates, 2024-01-01 to 2026-05-04 |
| `geo` | object | MMM base | 6 DMA markets |
| `Brand_Cost` | float64 | MMM base | |
| `Non_Brand_Cost` | float64 | MMM base | |
| `DVD_Cost` | float64 | MMM base | |
| `Retargeting_Cost` | float64 | MMM base | |
| `Prospecting_Cost` | float64 | MMM base | |
| `Brand_Impressions` | float64 | MMM base | |
| `Non_Brand_Impressions` | float64 | MMM base | |
| `DVD_Impressions` | float64 | MMM base | |
| `Retargeting_Impressions` | float64 | MMM base | |
| `Prospecting_Impressions` | float64 | MMM base | |
| `Reddit_Cost` | float64 | MMM base | New channel added Apr26; ~94% zeros; active from 2026-03-16 |
| `Reddit_Impressions` | float64 | MMM base | San Antonio artifact corrected (2 rows zeroed) |
| `Gross_Leads` | float64 | MMM base | KPI |
| `tax_credit_shift` | float64 | MMM base | Existing control |
| `storm_acute` | float64 | MMM base | Existing control (renamed from storm_date in Apr26 data) |
| `storm_tail` | float64 | MMM base | Existing control (new in Apr26 data) |
| `population` | float64 | MMM base | Geo-level population |
| `Billboard_Cost` | float64 | MMM base | |
| `Billboard_Impressions` | float64 | MMM base | |
| `DirectMail_Impressions` | float64 | MMM base | |
| `GQV_Brand` | float64 | GQV (computed) | min=0.000060, max=0.001870, mean=0.000589 |
| `GQV_Generic` | float64 | GQV (computed) | min=0.0740, max=1.5422, mean=0.4997 |

**Validation results (all passed — 2026-05-06 run):**
- Row count matches MMM base (738)
- Zero NaN in GQV_Brand and GQV_Generic
- All dates Monday-aligned
- No column names containing spaces
