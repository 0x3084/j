"""Multi-strategy portfolio construction from out-of-sample strategy return streams.

Only strategies that passed the pre-registered gate are eligible. If none passed, the portfolio is
CASH (zero positions) - this is an allowed, and sometimes the correct, outcome.

Allocation is itself walk-forward: weights at each monthly rebalance use only trailing returns.
Combination at the return level ignores netting of offsetting positions across strategies, which
slightly overstates costs (conservative).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.backtest.metrics import summarize


def corr_matrix(rets: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.concat(rets, axis=1).dropna(how="all").fillna(0.0).corr()


def allocate(rets: pd.DataFrame, method: str = "inv_vol", lookback: int = 756, min_obs: int = 252,
             target_vol: float | None = None, max_lev: float = 1.0, ppy: int = 252) -> pd.DataFrame:
    """Monthly walk-forward weights over strategy return streams (columns)."""
    R = rets.fillna(0.0)
    idx = R.index
    first = pd.Series(idx, index=idx)
    reb = (first.dt.month != first.shift(1).dt.month).to_numpy()
    W = pd.DataFrame(np.nan, index=idx, columns=R.columns)
    for i in np.where(reb)[0]:
        hist = R.iloc[max(0, i - lookback):i]
        live = [c for c in R.columns if (rets[c].iloc[max(0, i - lookback):i].notna().sum() >= min_obs)]
        if not live:
            W.iloc[i] = 0.0
            continue
        h = hist[live]
        if method == "equal":
            w = pd.Series(1.0 / len(live), index=live)
        elif method == "inv_vol":
            iv = 1 / h.std().replace(0, np.nan)
            w = (iv / iv.sum()).fillna(0.0)
        elif method == "min_var":
            C = h.cov().to_numpy() + np.eye(len(live)) * 1e-8
            x = np.linalg.solve(C, np.ones(len(live)))
            x = np.clip(x, 0, None)
            w = pd.Series(x / x.sum() if x.sum() > 0 else np.ones(len(live)) / len(live), index=live)
        else:
            raise ValueError(method)
        if target_vol:
            v = float(np.sqrt(w.to_numpy() @ h.cov().to_numpy() @ w.to_numpy() * ppy))
            w = w * min(target_vol / v, max_lev) if v > 0 else w
        row = pd.Series(0.0, index=R.columns)
        row[live] = w
        W.iloc[i] = row.to_numpy()
    return W.ffill().fillna(0.0)


def combine(rets: dict[str, pd.Series], method: str = "inv_vol", ppy: int = 252, rf: pd.Series | None = None,
            **kw) -> tuple[pd.Series, pd.DataFrame, dict]:
    if not rets:
        idx = rf.index if rf is not None else pd.DatetimeIndex([])
        cash = rf if rf is not None else pd.Series(0.0, index=idx)
        return cash, pd.DataFrame(index=idx), {"note": "no strategy passed validation -> 100% cash"}
    R = pd.concat(rets, axis=1).sort_index()
    W = allocate(R, method, ppy=ppy, **kw)
    # strategy returns are fully-invested-equity returns; unallocated capital earns rf
    port = (W.shift(1).fillna(0.0) * R.fillna(0.0)).sum(axis=1)
    if rf is not None:
        port = port + (1 - W.shift(1).fillna(0.0).sum(axis=1)).clip(lower=0) * rf.reindex(port.index).fillna(0.0)
    return port, W, summarize(port, ppy, rf=rf)
