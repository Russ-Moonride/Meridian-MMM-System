"""
src/crps.py
~~~~~~~~~~~
CRPS (Continuous Ranked Probability Score) utilities for Meridian MMM evaluation.

CRPS is a proper scoring rule for probabilistic forecasts — unlike RMSE, it rewards
the full predictive distribution, not just the point estimate. Lower is better.

Two main use cases:
  1. Holdout evaluation — score a fitted model on withheld time periods
  2. Hyperparameter tuning — use dev-mode CRPS to search knots / max_lag before
     committing to a full prod MCMC run (Optuna two-tier approach from Luca Fiaschi)

Usage
-----
    from src.crps import compute_crps_holdout, tune_hyperparams

    # Score a fitted model on holdout weeks
    score = compute_crps_holdout(mmm, holdout_dates=["2026-01-06", "2026-01-13", ...], df=df, cfg=cfg)
    print(f"Holdout CRPS: {score:.4f}")

    # Optuna search for best (knots, max_lag) — uses dev-mode MCMC as a surrogate
    best_params = tune_hyperparams(data, prior, cfg, n_trials=30)
    print(best_params)  # {"knots": 20, "max_lag": 6}

References
----------
- Gneiting & Raftery (2007): Strictly Proper Scoring Rules, Prediction, and Estimation
- Luca Fiaschi MMM blog: Optuna + CRPS for MMM hyperparameter tuning
- Meridian docs: holdout_id argument in ModelSpec
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

# ── CRPS core ─────────────────────────────────────────────────────────────────

def crps_samples(samples: np.ndarray, observation: float) -> float:
    """
    Compute CRPS for a single observation given an array of predictive samples.

    CRPS(F, y) = E_F[|X - y|] - 0.5 * E_F[|X - X'|]

    Parameters
    ----------
    samples     : 1D array of posterior predictive samples
    observation : Scalar observed value

    Returns
    -------
    CRPS scalar (lower is better)
    """
    samples = np.asarray(samples, dtype=np.float64).ravel()
    n = len(samples)
    term1 = np.mean(np.abs(samples - observation))
    # Efficient pairwise expected absolute difference: sort-based O(n log n)
    s_sorted = np.sort(samples)
    weights = (2 * np.arange(1, n + 1) - n - 1) / n
    term2 = np.dot(weights, s_sorted) / n
    return float(term1 - term2)


def crps_ensemble(
    posterior_samples: np.ndarray,
    observations: np.ndarray,
) -> np.ndarray:
    """
    Compute CRPS for each time-geo observation given a 2D array of posterior samples.

    Parameters
    ----------
    posterior_samples : shape (n_samples, n_observations) — posterior predictive draws
    observations      : shape (n_observations,) — actual observed values

    Returns
    -------
    crps_per_obs : shape (n_observations,) — CRPS for each observation
    """
    posterior_samples = np.asarray(posterior_samples, dtype=np.float64)
    observations      = np.asarray(observations,      dtype=np.float64)

    if posterior_samples.ndim != 2:
        raise ValueError(f"posterior_samples must be 2D (n_samples, n_obs); got shape {posterior_samples.shape}")
    if posterior_samples.shape[1] != len(observations):
        raise ValueError(
            f"posterior_samples has {posterior_samples.shape[1]} columns "
            f"but observations has {len(observations)} elements."
        )

    crps_vals = np.array([
        crps_samples(posterior_samples[:, i], observations[i])
        for i in range(len(observations))
    ])
    return crps_vals


def mean_crps(
    posterior_samples: np.ndarray,
    observations: np.ndarray,
    weights: np.ndarray | None = None,
) -> float:
    """
    Mean CRPS across observations, optionally weighted (e.g. by actual KPI value).

    Weighted CRPS (wCRPS) is preferred — it de-emphasizes small geos / quiet weeks,
    analogous to wMAPE vs MAPE.

    Parameters
    ----------
    posterior_samples : shape (n_samples, n_observations)
    observations      : shape (n_observations,)
    weights           : shape (n_observations,) — if None, unweighted mean

    Returns
    -------
    scalar mean CRPS
    """
    crps_vals = crps_ensemble(posterior_samples, observations)
    if weights is not None:
        weights = np.asarray(weights, dtype=np.float64)
        weights = weights / weights.sum()
        return float(np.dot(weights, crps_vals))
    return float(crps_vals.mean())


# ── Holdout evaluation ────────────────────────────────────────────────────────

def compute_crps_holdout(
    mmm,
    holdout_dates: list[str],
    df: pd.DataFrame,
    cfg: dict[str, Any],
    weighted: bool = True,
    aggregate_geos: bool = True,
) -> float:
    """
    Compute CRPS on withheld time periods using Meridian's posterior predictive.

    Prerequisites
    -------------
    The model must have been fitted with holdout_id specified in ModelSpec:
        holdout_id = df[date_col].isin(holdout_dates).astype(int).values
        model_spec = spec.ModelSpec(..., holdout_id=holdout_id)

    Parameters
    ----------
    mmm           : Fitted meridian.model.model.Meridian object
    holdout_dates : List of ISO date strings (YYYY-MM-DD) held out during fitting
    df            : The full DataFrame used to build InputData (including holdout rows)
    cfg           : Client config dict
    weighted      : If True, weight CRPS by observed KPI (wCRPS — preferred)
    aggregate_geos: If True, sum KPI across geos before scoring

    Returns
    -------
    mean (weighted) CRPS scalar — lower is better
    """
    date_col = cfg["date_column"]
    geo_col  = cfg["geo_column"]
    kpi_col  = cfg["kpi_column"]

    holdout_dates_ts = pd.to_datetime(holdout_dates)

    # ── Get actual holdout observations ───────────────────────────────────────
    holdout_df = df[df[date_col].isin(holdout_dates_ts)].copy()
    holdout_df[date_col] = pd.to_datetime(holdout_df[date_col])

    if aggregate_geos:
        actuals = (
            holdout_df.groupby(date_col)[kpi_col].sum().reindex(holdout_dates_ts).values
        )
    else:
        actuals = holdout_df.set_index([date_col, geo_col])[kpi_col].values

    # ── Get posterior predictive samples for holdout ──────────────────────────
    # Meridian stores posterior predictive in inference_data.posterior_predictive
    # when holdout_id is set. Access the expected outcome for holdout time steps.
    pp = mmm.inference_data.posterior_predictive
    if not hasattr(pp, "mu"):
        warnings.warn(
            "No posterior_predictive found in inference_data. "
            "Ensure holdout_id was set in ModelSpec and sample_posterior() was called. "
            "Falling back to in-sample expected outcome (not a holdout CRPS).",
            UserWarning,
        )
        # Fall back to in-sample for debugging
        pp = mmm.inference_data.posterior

    # Extract holdout time indices
    mmm_dates = pd.to_datetime(mmm.input_data.time)
    holdout_mask = np.isin(mmm_dates, holdout_dates_ts)

    try:
        # shape: (chain, draw, time, geo) or (chain, draw, time)
        mu_samples = pp.mu.values
        # Flatten chain/draw → samples axis
        n_chains, n_draws = mu_samples.shape[0], mu_samples.shape[1]
        mu_flat = mu_samples.reshape(n_chains * n_draws, *mu_samples.shape[2:])

        # Select holdout time steps
        mu_holdout = mu_flat[:, holdout_mask, ...]   # (samples, holdout_times, [geos])

        if aggregate_geos and mu_holdout.ndim == 3:
            mu_holdout = mu_holdout.sum(axis=2)      # sum geos → (samples, holdout_times)

        # mu_holdout: (n_samples, n_obs)
        weights = actuals if weighted else None
        score = mean_crps(mu_holdout, actuals, weights=weights)

    except Exception as e:
        raise RuntimeError(
            f"Could not extract posterior predictive samples: {e}. "
            "Check that holdout_id was set correctly in ModelSpec."
        ) from e

    return score


def holdout_split(
    df: pd.DataFrame,
    cfg: dict[str, Any],
    n_holdout_weeks: int = 8,
    strategy: str = "last",
) -> tuple[list[str], np.ndarray]:
    """
    Generate holdout dates and holdout_id array for use in ModelSpec.

    Parameters
    ----------
    df               : Full DataFrame
    cfg              : Client config dict
    n_holdout_weeks  : Number of weeks to hold out (default 8 = ~2 months)
    strategy         : "last" (most recent weeks) | "interleaved" (every N-th week)
                       Meridian requires balanced holdout, not contiguous time chunks —
                       use "interleaved" for cleaner estimation.

    Returns
    -------
    holdout_dates : List of ISO date strings
    holdout_id    : Integer array (1 = holdout, 0 = training), shape (n_weeks_x_geos,)

    Notes
    -----
    Meridian's holdout_id must align with the time dimension of InputData, not the
    raw DataFrame rows. One value per time period (not per geo-week row).
    """
    date_col = cfg["date_column"]
    dates = pd.to_datetime(df[date_col]).drop_duplicates().sort_values().tolist()
    n_total = len(dates)

    if strategy == "last":
        holdout_dates = [d.strftime("%Y-%m-%d") for d in dates[-n_holdout_weeks:]]
    elif strategy == "interleaved":
        step = max(1, n_total // n_holdout_weeks)
        holdout_dates = [dates[i].strftime("%Y-%m-%d") for i in range(0, n_total, step)][:n_holdout_weeks]
    else:
        raise ValueError(f"Unknown strategy '{strategy}'. Use 'last' or 'interleaved'.")

    holdout_dates_ts = set(pd.to_datetime(holdout_dates))
    holdout_id = np.array([1 if d in holdout_dates_ts else 0 for d in dates], dtype=np.int32)

    print(f"Holdout: {n_holdout_weeks} weeks ({strategy} strategy)")
    print(f"  Training: {(holdout_id == 0).sum()} weeks")
    print(f"  Holdout:  {(holdout_id == 1).sum()} weeks ({holdout_dates[0]} → {holdout_dates[-1]})")

    return holdout_dates, holdout_id


# ── Optuna hyperparameter tuning ──────────────────────────────────────────────

def tune_hyperparams(
    data,
    prior,
    cfg: dict[str, Any],
    n_trials: int = 30,
    knots_range: tuple[int, int] = (10, 50),
    max_lag_range: tuple[int, int] = (2, 10),
    n_holdout_weeks: int = 8,
    dev_mcmc: dict[str, int] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Use Optuna to find the best (knots, max_lag) via dev-mode CRPS.

    This is the two-tier approach from Luca Fiaschi's MMM blog:
      Tier 1 (cheap): Dev-mode MCMC (1 chain, 200 samples) as surrogate
      Tier 2 (prod): Full MCMC once with the best hyperparameters found in Tier 1

    The key insight: CRPS on holdout data is a proper scoring rule — it rewards
    calibration and sharpness of the full predictive distribution, making it
    suitable as a Bayesian hyperparameter search objective even with cheap dev runs.

    Parameters
    ----------
    data           : Meridian InputData object (pre-built)
    prior          : PriorDistribution object
    cfg            : Client config dict
    n_trials       : Number of Optuna trials (default 30; increase for broader search)
    knots_range    : (min_knots, max_knots) search space
    max_lag_range  : (min_lag, max_lag) search space
    n_holdout_weeks: Weeks to hold out for CRPS evaluation
    dev_mcmc       : Dev MCMC settings dict (default: 1 chain, 200/200/200)
    seed           : Random seed for reproducibility

    Returns
    -------
    dict with keys: knots, max_lag, best_crps, study (Optuna study object)
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        raise ImportError(
            "optuna not installed. Run: pip install optuna\n"
            "Or skip tuning and use the default knots/max_lag from your config."
        )

    from meridian.model import model as meridian_model
    from meridian.model import spec

    if dev_mcmc is None:
        dev_mcmc = {"n_chains": 1, "n_adapt": 200, "n_burnin": 200, "n_keep": 200}

    # Build holdout split once — same for all trials
    df_for_split = _build_df_for_split(data, cfg)
    holdout_dates, holdout_id = holdout_split(
        df_for_split, cfg, n_holdout_weeks=n_holdout_weeks, strategy="interleaved"
    )

    adstock = cfg.get("adstock_decay_spec", "geometric")
    prior_type = cfg.get("media_prior_type", "roi")

    def objective(trial: "optuna.Trial") -> float:
        knots   = trial.suggest_int("knots",   *knots_range)
        max_lag = trial.suggest_int("max_lag", *max_lag_range)

        model_spec = spec.ModelSpec(
            prior=prior,
            knots=knots,
            max_lag=max_lag,
            adstock_decay_spec=adstock,
            media_prior_type=prior_type,
            organic_media_prior_type="contribution",
            media_effects_dist="log_normal",
            holdout_id=holdout_id,
        )

        try:
            mmm = meridian_model.Meridian(input_data=data, model_spec=model_spec)
            mmm.sample_posterior(
                n_chains=dev_mcmc["n_chains"],
                n_adapt=dev_mcmc["n_adapt"],
                n_burnin=dev_mcmc["n_burnin"],
                n_keep=dev_mcmc["n_keep"],
                seed=seed,
            )
            score = compute_crps_holdout(
                mmm, holdout_dates, df_for_split, cfg, weighted=True
            )
        except Exception as e:
            print(f"  Trial {trial.number} failed: {e}")
            return float("inf")

        print(f"  Trial {trial.number}: knots={knots}, max_lag={max_lag} → wCRPS={score:.4f}")
        return score

    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=seed),
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    best = study.best_params
    print(f"\nBest hyperparameters found (wCRPS={study.best_value:.4f}):")
    print(f"  knots   = {best['knots']}")
    print(f"  max_lag = {best['max_lag']}")
    print("\nNext step: run full prod MCMC with these values in your config, then Colab.")

    return {
        "knots":     best["knots"],
        "max_lag":   best["max_lag"],
        "best_crps": study.best_value,
        "study":     study,
    }


def _build_df_for_split(data, cfg: dict[str, Any]) -> pd.DataFrame:
    """Reconstruct a minimal DataFrame from InputData for holdout_split."""
    date_col = cfg["date_column"]
    kpi_col  = cfg["kpi_column"]

    dates = pd.to_datetime(data.time.values)
    kpi   = data.kpi.values  # shape: (time, geo) or (time,)

    if kpi.ndim == 2:
        kpi_series = kpi.sum(axis=1)  # aggregate geos
    else:
        kpi_series = kpi

    return pd.DataFrame({date_col: dates, kpi_col: kpi_series})


# ── Comparison utilities ───────────────────────────────────────────────────────

def compare_models(
    models: dict[str, Any],
    holdout_dates: list[str],
    df: pd.DataFrame,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """
    Compare multiple fitted models by holdout wCRPS.

    Parameters
    ----------
    models        : dict of {label: fitted_mmm_object}
    holdout_dates : Holdout dates used in all models (must be the same)
    df            : Full DataFrame
    cfg           : Client config dict

    Returns
    -------
    DataFrame with columns: model, wCRPS, rank
    """
    rows = []
    for label, mmm in models.items():
        score = compute_crps_holdout(mmm, holdout_dates, df, cfg, weighted=True)
        rows.append({"model": label, "wCRPS": round(score, 5)})

    result = pd.DataFrame(rows).sort_values("wCRPS").reset_index(drop=True)
    result["rank"] = result.index + 1
    return result
