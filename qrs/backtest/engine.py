"""Daily portfolio backtest engine (research engine).

Timing convention (no look-ahead):
    * A strategy emits target weights ``W.loc[t]`` using information available at the CLOSE of bar t.
    * Orders are executed at the OPEN of bar ``t + lag`` (default lag=1: next session's open), paying
      half-spread + slippage + commission on the traded notional.
    * Between the previous close and the execution open the *old* (drifted) positions bear the
      overnight gap; after execution the new positions bear the open->close move.
    * A NaN row in W means "no rebalance" (hold drifted positions). A row of zeros is the explicit
      NO-TRADE / flat state.

Realism features: per-asset costs, cost stress multipliers, short-borrow fees, leverage financing,
interest on idle cash (risk-free proxy), perpetual-futures funding, tradability masks (invalid or
missing bars cannot be traded; positions in assets with no data for ``max_stale`` bars are force-
closed at the last valid price with triple costs, which handles delistings), rebalance bands,
gross-leverage caps and optional ADV participation caps.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qrs.backtest.costs import CostModel


@dataclass
class BacktestResult:
    returns: pd.DataFrame          # per-bar: net, gross (= before transaction costs, after financing), cost,
                                   # financing, turnover, gross_exp, net_exp, n_pos
    weights: pd.DataFrame          # post-trade weights at the execution open of each bar
    contrib: pd.DataFrame          # per-asset net return contribution per bar
    trades: pd.DataFrame           # round-trip (episode) table
    meta: dict

    @property
    def net(self) -> pd.Series:
        return self.returns["net"]

    def equity(self, start: float = 1.0) -> pd.Series:
        return start * (1 + self.net).cumprod()


def run_backtest(W: pd.DataFrame, open_: pd.DataFrame, close: pd.DataFrame, costs: CostModel,
                 rf: pd.Series | None = None, funding: pd.DataFrame | None = None, lag: int = 1,
                 max_gross: float = 1.0, band: float = 0.0, max_stale: int = 5,
                 adv: pd.DataFrame | None = None, capital: float | None = None,
                 max_participation: float = 0.05, start=None, end=None) -> BacktestResult:
    """Simulate target weights W on open/close prices. All frames are aligned to close.index."""
    idx = close.index
    cols = list(W.columns)
    O = open_.reindex(index=idx, columns=cols).to_numpy(float)
    C = close.reindex(index=idx, columns=cols).to_numpy(float)
    Wt = W.reindex(index=idx, columns=cols).to_numpy(float)
    T, N = C.shape
    valid = np.isfinite(O) & np.isfinite(C) & (O > 0) & (C > 0)
    cvec = costs.vector(cols)
    bvec = costs.borrow_vector(cols)
    shortable = costs.shortable.reindex(cols).fillna(False).to_numpy(bool)
    ppy = costs.periods_per_year
    rfa = (rf.reindex(idx).fillna(0.0).to_numpy(float) if (rf is not None and costs.cash_yield)
           else np.zeros(T))
    fund = funding.reindex(index=idx, columns=cols).fillna(0.0).to_numpy(float) if funding is not None else None
    advv = adv.reindex(index=idx, columns=cols).to_numpy(float) if (adv is not None and capital) else None

    lo = 0 if start is None else int(idx.searchsorted(pd.Timestamp(start)))
    hi = T if end is None else int(idx.searchsorted(pd.Timestamp(end), side="right"))

    h = np.zeros(N)                 # weights at previous close
    last_c = np.full(N, np.nan)     # last valid close (valuation)
    stale = np.zeros(N, int)
    eq = 1.0
    out = np.zeros((T, 8))
    Wpost = np.zeros((T, N))
    contrib = np.zeros((T, N))
    for i in range(T):
        v = valid[i]
        if i < lo or i >= hi:
            last_c = np.where(v, C[i], last_c)
            continue
        # ---- 1. overnight gap on existing positions (prev valid close -> today's open)
        g = np.zeros(N)
        ok = v & np.isfinite(last_c)
        g[ok] = O[i, ok] / last_c[ok] - 1.0
        G = float(h @ g)
        gap_c = h * g
        eq_open = eq * (1.0 + G)
        h_open = h * (1.0 + g) / (1.0 + G) if (1.0 + G) > 1e-9 else np.zeros(N)

        # ---- 2. determine new target
        stale = np.where(v, 0, stale + 1)
        j = i - lag
        tgt = Wt[j] if j >= 0 else np.full(N, np.nan)
        w_new = h_open.copy()
        forced = (stale >= max_stale) & (np.abs(h_open) > 0)
        if np.isfinite(tgt).any():
            t = np.nan_to_num(tgt, nan=0.0)
            t = np.where(shortable, t, np.maximum(t, 0.0))
            gross = np.abs(t).sum()
            if gross > max_gross:
                t = t * (max_gross / gross)
            tradable = v.copy()
            chg = np.abs(t - h_open)
            do = tradable & (chg > band)
            # rebalance-to-zero always allowed (band must not trap a NO-TRADE exit)
            do |= tradable & (t == 0) & (h_open != 0)
            w_new = np.where(do, t, h_open)
        w_new = np.where(forced, 0.0, w_new)
        trade = w_new - h_open
        if advv is not None:
            cap = max_participation * np.nan_to_num(advv[i], nan=0.0) / max(eq_open * capital, 1e-9)
            trade = np.clip(trade, -cap, cap)
            trade = np.where(forced, -h_open, trade)
            w_new = h_open + trade
        cvec_i = np.where(forced, 3 * cvec, cvec)
        cost_c = np.abs(trade) * cvec_i
        cost = float(cost_c.sum())

        # ---- 3. intraday return on new positions
        r = np.zeros(N)
        r[v] = C[i, v] / O[i, v] - 1.0
        R = float(w_new @ r)

        # ---- 4. financing (per bar)
        long_mv = float(np.clip(w_new, 0, None).sum())
        short_w = np.clip(-w_new, 0, None)
        fin = 0.0
        cash = 1.0 - long_mv
        if costs.cash_yield:
            fin += rfa[i] * max(cash, 0.0)
            fin -= (rfa[i] + costs.financing_spread_yr / ppy) * max(-cash, 0.0)
        fin_c = -short_w * bvec
        if fund is not None:
            fin_c = fin_c - w_new * fund[i]           # longs pay positive funding
        fin += float(fin_c.sum())

        net_ret = (1.0 + G) * (1.0 - cost) * (1.0 + R + fin) - 1.0
        eq = eq * (1.0 + net_ret)
        out[i] = [net_ret, (1 + G) * (1 + R + fin) - 1, cost, fin, np.abs(trade).sum(),
                  np.abs(w_new).sum(), w_new.sum(), int((np.abs(w_new) > 1e-6).sum())]
        Wpost[i] = w_new
        contrib[i] = gap_c + w_new * r - cost_c + fin_c
        # ---- 5. drift to close
        denom = 1.0 + R
        h = w_new * (1.0 + r) / denom if denom > 1e-9 else np.zeros(N)
        last_c = np.where(v, C[i], last_c)
        if eq <= 1e-6:      # account wiped out
            eq = 1e-6
            h = np.zeros(N)

    sl = slice(lo, hi)
    res = pd.DataFrame(out[sl], index=idx[sl],
                       columns=["net", "gross", "cost", "financing", "turnover", "gross_exp", "net_exp", "n_pos"])
    wp = pd.DataFrame(Wpost[sl], index=idx[sl], columns=cols)
    ct = pd.DataFrame(contrib[sl], index=idx[sl], columns=cols)
    return BacktestResult(res, wp, ct, extract_trades(wp, ct), {"lag": lag, "max_gross": max_gross, "band": band,
                                                                 "cost_mult": costs.cost_mult})


def extract_trades(weights: pd.DataFrame, contrib: pd.DataFrame, eps: float = 1e-6) -> pd.DataFrame:
    """Round trips: an episode starts when a position opens (or flips sign) and ends when it closes/flips."""
    rows = []
    Wv = weights.to_numpy()
    Cv = contrib.to_numpy()
    dates = weights.index
    for k, sym in enumerate(weights.columns):
        s = np.sign(np.where(np.abs(Wv[:, k]) > eps, Wv[:, k], 0.0))
        start, pnl, side = None, 0.0, 0
        for i in range(len(s)):
            if start is not None:
                pnl += Cv[i, k]
            if s[i] != side:
                if start is not None and side != 0:
                    rows.append((sym, dates[start], dates[i], "long" if side > 0 else "short", pnl, i - start))
                first = Cv[i, k] if side == 0 else 0.0   # on a flip the bar's P&L already went to the old leg
                start, pnl, side = (i, first, s[i]) if s[i] != 0 else (None, 0.0, 0)
        if start is not None and side != 0:
            rows.append((sym, dates[start], dates[-1], "long" if side > 0 else "short", pnl, len(s) - 1 - start))
    return pd.DataFrame(rows, columns=["symbol", "entry", "exit", "side", "pnl", "bars"])
