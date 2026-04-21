# Transform Log: freedom_power / gsq
**Script:** `src/transforms/freedom_power_gsq.py`
**Input (GQV):** `data/raw/Freedom_Power/Freedom-GQVdata-Mar26.csv`
**Input (base):** `data/raw/Freedom_Power/Freedom_MMM_data_Mar26.csv`
**Output:** `data/processed/Freedom_Power/Freedom_MMM_data_Mar26_gqv.csv`

**EDA report:** `docs/eda/Freedom-GQVdata-Mar26_report.md`
**Date:** 2026-04-21

---

## Summary

Google Search Query Volume (BRAND and GENERIC labels) was filtered to the 6 active Freedom Power DMA markets, pivoted from long to wide format, and left-joined to the existing Freedom Power MMM dataset. The result is a drop-in replacement for the raw MMM CSV with two new control columns appended: `GQV_Brand` and `GQV_Generic`. The output preserves the full MMM date/geo scope (804 rows, 134 weeks × 6 geos) with zero rows added or removed.

---

## Decisions Made

| # | Decision | What | Why |
|---|---|---|---|
| 1 | GeoType filter | Kept `DMA_REGION` only; dropped `STATE` rows | The Freedom Power model operates at DMA level. STATE-level aggregations represent a different geographic scope and would not align to the model's geo dimension. |
| 2 | Non-model DMA filter | Kept only 6 model geos; dropped all other DMA rows | The GQV file covers 185 DMAs nationwide. Only the 6 active Freedom Power markets are relevant. Dropping unused geos is not a data loss — they were never part of the model frame. |
| 3 | QueryLabel pivot | Pivoted from long (one row per label) to wide (one column per label) | Pipeline expects one row per date × geo. The two labels (BRAND, GENERIC) become `GQV_Brand` and `GQV_Generic` columns. |
| 4 | Date rename | `ReportDate` → `date` | Matches the `date_column` in `configs/Freedom_Power.yaml`. |
| 5 | Geo name mapping | GQV `GeoName` strings → MMM `geo` short names (6 exact mappings) | MMM uses short names (e.g. `DFW`); GQV uses full DMA strings (e.g. `Dallas-Ft. Worth, TX`). Deterministic mapping, no ambiguity. |
| 6 | Join type | Left join on MMM base frame | MMM data is the authoritative date/geo scope. All 804 MMM rows are preserved. GQV provides the supplementary signal. |
| 7 | Forward-fill (Apr 2026) | Forward-filled `GQV_Brand` and `GQV_Generic` for 4 trailing weeks | GQV data ends 2026-03-30; MMM data extends to 2026-04-27. The 4 missing weeks (24 rows across 6 geos) were filled with the last available value per geo (Mar 30, 2026 observation). This is an assumption — see Analyst Review Required section. |
| 8 | No lag applied | GQV values used contemporaneously | Analyst confirmed: Meridian does not apply adstock to controls, and no manual lag is needed at this stage. Contemporaneous is the correct starting point. |
| 9 | No scaling applied | Raw indexed values preserved | BRAND (~0.0005 scale) and GENERIC (~0.5 scale) kept as-is. Meridian will fit separate coefficients to each; the scale difference does not cause a problem but may result in a much larger coefficient for GQV_Brand. Monitor after first dev run. |
| 10 | Column order | MMM columns preserved in original order, GQV columns appended at end | Minimises disruption to any downstream code that references columns positionally. |

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

No rows were dropped from the MMM base frame. Output retains all 804 MMM rows.

---

## Nulls Handled

| Column | Null count (pre-fill) | Approach | Flagged assumption? |
|---|---|---|---|
| `GQV_Brand` | 24 rows | Forward-fill per geo from last observation | ⚠️ Yes — see below |
| `GQV_Generic` | 24 rows | Forward-fill per geo from last observation | ⚠️ Yes — see below |

All other columns: 0 nulls (inherited from MMM base frame, which had no nulls).

---

## Analyst Review Required

**Forward-fill for 4 trailing Apr 2026 weeks**

The GQV export ends 2026-03-30. The MMM modeling data extends through 2026-04-27, leaving weeks of 2026-04-06, 2026-04-13, 2026-04-20, and 2026-04-27 without GQV data. These 4 weeks × 6 geos = 24 rows were forward-filled from the Mar 30 values.

This is the lowest-risk imputation: demand for energy/solar searches does not change dramatically week-to-week, so carrying the final observed value forward for 4 weeks is defensible. However, it is an assumption — the true Apr 2026 GQV values may differ.

**Options if this assumption is not acceptable:**
1. Pull a fresher GQV export from Google Ads that covers Apr 2026, re-run this script
2. Leave as NaN (Meridian handles missing control values, but this should be confirmed for the version in use)
3. Accept the forward-fill and note it in the model run log

---

## Output Schema

```
804 rows × 18 columns
```

| Column | Type | Source | Notes |
|---|---|---|---|
| `date` | datetime64 | MMM base | Monday-aligned weekly dates |
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
| `Gross_Leads` | float64 | MMM base | KPI |
| `tax_credit_shift` | float64 | MMM base | Existing control |
| `storm_date` | float64 | MMM base | Existing control |
| `population` | float64 | MMM base | Geo-level population |
| `GQV_Brand` | float64 | GQV (new) | min=0.000060, max=0.001870, mean=0.000574 |
| `GQV_Generic` | float64 | GQV (new) | min=0.0740, max=1.5422, mean=0.4920 |

**Validation results (all passed):**
- ✓ Row count matches MMM base (804)
- ✓ Zero NaN in GQV_Brand and GQV_Generic
- ✓ All dates Monday-aligned
- ✓ No column names containing spaces
