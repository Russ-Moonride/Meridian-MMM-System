"""
Billboard data correction for Freedom Power Apr26 dataset.

Issues corrected:
  Austin:
    - Impressions were flat 845,515/wk for all 10 weeks; now variable per board schedule
      (Board 9082 I-35 ends 4/12, Board 9390 Lamar ends 4/26)
    - Spend zeroed out after 4/26 when both boards ended
    - Weeks 4/13-4/26 spend adjusted proportionally for board 9390 only
  Houston:
    - Two boards completely missing; added from spend table (Apr 2026)
      HOU001369 (Hwy 290 NW Frwy): active from 3/16/2026 at $2,100/wk
      HOU005480 (I-610 West Loop):  active from 3/23/2026 at $6,125/wk
    - Impressions use 700k/board/week proxy (Geopath actuals not yet available)

Sources:
  Reagan Outdoor Austin location list 2/17/2026 (PDF)
  Billboard spend table Apr 2026 (PNG)
"""

import pandas as pd
from pathlib import Path

# ── Austin board schedule (Reagan Outdoor Austin) ─────────────────────────────
AUSTIN_9082_IMPR = 688_700     # I-35 N, weekly A18+ impressions
AUSTIN_9390_IMPR = 165_815     # Lamar Blvd S, weekly A18+ impressions
AUSTIN_9082_END  = pd.Timestamp("2026-04-12")
AUSTIN_9390_END  = pd.Timestamp("2026-04-26")
AUSTIN_START         = pd.Timestamp("2026-03-02")   # both boards launch together
AUSTIN_COMBINED_COST = 32_900.0  # both boards active together
AUSTIN_9390_COST = round(AUSTIN_COMBINED_COST * AUSTIN_9390_IMPR /
                         (AUSTIN_9082_IMPR + AUSTIN_9390_IMPR), 2)  # 6,384.11

# ── Houston board schedule (spend table Apr 2026) ─────────────────────────────
HOU001369_START  = pd.Timestamp("2026-03-16")
HOU001369_COST   = 2_100.0     # $8,400 / 4-week period

HOU005480_START  = pd.Timestamp("2026-03-23")
HOU005480_COST   = 6_125.0     # $24,500 / 4-week period

HOUSTON_BOARD_PROXY_IMPR = 700_000  # per board per week (analyst proxy)


def _austin_values(date: pd.Timestamp):
    if date < AUSTIN_START:
        return 0.0, 0.0
    b9082 = date <= AUSTIN_9082_END
    b9390 = date <= AUSTIN_9390_END
    if b9082 and b9390:
        return AUSTIN_COMBINED_COST, float(AUSTIN_9082_IMPR + AUSTIN_9390_IMPR)
    elif b9390:
        return AUSTIN_9390_COST, float(AUSTIN_9390_IMPR)
    else:
        return 0.0, 0.0


def _houston_values(date: pd.Timestamp):
    h1 = date >= HOU001369_START
    h2 = date >= HOU005480_START
    cost  = (HOU001369_COST if h1 else 0.0) + (HOU005480_COST if h2 else 0.0)
    impr  = ((1 if h1 else 0) + (1 if h2 else 0)) * HOUSTON_BOARD_PROXY_IMPR
    return cost, float(impr)


def apply_corrections(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    for idx, row in df.iterrows():
        if row["geo"] == "Austin":
            cost, impr = _austin_values(row["date"])
            df.at[idx, "Billboard_Cost"]        = cost
            df.at[idx, "Billboard_Impressions"] = impr
        elif row["geo"] == "Houston":
            cost, impr = _houston_values(row["date"])
            df.at[idx, "Billboard_Cost"]        = cost
            df.at[idx, "Billboard_Impressions"] = impr

    return df


if __name__ == "__main__":
    RAW_PATH  = Path("data/raw/Freedom_Power/Freedom_MMM_data_Apr26.csv")
    PROC_PATH = Path("data/processed/Freedom_Power/Freedom_MMM_data_Apr26_gqv.csv")

    for path in (RAW_PATH, PROC_PATH):
        df = pd.read_csv(path)
        df_fixed = apply_corrections(df)
        df_fixed.to_csv(path, index=False)
        print(f"Updated: {path}")

    # Quick verification
    df_check = pd.read_csv(RAW_PATH)
    df_check["date"] = pd.to_datetime(df_check["date"])
    print("\nAustin billboard (active weeks):")
    print(df_check[df_check["geo"] == "Austin"][["date", "Billboard_Cost", "Billboard_Impressions"]]
          [df_check["Billboard_Cost"] > 0].to_string(index=False))
    print("\nHouston billboard (active weeks):")
    print(df_check[df_check["geo"] == "Houston"][["date", "Billboard_Cost", "Billboard_Impressions"]]
          [df_check["Billboard_Cost"] > 0].to_string(index=False))
