"""
src/data_prep.py
~~~~~~~~~~~~~~~~
Data preparation for the Meridian MMM pipeline.

Public API
----------
load_config(path)   → dict
prepare_data(config) → pd.DataFrame

``prepare_data`` accepts a client config dict (from ``configs/{client_id}.yaml``)
and returns a validated, Monday-aligned DataFrame ready for Meridian's
DataFrameInputDataBuilder.  It mirrors the steps in the modeling notebooks
without any notebook-specific hard-coding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


# ── Public API ────────────────────────────────────────────────────────────────

def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load a client YAML config from disk and return it as a dict."""
    with open(config_path) as fh:
        return yaml.safe_load(fh)


def prepare_data(config: dict[str, Any]) -> pd.DataFrame:
    """
    Load, align, engineer features, and validate a weekly MMM DataFrame.

    Steps
    -----
    1. Load CSV from ``config['data_path']``
    2. Optionally filter to ``[start_date, end_date]``
    3. Coerce all dates to the Monday of their ISO week
    4. Build the perfect (date × geo) cross-product index; fill gaps with 0.
       Population is propagated per-geo before zero-filling so that newly
       created rows inherit the correct constant value.
    5. Drop geos listed in ``config['geos_to_drop']``
    6. Engineer the ``black_friday`` indicator if ``'black_friday'`` is listed
       in ``config['controls']``
    7. Cast KPI, media (cost + impressions), organic (views), population, and
       control columns to float32
    8. Validate: required columns present, no NaNs in KPI / media columns,
       all dates Monday-aligned, population non-zero

    Parameters
    ----------
    config : dict
        Loaded from ``configs/{client_id}.yaml``.
        Required keys: ``data_path``, ``date_column``, ``geo_column``,
        ``kpi_column``, ``channels``.
        Optional keys: ``organic_channels``, ``controls``,
        ``population_column``, ``geos_to_drop``, ``start_date``, ``end_date``.

    Returns
    -------
    pd.DataFrame
        Sorted by ``(geo_column, date_column)``.  All numeric model columns
        are float32.

    Raises
    ------
    FileNotFoundError
        If ``data_path`` does not exist.
    ValueError
        If required columns are missing, NaN values remain in KPI or media
        columns after gap-filling, dates are not Monday-aligned, or
        population contains zeros.
    """
    date_col     = config["date_column"]
    geo_col      = config["geo_column"]
    kpi_col      = config["kpi_column"]
    channels     = config["channels"]
    organic_chs  = config.get("organic_channels", [])
    controls     = config.get("controls", [])
    pop_col      = config.get("population_column", "population")
    geos_to_drop = config.get("geos_to_drop", [])

    # ── 1. Load ────────────────────────────────────────────────────────────────
    data_path = Path(config["data_path"])
    if not data_path.exists():
        gcs_path = config.get("gcs_data_path", "")
        if gcs_path.startswith("gs://"):
            data_path = _download_from_gcs(gcs_path)
        else:
            raise FileNotFoundError(f"Data file not found: {data_path}")

    df = pd.read_csv(data_path, parse_dates=[date_col])

    # ── 2. Date filter (optional) ──────────────────────────────────────────────
    if "start_date" in config:
        df = df[df[date_col] >= pd.to_datetime(config["start_date"])]
    if "end_date" in config:
        df = df[df[date_col] <= pd.to_datetime(config["end_date"])]
    df = df.copy()

    # ── 3. Monday alignment ────────────────────────────────────────────────────
    # Subtracting weekday() days always lands on Monday (weekday 0).
    df[date_col] = df[date_col] - pd.to_timedelta(df[date_col].dt.weekday, unit="D")

    # ── 4. Perfect (date × geo) index ─────────────────────────────────────────
    # Meridian requires every geo to have an entry for every time point.
    # Any (date, geo) combination absent from the source CSV is injected and
    # filled with 0 for spend / KPI / organic columns.
    #
    # Population is a per-geo constant, so propagate it within each geo
    # BEFORE zeroing everything else — otherwise new rows would inherit 0.
    all_dates = sorted(df[date_col].unique())
    all_geos  = sorted(df[geo_col].unique())

    perfect = pd.DataFrame(
        pd.MultiIndex.from_product(
            [all_dates, all_geos], names=[date_col, geo_col]
        ).to_frame(index=False)
    )
    df = perfect.merge(df, on=[date_col, geo_col], how="left")

    if pop_col in df.columns:
        df[pop_col] = (
            df.groupby(geo_col)[pop_col]
            .transform(lambda s: s.ffill().bfill())
        )

    df = (
        df.fillna(0)
        .sort_values([geo_col, date_col])
        .reset_index(drop=True)
    )

    # ── 5. Drop low-volume / excluded geos ────────────────────────────────────
    if geos_to_drop:
        df = df[~df[geo_col].isin(geos_to_drop)].reset_index(drop=True)

    # ── 6. Black Friday indicator ──────────────────────────────────────────────
    # Computed from the calendar rather than read from CSV, because the raw
    # bf_date column records a raw date rather than a weekly indicator.
    if "black_friday" in controls:
        bf_starts = _black_friday_week_starts(df[date_col].dt.year.unique())
        df["black_friday"] = df[date_col].isin(bf_starts).astype(np.int32)

    # ── 7. Float32 casting ─────────────────────────────────────────────────────
    df[kpi_col] = df[kpi_col].astype(np.float32)

    for ch in channels:
        df[f"{ch}_Cost"]        = df[f"{ch}_Cost"].astype(np.float32)
        df[f"{ch}_Impressions"] = df[f"{ch}_Impressions"].astype(np.float32)

    for ch in organic_chs:
        df[f"{ch}_Views"] = df[f"{ch}_Views"].astype(np.float32)

    if pop_col in df.columns:
        df[pop_col] = df[pop_col].astype(np.float32)

    for ctrl in controls:
        if ctrl in df.columns:
            df[ctrl] = df[ctrl].astype(np.float32)

    # ── 8. Validation ──────────────────────────────────────────────────────────
    _validate(df, config)

    return df


# ── Internal helpers ──────────────────────────────────────────────────────────

def _download_from_gcs(gcs_uri: str) -> Path:
    """Download a GCS file to /tmp and return the local Path."""
    import tempfile
    from google.cloud import storage

    # gs://bucket/path/to/file.csv → bucket, blob_path
    without_scheme = gcs_uri[len("gs://"):]
    bucket_name, blob_path = without_scheme.split("/", 1)

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob   = bucket.blob(blob_path)

    suffix = Path(blob_path).suffix
    tmp    = Path(tempfile.mktemp(suffix=suffix))
    blob.download_to_filename(str(tmp))
    print(f"     Downloaded {gcs_uri} → {tmp}")
    return tmp

def _black_friday_week_starts(years) -> set[pd.Timestamp]:
    """
    Return the Monday of Black Friday week for each year in *years*.

    Black Friday is the day after the fourth Thursday of November.
    We return the Monday of that same week so it aligns with Meridian's
    Monday-anchored time index.
    """
    result: set[pd.Timestamp] = set()
    for year in years:
        nov1       = pd.Timestamp(year=int(year), month=11, day=1)
        first_thu  = nov1 + pd.Timedelta(days=(3 - nov1.weekday()) % 7)
        fourth_thu = first_thu + pd.Timedelta(days=21)
        bf         = fourth_thu + pd.Timedelta(days=1)          # Friday
        monday     = bf - pd.Timedelta(days=bf.weekday())        # Monday of that week
        result.add(monday)
    return result


def _validate(df: pd.DataFrame, config: dict[str, Any]) -> None:
    """
    Assert the DataFrame is ready for DataFrameInputDataBuilder.
    Raises ValueError with a specific message on the first failure found.
    """
    date_col  = config["date_column"]
    geo_col   = config["geo_column"]
    kpi_col   = config["kpi_column"]
    channels  = config["channels"]
    organic   = config.get("organic_channels", [])
    pop_col   = config.get("population_column", "population")

    # Required columns must exist
    required = (
        [date_col, geo_col, kpi_col]
        + [f"{c}_Cost"        for c in channels]
        + [f"{c}_Impressions" for c in channels]
        + [f"{c}_Views"       for c in organic]
    )
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns after preparation: {missing}")

    # All dates must be Monday-aligned (weekday == 0)
    bad = df.loc[df[date_col].dt.weekday != 0, date_col].unique()
    if len(bad):
        raise ValueError(
            f"Non-Monday dates remain after alignment: {sorted(bad)[:5]}"
        )

    # No NaN in KPI or media columns
    check_nulls = (
        [kpi_col]
        + [f"{c}_Cost"        for c in channels]
        + [f"{c}_Impressions" for c in channels]
    )
    for col in check_nulls:
        n_null = int(df[col].isna().sum())
        if n_null:
            raise ValueError(f"Column '{col}' has {n_null} NaN values after gap-fill")

    # Population must be positive for every row (gap-fill propagation check)
    if pop_col in df.columns:
        n_zero = int((df[pop_col] == 0).sum())
        if n_zero:
            raise ValueError(
                f"'{pop_col}' has {n_zero} zero-valued rows — "
                "check geo names match the population_column values in the CSV"
            )


# ── Test call ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    config_path = Path("configs/NorthSpore.yaml")
    print(f"Loading config: {config_path}")
    cfg = load_config(config_path)

    print(f"Client:   {cfg['client_id']}")
    print(f"KPI:      {cfg['kpi_column']} ({cfg['kpi_type']})")
    print(f"Channels: {cfg['channels']}")
    print(f"Organic:  {cfg.get('organic_channels', [])}")
    print(f"Controls: {cfg.get('controls', [])}")
    print()

    print("Running prepare_data …")
    df = prepare_data(cfg)

    n_dates = df[cfg["date_column"]].nunique()
    n_geos  = df[cfg["geo_column"]].nunique()

    print(f"  Shape:      {df.shape}")
    print(f"  Weeks:      {n_dates}")
    print(f"  Geos:       {n_geos}  →  {sorted(df[cfg['geo_column']].unique())}")
    print(f"  Date range: {df[cfg['date_column']].min().date()} → {df[cfg['date_column']].max().date()}")
    print(f"  Expected rows: {n_dates} × {n_geos} = {n_dates * n_geos}  (actual: {len(df)})")
    print()

    # Spot-check: black_friday should fire exactly once per year per geo
    if "black_friday" in df.columns:
        bf_weeks = df.loc[df["black_friday"] == 1, cfg["date_column"]].sort_values().unique()
        print(f"  Black Friday weeks ({len(bf_weeks)}): {[str(d.date()) for d in bf_weeks]}")
        print()

    # Spot-check: population non-zero
    pop_col = cfg.get("population_column", "population")
    if pop_col in df.columns:
        zero_pop = (df[pop_col] == 0).sum()
        print(f"  Zero-population rows: {zero_pop}  (should be 0)")
        print()

    print("Column dtypes (numeric model columns):")
    model_cols = (
        [cfg["kpi_column"]]
        + [f"{c}_Cost"        for c in cfg["channels"]]
        + [f"{c}_Impressions" for c in cfg["channels"]]
        + [f"{c}_Views"       for c in cfg.get("organic_channels", [])]
    )
    for col in model_cols:
        print(f"  {col:<35} {df[col].dtype}")

    print()
    print("Validation passed. DataFrame is ready for DataFrameInputDataBuilder.")
    sys.exit(0)
