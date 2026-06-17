"""
Refresh Freedom Power Closes dataset (KPI = HubSpot_Closed).

Identical pipeline to refresh_freedom_power.py but pulls HubSpot_Closed
instead of Gross_Leads. Used to fit the downstream Closes MMM model.

Test mode (default):
  BQ pull limited to last 16 weeks for fast validation.
  Output: data/processed/Freedom_Power/test_refresh_closes.csv

Production mode (--prod):
  Full pull from 2024-01-01 to current date.
  Output: data/processed/Freedom_Power/Freedom_MMM_closes_{vintage}_gqv.csv

Usage:
    source .venv/bin/activate
    python scripts/refresh_freedom_power_closes.py           # test
    python scripts/refresh_freedom_power_closes.py --prod    # production
"""

import argparse
import re
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
from google.cloud import bigquery, storage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.transforms.freedom_billboard_correction import apply_corrections

# ── GCP ───────────────────────────────────────────────────────────────────────
BQ_PROJECT = "freedom-solar-406415"
GQV_BUCKET = "freedom_power_mmm"
GQV_PREFIX = "google-mmm/data/google-mmm-gqv/"

# ── Static constants ──────────────────────────────────────────────────────────
BQ_START_DATE = "2024-01-01"

GEOS_TO_DROP = frozenset(["Carolinas", "Denver", "Virginia", "Colorado Springs", "Richmond", "OOT"])

DMA_POPULATION = {
    "DFW":           3_264_490,
    "Houston":       2_797_420,
    "Tampa":         2_221_240,
    "Orlando":       1_902_420,
    "San Antonio":   1_096_400,
    "Austin":        1_029_800,
}

# GQV geo name mapping: model short name → Google DMA name
GEO_MAP = {
    "Austin":      "Austin, TX",
    "DFW":         "Dallas-Ft. Worth, TX",
    "Houston":     "Houston, TX",
    "Orlando":     "Orlando-Daytona Beach-Melbourne, FL",
    "San Antonio": "San Antonio, TX",
    "Tampa":       "Tampa-St Petersburg (Sarasota), FL",
}
REVERSE_GEO = {v: k for k, v in GEO_MAP.items()}

# ── BigQuery query ─────────────────────────────────────────────────────────────
# Solar + HVAC each carry paid media spend/impressions and Gross_Leads.
# Reddit carries only Reddit_Cost and Reddit_Impressions.
# All three are summed after the UNION to collapse Solar+HVAC rows per week/geo.
BQ_QUERY_TEMPLATE = """
WITH base AS (
  SELECT
    DATE_TRUNC(Date, WEEK(MONDAY)) AS date,
    Region AS geo,
    SUM(CASE WHEN Type = 'Brand'       THEN Cost ELSE 0 END) AS Brand_Cost,
    SUM(CASE WHEN Type = 'Non-Brand'   THEN Cost ELSE 0 END) AS Non_Brand_Cost,
    SUM(CASE WHEN Type = 'DVD'         THEN Cost ELSE 0 END) AS DVD_Cost,
    SUM(CASE WHEN Type = 'Retargeting' THEN Cost ELSE 0 END) AS Retargeting_Cost,
    SUM(CASE WHEN Type = 'Prospecting' THEN Cost ELSE 0 END) AS Prospecting_Cost,
    SUM(CASE WHEN Type = 'Brand'       THEN Impressions ELSE 0 END) AS Brand_Impressions,
    SUM(CASE WHEN Type = 'Non-Brand'   THEN Impressions ELSE 0 END) AS Non_Brand_Impressions,
    SUM(CASE WHEN Type = 'DVD'         THEN Impressions ELSE 0 END) AS DVD_Impressions,
    SUM(CASE WHEN Type = 'Retargeting' THEN Impressions ELSE 0 END) AS Retargeting_Impressions,
    SUM(CASE WHEN Type = 'Prospecting' THEN Impressions ELSE 0 END) AS Prospecting_Impressions,
    NULL AS Reddit_Cost,
    NULL AS Reddit_Impressions,
    SUM(HubSpot_Closed) AS HubSpot_Closed
  FROM `freedom_solar_agg.full_funnel_unmatched`
  WHERE Date >= "{start_date}" AND Region != "Other"
  GROUP BY date, geo

  UNION ALL

  SELECT
    DATE_TRUNC(Date, WEEK(MONDAY)) AS date,
    Region AS geo,
    SUM(CASE WHEN Type = 'Brand'       THEN Cost ELSE 0 END) AS Brand_Cost,
    SUM(CASE WHEN Type = 'Non-Brand'   THEN Cost ELSE 0 END) AS Non_Brand_Cost,
    SUM(CASE WHEN Type = 'DVD'         THEN Cost ELSE 0 END) AS DVD_Cost,
    SUM(CASE WHEN Type = 'Retargeting' THEN Cost ELSE 0 END) AS Retargeting_Cost,
    SUM(CASE WHEN Type = 'Prospecting' THEN Cost ELSE 0 END) AS Prospecting_Cost,
    SUM(CASE WHEN Type = 'Brand'       THEN Impressions ELSE 0 END) AS Brand_Impressions,
    SUM(CASE WHEN Type = 'Non-Brand'   THEN Impressions ELSE 0 END) AS Non_Brand_Impressions,
    SUM(CASE WHEN Type = 'DVD'         THEN Impressions ELSE 0 END) AS DVD_Impressions,
    SUM(CASE WHEN Type = 'Retargeting' THEN Impressions ELSE 0 END) AS Retargeting_Impressions,
    SUM(CASE WHEN Type = 'Prospecting' THEN Impressions ELSE 0 END) AS Prospecting_Impressions,
    NULL AS Reddit_Cost,
    NULL AS Reddit_Impressions,
    SUM(Closed) AS HubSpot_Closed
  FROM `freedom-solar-406415.freedom_solar_hvac.full_funnel_HVAC`
  WHERE Date >= "{start_date}" AND Region != "Other"
  GROUP BY date, geo

  UNION ALL

  SELECT
    DATE_TRUNC(Date, WEEK(MONDAY)) AS date,
    Region AS geo,
    NULL AS Brand_Cost,
    NULL AS Non_Brand_Cost,
    NULL AS DVD_Cost,
    NULL AS Retargeting_Cost,
    NULL AS Prospecting_Cost,
    NULL AS Brand_Impressions,
    NULL AS Non_Brand_Impressions,
    NULL AS DVD_Impressions,
    NULL AS Retargeting_Impressions,
    NULL AS Prospecting_Impressions,
    SUM(Cost)        AS Reddit_Cost,
    SUM(Impressions) AS Reddit_Impressions,
    NULL AS HubSpot_Closed
  FROM `freedom-solar-406415.freedom_solar_segments.reddit_data`
  WHERE Date >= "{start_date}" AND Region != "Other"
  GROUP BY date, geo
)
SELECT
  date, geo,
  SUM(Brand_Cost)              AS Brand_Cost,
  SUM(Non_Brand_Cost)          AS Non_Brand_Cost,
  SUM(DVD_Cost)                AS DVD_Cost,
  SUM(Retargeting_Cost)        AS Retargeting_Cost,
  SUM(Prospecting_Cost)        AS Prospecting_Cost,
  SUM(Brand_Impressions)       AS Brand_Impressions,
  SUM(Non_Brand_Impressions)   AS Non_Brand_Impressions,
  SUM(DVD_Impressions)         AS DVD_Impressions,
  SUM(Retargeting_Impressions) AS Retargeting_Impressions,
  SUM(Prospecting_Impressions) AS Prospecting_Impressions,
  SUM(Reddit_Cost)             AS Reddit_Cost,
  SUM(Reddit_Impressions)      AS Reddit_Impressions,
  SUM(HubSpot_Closed)           AS HubSpot_Closed
FROM base
WHERE date < CURRENT_DATE()
GROUP BY date, geo
ORDER BY date, geo
"""


# ── Step 1: BigQuery ──────────────────────────────────────────────────────────

def pull_bq(start_date: str) -> pd.DataFrame:
    print(f"[BQ] Pulling from {start_date} → today ...")
    client = bigquery.Client(project=BQ_PROJECT)
    df = client.query(BQ_QUERY_TEMPLATE.format(start_date=start_date)).to_dataframe()
    df["date"] = pd.to_datetime(df["date"])
    print(f"[BQ] {len(df):,} rows | {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"[BQ] Geos in data: {sorted(df['geo'].unique())}")
    return df


# ── Step 2: Static controls ───────────────────────────────────────────────────

def add_static_controls(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Drop geos not in model
    before = len(df)
    df = df[~df["geo"].isin(GEOS_TO_DROP)].reset_index(drop=True)
    if len(df) < before:
        print(f"[controls] Dropped {before - len(df):,} rows (low-volume geos)")

    # Complete the date × geo panel (Meridian requires no gaps)
    all_dates = df["date"].unique()
    all_geos  = df["geo"].unique()
    idx = pd.MultiIndex.from_product([all_dates, all_geos], names=["date", "geo"])
    df = (
        pd.DataFrame(index=idx)
        .reset_index()
        .merge(df, on=["date", "geo"], how="left")
        .fillna(0)
        .sort_values(["geo", "date"])
        .reset_index(drop=True)
    )
    print(f"[controls] Panel: {len(df):,} rows ({len(all_dates)} weeks × {len(all_geos)} geos)")

    # Population
    df["population"] = df["geo"].map(DMA_POPULATION)
    missing = df["population"].isna().sum()
    if missing:
        print(f"[controls] ⚠️  {missing} rows missing population mapping — check geo names")

    # Storm flags (Austin hail events, summer 2024)
    df["storm_acute"] = (
        (df["date"] >= pd.Timestamp("2024-05-15")) &
        (df["date"] <  pd.Timestamp("2024-07-15"))
    ).astype(float)
    df["storm_tail"] = (
        (df["date"] >= pd.Timestamp("2024-07-15")) &
        (df["date"] <  pd.Timestamp("2024-09-01"))
    ).astype(float)

    # ITC policy shift
    df["tax_credit_shift"] = (df["date"] >= pd.Timestamp("2025-10-01")).astype(float)

    # Billboard/DirectMail — zeroed here, billboard_correction fills actuals below
    df["Billboard_Cost"]         = 0.0
    df["Billboard_Impressions"]  = 0.0
    df["DirectMail_Impressions"] = 0.0

    # DirectMail: single Austin week (2026-03-30 drop)
    dm = (df["geo"] == "Austin") & (df["date"] == pd.Timestamp("2026-03-30"))
    df.loc[dm, "DirectMail_Impressions"] = 20_000.0

    # San Antonio Reddit artifact: impressions logged with $0 spend
    sa_artifact = (
        (df["geo"] == "San Antonio") &
        (df["Reddit_Cost"] == 0) &
        (df["Reddit_Impressions"] > 0)
    )
    if sa_artifact.sum():
        df.loc[sa_artifact, "Reddit_Impressions"] = 0.0
        print(f"[controls] Zeroed Reddit_Impressions for {sa_artifact.sum()} SA rows ($0 spend)")

    return df


# ── Step 3: GQV from GCS ──────────────────────────────────────────────────────

def _parse_file_date(filename: str):
    """Extract MonthYear date from filename (e.g. 'Apr2026' → Timestamp).
    Returns None for files with no date tag (treated as oldest baseline)."""
    months = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    m = re.search(r"([A-Za-z]{3})(\d{4})", filename, re.IGNORECASE)
    if not m:
        return None
    mon = months.get(m.group(1).lower())
    return pd.Timestamp(year=int(m.group(2)), month=mon, day=1) if mon else None


def pull_gqv_from_gcs() -> pd.DataFrame:
    """List all GQV CSVs in GCS, sort oldest-first, concat, and deduplicate."""
    print(f"[GQV] Listing gs://{GQV_BUCKET}/{GQV_PREFIX} ...")
    gcs = storage.Client()
    blobs = [b for b in gcs.list_blobs(GQV_BUCKET, prefix=GQV_PREFIX) if b.name.endswith(".csv")]

    if not blobs:
        raise FileNotFoundError(f"No CSV files found at gs://{GQV_BUCKET}/{GQV_PREFIX}")

    blobs.sort(key=lambda b: _parse_file_date(Path(b.name).name) or pd.Timestamp.min)

    dfs = []
    for blob in blobs:
        print(f"[GQV]   {Path(blob.name).name}")
        df = pd.read_csv(StringIO(blob.download_as_text()))
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    combined["ReportDate"] = pd.to_datetime(combined["ReportDate"])

    before = len(combined)
    combined = combined.drop_duplicates(
        subset=["QueryLabel", "ReportDate", "GeoCriteriaId"], keep="last"
    )
    print(f"[GQV] {before:,} rows → {len(combined):,} after dedup | "
          f"{combined['ReportDate'].min().date()} → {combined['ReportDate'].max().date()}")
    return combined


def _yoy_estimate_missing_weeks(gqv: pd.DataFrame, target_mondays: pd.DatetimeIndex) -> pd.DataFrame:
    """Estimate GQV for any target weeks beyond the GQV data using Q1 YoY ratios."""
    gqv_max = gqv["ReportDate"].max()
    missing = sorted(d for d in target_mondays if d > gqv_max)
    if not missing:
        return gqv

    print(f"[GQV] ⚠️  {len(missing)} weeks beyond GQV coverage — estimating via YoY")

    q1_25 = gqv[(gqv["ReportDate"] >= "2025-01-01") & (gqv["ReportDate"] <= "2025-03-31")]
    q1_26 = gqv[(gqv["ReportDate"] >= "2026-01-01") & (gqv["ReportDate"] <= "2026-03-30")]
    mean_25 = q1_25.groupby(["geo", "QueryLabel"])["IndexedQueryVolume"].mean().rename("mean_25")
    mean_26 = q1_26.groupby(["geo", "QueryLabel"])["IndexedQueryVolume"].mean().rename("mean_26")
    ratios = pd.concat([mean_25, mean_26], axis=1)
    ratios["yoy_ratio"] = ratios["mean_26"] / ratios["mean_25"]
    ratios = ratios.reset_index()

    appended = []
    for d in missing:
        base = d - pd.DateOffset(days=364)  # same calendar position, prior year
        week_prior = gqv[gqv["ReportDate"] == base]
        if week_prior.empty:
            nearby = gqv[
                (gqv["ReportDate"] >= base - pd.Timedelta(days=7)) &
                (gqv["ReportDate"] <= base + pd.Timedelta(days=7))
            ]
            if not nearby.empty:
                base = nearby["ReportDate"].iloc[0]
                week_prior = gqv[gqv["ReportDate"] == base]
        if week_prior.empty:
            print(f"  ⚠️  No prior-year base for {d.date()} — skipping")
            continue
        est = week_prior.merge(ratios[["geo", "QueryLabel", "yoy_ratio"]],
                               on=["geo", "QueryLabel"], how="left")
        est["IndexedQueryVolume"] *= est["yoy_ratio"]
        est["ReportDate"] = d
        appended.append(est.drop(columns=["yoy_ratio"]))
        print(f"  Estimated {d.date()} from {base.date()}")

    return pd.concat([gqv] + appended, ignore_index=True) if appended else gqv


def join_gqv(base: pd.DataFrame, gqv_raw: pd.DataFrame) -> pd.DataFrame:
    """Filter GQV to model DMAs, estimate missing weeks, pivot wide, and join."""
    gqv = gqv_raw[gqv_raw["GeoType"] == "DMA_REGION"].copy()
    gqv = gqv[gqv["GeoName"].isin(list(GEO_MAP.values()))].copy()
    gqv["geo"] = gqv["GeoName"].map(REVERSE_GEO)

    target = pd.to_datetime(base["date"].unique())
    gqv = _yoy_estimate_missing_weeks(gqv, target)

    wide = gqv.pivot_table(
        index=["ReportDate", "geo"],
        columns="QueryLabel",
        values="IndexedQueryVolume",
        aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={"ReportDate": "date", "BRAND": "GQV_Brand", "GENERIC": "GQV_Generic"})
    wide = wide[["date", "geo", "GQV_Brand", "GQV_Generic"]]

    merged = base.merge(wide, on=["date", "geo"], how="left")

    nan_count = merged["GQV_Brand"].isna().sum()
    if nan_count:
        print(f"[GQV] Backfilling {nan_count} pre-series NaN rows")
        merged = merged.sort_values(["geo", "date"]).reset_index(drop=True)
        merged[["GQV_Brand", "GQV_Generic"]] = (
            merged.groupby("geo")[["GQV_Brand", "GQV_Generic"]].transform(lambda s: s.bfill())
        )

    print(f"[GQV] Join complete | GQV_Brand {merged['GQV_Brand'].min():.5f}–{merged['GQV_Brand'].max():.5f}")
    return merged


# ── Step 4: Validate ──────────────────────────────────────────────────────────

def validate(df: pd.DataFrame) -> bool:
    checks = [
        (df["GQV_Brand"].isna().sum() == 0,                     "GQV_Brand has no NaNs"),
        (df["GQV_Generic"].isna().sum() == 0,                   "GQV_Generic has no NaNs"),
        (df["population"].isna().sum() == 0,                    "population has no NaNs"),
        (pd.to_datetime(df["date"]).dt.dayofweek.eq(0).all(),   "All dates are Monday-aligned"),
        (not df.duplicated(["date", "geo"]).any(),              "No duplicate date×geo rows"),
        ((df["HubSpot_Closed"] >= 0).all(),                        "HubSpot_Closed non-negative"),
    ]
    all_passed = True
    for passed, label in checks:
        mark = "✓" if passed else "✗"
        print(f"  [{mark}] {label}")
        if not passed:
            all_passed = False
    return all_passed


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true",
                        help="Production mode: full pull, write to processed/")
    args = parser.parse_args()

    out_dir = ROOT / "data" / "processed" / "Freedom_Power"

    if args.prod:
        start_date = BQ_START_DATE
        print("=" * 60)
        print("MODE: PRODUCTION — full pull from 2024-01-01")
        print("=" * 60)
    else:
        start_date = (pd.Timestamp.today() - pd.DateOffset(weeks=16)).strftime("%Y-%m-%d")
        print("=" * 60)
        print(f"MODE: TEST — last 16 weeks (from {start_date})")
        print(f"Output will NOT overwrite production data.")
        print("=" * 60)

    # 1. BQ pull
    df = pull_bq(start_date)

    # 2. Static controls + panel completion
    df = add_static_controls(df)

    # 3. Billboard corrections (Austin + Houston board schedule)
    df = apply_corrections(df)
    bb_rows = (df["Billboard_Cost"] > 0).sum()
    print(f"[billboard] {bb_rows} non-zero billboard rows")

    # 4. GQV from GCS
    gqv_raw = pull_gqv_from_gcs()
    df = join_gqv(df, gqv_raw)

    # 5. Validate
    print("\n[validate]")
    ok = validate(df)
    if not ok:
        print("\n⚠️  Validation issues found — review before using in production.")

    # 6. Write
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.prod:
        vintage = pd.to_datetime(df["date"]).max().strftime("%b%y")  # e.g. "Jun26"
        out_path = out_dir / f"Freedom_MMM_closes_{vintage}_gqv.csv"
    else:
        out_path = out_dir / "test_refresh_closes.csv"

    df.to_csv(out_path, index=False)

    print(f"\n[done] {len(df):,} rows × {len(df.columns)} cols → {out_path.relative_to(ROOT)}")
    print(f"       {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"       Geos: {sorted(df['geo'].unique())}")
    print(f"       Columns: {list(df.columns)}")

    if args.prod:
        vintage_str = pd.to_datetime(df["date"]).max().strftime("%b%y")
        print(f"\nNext: update configs/Freedom_Power_Closes.yaml data_path to:")
        print(f'  data/processed/Freedom_Power/Freedom_MMM_closes_{vintage_str}_gqv.csv')


if __name__ == "__main__":
    main()
