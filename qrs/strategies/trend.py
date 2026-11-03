"""Trend-following families: time-series momentum, Donchian breakout, multi-timeframe EWMAC."""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.research.market import Market
from qrs.strategies.common import ema, rebalance_every, vol_scale


def tsmom(m: Market, lookback: int = 252, vol_target: float = 0.10, long_only: bool = False,
          rebalance: int = 5, skip: int = 0) -> pd.DataFrame:
    """Moskowitz-Ooi-Pedersen time-series momentum. lookback=0 -> blend of 21/63/126/252-day signals."""
    px = m.close.ffill(limit=5)
    if lookback == 0:
        sig = sum(np.sign(px.shift(skip) / px.shift(skip + L) - 1) for L in (21, 63, 126, 252)) / 4
    else:
        sig = np.sign(px.shift(skip) / px.shift(skip + lookback) - 1)
    if long_only:
        sig = sig.clip(lower=0)
    sig = sig.where(m.eligible, 0.0)
    n = m.eligible.sum(axis=1)
    W = vol_scale(sig, m.vol(), vol_target * np.sqrt(n.clip(lower=1)), n)   # each asset ~ vt/sqrt(N) vol
    return rebalance_every(W, rebalance)


def breakout(m: Market, n: int = 55, exit_frac: float = 0.5, vol_target: float = 0.10,
             long_only: bool = False) -> pd.DataFrame:
    """Donchian channel breakout: enter on close beyond the prior n-day high/low, exit on the
    opposite exit_frac*n-day channel. Vol-scaled sizing. State machine -> explicit loop (causal)."""
    hi = m.high.rolling(n, min_periods=n).max().shift(1)
    lo = m.low.rolling(n, min_periods=n).min().shift(1)
    ne = max(int(n * exit_frac), 2)
    xhi = m.high.rolling(ne, min_periods=ne).max().shift(1)
    xlo = m.low.rolling(ne, min_periods=ne).min().shift(1)
    C = m.close.to_numpy()
    H, L, XH, XL = hi.to_numpy(), lo.to_numpy(), xhi.to_numpy(), xlo.to_numpy()
    E = m.eligible.to_numpy()
    pos = np.zeros_like(C)
    cur = np.zeros(C.shape[1])
    for i in range(len(C)):
        c = C[i]
        with np.errstate(invalid="ignore"):
            cur = np.where((cur > 0) & (c < XL[i]), 0, cur)
            cur = np.where((cur < 0) & (c > XH[i]), 0, cur)
            cur = np.where(c > H[i], 1, cur)
            if not long_only:
                cur = np.where(c < L[i], -1, cur)
        cur = np.where(E[i], cur, 0)
        pos[i] = cur
    sig = pd.DataFrame(pos, index=m.close.index, columns=m.close.columns)
    nn = m.eligible.sum(axis=1)
    return vol_scale(sig, m.vol(), vol_target * np.sqrt(nn.clip(lower=1)), nn)


def ewmac(m: Market, speeds: str = "medium", vol_target: float = 0.10, threshold: float = 0.0,
          long_only: bool = False, rebalance: int = 5) -> pd.DataFrame:
    """Multi-timeframe EWMA crossover forecast (continuous, capped at +-2). Forecasts with
    |f| < threshold map to zero: the NO-TRADE state when trend evidence is weak."""
    pairs = {"fast": [(8, 32), (16, 64)], "medium": [(16, 64), (32, 128), (64, 256)],
             "slow": [(32, 128), (64, 256)], "all": [(8, 32), (16, 64), (32, 128), (64, 256)]}[speeds]
    px = m.close.ffill(limit=5)
    sd_px = px.diff().ewm(span=36, min_periods=20).std()
    f = 0
    for a, b in pairs:
        raw = (ema(px, a) - ema(px, b)) / sd_px
        # normalise each speed so its average absolute forecast is ~1 (expanding, causal)
        scale = raw.abs().expanding(min_periods=252).mean()
        f = f + raw / scale
    f = (f / len(pairs)).clip(-2, 2)
    f = f.where(f.abs() >= threshold, 0.0)
    if long_only:
        f = f.clip(lower=0)
    f = f.where(m.eligible, 0.0) / 2.0     # +-1 at full conviction
    n = m.eligible.sum(axis=1)
    W = vol_scale(f, m.vol(), vol_target * np.sqrt(n.clip(lower=1)), n)
    return rebalance_every(W, rebalance)
