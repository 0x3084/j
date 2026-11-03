"""Statistical arbitrage: cointegration-based pairs trading with walk-forward pair selection."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

from qrs.research.market import Market


_PAIR_CACHE: dict = {}


def _select_pairs(logp: pd.DataFrame, symbols: list[str], max_pairs: int, pmax: float) -> list[tuple]:
    key = (logp.index[0], logp.index[-1], tuple(symbols), max_pairs, pmax)
    if key in _PAIR_CACHE:
        return _PAIR_CACHE[key]
    found = []
    for a, b in itertools.combinations(symbols, 2):
        x = logp[[a, b]].dropna()
        if len(x) < 200:
            continue
        try:
            p = coint(x[a], x[b])[1]
        except Exception:
            continue
        if p < pmax:
            found.append((p, a, b))
    found.sort()
    _PAIR_CACHE[key] = [(a, b) for _, a, b in found[:max_pairs]]
    return _PAIR_CACHE[key]


def pairs_cointegration(m: Market, formation: int = 504, z_entry: float = 2.0, z_exit: float = 0.5,
                        z_stop: float = 4.0, max_pairs: int = 5, pmax: float = 0.05,
                        zwin: int = 60, reselect: str = "YS", symbols: list[str] | None = None,
                        max_hold: int = 60) -> pd.DataFrame:
    """Engle-Granger pairs. At each reselection date, pairs are chosen using ONLY the trailing
    `formation` bars; the hedge ratio is a rolling OLS beta (data <= t) and the spread z-score uses a
    rolling `zwin` window. Positions: +1 spread = long A / short beta*B, dollar-scaled per pair."""
    syms = symbols or m.symbols
    logp = np.log(m.close[syms].ffill(limit=5))
    idx = logp.index
    W = pd.DataFrame(0.0, index=idx, columns=m.symbols)
    resel = pd.Series(idx, index=idx).groupby(idx.to_period("Y" if reselect == "YS" else "Q")).first()
    resel_dates = list(resel.values)
    for k, d in enumerate(resel_dates):
        i0 = idx.get_loc(d)
        if i0 < formation:
            continue
        nxt = idx.get_loc(resel_dates[k + 1]) if k + 1 < len(resel_dates) else len(idx)
        hist = logp.iloc[i0 - formation:i0]
        elig = [s for s in syms if m.eligible[s].iloc[i0 - 1] and hist[s].notna().sum() > formation * 0.95]
        pairs = _select_pairs(hist, elig, max_pairs, pmax)
        if not pairs:
            continue
        seg = slice(max(i0 - formation, 0), nxt)
        for a, b in pairs:
            ya, yb = logp[a].iloc[seg], logp[b].iloc[seg]
            cov = ya.rolling(formation, min_periods=zwin).cov(yb)
            var = yb.rolling(formation, min_periods=zwin).var()
            beta = (cov / var).clip(0.2, 5.0)
            spread = ya - beta * yb
            z = (spread - spread.rolling(zwin).mean()) / spread.rolling(zwin).std()
            z = z.iloc[i0 - seg.start:]
            bt = beta.iloc[i0 - seg.start:]
            pos = np.zeros(len(z))
            cur, age = 0.0, 0
            for t, zz in enumerate(z.to_numpy()):
                if not np.isfinite(zz):
                    cur = 0.0
                elif cur == 0 and abs(zz) > z_entry and abs(zz) < z_stop:
                    cur, age = -np.sign(zz), 0
                elif cur != 0 and (abs(zz) < z_exit or abs(zz) > z_stop or age >= max_hold or np.sign(zz) == cur):
                    cur = 0.0
                age += 1
                pos[t] = cur
            pos[-1] = 0.0 if nxt < len(idx) else pos[-1]   # pairs are closed at reselection
            bb = bt.to_numpy()
            gross = 1 + bb
            wa = pos / gross / len(pairs)
            wb = -pos * bb / gross / len(pairs)
            W.iloc[i0:nxt, W.columns.get_loc(a)] += wa
            W.iloc[i0:nxt, W.columns.get_loc(b)] += wb
    return W
