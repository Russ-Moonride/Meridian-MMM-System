"""
src/model_config.py
~~~~~~~~~~~~~~~~~~~
Build Meridian model objects from a client config dict.

Public API
----------
build_input_data(df, config) → InputData
build_priors(config)         → PriorDistribution
build_model_spec(config)     → ModelSpec
build_model(df, config)      → Meridian
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import tensorflow as tf
import tensorflow_probability as tfp

from meridian.data import data_frame_input_data_builder
from meridian.model import model, prior_distribution, spec

tfd = tfp.distributions


def build_input_data(df: pd.DataFrame, config: dict[str, Any]):
    """Assemble a Meridian InputData from a prepared DataFrame and config."""
    date_col    = config["date_column"]
    geo_col     = config["geo_column"]
    kpi_col     = config["kpi_column"]
    kpi_type    = config.get("kpi_type", "revenue")
    channels    = config["channels"]
    organic_chs = config.get("organic_channels", [])
    controls    = config.get("controls", [])
    pop_col     = config.get("population_column", "population")

    # Only pass controls that exist in the DataFrame (black_friday is computed by data_prep)
    actual_controls = [c for c in controls if c in df.columns]

    builder = data_frame_input_data_builder.DataFrameInputDataBuilder(kpi_type=kpi_type)
    builder = builder.with_kpi(df, kpi_col=kpi_col, time_col=date_col, geo_col=geo_col)
    builder = builder.with_media(
        df,
        media_channels=channels,
        media_spend_cols=[f"{c}_Cost" for c in channels],
        media_cols=[f"{c}_Impressions" for c in channels],
        time_col=date_col,
        geo_col=geo_col,
    )
    if organic_chs:
        organic_col_map = config.get("organic_cols", {})
        builder = builder.with_organic_media(
            df,
            organic_media_cols=[organic_col_map.get(c, f"{c}_Views") for c in organic_chs],
            organic_media_channels=organic_chs,
            media_time_col=date_col,
            geo_col=geo_col,
        )
    if actual_controls:
        builder = builder.with_controls(
            df,
            control_cols=actual_controls,
            time_col=date_col,
            geo_col=geo_col,
        )
    if pop_col in df.columns:
        builder = builder.with_population(df, population_col=pop_col, geo_col=geo_col)

    return builder.build()


def build_priors(config: dict[str, Any]):
    """Build a PriorDistribution from config.

    ROI mode:          reads prior_roi_ranges per channel → LogNormal roi_m
    Contribution mode: reads channel_media_shares + concentration settings
                       for per-channel Beta priors; also builds contribution_o
                       for organic channels if organic_contribution_prior is set.
    """
    prior_type = config.get("prior_type", "roi")

    if prior_type == "contribution":
        channels    = config["channels"]
        total       = config.get("total_media_contribution", config.get("target_contribution", 0.60))
        conc_def    = config.get("concentration_default", config.get("prior_concentration", 10.0))
        shares      = config.get("channel_media_shares", {})

        if shares:
            scale   = total / sum(shares.values())
            targets = {ch: shares.get(ch, total / len(channels)) * scale for ch in channels}
        else:
            targets = {ch: total / len(channels) for ch in channels}

        a_params, b_params = [], []
        for ch in channels:
            mu   = targets[ch]
            conc = config.get(f"concentration_{ch.lower()}", conc_def)
            a_params.append(mu * conc)
            b_params.append((1.0 - mu) * conc)

        prior_kwargs: dict[str, Any] = {
            "contribution_m": tfd.Beta(
                concentration1=tf.cast(a_params, tf.float32),
                concentration0=tf.cast(b_params, tf.float32),
            )
        }

        organic_prior_cfg = config.get("organic_contribution_prior", {})
        organic_chs = config.get("organic_channels", [])
        if organic_prior_cfg and organic_chs:
            o_a, o_b = [], []
            for ch in organic_chs:
                ch_cfg = organic_prior_cfg.get(ch, {})
                mu   = ch_cfg.get("mu", 0.005)
                conc = ch_cfg.get("concentration", 8.0)
                o_a.append(mu * conc)
                o_b.append((1.0 - mu) * conc)
            prior_kwargs["contribution_om"] = tfd.Beta(
                concentration1=tf.cast(o_a, tf.float32),
                concentration0=tf.cast(o_b, tf.float32),
            )

        return prior_distribution.PriorDistribution(**prior_kwargs)

    channels   = config["channels"]
    roi_ranges = config["prior_roi_ranges"]
    mass_pct   = config.get("prior_roi_mass_percent", 0.95)

    roi_dists = [
        prior_distribution.lognormal_dist_from_range(
            low=roi_ranges[ch][0],
            high=roi_ranges[ch][1],
            mass_percent=mass_pct,
        )
        for ch in channels
    ]

    roi_loc_vec   = tf.cast([d.loc   for d in roi_dists], tf.float32)
    roi_scale_vec = tf.cast([d.scale for d in roi_dists], tf.float32)

    return prior_distribution.PriorDistribution(
        roi_m=tfd.LogNormal(loc=roi_loc_vec, scale=roi_scale_vec)
    )


def build_model_spec(config: dict[str, Any], n_weeks: int | None = None):
    """Build a ModelSpec from config.

    n_weeks is required when config['knots'] == 'auto'.
    """
    priors = build_priors(config)

    knots = config.get("knots", 26)
    if str(knots).lower() == "auto":
        if n_weeks is None:
            raise ValueError("knots='auto' requires n_weeks to be passed to build_model_spec")
        knots = n_weeks // 2

    return spec.ModelSpec(
        prior=priors,
        media_prior_type=config.get("media_prior_type", config.get("prior_type", "roi")),
        knots=knots,
        max_lag=config.get("max_lag", 6),
        adstock_decay_spec=config.get("adstock_decay_spec", "geometric"),
        media_effects_dist=config.get("media_effects_dist", "log_normal"),
    )


def build_model(df: pd.DataFrame, config: dict[str, Any]):
    """Assemble a Meridian model object (unfitted)."""
    input_data = build_input_data(df, config)
    n_weeks    = df[config["date_column"]].nunique()
    model_spec = build_model_spec(config, n_weeks=n_weeks)
    return model.Meridian(input_data=input_data, model_spec=model_spec)
