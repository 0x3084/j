"""Statistical inference for backtests: bootstrap CIs, PSR/DSR, reality check, multiple testing."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as st

EULER = 0.5772156649015329


def stationary_bootstrap_idx(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices (preserves serial dependence)."""
    p = 1.0 / mean_block
    idx = np.empty(n, dtype=np.int64)
    idx[0] = rng.integers(n)
    new = rng.random(n) < p
    starts = rng.integers(n, size=n)
    for t in range(1, n):
        idx[t] = starts[t] if new[t] else (idx[t - 1] + 1) % n
    return idx


def bootstrap_metrics(r: pd.Series, ppy: int, n_boot: int = 1000, mean_block: float = 20.0,
                      seed: int = 7) -> dict:
    """95% CIs for annualised Sharpe and mean return; one-sided p-value for Sharpe <= 0."""
    x = r.dropna().to_numpy(float)
    n = len(x)
    if n < 60 or x.std() == 0:
        return {"sharpe_lo": np.nan, "sharpe_hi": np.nan, "ret_lo": np.nan, "ret_hi": np.nan, "p_sharpe": np.nan}
    rng = np.random.default_rng(seed)
    sh, mu = np.empty(n_boot), np.empty(n_boot)
    xc = x - x.mean()  # centred series: bootstrap distribution under H0 (mean 0)
    null = np.empty(n_boot)
    for b in range(n_boot):
        ii = stationary_bootstrap_idx(n, mean_block, rng)
        s = x[ii]
        sd = s.std(ddof=1)
        sh[b] = s.mean() / sd * np.sqrt(ppy) if sd > 0 else 0.0
        mu[b] = s.mean() * ppy
        sc = xc[ii]
        null[b] = sc.mean() / sc.std(ddof=1) * np.sqrt(ppy)
    obs = x.mean() / x.std(ddof=1) * np.sqrt(ppy)
    return {"sharpe_lo": float(np.quantile(sh, 0.025)), "sharpe_hi": float(np.quantile(sh, 0.975)),
            "ret_lo": float(np.quantile(mu, 0.025)), "ret_hi": float(np.quantile(mu, 0.975)),
            "p_sharpe": float((null >= obs).mean())}


def probabilistic_sharpe(r: pd.Series, sr_benchmark: float = 0.0) -> float:
    """PSR (Bailey & Lopez de Prado 2012) using per-period Sharpe; benchmark given per period."""
    x = r.dropna().to_numpy(float)
    n = len(x)
    if n < 30 or x.std() == 0:
        return np.nan
    sr = x.mean() / x.std(ddof=1)
    g3 = st.skew(x)
    g4 = st.kurtosis(x, fisher=False)
    den = np.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2, 1e-12))
    return float(st.norm.cdf((sr - sr_benchmark) * np.sqrt(n - 1) / den))


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """Expected maximum of n_trials iid Sharpe estimates with variance var_sr (per-period units)."""
    if n_trials <= 1:
        return 0.0
    z1 = st.norm.ppf(1 - 1.0 / n_trials)
    z2 = st.norm.ppf(1 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(var_sr) * ((1 - EULER) * z1 + EULER * z2))


def deflated_sharpe(r: pd.Series, n_trials: int, trial_sr_var: float | None = None) -> float:
    """DSR: PSR against the Sharpe one would expect from the best of ``n_trials`` pure-noise strategies.

    trial_sr_var: variance (per-period units) of Sharpe ratios across trials; if None uses the
    asymptotic sampling variance of a zero-Sharpe estimator, 1/T.
    """
    x = r.dropna()
    if trial_sr_var is None:
        trial_sr_var = 1.0 / max(len(x), 1)
    return probabilistic_sharpe(x, expected_max_sharpe(n_trials, trial_sr_var))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values."""
    items = sorted((p, k) for k, p in pvals.items() if np.isfinite(p))
    m = len(items)
    adj, running = {}, 0.0
    for i, (p, k) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    for k, p in pvals.items():
        adj.setdefault(k, np.nan)
    return adj


def reality_check(R: pd.DataFrame, n_boot: int = 1000, mean_block: float = 20.0, seed: int = 11) -> dict:
    """White (2000) Reality Check / Hansen SPA-style test that the BEST of many strategies has
    positive mean excess return (columns of R are per-period excess returns vs the benchmark).

    Returns the p-value of the max statistic (studentised) and the consistent SPA p-value.
    """
    X = R.dropna(how="all").fillna(0.0).to_numpy(float)
    n, k = X.shape
    if n < 60 or k == 0:
        return {"p_rc": np.nan, "p_spa": np.nan}
    mu = X.mean(0)
    sd = X.std(0, ddof=1)
    sd[sd == 0] = np.inf
    t_obs = np.max(np.sqrt(n) * mu / sd)
    # Hansen's consistent recentring: only strategies not "too bad" are recentred to zero
    thresh = -np.sqrt(2 * np.log(np.log(n))) * sd / np.sqrt(n)
    mu_c = np.where(mu >= thresh, mu, 0.0)
    rng = np.random.default_rng(seed)
    t_rc, t_spa = np.empty(n_boot), np.empty(n_boot)
    for b in range(n_boot):
        ii = stationary_bootstrap_idx(n, mean_block, rng)
        mb = X[ii].mean(0)
        t_rc[b] = np.max(np.sqrt(n) * (mb - mu) / sd)
        t_spa[b] = np.max(np.sqrt(n) * (mb - mu_c) / sd)
    return {"t_obs": float(t_obs), "p_rc": float((t_rc >= t_obs).mean()),
            "p_spa": float((np.maximum(t_spa, 0) >= max(t_obs, 0)).mean())}


def min_track_record(r: pd.Series, sr_target: float = 0.0, conf: float = 0.95) -> float:
    """Minimum number of periods needed for PSR(sr_target) >= conf (Bailey & Lopez de Prado)."""
    x = r.dropna().to_numpy(float)
    if len(x) < 30 or x.std() == 0:
        return np.nan
    sr = x.mean() / x.std(ddof=1)
    if sr <= sr_target:
        return np.inf
    g3, g4 = st.skew(x), st.kurtosis(x, fisher=False)
    z = st.norm.ppf(conf)
    return float(1 + (1 - g3 * sr + (g4 - 1) / 4 * sr ** 2) * (z / (sr - sr_target)) ** 2)
