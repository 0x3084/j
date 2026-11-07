"""Fixed-income / curve strategies using the available Treasury-ETF proxies.

No futures curve or swap data is available in this environment, so "carry" here is approximated by
trailing total return of the long-duration leg relative to the short-duration leg (a duration-
momentum proxy), not a true forward-implied carry. This is stated explicitly in the research report
if the strategy is promoted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.research.market import Market
from qrs.strategies.common import rebalance_every


def duration_momentum(m: Market, long_asset: str = "TLT", short_asset: str = "SHY", lookback: int = 126,
                      threshold: float = 0.0, vol_target: float = 0.08, rebalance: int = 5) -> pd.DataFrame:
    """Time-series momentum on the duration spread log(long/short). Long duration (TLT, short SHY as
    the funding leg) when the spread trend is positive and above `threshold`; flat/inverted otherwise.
    This is the classic "don't fight the bond trend" rule, applied to the curve rather than to levels."""
    if long_asset not in m.symbols or short_asset not in m.symbols:
        return pd.DataFrame(0.0, index=m.close.index, columns=m.symbols)
    px_l, px_s = m.close[long_asset].ffill(limit=5), m.close[short_asset].ffill(limit=5)
    spread = np.log(px_l / px_s)
    mom = spread - spread.shift(lookback)
    sd = spread.diff().rolling(60, min_periods=30).std()
    z = (mom / (sd * np.sqrt(lookback))).clip(-3, 3)
    sig = np.where(z > threshold, 1.0, np.where(z < -threshold, -1.0, 0.0))
    sig = pd.Series(sig, index=m.close.index).where(m.eligible[long_asset] & m.eligible[short_asset], 0.0)

    vol_sprd = spread.diff().rolling(60, min_periods=30).std() * np.sqrt(m.ppy)
    lev = (vol_target / vol_sprd).clip(upper=3.0).fillna(0.0)
    w_long = (sig * lev).clip(-1.5, 1.5)

    W = pd.DataFrame(0.0, index=m.close.index, columns=m.symbols)
    W[long_asset] = w_long
    W[short_asset] = -w_long          # funded by shorting/holding less of the short-duration leg
    return rebalance_every(W, rebalance)


def curve_steepener_flattener(m: Market, short_asset: str = "SHY", mid_asset: str = "IEF",
                              long_asset: str = "TLT", lookback: int = 63, vol_target: float = 0.08,
                              rebalance: int = 5) -> pd.DataFrame:
    """Butterfly: long/short mid vs the average of short+long duration, sized by trend in the butterfly
    spread. Tests a genuinely different signal (curve shape) rather than outright duration direction."""
    need = [short_asset, mid_asset, long_asset]
    if not all(a in m.symbols for a in need):
        return pd.DataFrame(0.0, index=m.close.index, columns=m.symbols)
    px = {a: np.log(m.close[a].ffill(limit=5)) for a in need}
    fly = px[mid_asset] - 0.5 * (px[short_asset] + px[long_asset])
    mom = fly - fly.shift(lookback)
    sd = fly.diff().rolling(60, min_periods=30).std()
    z = (mom / (sd * np.sqrt(lookback))).clip(-3, 3)
    sig = np.sign(z).where(z.abs() > 0.5, 0.0)
    elig = m.eligible[short_asset] & m.eligible[mid_asset] & m.eligible[long_asset]
    sig = sig.where(elig, 0.0)
    vol_fly = fly.diff().rolling(60, min_periods=30).std() * np.sqrt(m.ppy)
    lev = (vol_target / vol_fly).clip(upper=3.0).fillna(0.0)
    w_mid = (sig * lev).clip(-1.5, 1.5)

    W = pd.DataFrame(0.0, index=m.close.index, columns=m.symbols)
    W[mid_asset] = w_mid
    W[short_asset] = -0.5 * w_mid
    W[long_asset] = -0.5 * w_mid
    return rebalance_every(W, rebalance)
