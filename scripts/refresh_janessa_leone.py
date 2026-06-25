"""
Refresh Janessa Leone processed dataset.

Automated sources:
  - BigQuery (paid media + revenue): janessa-leone GCP project

Manual columns to add after running:
  - ShopMy_Impressions  — populate with Clicks from ShopMy affiliate source
  - AWIN_Impressions    — populate with Clicks from AWIN affiliate source

Test mode (default):
  BQ pull limited to last 16 weeks.
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
  SUM(CASE WHEN Type = "ShopMy COGS"    THEN Cost ELSE 0 END)          AS ShopMy_Cost,
  SUM(CASE WHEN Type = "AWIN COGS"      THEN Cost ELSE 0 END)          AS AWIN_Cost,
  SUM(CASE WHEN Type = "Brand"          THEN Impressions ELSE 0 END)   AS Brand_Impressions,
  SUM(CASE WHEN Type = "Non-Brand"      THEN Impressions ELSE 0 END)   AS Non_Brand_Impressions,
  SUM(CASE WHEN Type = "Brand Shopping" THEN Impressions ELSE 0 END)   AS Brand_Shopping_Impressions,
  SUM(CASE WHEN Type = "Prospecting"    THEN Impressions ELSE 0 END)   AS Prospecting_Impressions,
  SUM(CASE WHEN Type = "Retargeting"    THEN Impressions ELSE 0 END)   AS Retargeting_Impressions,
  SUM(CASE WHEN Type = "Remarketing"    THEN Impressions ELSE 0 END)   AS Remarketing_Impressions,
  SUM(CASE WHEN Type = "Pinterest"      THEN Impressions ELSE 0 END)   AS Pinterest_Impressions,
  -- ShopMy_Impressions / AWIN_Impressions: omitted — populate manually with Clicks
  SUM(Gross_Sales__Shopify)                                             AS Revenue
FROM `janessa-leone-462017.janessa_leone_segments.full_segments`
WHERE Date >= "{start_date}"
  AND Date < CURRENT_DATE()
GROUP BY date
ORDER BY date DESC
"""


def pull_bq(start_date: str) -> pd.DataFrame:
    print(f"[BQ] Pulling paid media from {start_date} → today ...")
    client = bigquery.Client(project=BQ_PROJECT)
    df = client.query(BQ_QUERY_TEMPLATE.format(start_date=start_date)).to_dataframe()
    df["date"] = pd.to_datetime(df["date"])
    print(f"[BQ] {len(df):,} rows | {df['date'].min().date()} → {df['date'].max().date()}")
    return df


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

    # 2. Controls
    df = add_controls(df)

    # 3. Validate
    print("\n[validate]")
    ok = validate(df)
    if not ok:
        print("\n⚠️  Validation issues found — review before using in production.")

    # 4. Write
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
    print(f"\n⚠️  Next step: manually add ShopMy_Impressions and AWIN_Impressions (Clicks) to {out_path.name}")


if __name__ == "__main__":
    main()
