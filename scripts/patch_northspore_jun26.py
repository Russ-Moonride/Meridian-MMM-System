"""
Patch NorthSpore MMM dataset: replace June 15 2026 with correct BQ data and add June 22.

The existing NS_mmm_data_Jun26.csv ends at 2026-06-15, but that row was captured
from an incomplete mid-week BQ pull (revenue ~$112K vs $252K in BQ now). This script:
  1. Keeps existing data through 2026-06-08 (last clean week).
  2. Pulls geo-level paid media + revenue from BQ for 2026-06-15 and 2026-06-22.
  3. Adds Pmax from BQ (national, population-weighted to geos).
  4. Extends organic views (IG/FB/YT) using prior-year same-week from existing data
     scaled by YoY organic trend (no platform exports available).
  5. Merges promo (carries June 15 from file; June 22 defaults to 25% match recent weeks).
  6. Pulls weather via Open-Meteo archive API.
  7. Sets TikTok = 0 (channel paused after 2026-05-04).
  8. Writes data/processed/northspore/NS_mmm_data_Jun26.csv (in-place update).

Run from repo root with .venv active:
    python scripts/patch_northspore_jun26.py
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from google.cloud import bigquery

ROOT     = Path(__file__).resolve().parent.parent
RAW_DIR  = ROOT / "data" / "raw" / "northspore"
PROC_DIR = ROOT / "data" / "processed" / "northspore"

BQ_PROJECT  = "north-spore"
PATCH_START = "2026-06-15"   # keep everything before this; re-pull from here
PATCH_END   = "2026-06-22"   # last week to include

STATE_POPULATION = {
    "PA":13210000,"NH":1400000,"GA":11400000,"ID":2010000,"WI":5960000,"MO":6190000,
    "KY":4540000,"MI":10300000,"NE":1980000,"SC":5660000,"CO":6070000,"CA":39900000,
    "WA":8160000,"IL":12800000,"IA":3210000,"NJ":9740000,"AR":3080000,"MA":7280000,
    "MN":5790000,"OR":4300000,"KS":2950000,"AL":5100000,"NV":3220000,"IN":7010000,
    "MS":2960000,"HI":1440000,"WY":590000,"DE":1080000,"VT":650000,"ME":1390000,
    "NC":11400000,"AZ":7800000,"OH":12000000,"UT":3500000,"MT":1140000,"RI":1110000,
    "DC":680000,"ND":810000,"MD":6360000,"CT":3620000,"OK":4090000,"SD":920000,
    "WV":1770000,"LA":4590000,"VA":8960000,"AK":750000,"TN":7390000,"FL":24300000,
    "NM":2120000,"TX":32400000,"NY":20100000,
}

VIABLE_STATES = list(STATE_POPULATION.keys())

STATE_CITY_COORDS = {
    "AK": (61.2181, -149.9003), "AL": (33.5186,  -86.8104), "AR": (34.7465,  -92.2896),
    "AZ": (33.4484, -112.0740), "CA": (34.0522, -118.2437), "CO": (39.7392, -104.9903),
    "CT": (41.1865,  -73.1952), "DC": (38.9072,  -77.0369), "DE": (39.7447,  -75.5484),
    "FL": (30.3322,  -81.6557), "GA": (33.7490,  -84.3880), "HI": (21.3069, -157.8583),
    "IA": (41.5868,  -93.6250), "ID": (43.6150, -116.2023), "IL": (41.8781,  -87.6298),
    "IN": (39.7684,  -86.1581), "KS": (37.6872,  -97.3301), "KY": (38.2527,  -85.7585),
    "LA": (29.9511,  -90.0715), "MA": (42.3601,  -71.0589), "MD": (39.2904,  -76.6122),
    "ME": (43.6591,  -70.2568), "MI": (42.3314,  -83.0458), "MN": (44.9778,  -93.2650),
    "MO": (39.0997,  -94.5786), "MS": (32.2988,  -90.1848), "MT": (45.7833, -108.5007),
    "NC": (35.2271,  -80.8431), "ND": (46.8772,  -96.7898), "NE": (41.2565,  -95.9345),
    "NH": (42.9956,  -71.4548), "NJ": (40.7357,  -74.1724), "NM": (35.0844, -106.6504),
    "NV": (36.1699, -115.1398), "NY": (40.7128,  -74.0060), "OH": (39.9612,  -82.9988),
    "OK": (35.4676,  -97.5164), "OR": (45.5051, -122.6750), "PA": (39.9526,  -75.1652),
    "RI": (41.8240,  -71.4128), "SC": (34.0007,  -81.0348), "SD": (43.5446,  -96.7311),
    "TN": (36.1627,  -86.7816), "TX": (29.7604,  -95.3698), "UT": (40.7608, -111.8910),
    "VA": (36.8529,  -75.9780), "VT": (44.4759,  -73.2121), "WA": (47.6062, -122.3321),
    "WI": (43.0389,  -87.9065), "WV": (38.3498,  -81.6326), "WY": (41.1400, -104.8202),
}

BF_DATES = [
    "2024-11-18", "2024-11-25", "2024-12-02",
    "2025-11-17", "2025-11-24", "2025-12-01",
]

STATE_MAP_FULL = {
    "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
    "Colorado":"CO","Connecticut":"CT","Delaware":"DE","District of Columbia":"DC",
    "Florida":"FL","Georgia":"GA","Hawaii":"HI","Idaho":"ID","Illinois":"IL",
    "Indiana":"IN","Iowa":"IA","Kansas":"KS","Kentucky":"KY","Louisiana":"LA",
    "Maine":"ME","Maryland":"MD","Massachusetts":"MA","Michigan":"MI","Minnesota":"MN",
    "Mississippi":"MS","Missouri":"MO","Montana":"MT","Nebraska":"NE","Nevada":"NV",
    "New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM","New York":"NY",
    "North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK","Oregon":"OR",
    "Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC","South Dakota":"SD",
    "Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT","Virginia":"VA",
    "Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY",
}


def load_base() -> pd.DataFrame:
    path = PROC_DIR / "NS_mmm_data_Jun26.csv"
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] < pd.Timestamp(PATCH_START)].copy()
    print(f"[base] Kept {len(df):,} rows through {df['date'].max().date()}")
    return df


def pull_bq_geo() -> pd.DataFrame:
    print(f"[BQ] Pulling geo paid media {PATCH_START} → {PATCH_END} ...")
    client = bigquery.Client(project=BQ_PROJECT)
    q = f"""
    WITH base AS (
      SELECT * EXCEPT(Type),
        CASE WHEN Platform = "DVD" THEN "DVD" ELSE Type END AS Type
      FROM `north-spore.north_spore_segments.full_segments_region`
    )
    SELECT
      DATE_TRUNC(Date, WEEK(MONDAY)) AS date,
      State AS geo,
      SUM(CASE WHEN Type = "DVD"            THEN Cost ELSE 0 END) AS DVD_Cost,
      SUM(CASE WHEN Type = "Competitors"    THEN Cost ELSE 0 END) AS Competitors_Cost,
      SUM(CASE WHEN Type = "Retargeting"    THEN Cost ELSE 0 END) AS Retargeting_Cost,
      SUM(CASE WHEN Type = "Brand Shopping" THEN Cost ELSE 0 END) AS Brand_Shopping_Cost,
      SUM(CASE WHEN Type = "Shopping"       THEN Cost ELSE 0 END) AS Shopping_Cost,
      SUM(CASE WHEN Type = "Prospecting"    THEN Cost ELSE 0 END) AS Prospecting_Cost,
      SUM(CASE WHEN Type = "Remarketing"    THEN Cost ELSE 0 END) AS Remarketing_Cost,
      SUM(CASE WHEN Type = "Brand"          THEN Cost ELSE 0 END) AS Brand_Cost,
      SUM(CASE WHEN Type = "Non-Brand"      THEN Cost ELSE 0 END) AS Non_Brand_Cost,
      SUM(CASE WHEN Type = "DVD"            THEN Impressions ELSE 0 END) AS DVD_Impressions,
      SUM(CASE WHEN Type = "Competitors"    THEN Impressions ELSE 0 END) AS Competitors_Impressions,
      SUM(CASE WHEN Type = "Retargeting"    THEN Impressions ELSE 0 END) AS Retargeting_Impressions,
      SUM(CASE WHEN Type = "Brand Shopping" THEN Impressions ELSE 0 END) AS Brand_Shopping_Impressions,
      SUM(CASE WHEN Type = "Shopping"       THEN Impressions ELSE 0 END) AS Shopping_Impressions,
      SUM(CASE WHEN Type = "Prospecting"    THEN Impressions ELSE 0 END) AS Prospecting_Impressions,
      SUM(CASE WHEN Type = "Remarketing"    THEN Impressions ELSE 0 END) AS Remarketing_Impressions,
      SUM(CASE WHEN Type = "Brand"          THEN Impressions ELSE 0 END) AS Brand_Impressions,
      SUM(CASE WHEN Type = "Non-Brand"      THEN Impressions ELSE 0 END) AS Non_Brand_Impressions,
      SUM(Shopify_Purchases) AS Purchases,
      SUM(Shopify_Revenue)   AS Revenue
    FROM base
    WHERE Date >= "{PATCH_START}"
      AND DATE_TRUNC(Date, WEEK(MONDAY)) <= "{PATCH_END}"
      AND State != "Other"
    GROUP BY date, geo
    ORDER BY date, geo
    """
    df = client.query(q).to_dataframe()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["geo"].isin(VIABLE_STATES)].copy()
    print(f"[BQ] Geo paid: {len(df):,} rows | {df['date'].min().date()} → {df['date'].max().date()}")
    return df


def pull_bq_pmax() -> pd.DataFrame:
    print(f"[BQ] Pulling Pmax {PATCH_START} → {PATCH_END} ...")
    client = bigquery.Client(project=BQ_PROJECT)
    q = f"""
    SELECT
      DATE_TRUNC(Date, WEEK(MONDAY)) AS date,
      SUM(CASE WHEN Type = "Performance Max" THEN Cost ELSE 0 END) AS Pmax_Cost,
      SUM(CASE WHEN Type = "Performance Max" THEN Impressions ELSE 0 END) AS Pmax_Impressions
    FROM `north-spore.north_spore_segments.full_segments`
    WHERE Date >= "{PATCH_START}"
      AND DATE_TRUNC(Date, WEEK(MONDAY)) <= "{PATCH_END}"
    GROUP BY date
    ORDER BY date
    """
    df = client.query(q).to_dataframe()
    df["date"] = pd.to_datetime(df["date"])
    print(f"[BQ] Pmax: {len(df):,} rows")
    return df


def build_new_panel(geo_df: pd.DataFrame, pmax_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = geo_df.copy()

    all_dates = sorted(df["date"].unique())
    all_geos  = VIABLE_STATES
    idx = pd.MultiIndex.from_product([all_dates, all_geos], names=["date", "geo"])
    df = (
        pd.DataFrame(index=idx)
        .reset_index()
        .merge(df, on=["date", "geo"], how="left")
        .fillna(0)
        .sort_values(["geo", "date"])
        .reset_index(drop=True)
    )
    print(f"[panel] {len(df):,} rows ({len(all_dates)} weeks × {len(all_geos)} states)")

    df["population"] = df["geo"].map(STATE_POPULATION)
    df["bf_date"]    = df["date"].isin(pd.to_datetime(BF_DATES)).astype(int)

    pop = df[["date", "geo", "population"]].drop_duplicates(["date", "geo"]).copy()
    pop["total_pop"]  = pop.groupby("date")["population"].transform("sum")
    pop["pop_weight"] = pop["population"] / pop["total_pop"]

    pmax_exp = pop.merge(pmax_df[["date", "Pmax_Cost", "Pmax_Impressions"]], on="date", how="left")
    pmax_exp["Pmax_Cost"]        = pmax_exp["Pmax_Cost"].fillna(0)        * pmax_exp["pop_weight"]
    pmax_exp["Pmax_Impressions"] = pmax_exp["Pmax_Impressions"].fillna(0) * pmax_exp["pop_weight"]
    df = df.merge(pmax_exp[["date", "geo", "Pmax_Cost", "Pmax_Impressions"]], on=["date", "geo"], how="left")
    df[["Pmax_Cost", "Pmax_Impressions"]] = df[["Pmax_Cost", "Pmax_Impressions"]].fillna(0)

    df["Brand_Cost"]            = df.get("Brand_Cost", 0)     + df.get("Brand_Shopping_Cost", 0)
    df["Brand_Impressions"]     = df.get("Brand_Impressions", 0) + df.get("Brand_Shopping_Impressions", 0)
    df["Non_Brand_Cost"]        = df.get("Non_Brand_Cost", 0)  + df.get("Competitors_Cost", 0)
    df["Non_Brand_Impressions"] = df.get("Non_Brand_Impressions", 0) + df.get("Competitors_Impressions", 0)
    df.drop(columns=[c for c in ["Brand_Shopping_Cost", "Brand_Shopping_Impressions",
                                  "Competitors_Cost", "Competitors_Impressions"] if c in df.columns],
            inplace=True)

    return df, pop


def extend_organic(new_panel: pd.DataFrame, base: pd.DataFrame, pop: pd.DataFrame) -> pd.DataFrame:
    organic_cols = ["Facebook_Views", "Instagram_Views", "YouTube_Views"]
    new_dates = sorted(new_panel["date"].unique())

    max_base = base["date"].max()
    recent   = base[base["date"] > max_base - pd.Timedelta(weeks=8)]
    year_ago = base[
        (base["date"] > max_base - pd.Timedelta(weeks=60)) &
        (base["date"] <= max_base - pd.Timedelta(weeks=52))
    ]
    trend_by_col = {}
    for col in organic_cols:
        rec_mean = recent.groupby("date")[col].sum().mean()
        ago_mean = year_ago.groupby("date")[col].sum().mean()
        trend_by_col[col] = (rec_mean / ago_mean) if ago_mean > 0 else 1.0
    print(f"[organic] YoY trend factors: {', '.join(f'{c}={v:.2f}x' for c, v in trend_by_col.items())}")

    base_national = base.groupby("date")[organic_cols].sum().reset_index()
    base_nat_dict = base_national.set_index("date")[organic_cols].to_dict(orient="index")

    new_national = []
    for nd in new_dates:
        prior = nd - pd.Timedelta(weeks=52)
        if prior not in base_nat_dict:
            prior = nd - pd.Timedelta(weeks=53)
        row    = base_nat_dict.get(prior, {c: 0.0 for c in organic_cols})
        scaled = {c: row.get(c, 0.0) * trend_by_col[c] for c in organic_cols}
        scaled["date"] = nd
        new_national.append(scaled)
        prior_dt = prior if prior in base_nat_dict else nd - pd.Timedelta(weeks=53)
        print(f"[organic] {nd.date()} ← prior {prior_dt.date()} | "
              f"FB={scaled['Facebook_Views']:.0f} IG={scaled['Instagram_Views']:.0f} "
              f"YT={scaled['YouTube_Views']:.0f}")

    nat_df   = pd.DataFrame(new_national)
    expanded = pop.merge(nat_df, on="date", how="left")
    for col in organic_cols:
        expanded[col] = expanded[col].fillna(0) * expanded["pop_weight"]

    organic_state = expanded[["date", "geo"] + organic_cols].copy()
    new_panel = new_panel.merge(organic_state, on=["date", "geo"], how="left")
    new_panel[organic_cols] = new_panel[organic_cols].fillna(0)
    return new_panel


def load_promo() -> pd.DataFrame:
    candidates = list(RAW_DIR.glob("NS_Promos*.csv")) + list(RAW_DIR.glob("NorthSpore*Promo*.csv"))
    if not candidates:
        print("[promo] WARNING: no promo file found")
        return pd.DataFrame(columns=["Date", "Promo Intensity", "Product Launch"])
    path = candidates[-1]
    print(f"[promo] Loading {path.name}")
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Promo Intensity"] = (
        df["Promo Intensity"].astype(str).str.replace("%", "").astype(float) / 100
    )
    df["Product Launch"] = df["Product Launch"].fillna(0).astype(float)

    # June 22 is not in the promo file; carry forward 25% (matches June 1-15 pattern)
    jun22 = pd.Timestamp("2026-06-22")
    if jun22 not in df["Date"].values:
        df = pd.concat([df, pd.DataFrame([{
            "Date": jun22, "Promo Intensity": 0.25, "Product Launch": 0.0
        }])], ignore_index=True)
        print("[promo] June 22 not in file — defaulted to 25% (carry-forward)")

    return df[["Date", "Promo Intensity", "Product Launch"]]


def pull_weather(start_date: str, end_date: str) -> pd.DataFrame:
    print(f"[weather] Pulling Open-Meteo {start_date} → {end_date} ...")
    base_url = "https://archive-api.open-meteo.com/v1/archive"
    rows = []
    for i, (state, (lat, lon)) in enumerate(STATE_CITY_COORDS.items()):
        resp = requests.get(base_url, params={
            "latitude": lat, "longitude": lon,
            "start_date": start_date, "end_date": end_date,
            "daily": "temperature_2m_mean,precipitation_sum",
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "timezone": "auto",
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()["daily"]
        for date_str, temp, rain in zip(data["time"], data["temperature_2m_mean"], data["precipitation_sum"]):
            rows.append({
                "geo": state, "date": pd.Timestamp(date_str),
                "temp": temp if temp is not None else float("nan"),
                "rain": rain if rain is not None else 0.0,
            })
        if (i + 1) % 10 == 0:
            print(f"[weather]   {i+1}/{len(STATE_CITY_COORDS)} states done")
        time.sleep(0.05)

    daily = pd.DataFrame(rows)
    daily["week_start"] = daily["date"] - pd.to_timedelta(daily["date"].dt.weekday, unit="d")
    weekly = (
        daily.groupby(["geo", "week_start"])
        .agg(weekly_average_temp=("temp", "mean"), weekly_rainfall=("rain", "sum"))
        .reset_index().rename(columns={"week_start": "date"})
    )
    print(f"[weather] {len(weekly):,} state-week rows")
    return weekly


def main():
    PROC_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print(f"NorthSpore patch: {PATCH_START} → {PATCH_END}")
    print(f"  June 15: re-pull (was incomplete mid-week capture)")
    print(f"  June 22: new week (through June 28)")
    print("=" * 60)

    # 1. Base
    base = load_base()

    # 2. BQ
    geo_df  = pull_bq_geo()
    pmax_df = pull_bq_pmax()

    # 3. Panel
    new_panel, pop = build_new_panel(geo_df, pmax_df)

    # 4. Organic
    new_panel = extend_organic(new_panel, base, pop)

    # 5. Promo
    promo = load_promo()
    if len(promo):
        new_panel = new_panel.merge(promo.rename(columns={"Date": "date"}), on="date", how="left")
        new_panel["Promo Intensity"] = new_panel["Promo Intensity"].fillna(0)
        new_panel["Product Launch"]  = new_panel["Product Launch"].fillna(0)
    else:
        new_panel["Promo Intensity"] = 0.0
        new_panel["Product Launch"]  = 0.0

    # 6. Weather — pull through June 28 so the June 22 week gets all 7 days
    weather = pull_weather(PATCH_START, "2026-06-28")
    new_panel = new_panel.merge(weather, on=["date", "geo"], how="left")
    new_panel["weekly_average_temp"] = new_panel["weekly_average_temp"].fillna(0)
    new_panel["weekly_rainfall"]     = new_panel["weekly_rainfall"].fillna(0)

    # 7. TikTok = 0 (channel paused since May 2026)
    new_panel["TikTok_Cost"]        = 0.0
    new_panel["TikTok_Impressions"] = 0.0

    # 8. Align columns to base schema
    base_cols = list(base.columns)
    for col in base_cols:
        if col not in new_panel.columns:
            new_panel[col] = 0.0
    new_panel = new_panel[base_cols]

    # 9. Combine
    combined = pd.concat([base, new_panel], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.sort_values(["geo", "date"]).reset_index(drop=True)
    numeric_cols = combined.select_dtypes(include=[np.number]).columns
    combined[numeric_cols] = combined[numeric_cols].fillna(0)

    # 10. Validate
    print("\n[validate]")
    # Temperature check excludes DC — it has pre-existing 0s in base data (historical gap)
    non_dc = combined[combined["geo"] != "DC"]
    hard_checks = [
        (pd.to_datetime(combined["date"]).dt.dayofweek.eq(0).all(), "All dates Monday-aligned"),
        (not combined.duplicated(["date", "geo"]).any(),             "No duplicate date×geo"),
        ((combined["Revenue"] >= 0).all(),                           "Revenue non-negative"),
        ((non_dc["weekly_average_temp"] != 0).all(),                 "No zero temperatures (non-DC)"),
    ]
    soft_checks = [
        ((combined["weekly_average_temp"] != 0).all(),
         f"No zero temperatures (all geos) — DC has {(combined[combined['geo']=='DC']['weekly_average_temp']==0).sum()} pre-existing zeros"),
    ]
    all_ok = True
    for passed, label in hard_checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {label}")
        if not passed:
            all_ok = False
    for passed, label in soft_checks:
        print(f"  [{'OK' if passed else 'WARN'}] {label}")

    if not all_ok:
        print("\nHard validation failures — aborting write.")
        sys.exit(1)

    out_path = PROC_DIR / "NS_mmm_data_Jun26.csv"
    combined.to_csv(out_path, index=False)

    print(f"\n[done] {len(combined):,} rows × {len(combined.columns)} cols → {out_path.relative_to(ROOT)}")
    print(f"       {combined['date'].min().date()} → {combined['date'].max().date()}")
    print(f"       States: {combined['geo'].nunique()}")

    spend_cols = [c for c in combined.columns if c.endswith("_Cost")]
    print("\nSpot-check: June 2026 national totals")
    june = combined[combined["date"].dt.month == 6].copy()
    spot = june.groupby("date").agg(
        Revenue=("Revenue", "sum"),
        Purchases=("Purchases", "sum"),
    )
    for col in spend_cols:
        spot[col] = june.groupby("date")[col].sum()
    spot["Total_Spend"] = spot[spend_cols].sum(axis=1)
    print(spot[["Revenue", "Purchases", "Total_Spend"]].round(0).to_string())


if __name__ == "__main__":
    main()
