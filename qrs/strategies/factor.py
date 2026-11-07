"""Cross-sectional equity-style factors beyond plain momentum."""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.research.market import Market
from qrs.strategies.common import rebalance_monthly


def low_vol_factor(m: Market, lookback: int = 60, k: int = 3, weighting: str = "equal") -> pd.DataFrame:
    """Low-volatility anomaly (Ang et al. 2006; Baker, Bradley & Wurgler 2011): rank eligible assets by
    trailing realised volatility, hold the k LOWEST-vol names, rebalanced monthly. Long-only (the
    anomaly is about return per unit of risk among risky assets, not a directional short)."""
    vol = m.vol(lookback)
    v = vol.where(m.eligible)
    rk = v.rank(axis=1, ascending=True)   # rank 1 = lowest vol
    sel = rk.le(k)
    if weighting == "inv_vol":
        iv = (1 / v).where(sel)
        W = iv.div(iv.sum(axis=1), axis=0).fillna(0.0)
    else:
        W = sel.astype(float).div(sel.sum(axis=1).clip(lower=1), axis=0)
    return rebalance_monthly(W)


def high_minus_low_vol(m: Market, lookback: int = 60, k: int = 3) -> pd.DataFrame:
    """Long-short variant: long the k lowest-vol names, short the k highest-vol (only where shortable),
    dollar-neutral. Tests whether the low-vol anomaly survives as a genuine long/short spread."""
    vol = m.vol(lookback).where(m.eligible)
    n = vol.notna().sum(axis=1)
    rk = vol.rank(axis=1, ascending=True)
    lo = rk.le(k)
    hi = rk.gt(n - k, axis=0)
    sh = m.costs.shortable.reindex(m.symbols).fillna(False).to_numpy()
    W = lo.astype(float).div(k) - hi.astype(float).mul(sh, axis=1).div(k)
    return rebalance_monthly(W / 2)
