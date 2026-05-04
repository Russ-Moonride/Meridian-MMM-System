"""
Transform: freedom_power / gsq (Google Search Query Volume)
Input:  data/raw/Freedom_Power/Freedom-GQVdata-Mar26.csv
        data/raw/Freedom_Power/Freedom_MMM_data_Apr26.csv  (base frame)
Output: data/processed/Freedom_Power/Freedom_MMM_data_Apr26_gqv.csv

Missing GQV weeks (2026-04-06 → 2026-04-27) are estimated via YoY adjustment:
  estimate[geo, label, week] = gqv[geo, label, same_week_2025] × ratio_Q1[geo, label]
where ratio_Q1 = mean(Q1-2026) / mean(Q1-2025) per geo × label.

Decisions and assumptions: see docs/eda/freedom_power_gsq_transform_log.md
"""

import pandas as pd
from pathlib import Path

GQV_RAW  = Path("data/raw/Freedom_Power/Freedom-GQVdata-Mar26.csv")
MMM_RAW  = Path("data/raw/Freedom_Power/Freedom_MMM_data_Apr26.csv")
OUT_PATH = Path("data/processed/Freedom_Power/Freedom_MMM_data_Apr26_gqv.csv")

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

# Missing 2026 week → matching 2025 week (same position in April)
WEEK_MAP_2026_TO_2025 = {
    pd.Timestamp("2026-04-06"): pd.Timestamp("2025-04-07"),
    pd.Timestamp("2026-04-13"): pd.Timestamp("2025-04-14"),
    pd.Timestamp("2026-04-20"): pd.Timestamp("2025-04-21"),
    pd.Timestamp("2026-04-27"): pd.Timestamp("2025-04-28"),
}


def load_and_filter_gqv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    rows_raw = len(df)
    df = df[df["GeoType"] == "DMA_REGION"].copy()
    df = df[df["GeoName"].isin(MODEL_GQV_GEOS)].copy()
    print(f"[GQV load]  Raw: {rows_raw:,} → after DMA+geo filter: {len(df):,}")
    df["ReportDate"] = pd.to_datetime(df["ReportDate"])
    df["geo"] = df["GeoName"].map(REVERSE_GEO)
    return df


def compute_yoy_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Per geo × label: Q1-2026 mean / Q1-2025 mean."""
    q1_25 = df[(df["ReportDate"] >= "2025-01-01") & (df["ReportDate"] <= "2025-03-31")]
    q1_26 = df[(df["ReportDate"] >= "2026-01-01") & (df["ReportDate"] <= "2026-03-30")]
    mean_25 = q1_25.groupby(["geo", "QueryLabel"])["IndexedQueryVolume"].mean().rename("mean_25")
    mean_26 = q1_26.groupby(["geo", "QueryLabel"])["IndexedQueryVolume"].mean().rename("mean_26")
    ratios = pd.concat([mean_25, mean_26], axis=1)
    ratios["yoy_ratio"] = ratios["mean_26"] / ratios["mean_25"]
    print("\n[YoY ratios]  Q1-2026 / Q1-2025 per geo × label:")
    print(ratios[["mean_25", "mean_26", "yoy_ratio"]].to_string())
    return ratios.reset_index()


def build_extended_gqv(df: pd.DataFrame, ratios: pd.DataFrame) -> pd.DataFrame:
    """Append YoY-adjusted rows for the 4 missing Apr-2026 weeks."""
    appended = []
    for date_2026, date_2025 in WEEK_MAP_2026_TO_2025.items():
        week_2025 = df[df["ReportDate"] == date_2025]
        if week_2025.empty:
            print(f"  ⚠️  No 2025 data for {date_2025.date()} — skipping")
            continue
        week_est = week_2025.copy()
        week_est = week_est.merge(
            ratios[["geo", "QueryLabel", "yoy_ratio"]], on=["geo", "QueryLabel"], how="left"
        )
        week_est["IndexedQueryVolume"] = week_est["IndexedQueryVolume"] * week_est["yoy_ratio"]
        week_est["ReportDate"] = date_2026
        appended.append(week_est.drop(columns=["yoy_ratio"]))
        for _, row in week_est.iterrows():
            print(f"  {date_2026.date()}  {row['geo']:12s}  {row['QueryLabel']:7s}  "
                  f"base={week_2025.loc[week_2025['geo']==row['geo'], 'IndexedQueryVolume'].values[0]:.5f}"
                  f" × {row['yoy_ratio']:.3f} = {row['IndexedQueryVolume']:.5f}")

    if appended:
        extended = pd.concat([df] + appended, ignore_index=True)
    else:
        extended = df.copy()

    return extended


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
        "BRAND":   "GQV_Brand",
        "GENERIC": "GQV_Generic",
    })
    return wide[["date", "geo", "GQV_Brand", "GQV_Generic"]]


def validate(df: pd.DataFrame, mmm_rows: int) -> None:
    assert len(df) == mmm_rows, f"Row count mismatch: expected {mmm_rows}, got {len(df)}"
    assert df["GQV_Brand"].isna().sum() == 0, "NaN in GQV_Brand after transform"
    assert df["GQV_Generic"].isna().sum() == 0, "NaN in GQV_Generic after transform"
    assert df["date"].dt.dayofweek.eq(0).all(), "Non-Monday dates in output"
    for col in df.columns:
        assert " " not in col, f"Column name contains space: '{col}'"
    print("\n[validate]  All checks passed ✓")


def main():
    mmm = pd.read_csv(MMM_RAW)
    if "Unnamed: 0" in mmm.columns:
        mmm = mmm.drop(columns=["Unnamed: 0"])
    mmm["date"] = pd.to_datetime(mmm["date"])
    mmm_rows = len(mmm)
    print(f"[MMM base]  {mmm_rows:,} rows  |  "
          f"{mmm['date'].min().date()} → {mmm['date'].max().date()}  |  "
          f"geos: {sorted(mmm['geo'].unique())}")

    gqv_raw = load_and_filter_gqv(GQV_RAW)

    ratios = compute_yoy_ratios(gqv_raw)

    print(f"\n[extend]  Appending YoY-adjusted estimates for {len(WEEK_MAP_2026_TO_2025)} missing weeks:")
    gqv_extended = build_extended_gqv(gqv_raw, ratios)

    gqv_wide = pivot_to_wide(gqv_extended)
    print(f"\n[pivot]  GQV wide: {len(gqv_wide):,} rows | cols: {list(gqv_wide.columns)}")

    merged = mmm.merge(gqv_wide, on=["date", "geo"], how="left")
    nan_brand = merged["GQV_Brand"].isna().sum()
    print(f"\n[join]  Merged rows: {len(merged):,}  (NaN GQV_Brand: {nan_brand})")
    if nan_brand > 0:
        missing = merged[merged["GQV_Brand"].isna()][["date", "geo"]].drop_duplicates()
        print("  Rows with NaN GQV (pre-data-start or gap):")
        print(missing.to_string())
        # Backfill any pre-series leading NaNs with the first available observation per geo
        merged = merged.sort_values(["geo", "date"]).reset_index(drop=True)
        merged[["GQV_Brand", "GQV_Generic"]] = (
            merged.groupby("geo")[["GQV_Brand", "GQV_Generic"]]
            .transform(lambda s: s.bfill())
        )

    mmm_cols = list(mmm.columns)
    merged = merged[mmm_cols + ["GQV_Brand", "GQV_Generic"]]

    validate(merged, mmm_rows)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(OUT_PATH, index=False)

    print(f"\n[done]  {len(merged):,} rows × {len(merged.columns)} cols → {OUT_PATH}")
    print(f"        GQV_Brand   — min={merged['GQV_Brand'].min():.6f}  "
          f"max={merged['GQV_Brand'].max():.6f}  mean={merged['GQV_Brand'].mean():.6f}")
    print(f"        GQV_Generic — min={merged['GQV_Generic'].min():.4f}  "
          f"max={merged['GQV_Generic'].max():.4f}  mean={merged['GQV_Generic'].mean():.4f}")
    print(f"\n        Sample tail (last 8 rows):")
    print(merged[["date", "geo", "GQV_Brand", "GQV_Generic"]].tail(8).to_string(index=False))


if __name__ == "__main__":
    main()
