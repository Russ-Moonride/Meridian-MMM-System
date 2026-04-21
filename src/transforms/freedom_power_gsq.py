"""
Transform: freedom_power / gsq (Google Search Query Volume)
Input:  data/raw/Freedom_Power/Freedom-GQVdata-Mar26.csv
        data/raw/Freedom_Power/Freedom_MMM_data_Mar26.csv  (base frame)
Output: data/processed/Freedom_Power/Freedom_MMM_data_Mar26_gqv.csv

Decisions and assumptions: see docs/eda/freedom_power_gsq_transform_log.md
"""

import pandas as pd
from pathlib import Path

GQV_RAW   = Path("data/raw/Freedom_Power/Freedom-GQVdata-Mar26.csv")
MMM_RAW   = Path("data/raw/Freedom_Power/Freedom_MMM_data_Mar26.csv")
OUT_PATH  = Path("data/processed/Freedom_Power/Freedom_MMM_data_Mar26_gqv.csv")

# Exact mapping: MMM geo names → GQV DMA GeoName strings
GEO_MAP = {
    "Austin":      "Austin, TX",
    "DFW":         "Dallas-Ft. Worth, TX",
    "Houston":     "Houston, TX",
    "Orlando":     "Orlando-Daytona Beach-Melbourne, FL",
    "San Antonio": "San Antonio, TX",
    "Tampa":       "Tampa-St Petersburg (Sarasota), FL",
}
REVERSE_GEO = {v: k for k, v in GEO_MAP.items()}
MODEL_GQV_GEOS = list(GEO_MAP.values())


def load_and_filter_gqv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    rows_raw = len(df)

    # Keep DMA_REGION only — model is DMA-level; STATE rows are a different aggregation
    df = df[df["GeoType"] == "DMA_REGION"].copy()
    rows_after_geotype = len(df)

    # Keep only the 6 active Freedom Power model geos
    df = df[df["GeoName"].isin(MODEL_GQV_GEOS)].copy()
    rows_after_geo_filter = len(df)

    print(f"[GQV load]  Raw rows:              {rows_raw:,}")
    print(f"            After DMA_REGION filter: {rows_after_geotype:,}  "
          f"(-{rows_raw - rows_after_geotype:,} STATE rows dropped)")
    print(f"            After model-geo filter:  {rows_after_geo_filter:,}  "
          f"(-{rows_after_geotype - rows_after_geo_filter:,} non-model DMA rows dropped)")

    df["ReportDate"] = pd.to_datetime(df["ReportDate"])
    df["geo"] = df["GeoName"].map(REVERSE_GEO)
    return df


def pivot_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    wide = df.pivot_table(
        index=["ReportDate", "geo"],
        columns="QueryLabel",
        values="IndexedQueryVolume",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={
        "ReportDate": "date",
        "BRAND":      "GQV_Brand",
        "GENERIC":    "GQV_Generic",
    })
    return wide[["date", "geo", "GQV_Brand", "GQV_Generic"]]


def forward_fill_missing_weeks(merged: pd.DataFrame) -> pd.DataFrame:
    missing_mask = merged["GQV_Brand"].isna()
    n_missing = missing_mask.sum()
    if n_missing == 0:
        return merged

    missing_dates = sorted(merged.loc[missing_mask, "date"].unique())
    print(f"\n[ffill]  {n_missing} rows missing GQV (across {len(missing_dates)} weeks):")
    for d in missing_dates:
        print(f"         {pd.Timestamp(d).date()}")
    print("         Applying forward-fill per geo from last available GQV observation.")

    # Sort and ffill within each geo
    merged = merged.sort_values(["geo", "date"]).reset_index(drop=True)
    merged[["GQV_Brand", "GQV_Generic"]] = (
        merged.groupby("geo")[["GQV_Brand", "GQV_Generic"]]
        .transform(lambda s: s.ffill())
    )

    still_missing = merged["GQV_Brand"].isna().sum()
    if still_missing > 0:
        print(f"  ⚠️  {still_missing} rows still NaN after ffill — check for leading NaN gaps")
    else:
        print("         Forward-fill complete — 0 NaN remaining.")

    return merged


def validate(df: pd.DataFrame, mmm_rows: int) -> None:
    assert len(df) == mmm_rows, f"Row count mismatch: expected {mmm_rows}, got {len(df)}"
    assert df["GQV_Brand"].isna().sum() == 0, "NaN in GQV_Brand after transform"
    assert df["GQV_Generic"].isna().sum() == 0, "NaN in GQV_Generic after transform"
    assert df["date"].dt.dayofweek.eq(0).all(), "Non-Monday dates in output"
    for col in df.columns:
        assert " " not in col, f"Column name contains space: '{col}'"
    print("\n[validate]  All checks passed ✓")


def main():
    # ── Load base frame ────────────────────────────────────────────────────────
    mmm = pd.read_csv(MMM_RAW)
    mmm["date"] = pd.to_datetime(mmm["date"])
    mmm_rows = len(mmm)
    print(f"[MMM base]  {mmm_rows:,} rows  |  "
          f"{mmm['date'].min().date()} → {mmm['date'].max().date()}  |  "
          f"geos: {sorted(mmm['geo'].unique())}")

    # ── Load and filter GQV ────────────────────────────────────────────────────
    gqv_raw = load_and_filter_gqv(GQV_RAW)

    # ── Pivot BRAND / GENERIC to wide ─────────────────────────────────────────
    gqv_wide = pivot_to_wide(gqv_raw)
    print(f"\n[pivot]  GQV wide: {len(gqv_wide):,} rows  |  "
          f"cols: {list(gqv_wide.columns)}")

    # ── Left join: MMM is the base frame ──────────────────────────────────────
    merged = mmm.merge(gqv_wide, on=["date", "geo"], how="left")
    print(f"\n[join]  Merged rows: {len(merged):,}  "
          f"(NaN GQV_Brand: {merged['GQV_Brand'].isna().sum()}, "
          f"GQV_Generic: {merged['GQV_Generic'].isna().sum()})")

    # ── Forward-fill the 4 trailing Apr-2026 weeks ────────────────────────────
    merged = forward_fill_missing_weeks(merged)

    # ── Restore original MMM column order + append GQV columns ───────────────
    mmm_cols = list(mmm.columns)
    merged = merged[mmm_cols + ["GQV_Brand", "GQV_Generic"]]

    # ── Validate ──────────────────────────────────────────────────────────────
    validate(merged, mmm_rows)

    # ── Write ─────────────────────────────────────────────────────────────────
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_PATH, index=False)

    print(f"\n[done]  {len(merged):,} rows × {len(merged.columns)} columns → {OUT_PATH}")
    print(f"        Columns: {list(merged.columns)}")
    print(f"\n        GQV_Brand   — min: {merged['GQV_Brand'].min():.6f}  "
          f"max: {merged['GQV_Brand'].max():.6f}  "
          f"mean: {merged['GQV_Brand'].mean():.6f}")
    print(f"        GQV_Generic — min: {merged['GQV_Generic'].min():.4f}  "
          f"max: {merged['GQV_Generic'].max():.4f}  "
          f"mean: {merged['GQV_Generic'].mean():.4f}")


if __name__ == "__main__":
    main()
