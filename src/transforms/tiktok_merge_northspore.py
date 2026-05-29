"""
Merges TikTok daily geo-level spend/impressions into the Northspore MMM dataset.

Sources:
  data/raw/northspore/Tiktok Ads_Untitled report_North Spore_20250401-20250731.xlsx
  data/raw/northspore/Tiktok Ads_Untitled report_North Spore_20260101-20260529.xlsx

Output:
  data/processed/northspore/NS_mmm_data_May26.csv

Key transforms:
  1. Parse both Excel files, combine
  2. Map full state names -> 2-letter USPS codes; drop rows with unmappable geos after redistribution
  3. Distribute geo="Unknown" spend proportionally to known geos within each day
     (TikTok iOS attribution gap). If a day has zero known spend, distribute equally across 51 states.
  4. Aggregate daily -> Monday-aligned weekly sums per geo
  5. Trim to model end date (2026-05-04)
  6. Merge onto existing NS base dataset (NS_mmm_data_Apr26.csv) as new columns:
     TikTok_Cost, TikTok_Impressions — zero-filled for all weeks with no TikTok activity
"""

import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/northspore"
OUT = ROOT / "data/processed/northspore"
OUT.mkdir(parents=True, exist_ok=True)

BASE_CSV = RAW / "NS_mmm_data_Apr26.csv"
MODEL_END = pd.Timestamp("2026-05-04")

TIKTOK_FILES = [
    RAW / "Tiktok Ads_Untitled report_North Spore_20250401-20250731.xlsx",
    RAW / "Tiktok Ads_Untitled report_North Spore_20260101-20260529.xlsx",
]

STATE_MAP = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


def load_tiktok_raw() -> pd.DataFrame:
    dfs = []
    for f in TIKTOK_FILES:
        df = pd.read_excel(f, header=0)
        df.columns = ["account", "date", "subregion", "cost", "impressions", "currency"]
        df["date"] = pd.to_datetime(df["date"])
        dfs.append(df)
    tt = pd.concat(dfs, ignore_index=True)
    tt = tt[tt["date"] <= MODEL_END].copy()
    return tt


def redistribute_unknown(tt: pd.DataFrame) -> pd.DataFrame:
    """
    For each day, apportion geo='Unknown' spend proportionally to known geos.
    If a day has no known spend at all, distribute equally across 51 states.
    """
    ALL_STATES = list(STATE_MAP.values())
    known = tt[tt["subregion"] != "Unknown"].copy()
    unknown = tt[tt["subregion"] == "Unknown"].copy()

    if unknown.empty:
        return known

    results = [known]
    for day, unk_day in unknown.groupby("date"):
        unk_cost = unk_day["cost"].sum()
        unk_imps = unk_day["impressions"].sum()
        if unk_cost == 0 and unk_imps == 0:
            continue

        known_day = known[known["date"] == day].copy()
        total_known_cost = known_day["cost"].sum()

        if total_known_cost > 0:
            # proportional by that day's known spend
            known_day = known_day.copy()
            known_day["_w"] = known_day["cost"] / total_known_cost
        else:
            # equal weight across all 51 states
            known_day = pd.DataFrame({"date": day, "subregion": ALL_STATES,
                                      "cost": 0.0, "impressions": 0.0, "_w": 1.0 / 51})

        addition = known_day[["date", "subregion", "_w"]].copy()
        addition["cost"] = addition["_w"] * unk_cost
        addition["impressions"] = addition["_w"] * unk_imps
        results.append(addition.drop(columns=["_w"]))

    return pd.concat(results, ignore_index=True)


def to_weekly_geo(tt: pd.DataFrame) -> pd.DataFrame:
    tt = tt.copy()
    tt["geo"] = tt["subregion"].map(STATE_MAP)
    unmapped = tt[tt["geo"].isna()]["subregion"].unique()
    if len(unmapped) > 0:
        print(f"WARNING: dropping unmapped subregions: {unmapped}")
    tt = tt[tt["geo"].notna()]

    # Monday-aligned week
    tt["week"] = tt["date"] - pd.to_timedelta(tt["date"].dt.dayofweek, unit="d")

    weekly = (
        tt.groupby(["week", "geo"])[["cost", "impressions"]]
        .sum()
        .reset_index()
        .rename(columns={"week": "date", "cost": "TikTok_Cost", "impressions": "TikTok_Impressions"})
    )
    return weekly


def merge_into_base(weekly_tt: pd.DataFrame) -> pd.DataFrame:
    base = pd.read_csv(BASE_CSV, parse_dates=["date"])

    merged = base.merge(weekly_tt, on=["date", "geo"], how="left")
    merged["TikTok_Cost"] = merged["TikTok_Cost"].fillna(0.0)
    merged["TikTok_Impressions"] = merged["TikTok_Impressions"].fillna(0.0)
    return merged


def main():
    print("Loading TikTok raw data...")
    tt = load_tiktok_raw()
    print(f"  Rows loaded: {len(tt)}, total cost: ${tt['cost'].sum():,.2f}")

    print("Redistributing Unknown geo spend...")
    tt = redistribute_unknown(tt)
    unk_cost_orig = sum(
        pd.read_excel(f, header=0).rename(columns={c: ["account","date","subregion","cost","impressions","currency"][i]
                                                    for i, c in enumerate(pd.read_excel(f, header=0).columns)})
        .query("subregion == 'Unknown'")["cost"].sum()
        for f in TIKTOK_FILES
    )
    print(f"  Unknown cost redistributed: ${unk_cost_orig:,.2f}")

    print("Aggregating to weekly geo level...")
    weekly_tt = to_weekly_geo(tt)
    print(f"  Weeks with nonzero TikTok spend: {(weekly_tt['TikTok_Cost'] > 0).sum()} geo-week rows")

    print("Merging into NS base dataset...")
    final = merge_into_base(weekly_tt)
    print(f"  Final shape: {final.shape}")
    print(f"  TikTok_Cost total in dataset: ${final['TikTok_Cost'].sum():,.2f}")
    print(f"  TikTok_Impressions total: {final['TikTok_Impressions'].sum():,.0f}")
    nonzero_weeks = final.groupby("date")["TikTok_Cost"].sum()
    print(f"  Weeks with any TikTok spend:")
    print(nonzero_weeks[nonzero_weeks > 0].to_string())

    out_path = OUT / "NS_mmm_data_May26.csv"
    final.to_csv(out_path, index=False)
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
