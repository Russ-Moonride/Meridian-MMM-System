"""
Extends NS_mmm_data_Apr26.csv through 2026-06-15 by:
  - Backfilling TikTok data from downloaded xlsx files
  - Adding 6 new weeks (2026-05-11 → 2026-06-15)
  - Projecting paid/organic channels using same-week-prior-year values
  - Applying updated promo data from NorthSpore promo CSV
  - Carrying forward weather from prior-year same weeks
  - Projecting Revenue/Purchases via same-week-prior-year × recent trend factor
Output: data/processed/northspore/NS_mmm_data_Jun26.csv
"""

from pathlib import Path
import numpy as np
import pandas as pd

WORKSPACE = Path(__file__).resolve().parents[2]
RAW_DIR = WORKSPACE / "data/raw/northspore"
PROC_DIR = WORKSPACE / "data/processed/northspore"

STATE_ABBREV = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}

PAID_CHANNELS = [
    "Brand", "Non_Brand", "DVD", "Retargeting", "Prospecting",
    "Remarketing", "Shopping", "Pmax",
]
ORGANIC_COLS = ["Facebook_Views", "Instagram_Views", "YouTube_Views"]


def load_tiktok_weekly(xlsx_path: Path) -> pd.DataFrame:
    """Aggregate daily TikTok state data to weekly geo totals."""
    df = pd.read_excel(xlsx_path)
    df["By Day"] = pd.to_datetime(df["By Day"])
    df["week_start"] = df["By Day"] - pd.to_timedelta(df["By Day"].dt.weekday, unit="D")
    df["geo"] = df["Subregion"].map(STATE_ABBREV)
    df = df.dropna(subset=["geo"])
    weekly = (
        df.groupby(["week_start", "geo"])[["Cost", "Impressions"]]
        .sum()
        .reset_index()
        .rename(columns={"week_start": "date", "Cost": "TikTok_Cost", "Impressions": "TikTok_Impressions"})
    )
    return weekly


def build_tiktok_lookup() -> pd.DataFrame:
    """Merge both TikTok xlsx files into a single weekly lookup."""
    parts = []
    for fname in [
        "Tiktok Ads_Untitled report_North Spore_20250401-20250731.xlsx",
        "Tiktok Ads_Untitled report_North Spore_20260101-20260529.xlsx",
    ]:
        p = RAW_DIR / fname
        if p.exists():
            parts.append(load_tiktok_weekly(p))
    if not parts:
        return pd.DataFrame(columns=["date", "geo", "TikTok_Cost", "TikTok_Impressions"])
    tt = pd.concat(parts).drop_duplicates(subset=["date", "geo"])
    tt["date"] = pd.to_datetime(tt["date"])
    return tt


def load_promo(csv_path: Path) -> pd.DataFrame:
    """Load and clean the promo CSV."""
    promo = pd.read_csv(csv_path)
    promo["Date"] = pd.to_datetime(promo["Date"])
    promo["Promo Intensity"] = (
        promo["Promo Intensity"].astype(str).str.rstrip("%").astype(float) / 100.0
    )
    promo["Product Launch"] = promo["Product Launch"].fillna(0).astype(float)
    promo = promo.rename(columns={"Date": "date"})
    return promo[["date", "Promo Intensity", "Product Launch"]]


def prior_year_factor(base: pd.DataFrame, date_col: str = "date") -> float:
    """Compute ratio of mean of last 4 weeks vs same-4-weeks one year ago."""
    df = base.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    max_date = df[date_col].max()
    recent_4 = df[df[date_col] > max_date - pd.Timedelta(weeks=4)]
    year_ago_4 = df[
        (df[date_col] > max_date - pd.Timedelta(weeks=56))
        & (df[date_col] <= max_date - pd.Timedelta(weeks=52))
    ]
    # Use Revenue as proxy for overall business trend
    if recent_4["Revenue"].sum() == 0 or year_ago_4["Revenue"].sum() == 0:
        return 1.0
    return (recent_4["Revenue"].sum() / len(recent_4)) / (year_ago_4["Revenue"].sum() / len(year_ago_4))


def project_week_from_prior_year(
    base: pd.DataFrame, new_date: pd.Timestamp, trend_factor: float
) -> pd.DataFrame:
    """
    For a given new_date (Monday), pull the same geo rows from 52 weeks prior
    and scale numeric columns by trend_factor.
    """
    prior_date = new_date - pd.Timedelta(weeks=52)
    prior_rows = base[base["date"] == prior_date.strftime("%Y-%m-%d")].copy()
    if prior_rows.empty:
        prior_date = new_date - pd.Timedelta(weeks=53)
        prior_rows = base[base["date"] == prior_date.strftime("%Y-%m-%d")].copy()
    if prior_rows.empty:
        return pd.DataFrame()

    prior_rows = prior_rows.copy()
    prior_rows["date"] = new_date.strftime("%Y-%m-%d")

    # Scale all numeric media, organic, and KPI columns by trend factor
    scale_cols = (
        [f"{c}_Cost" for c in PAID_CHANNELS]
        + [f"{c}_Impressions" for c in PAID_CHANNELS]
        + ORGANIC_COLS
        + ["Revenue", "Purchases"]
    )
    for col in scale_cols:
        if col in prior_rows.columns:
            prior_rows[col] = (prior_rows[col] * trend_factor).round(6)

    # Reset Black Friday (no BF in May/June)
    if "black_friday" in prior_rows.columns:
        prior_rows["black_friday"] = 0
    if "bf_date" in prior_rows.columns:
        prior_rows["bf_date"] = 0

    return prior_rows


def main():
    # ── Load base processed data ─────────────────────────────────────────────
    base_path = PROC_DIR / "NS_mmm_data_Apr26.csv"
    df = pd.read_csv(base_path)
    df["date"] = pd.to_datetime(df["date"])

    print(f"Base data: {df['date'].min().date()} → {df['date'].max().date()} | {len(df):,} rows")

    # ── Build TikTok lookup and backfill existing rows ────────────────────────
    tt = build_tiktok_lookup()
    print(f"TikTok lookup: {len(tt):,} geo-week rows, {tt['date'].min().date()} → {tt['date'].max().date()}")

    if not tt.empty:
        df = df.merge(
            tt.rename(columns={"TikTok_Cost": "_tt_cost", "TikTok_Impressions": "_tt_imp"}),
            on=["date", "geo"],
            how="left",
        )
        for src, dst in [("_tt_cost", "TikTok_Cost"), ("_tt_imp", "TikTok_Impressions")]:
            if src in df.columns:
                mask = df[src].notna() & (df[src] > 0)
                df.loc[mask, dst] = df.loc[mask, src]
                df.drop(columns=[src], inplace=True)

    df["TikTok_Cost"] = df["TikTok_Cost"].fillna(0)
    df["TikTok_Impressions"] = df["TikTok_Impressions"].fillna(0)

    # ── Identify new weeks to add ─────────────────────────────────────────────
    last_date = df["date"].max()
    new_dates = pd.date_range(
        start=last_date + pd.Timedelta(weeks=1),
        end=pd.Timestamp("2026-06-15"),
        freq="W-MON",
    )
    print(f"New weeks to add: {[str(d.date()) for d in new_dates]}")

    # ── Compute year-over-year trend factor ───────────────────────────────────
    trend = prior_year_factor(df)
    print(f"YoY trend factor: {trend:.3f}x")

    # ── Load promo data ───────────────────────────────────────────────────────
    promo_csv = RAW_DIR / "NorthSpore - Promo List - PromoData (1).csv"
    if not promo_csv.exists():
        promo_csv = next(
            (p for p in sorted(WORKSPACE.rglob("*.csv")) if "PromoData" in p.name), None
        )
    if promo_csv:
        print(f"Using promo file: {promo_csv}")
        promo = load_promo(promo_csv)
    else:
        print("WARNING: promo file not found, using existing values")
        promo = None

    # ── Project each new week ─────────────────────────────────────────────────
    new_blocks = []
    for new_date in new_dates:
        block = project_week_from_prior_year(df, new_date, trend)
        if block.empty:
            print(f"WARNING: no prior-year data for {new_date.date()}, skipping")
            continue
        new_blocks.append(block)

    if not new_blocks:
        print("No new rows to add.")
        return

    new_df = pd.concat(new_blocks, ignore_index=True)
    new_df["date"] = pd.to_datetime(new_df["date"])

    # ── Patch TikTok from actual data for weeks where we have it ─────────────
    if not tt.empty:
        tt_patch = tt[tt["date"].isin(new_dates)]
        if not tt_patch.empty:
            new_df = new_df.merge(
                tt_patch.rename(columns={"TikTok_Cost": "_tt_cost", "TikTok_Impressions": "_tt_imp"}),
                on=["date", "geo"],
                how="left",
            )
            for src, dst in [("_tt_cost", "TikTok_Cost"), ("_tt_imp", "TikTok_Impressions")]:
                if src in new_df.columns:
                    mask = new_df[src].notna()
                    new_df.loc[mask, dst] = new_df.loc[mask, src]
                    new_df.drop(columns=[src], inplace=True)
        new_df["TikTok_Cost"] = new_df["TikTok_Cost"].fillna(0)
        new_df["TikTok_Impressions"] = new_df["TikTok_Impressions"].fillna(0)

    # ── Apply promo data to new rows ──────────────────────────────────────────
    if promo is not None:
        promo["date"] = pd.to_datetime(promo["date"])
        new_df = new_df.merge(
            promo.rename(columns={"Promo Intensity": "_pi", "Product Launch": "_pl"}),
            on="date",
            how="left",
        )
        new_df["Promo Intensity"] = new_df["_pi"].fillna(new_df["Promo Intensity"])
        new_df["Product Launch"] = new_df["_pl"].fillna(new_df["Product Launch"])
        new_df.drop(columns=["_pi", "_pl"], errors="ignore", inplace=True)

    # ── Also refresh promo for existing rows from updated file ────────────────
    if promo is not None:
        df = df.merge(
            promo.rename(columns={"Promo Intensity": "_pi", "Product Launch": "_pl"}),
            on="date",
            how="left",
        )
        mask = df["_pi"].notna()
        df.loc[mask, "Promo Intensity"] = df.loc[mask, "_pi"]
        df.loc[mask, "Product Launch"] = df.loc[mask, "_pl"]
        df.drop(columns=["_pi", "_pl"], errors="ignore", inplace=True)

    # ── Zero out TikTok for new weeks (channel paused after 2026-05-04) ───────
    new_df["TikTok_Cost"] = 0.0
    new_df["TikTok_Impressions"] = 0.0

    # ── Combine and finalize ──────────────────────────────────────────────────
    combined = pd.concat([df, new_df], ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    combined = combined.sort_values(["geo", "date"]).reset_index(drop=True)

    # Fill any remaining NaN
    numeric_cols = combined.select_dtypes(include=[np.number]).columns
    combined[numeric_cols] = combined[numeric_cols].fillna(0)

    out_path = PROC_DIR / "NS_mmm_data_Jun26.csv"
    combined.to_csv(out_path, index=False)

    final_dates = combined["date"].unique()
    print(f"\nOutput: {out_path}")
    print(f"  Rows: {len(combined):,}  |  Weeks: {len(final_dates)}  |  Geos: {combined['geo'].nunique()}")
    print(f"  Date range: {combined['date'].min().date()} → {combined['date'].max().date()}")

    # Spot-check new weeks
    spot = combined[combined["date"] >= "2026-05-11"].groupby("date").agg(
        Revenue=("Revenue", "sum"),
        Brand_Cost=("Brand_Cost", "sum"),
        TikTok_Cost=("TikTok_Cost", "sum"),
        Facebook_Views=("Facebook_Views", "sum"),
        Promo_Intensity=("Promo Intensity", "mean"),
    ).reset_index()
    print("\nSpot-check new weeks (national totals):")
    print(spot.to_string())


if __name__ == "__main__":
    main()
