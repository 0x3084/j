"""Mean-reversion families: short-term overreaction (RSI/z-score), vol-adjusted reversal,
and cross-sectional short-term reversal."""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.research.market import Market
from qrs.strategies.common import rsi


def rsi_reversion(m: Market, n: int = 2, entry: float = 10.0, exit_ma: int = 5, trend_ma: int = 200,
                  allow_short: bool = False, max_w: float = 1.0) -> pd.DataFrame:
    """Connors-style: buy oversold (RSI(n) < entry) in an uptrend (close > trend_ma), exit when
    close > exit_ma. Optionally short overbought in downtrends. Equal weight across open signals."""
    px = m.close
    r = rsi(px, n)
    up = px > px.rolling(trend_ma, min_periods=trend_ma).mean() if trend_ma else px.notna()
    xma = px.rolling(exit_ma, min_periods=exit_ma).mean()
    C, R, U, X, E = (a.to_numpy() for a in (px, r, up, xma, m.eligible))
    pos = np.zeros_like(C)
    cur = np.zeros(C.shape[1])
    for i in range(len(C)):
        with np.errstate(invalid="ignore"):
            cur = np.where((cur > 0) & (C[i] > X[i]), 0, cur)
            cur = np.where((cur < 0) & (C[i] < X[i]), 0, cur)
            cur = np.where((cur == 0) & (R[i] < entry) & U[i].astype(bool), 1, cur)
            if allow_short:
                cur = np.where((cur == 0) & (R[i] > 100 - entry) & ~U[i].astype(bool), -1, cur)
        cur = np.where(E[i], cur, 0)
        pos[i] = cur
    sig = pd.DataFrame(pos, index=px.index, columns=px.columns)
    k = sig.abs().sum(axis=1).clip(lower=1)
    # equal weight among active signals but never more than max_w per name and 1.0 gross
    return sig.div(np.maximum(k, 1.0 / max_w), axis=0).clip(-max_w, max_w)


def zscore_reversion(m: Market, lookback: int = 5, z_entry: float = 1.5, hold: int = 5,
                     trend_ma: int = 0, allow_short: bool = True, vol_target: float = 0.10) -> pd.DataFrame:
    """Volatility-adjusted reversal: fade |lookback-day return| / (vol*sqrt(lookback)) > z_entry,
    hold for `hold` bars. Position sized by inverse volatility."""
    px = m.close.ffill(limit=5)
    vol = m.vol(30) / np.sqrt(m.ppy)
    z = (px / px.shift(lookback) - 1) / (vol * np.sqrt(lookback))
    sig = -np.sign(z).where(z.abs() > z_entry, 0.0)
    if trend_ma:
        up = px > px.rolling(trend_ma, min_periods=trend_ma).mean()
        sig = sig.where(~((sig < 0) & up) & ~((sig > 0) & ~up), 0.0)
    if not allow_short:
        sig = sig.clip(lower=0)
    # hold: a signal persists for `hold` bars unless replaced
    held = sig.replace(0, np.nan).ffill(limit=hold - 1).fillna(0.0) if hold > 1 else sig
    held = held.where(m.eligible, 0.0)
    w = held * (vol_target / m.vol(30))
    n = m.eligible.sum(axis=1).clip(lower=1)
    w = w.div(np.sqrt(n), axis=0)
    g = w.abs().sum(axis=1)
    return w.div(g.clip(lower=1.0), axis=0).fillna(0.0)


def xs_reversal(m: Market, lookback: int = 5, k: int = 3, hold: int = 5) -> pd.DataFrame:
    """Cross-sectional short-term reversal: long the k worst performers over lookback (and short the
    k best if shortable), dollar neutral, rebalanced every `hold` bars."""
    px = m.close.ffill(limit=5)
    ret = (px / px.shift(lookback) - 1).where(m.eligible)
    rk = ret.rank(axis=1)
    n = ret.notna().sum(axis=1)
    long_ = rk.le(k)
    short = rk.gt(n - k, axis=0)
    shortable = m.costs.shortable.reindex(m.symbols).fillna(False).to_numpy()
    W = long_.astype(float) / k
    if shortable.any():
        W = W - short.astype(float).mul(shortable, axis=1) / k
        W = W / 2
    W = W.where(n >= 2 * k, 0.0)
    keep = np.arange(len(W)) % hold == 0
    W.loc[~keep] = np.nan
    return W
