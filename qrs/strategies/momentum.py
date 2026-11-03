"""Cross-sectional momentum / relative strength / asset rotation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.research.market import Market
from qrs.strategies.common import rebalance_monthly, rebalance_every


def xs_momentum(m: Market, lookback: int = 252, skip: int = 21, k: int = 3, abs_filter: bool = True,
                weighting: str = "equal", long_short: bool = False, vol_filter: float | None = None,
                rebalance: str = "monthly") -> pd.DataFrame:
    """Rank eligible assets by return over [t-lookback, t-skip]; hold the top k.

    abs_filter: dual momentum - an asset is only held if its own lookback return beats the risk-free
                rate (else that slot sits in cash = NO-TRADE).
    vol_filter: if set, skip assets whose ex-ante vol exceeds this annualised level.
    long_short: also short the bottom k (only where shortable), dollar-neutral.
    """
    px = m.close.ffill(limit=5)
    mom = (px.shift(skip) / px.shift(lookback) - 1).where(m.eligible)
    vol = m.vol(60)
    if vol_filter is not None:
        mom = mom.where(vol <= vol_filter)
    rk = mom.rank(axis=1, ascending=False)
    top = rk.le(k)
    if abs_filter:
        rf_cum = (1 + m.rf).rolling(lookback - skip, min_periods=1).apply(np.prod, raw=True).shift(skip) - 1
        top = top & mom.gt(rf_cum, axis=0)
    if weighting == "inv_vol":
        iv = (1 / vol).where(top)
        W = iv.div(iv.sum(axis=1) * (k / top.sum(axis=1).clip(lower=1)), axis=0).fillna(0.0)
        W = W.div(W.sum(axis=1).clip(lower=1.0), axis=0)
    else:
        W = top.astype(float) / k
    if long_short:
        n = mom.notna().sum(axis=1)
        bot = rk.gt(n - k, axis=0) & mom.notna()
        sh = m.costs.shortable.reindex(m.symbols).fillna(False).to_numpy()
        W = (top.astype(float) / k - bot.astype(float).mul(sh, axis=1) / k) / 2
    W = W.fillna(0.0)
    return rebalance_monthly(W) if rebalance == "monthly" else rebalance_every(W, int(rebalance))


def trend_filtered_rotation(m: Market, lookback: int = 126, k: int = 3, ma: int = 200,
                            regime_asset: str | None = None) -> pd.DataFrame:
    """Relative strength rotation gated by a market regime filter: hold top-k by momentum only
    while `regime_asset` (or each asset itself) trades above its `ma`-day moving average."""
    px = m.close.ffill(limit=5)
    mom = (px / px.shift(lookback) - 1).where(m.eligible)
    above = px > px.rolling(ma, min_periods=ma).mean()
    top = mom.rank(axis=1, ascending=False).le(k) & above
    if regime_asset is not None and regime_asset in px:
        reg = above[regime_asset]
        top = top.mul(reg, axis=0).astype(bool)
    W = top.astype(float) / k
    return rebalance_every(W, 5)
