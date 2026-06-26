"""
Refresh Janessa Leone processed dataset.

Automated sources:
  - BigQuery (paid media + revenue): janessa-leone GCP project
  - data/raw/janessa_leone/JL_ShopMy_*.csv   — ShopMy affiliate (Cost + Clicks)
  - data/raw/janessa_leone/JL_ShareASale_*.csv — AWIN/ShareASale affiliate (Cost + Clicks)

ShopMy and AWIN are sourced exclusively from CSVs — not from BigQuery.
Drop new affiliate CSV files in data/raw/janessa_leone/ before running.

Test mode (default):
  BQ pull limited to last 16 weeks. Affiliate CSVs still merged in full.
  Output: data/processed/janessa_leone/test_refresh.csv

Production mode (--prod):
  Full pull from 2024-01-01 to current date.
  Output: data/processed/janessa_leone/JL_mmm_data_{vintage}.csv

Usage:
    source .venv/bin/activate
    python scripts/refresh_janessa_leone.py           # test
    python scripts/refresh_janessa_leone.py --prod    # production
"""

import argparse
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

ROOT     = Path(__file__).resolve().parent.parent
PROC_DIR = ROOT / "data" / "processed" / "janessa_leone"

BQ_PROJECT    = "janessa-leone-462017"
BQ_START_DATE = "2024-01-01"

BF_DATES = [
    "2024-11-18", "2024-11-25", "2024-12-02",
    "2025-11-17", "2025-11-24", "2025-12-01",
]

BQ_QUERY_TEMPLATE = """
SELECT
  DATE_TRUNC(Date, WEEK(MONDAY))                                       AS date,
  SUM(CASE WHEN Type = "Brand"          THEN Cost ELSE 0 END)          AS Brand_Cost,
  SUM(CASE WHEN Type = "Non-Brand"      THEN Cost ELSE 0 END)          AS Non_Brand_Cost,
  SUM(CASE WHEN Type = "Brand Shopping" THEN Cost ELSE 0 END)          AS Brand_Shopping_Cost,
  SUM(CASE WHEN Type = "Prospecting"    THEN Cost ELSE 0 END)          AS Prospecting_Cost,
  SUM(CASE WHEN Type = "Retargeting"    THEN Cost ELSE 0 END)          AS Retargeting_Cost,
  SUM(CASE WHEN Type = "Remarketing"    THEN Cost ELSE 0 END)          AS Remarketing_Cost,
  SUM(CASE WHEN Type = "Pinterest"      THEN Cost ELSE 0 END)          AS Pinterest_Cost,
  SUM(CASE WHEN Type = "Brand"          THEN Impressions ELSE 0 END)   AS Brand_Impressions,
  SUM(CASE WHEN Type = "Non-Brand"      THEN Impressions ELSE 0 END)   AS Non_Brand_Impressions,
  SUM(CASE WHEN Type = "Brand Shopping" THEN Impressions ELSE 0 END)   AS Brand_Shopping_Impressions,
  SUM(CASE WHEN Type = "Prospecting"    THEN Impressions ELSE 0 END)   AS Prospecting_Impressions,
  SUM(CASE WHEN Type = "Retargeting"    THEN Impressions ELSE 0 END)   AS Retargeting_Impressions,
  SUM(CASE WHEN Type = "Remarketing"    THEN Impressions ELSE 0 END)   AS Remarketing_Impressions,
  SUM(CASE WHEN Type = "Pinterest"      THEN Impressions ELSE 0 END)   AS Pinterest_Impressions,
  -- ShopMy and AWIN are excluded — sourced from CSVs only
  SUM(Gross_Sales__Shopify)                                             AS Revenue
FROM `janessa-leone-462017.janessa_leone_segments.full_segments`
WHERE Date >= "{start_date}"
  AND Date < CURRENT_DATE()
GROUP BY date
ORDER BY date DESC
"""


RAW_DIR = ROOT / "data" / "raw" / "janessa_leone"


def pull_bq(start_date: str) -> pd.DataFrame:
    print(f"[BQ] Pulling paid media from {start_date} → today ...")
    client = bigquery.Client(project=BQ_PROJECT)
    df = client.query(BQ_QUERY_TEMPLATE.format(start_date=start_date)).to_dataframe()
    df["date"] = pd.to_datetime(df["date"])
    print(f"[BQ] {len(df):,} rows | {df['date'].min().date()} → {df['date'].max().date()}")
    return df


def _agg_affiliate_csv(pattern: str, cost_col: str, clicks_col: str) -> pd.DataFrame:
    """Load all CSVs matching pattern, dedup by date, aggregate to Monday weeks."""
    files = sorted(RAW_DIR.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No affiliate CSV found matching {RAW_DIR}/{pattern}")
    parts = []
    for f in files:
        df = pd.read_csv(f)
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=False)
        parts.append(df[["Date", "Cost", "Clicks"]])
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date"], keep="last")
    combined["date"] = combined["Date"] - pd.to_timedelta(combined["Date"].dt.dayofweek, unit="d")
    weekly = (
        combined.groupby("date")[["Cost", "Clicks"]].sum().reset_index()
        .rename(columns={"Cost": cost_col, "Clicks": clicks_col})
    )
    weekly = weekly[weekly["date"] >= BQ_START_DATE].copy()
    print(f"[affiliate] {cost_col}: {len(weekly)} weeks | "
          f"{(weekly[cost_col] > 0).sum()} non-zero | "
          f"total ${weekly[cost_col].sum():,.0f}")
    return weekly


def load_affiliates() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (shopmy_df, awin_df) — both weekly, Monday-aligned."""
    shopmy = _agg_affiliate_csv("JL_ShopMy_*.csv",     "ShopMy_Cost", "ShopMy_Impressions")
    awin   = _agg_affiliate_csv("JL_ShareASale_*.csv", "AWIN_Cost",   "AWIN_Impressions")
    return shopmy, awin


def add_controls(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["black_friday"] = df["date"].isin(pd.to_datetime(BF_DATES)).astype(int)
    return df


def validate(df: pd.DataFrame) -> bool:
    checks = [
        (pd.to_datetime(df["date"]).dt.dayofweek.eq(0).all(), "All dates are Monday-aligned"),
        (not df.duplicated(["date"]).any(),                   "No duplicate date rows"),
        ((df["Revenue"] >= 0).all(),                          "Revenue non-negative"),
        (df["Revenue"].sum() > 0,                             "Revenue has non-zero values"),
    ]
    all_passed = True
    for passed, label in checks:
        mark = "✓" if passed else "✗"
        print(f"  [{mark}] {label}")
        if not passed:
            all_passed = False
    return all_passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true",
                        help="Production mode: full pull from 2024-01-01, write to processed/")
    args = parser.parse_args()

    PROC_DIR.mkdir(parents=True, exist_ok=True)

    if args.prod:
        start_date = BQ_START_DATE
        print("=" * 60)
        print("MODE: PRODUCTION — full pull from 2024-01-01")
        print("=" * 60)
    else:
        start_date = (pd.Timestamp.today() - pd.DateOffset(weeks=16)).strftime("%Y-%m-%d")
        print("=" * 60)
        print(f"MODE: TEST — last 16 weeks (from {start_date})")
        print("=" * 60)

    # 1. BQ
    df = pull_bq(start_date)

    # 2. Affiliate CSVs (ShopMy + AWIN — not from BQ)
    print("\n[affiliate]")
    shopmy, awin = load_affiliates()
    df = df.merge(shopmy, on="date", how="left").merge(awin, on="date", how="left")
    df[["ShopMy_Cost", "ShopMy_Impressions", "AWIN_Cost", "AWIN_Impressions"]] = (
        df[["ShopMy_Cost", "ShopMy_Impressions", "AWIN_Cost", "AWIN_Impressions"]].fillna(0)
    )

    # 3. Controls
    df = add_controls(df)

    # 4. Column order
    df = df[[
        "date",
        "Brand_Cost", "Non_Brand_Cost", "Brand_Shopping_Cost", "Prospecting_Cost",
        "Retargeting_Cost", "Remarketing_Cost", "Pinterest_Cost", "ShopMy_Cost", "AWIN_Cost",
        "Brand_Impressions", "Non_Brand_Impressions", "Brand_Shopping_Impressions",
        "Prospecting_Impressions", "Retargeting_Impressions", "Remarketing_Impressions",
        "Pinterest_Impressions", "ShopMy_Impressions", "AWIN_Impressions",
        "Revenue", "black_friday",
    ]]

    # 5. Validate
    print("\n[validate]")
    ok = validate(df)
    if not ok:
        print("\n⚠️  Validation issues found — review before using in production.")

    # 6. Write
    model_end = df["date"].max()
    if args.prod:
        vintage  = model_end.strftime("%b%y")
        out_path = PROC_DIR / f"JL_mmm_data_{vintage}.csv"
    else:
        out_path = PROC_DIR / "test_refresh.csv"

    df.to_csv(out_path, index=False)

    print(f"\n[done] {len(df):,} rows × {len(df.columns)} cols → {out_path.relative_to(ROOT)}")
    print(f"       {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"       Columns: {list(df.columns)}")


if __name__ == "__main__":
    main()
