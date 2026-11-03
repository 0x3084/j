"""Shared helpers for strategies. Every function here is causal: the value at t uses data <= t."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rebalance_every(W: pd.DataFrame, n: int, offset: int = 0) -> pd.DataFrame:
    """Keep target rows only every n bars (others NaN = hold). Reduces turnover."""
    keep = (np.arange(len(W)) - offset) % n == 0
    out = W.copy()
    out.loc[~keep] = np.nan
    return out


def month_start_rows(index: pd.DatetimeIndex) -> np.ndarray:
    """First bar of each month. Strictly causal: only compares with the PREVIOUS bar's date
    (detecting month-END would require peeking at the next bar)."""
    s = pd.Series(index, index=index)
    return (s.dt.month != s.shift(1).dt.month).to_numpy()


def rebalance_monthly(W: pd.DataFrame) -> pd.DataFrame:
    out = W.copy()
    out.loc[~month_start_rows(W.index)] = np.nan
    return out


def vol_scale(signal: pd.DataFrame, vol: pd.DataFrame, target: float, n_eff: pd.Series | None = None,
              max_w: float = 1.0) -> pd.DataFrame:
    """Position = signal * target_vol / asset_vol, split across n_eff assets."""
    inv = 1.0 / vol.replace(0, np.nan)
    w = signal * inv
    w = w.mul(target, axis=0) if isinstance(target, pd.Series) else w * target
    if n_eff is not None:
        w = w.div(n_eff.replace(0, np.nan), axis=0)
    return w.clip(-max_w, max_w).fillna(0.0)


def ema(x: pd.DataFrame, span: int) -> pd.DataFrame:
    return x.ewm(span=span, min_periods=span).mean()


def rsi(close: pd.DataFrame, n: int) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def portfolio_vol_target(W: pd.DataFrame, rets: pd.DataFrame, target: float, ppy: int, lookback: int = 60,
                         max_lev: float = 2.0) -> pd.DataFrame:
    """Scale the whole book so that ex-ante portfolio vol (rolling covariance, data <= t) hits target."""
    r = rets.fillna(0.0)
    scale = pd.Series(np.nan, index=W.index)
    Wv = W.fillna(0.0).to_numpy()
    R = r.to_numpy()
    for i in range(lookback, len(W)):
        w = Wv[i]
        if not np.any(w):
            scale.iloc[i] = 1.0
            continue
        cov = np.cov(R[i - lookback + 1:i + 1].T)
        v = float(np.sqrt(max(w @ cov @ w, 0) * ppy))
        scale.iloc[i] = min(target / v, max_lev) if v > 0 else 1.0
    return W.mul(scale, axis=0)
