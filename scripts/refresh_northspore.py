"""
Refresh NorthSpore processed dataset.

Automated sources:
  - BigQuery (paid media + revenue): north-spore GCP project
  - Open-Meteo archive API (temperature + rainfall): free, no key required

Manual files required in data/raw/northspore/ before running:
  - NS_IG_data_{vintage}.csv    — Instagram organic views
  - NS_FB_data_{vintage}.csv    — Facebook organic views
  - NS_YT_data_{vintage}.csv    — YouTube organic views
  - NS_Promos_{vintage}.csv     — promo intensity + product launches
  TikTok Excel files optional (0-filled if absent):
  - Tiktok Ads_Untitled report_North Spore_{dates}.xlsx

Test mode (default):
  BQ pull limited to last 16 weeks.
  Output: data/processed/northspore/test_refresh.csv

Production mode (--prod):
  Full pull from 2024-01-01 to current date.
  Output: data/processed/northspore/NS_mmm_data_{vintage}.csv

Usage:
    source .venv/bin/activate
    python scripts/refresh_northspore.py           # test
    python scripts/refresh_northspore.py --prod    # production
"""

import argparse
import re
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

# ── GCP ───────────────────────────────────────────────────────────────────────
BQ_PROJECT    = "north-spore"
BQ_START_DATE = "2024-01-01"

# ── Model states ──────────────────────────────────────────────────────────────
VIABLE_STATES = [
    "MT","OH","NE","AZ","CO","MI","MO","WI","DE","MA","WY","MD","MS","CT","GA","SD",
    "ID","KS","WV","KY","TN","FL","IA","WA","CA","TX","DC","HI","RI","NJ","VT","NH",
    "NC","ME","SC","UT","PA","NY","IL","NM","AK","AR","MN","VA","LA","OR","AL","OK",
    "NV","IN","ND",
]

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

# Most populous city per state (lat, lon) — used for Open-Meteo temperature pull
STATE_CITY_COORDS = {
    "AK": (61.2181, -149.9003),  # Anchorage
    "AL": (33.5186,  -86.8104),  # Birmingham
    "AR": (34.7465,  -92.2896),  # Little Rock
    "AZ": (33.4484, -112.0740),  # Phoenix
    "CA": (34.0522, -118.2437),  # Los Angeles
    "CO": (39.7392, -104.9903),  # Denver
    "CT": (41.1865,  -73.1952),  # Bridgeport
    "DC": (38.9072,  -77.0369),  # Washington
    "DE": (39.7447,  -75.5484),  # Wilmington
    "FL": (30.3322,  -81.6557),  # Jacksonville
    "GA": (33.7490,  -84.3880),  # Atlanta
    "HI": (21.3069, -157.8583),  # Honolulu
    "IA": (41.5868,  -93.6250),  # Des Moines
    "ID": (43.6150, -116.2023),  # Boise
    "IL": (41.8781,  -87.6298),  # Chicago
    "IN": (39.7684,  -86.1581),  # Indianapolis
    "KS": (37.6872,  -97.3301),  # Wichita
    "KY": (38.2527,  -85.7585),  # Louisville
    "LA": (29.9511,  -90.0715),  # New Orleans
    "MA": (42.3601,  -71.0589),  # Boston
    "MD": (39.2904,  -76.6122),  # Baltimore
    "ME": (43.6591,  -70.2568),  # Portland
    "MI": (42.3314,  -83.0458),  # Detroit
    "MN": (44.9778,  -93.2650),  # Minneapolis
    "MO": (39.0997,  -94.5786),  # Kansas City
    "MS": (32.2988,  -90.1848),  # Jackson
    "MT": (45.7833, -108.5007),  # Billings
    "NC": (35.2271,  -80.8431),  # Charlotte
    "ND": (46.8772,  -96.7898),  # Fargo
    "NE": (41.2565,  -95.9345),  # Omaha
    "NH": (42.9956,  -71.4548),  # Manchester
    "NJ": (40.7357,  -74.1724),  # Newark
    "NM": (35.0844, -106.6504),  # Albuquerque
    "NV": (36.1699, -115.1398),  # Las Vegas
    "NY": (40.7128,  -74.0060),  # New York City
    "OH": (39.9612,  -82.9988),  # Columbus
    "OK": (35.4676,  -97.5164),  # Oklahoma City
    "OR": (45.5051, -122.6750),  # Portland
    "PA": (39.9526,  -75.1652),  # Philadelphia
    "RI": (41.8240,  -71.4128),  # Providence
    "SC": (34.0007,  -81.0348),  # Columbia
    "SD": (43.5446,  -96.7311),  # Sioux Falls
    "TN": (36.1627,  -86.7816),  # Nashville
    "TX": (29.7604,  -95.3698),  # Houston
    "UT": (40.7608, -111.8910),  # Salt Lake City
    "VA": (36.8529,  -75.9780),  # Virginia Beach
    "VT": (44.4759,  -73.2121),  # Burlington
    "WA": (47.6062, -122.3321),  # Seattle
    "WI": (43.0389,  -87.9065),  # Milwaukee
    "WV": (38.3498,  -81.6326),  # Charleston
    "WY": (41.1400, -104.8202),  # Cheyenne
}

# Black Friday + adjacent high-traffic weeks
BF_DATES = [
    "2024-11-18", "2024-11-25", "2024-12-02",
    "2025-11-17", "2025-11-24", "2025-12-01",
]

# ── BQ queries ────────────────────────────────────────────────────────────────
BQ_QUERY_TEMPLATE = """
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
WHERE Date >= "{start_date}" AND Date < CURRENT_DATE() AND State != "Other"
GROUP BY date, geo
ORDER BY date DESC
"""

PMAX_QUERY_TEMPLATE = """
SELECT
  DATE_TRUNC(Date, WEEK(MONDAY)) AS date,
  SUM(CASE WHEN Type = "Performance Max" THEN Cost ELSE 0 END) AS Pmax_Cost,
  SUM(CASE WHEN Type = "Performance Max" THEN Impressions ELSE 0 END) AS Pmax_Impressions
FROM `north-spore.north_spore_segments.full_segments`
WHERE Date >= "{start_date}"
GROUP BY date
ORDER BY date ASC
"""


# ── Pre-flight ────────────────────────────────────────────────────────────────

def preflight_check(raw_dir: Path) -> bool:
    """Verify all required manual files are present. Returns True if OK."""
    ok = True
    required = {
        "Instagram organic": list(raw_dir.glob("NS_IG_data*.csv")),
        "Facebook organic":  list(raw_dir.glob("NS_FB_data*.csv")),
        "YouTube organic":   list(raw_dir.glob("NS_YT_data*.csv")),
        "Promo intensity":   list(raw_dir.glob("NS_Promos*.csv")),
    }
    for label, files in required.items():
        if files:
            print(f"  [✓] {label}: {', '.join(f.name for f in files)}")
        else:
            print(f"  [✗] {label}: NO FILE FOUND — drop a NS_*.csv in {raw_dir}")
            ok = False

    tiktok_files = list(raw_dir.glob("Tiktok Ads_*.xlsx"))
    if tiktok_files:
        print(f"  [✓] TikTok: {', '.join(f.name for f in tiktok_files)}")
    else:
        print(f"  [!] TikTok: no Excel files found — TikTok columns will be 0")

    return ok


# ── Step 1: BigQuery ──────────────────────────────────────────────────────────

def pull_bq(start_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (geo_df, pmax_df)."""
    print(f"[BQ] Pulling paid media from {start_date} → today ...")
    client = bigquery.Client(project=BQ_PROJECT)

    geo_df = client.query(BQ_QUERY_TEMPLATE.format(start_date=start_date)).to_dataframe()
    geo_df["date"] = pd.to_datetime(geo_df["date"])
    geo_df = geo_df[geo_df["geo"].isin(VIABLE_STATES)].copy()
    print(f"[BQ] Paid media: {len(geo_df):,} rows | {geo_df['date'].min().date()} → {geo_df['date'].max().date()}")

    pmax_df = client.query(PMAX_QUERY_TEMPLATE.format(start_date=start_date)).to_dataframe()
    pmax_df["date"] = pd.to_datetime(pmax_df["date"])
    print(f"[BQ] Pmax: {len(pmax_df):,} rows")

    return geo_df, pmax_df


# ── Step 2: Panel + static controls ──────────────────────────────────────────

def build_panel(geo_df: pd.DataFrame, pmax_df: pd.DataFrame) -> pd.DataFrame:
    """Complete date×geo panel, add population, BF flag, allocate Pmax."""
    df = geo_df.copy()

    # Complete panel
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
    print(f"[panel] {len(df):,} rows ({len(all_dates)} weeks × {len(all_geos)} states)")

    # Population
    df["population"] = df["geo"].map(STATE_POPULATION)
    missing = df["population"].isna().sum()
    if missing:
        print(f"[panel] ⚠️  {missing} rows missing population mapping")

    # Black Friday flag
    df["bf_date"] = df["date"].isin(pd.to_datetime(BF_DATES)).astype(int)

    # Population weights per date (for Pmax + organic allocation)
    pop = df[["date", "geo", "population"]].drop_duplicates(["date", "geo"]).copy()
    pop["total_pop"] = pop.groupby("date")["population"].transform("sum")
    pop["pop_weight"] = pop["population"] / pop["total_pop"]

    # Allocate Pmax by population weight
    pmax_expanded = pop.merge(pmax_df[["date", "Pmax_Cost", "Pmax_Impressions"]], on="date", how="left")
    pmax_expanded["Pmax_Cost"]        = pmax_expanded["Pmax_Cost"].fillna(0) * pmax_expanded["pop_weight"]
    pmax_expanded["Pmax_Impressions"] = pmax_expanded["Pmax_Impressions"].fillna(0) * pmax_expanded["pop_weight"]

    df = df.merge(
        pmax_expanded[["date", "geo", "Pmax_Cost", "Pmax_Impressions"]],
        on=["date", "geo"], how="left"
    )
    df[["Pmax_Cost", "Pmax_Impressions"]] = df[["Pmax_Cost", "Pmax_Impressions"]].fillna(0)

    return df, pop


# ── Step 3: Organic CSVs ──────────────────────────────────────────────────────

def _vintage_sort_key(path: Path):
    """Parse MonthYear from filename for sorting; no-date files sort first."""
    months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
              "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    m = re.search(r"([A-Za-z]{3})[_]?(\d{2})", path.stem, re.IGNORECASE)
    if not m:
        return (0, 0)
    return (2000 + int(m.group(2)), months.get(m.group(1).lower(), 0))


def _load_one_organic(path: Path, source: str) -> pd.DataFrame:
    """Load a single organic CSV, normalise to (Date, Views, Data Source)."""
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])

    if source == "Facebook":
        # FB exports use 'Organic Impressions' instead of 'Views'
        if "Organic Impressions" in df.columns:
            df = df.rename(columns={"Organic Impressions": "Views"})

    df = df[["Date", "Views"]].copy()
    df["Data Source"] = source
    return df


def load_organic(raw_dir: Path, pop: pd.DataFrame) -> pd.DataFrame:
    """
    Combine all organic CSVs per source, deduplicate by date, allocate to states
    by population weight, aggregate to weekly, and pivot to wide columns.
    """
    sources = {
        "Instagram": sorted(raw_dir.glob("NS_IG_data*.csv"), key=_vintage_sort_key),
        "Facebook":  sorted(raw_dir.glob("NS_FB_data*.csv"), key=_vintage_sort_key),
        "YouTube":   sorted(raw_dir.glob("NS_YT_data*.csv"), key=_vintage_sort_key),
    }

    parts = []
    for src, files in sources.items():
        dfs = [_load_one_organic(f, src) for f in files]
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.sort_values("Date").drop_duplicates(subset=["Date", "Data Source"], keep="last")
        parts.append(combined)
        print(f"[organic] {src}: {len(combined):,} rows from {len(files)} file(s)")

    full_organic = pd.concat(parts, ignore_index=True)
    full_organic = full_organic.rename(columns={"Date": "date"})

    # Allocate national total to states by population weight
    expanded = pop.merge(full_organic[["date", "Data Source", "Views"]], on="date", how="left")
    expanded["Views"] = expanded["Views"].fillna(0) * expanded["pop_weight"]

    # Pivot to wide: Facebook_Views, Instagram_Views, YouTube_Views
    pivoted = expanded.pivot_table(
        index=["date", "geo"], columns="Data Source", values="Views", fill_value=0
    ).reset_index()
    pivoted.columns.name = None
    pivoted = pivoted.rename(columns={c: f"{c}_Views" for c in ["Facebook", "Instagram", "YouTube"]})

    # Aggregate to Monday-week
    organic_final = (
        pivoted
        .groupby([pd.Grouper(key="date", freq="W-MON", label="left", closed="left"), "geo"])
        [["Facebook_Views", "Instagram_Views", "YouTube_Views"]]
        .sum()
        .reset_index()
    )

    print(f"[organic] Allocated: {len(organic_final):,} rows")
    return organic_final


# ── Step 4: Promo data ────────────────────────────────────────────────────────

def load_promo(raw_dir: Path) -> pd.DataFrame:
    """Load the most recent promo CSV."""
    files = sorted(raw_dir.glob("NS_Promos*.csv"), key=_vintage_sort_key)
    if not files:
        raise FileNotFoundError(f"No NS_Promos*.csv found in {raw_dir}")
    path = files[-1]
    print(f"[promo] Loading {path.name}")

    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Promo Intensity"] = (
        df["Promo Intensity"].astype(str).str.replace("%", "").astype(float) / 100
    )
    df["Product Launch"] = df["Product Launch"].fillna(0).astype(float)
    return df[["Date", "Promo Intensity", "Product Launch"]]


# ── Step 5: Temperature via Open-Meteo ───────────────────────────────────────

def pull_weather(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Query Open-Meteo archive API for the most populous city in each state.
    Returns weekly_average_temp (°F) and weekly_rainfall (inches) per state per week.
    """
    print(f"[weather] Pulling Open-Meteo data {start_date} → {end_date} for {len(STATE_CITY_COORDS)} states ...")

    base_url = "https://archive-api.open-meteo.com/v1/archive"
    rows = []

    for i, (state, (lat, lon)) in enumerate(STATE_CITY_COORDS.items()):
        resp = requests.get(base_url, params={
            "latitude":           lat,
            "longitude":          lon,
            "start_date":         start_date,
            "end_date":           end_date,
            "daily":              "temperature_2m_mean,precipitation_sum",
            "temperature_unit":   "fahrenheit",
            "precipitation_unit": "inch",
            "timezone":           "auto",
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()["daily"]

        for date_str, temp, rain in zip(data["time"], data["temperature_2m_mean"], data["precipitation_sum"]):
            rows.append({
                "geo":   state,
                "date":  pd.Timestamp(date_str),
                "temp":  temp if temp is not None else float("nan"),
                "rain":  rain if rain is not None else 0.0,
            })

        if (i + 1) % 10 == 0:
            print(f"[weather]   {i+1}/{len(STATE_CITY_COORDS)} states done")
        time.sleep(0.05)  # polite rate limiting

    daily = pd.DataFrame(rows)
    daily["week_start"] = daily["date"] - pd.to_timedelta(daily["date"].dt.weekday, unit="d")

    weekly = (
        daily.groupby(["geo", "week_start"])
        .agg(weekly_average_temp=("temp", "mean"), weekly_rainfall=("rain", "sum"))
        .reset_index()
        .rename(columns={"week_start": "date"})
    )

    print(f"[weather] {len(weekly):,} state-week rows | "
          f"temp range: {weekly['weekly_average_temp'].min():.1f}–{weekly['weekly_average_temp'].max():.1f}°F")
    return weekly


# ── Step 6: TikTok ────────────────────────────────────────────────────────────

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


def load_tiktok(raw_dir: Path, model_end: pd.Timestamp) -> pd.DataFrame | None:
    """Load all TikTok Excel exports, redistribute Unknown geo, aggregate to weekly."""
    files = list(raw_dir.glob("Tiktok Ads_*.xlsx"))
    if not files:
        print("[tiktok] No Excel files found — TikTok columns will be 0")
        return None

    dfs = []
    for f in files:
        df = pd.read_excel(f, header=0)
        df.columns = ["account", "date", "subregion", "cost", "impressions", "currency"]
        df["date"] = pd.to_datetime(df["date"])
        dfs.append(df)

    tt = pd.concat(dfs, ignore_index=True)
    tt = tt[tt["date"] <= model_end].copy()
    print(f"[tiktok] Loaded {len(tt):,} rows from {len(files)} file(s)")

    # Redistribute Unknown geo proportionally
    all_states = list(STATE_MAP_FULL.values())
    known   = tt[tt["subregion"] != "Unknown"].copy()
    unknown = tt[tt["subregion"] == "Unknown"].copy()

    if not unknown.empty:
        parts = [known]
        for day, unk_day in unknown.groupby("date"):
            unk_cost = unk_day["cost"].sum()
            unk_imps = unk_day["impressions"].sum()
            if unk_cost == 0 and unk_imps == 0:
                continue
            known_day = known[known["date"] == day].copy()
            total = known_day["cost"].sum()
            if total > 0:
                known_day["_w"] = known_day["cost"] / total
            else:
                known_day = pd.DataFrame({
                    "date": day, "subregion": all_states,
                    "cost": 0.0, "impressions": 0.0, "_w": 1.0 / len(all_states)
                })
            add = known_day[["date", "subregion", "_w"]].copy()
            add["cost"]        = add["_w"] * unk_cost
            add["impressions"] = add["_w"] * unk_imps
            parts.append(add.drop(columns=["_w"]))
        tt = pd.concat(parts, ignore_index=True)

    tt["geo"] = tt["subregion"].map(STATE_MAP_FULL)
    tt = tt[tt["geo"].notna()].copy()
    tt["week"] = tt["date"] - pd.to_timedelta(tt["date"].dt.dayofweek, unit="d")

    weekly = (
        tt.groupby(["week", "geo"])[["cost", "impressions"]]
        .sum()
        .reset_index()
        .rename(columns={"week": "date", "cost": "TikTok_Cost", "impressions": "TikTok_Impressions"})
    )
    print(f"[tiktok] {(weekly['TikTok_Cost'] > 0).sum()} non-zero geo-week rows")
    return weekly


# ── Step 7: Consolidate channels ─────────────────────────────────────────────

def consolidate_channels(df: pd.DataFrame) -> pd.DataFrame:
    """Roll Brand Shopping into Brand; Competitors into Non_Brand. Drop source cols."""
    df = df.copy()
    df["Brand_Cost"]         += df["Brand_Shopping_Cost"]
    df["Brand_Impressions"]  += df["Brand_Shopping_Impressions"]
    df["Non_Brand_Cost"]     += df["Competitors_Cost"]
    df["Non_Brand_Impressions"] += df["Competitors_Impressions"]
    df.drop(columns=[
        "Brand_Shopping_Cost", "Brand_Shopping_Impressions",
        "Competitors_Cost", "Competitors_Impressions",
    ], inplace=True)
    return df


# ── Step 8: Validate ──────────────────────────────────────────────────────────

def validate(df: pd.DataFrame) -> bool:
    checks = [
        (df["weekly_average_temp"].isna().sum() == 0,         "weekly_average_temp has no NaNs"),
        (df["population"].isna().sum() == 0,                  "population has no NaNs"),
        (pd.to_datetime(df["date"]).dt.dayofweek.eq(0).all(), "All dates are Monday-aligned"),
        (not df.duplicated(["date", "geo"]).any(),            "No duplicate date×geo rows"),
        ((df["Revenue"] >= 0).all(),                          "Revenue non-negative"),
        ((df["weekly_average_temp"] != 0).all(),              "No zero temperatures"),
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

    # Pre-flight
    print("\n[preflight]")
    if not preflight_check(RAW_DIR):
        print("\nAborting — upload missing files and re-run.")
        sys.exit(1)

    # 1. BQ
    geo_df, pmax_df = pull_bq(start_date)
    model_end = geo_df["date"].max()

    # 2. Panel, population, BF flag, Pmax allocation
    df, pop = build_panel(geo_df, pmax_df)

    # 3. Organic
    organic = load_organic(RAW_DIR, pop)
    df = df.merge(organic, on=["date", "geo"], how="left")
    df[["Facebook_Views", "Instagram_Views", "YouTube_Views"]] = (
        df[["Facebook_Views", "Instagram_Views", "YouTube_Views"]].fillna(0)
    )

    # 4. Promo
    promo = load_promo(RAW_DIR)
    df = df.merge(promo, left_on="date", right_on="Date", how="left").drop(columns=["Date"])
    df["Promo Intensity"] = df["Promo Intensity"].fillna(0)
    df["Product Launch"]  = df["Product Launch"].fillna(0)

    # 5. Temperature
    end_date = model_end.strftime("%Y-%m-%d")
    weather = pull_weather(start_date, end_date)
    df = df.merge(weather, on=["date", "geo"], how="left")
    df["weekly_average_temp"] = df["weekly_average_temp"].fillna(0)
    df["weekly_rainfall"]     = df["weekly_rainfall"].fillna(0)

    # 6. TikTok
    tiktok = load_tiktok(RAW_DIR, model_end)
    if tiktok is not None:
        df = df.merge(tiktok, on=["date", "geo"], how="left")
    else:
        df["TikTok_Cost"]        = 0.0
        df["TikTok_Impressions"] = 0.0
    df[["TikTok_Cost", "TikTok_Impressions"]] = (
        df[["TikTok_Cost", "TikTok_Impressions"]].fillna(0)
    )

    # 7. Channel consolidation
    df = consolidate_channels(df)

    # 8. Validate
    print("\n[validate]")
    ok = validate(df)
    if not ok:
        print("\n⚠️  Validation issues found — review before using in production.")

    # 9. Write
    if args.prod:
        vintage = model_end.strftime("%b%y")
        out_path = PROC_DIR / f"NS_mmm_data_{vintage}.csv"
    else:
        out_path = PROC_DIR / "test_refresh.csv"

    df.to_csv(out_path, index=False)

    print(f"\n[done] {len(df):,} rows × {len(df.columns)} cols → {out_path.relative_to(ROOT)}")
    print(f"       {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"       States: {df['geo'].nunique()} | Columns: {list(df.columns)}")

    if args.prod:
        print(f"\nNotebook will auto-load this file on next run.")


if __name__ == "__main__":
    main()
