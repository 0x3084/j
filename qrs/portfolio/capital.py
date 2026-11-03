"""Capital-level feasibility and passive-income (withdrawal) simulation.

Two separate questions:
1. Execution feasibility at each capital level: an integer-share simulation with minimum
   commissions shows how much small accounts lose to rounding and fixed fees vs. the fractional
   research engine.
2. Range of outcomes and sustainable withdrawals: stationary block bootstrap of the strategy's
   realised out-of-sample daily NET returns (no parameter re-fitting), with periodic withdrawals.

Definitions used in the report:
* realised historical return  - what the backtest actually produced over its OOS window
* expected return            - mean of the bootstrap distribution (a model estimate, not a promise)
* growth                     - change in account value with no withdrawals
* withdrawable cash flow     - a withdrawal rate whose probability of depleting capital below a floor
                               over the horizon stays <= 5% in the bootstrap
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from qrs.backtest.stats import stationary_bootstrap_idx

CAPITAL_LEVELS = [1_000, 5_000, 10_000, 25_000, 50_000, 100_000]


def share_simulation(W: pd.DataFrame, open_: pd.DataFrame, close: pd.DataFrame, capital: float,
                     one_way_bps: pd.Series, per_share: float = 0.005, min_fee: float = 1.0, max_fee_pct: float = 0.01,
                     fx_cost_bps: float = 2.0, rf: pd.Series | None = None, lag: int = 1) -> pd.DataFrame:
    """Integer-share, account-currency simulation (IBKR-Pro-fixed-like fee: USD 0.005/share,
    min USD 1, max 1% of trade value; plus spread/slippage bps and an FX conversion cost on traded
    notional for a EUR account trading USD instruments). Orders at next open, like the research engine."""
    idx = close.index
    cols = list(W.columns)
    O = open_.reindex(index=idx, columns=cols).to_numpy(float)
    C = close.reindex(index=idx, columns=cols).to_numpy(float)
    Wt = W.reindex(index=idx, columns=cols).to_numpy(float)
    slip = one_way_bps.reindex(cols).fillna(5.0).to_numpy() * 1e-4
    rfa = rf.reindex(idx).fillna(0.0).to_numpy() if rf is not None else np.zeros(len(idx))
    shares = np.zeros(len(cols))
    cash = capital
    last_c = np.full(len(cols), np.nan)
    rows = []
    for i in range(len(idx)):
        v = np.isfinite(O[i]) & np.isfinite(C[i])
        j = i - lag
        fees = 0.0
        if j >= 0 and np.isfinite(Wt[j]).any():
            mark = np.where(np.isfinite(last_c), last_c, 0.0)
            eq = cash + float(shares @ mark)
            tgt = np.where(v, np.floor(np.abs(np.nan_to_num(Wt[j])) * max(eq, 0) / np.where(v, O[i], np.inf)) *
                           np.sign(np.nan_to_num(Wt[j])), shares)
            d = tgt - shares
            for k in np.where(np.abs(d) > 0)[0]:
                px = O[i, k] * (1 + slip[k] * np.sign(d[k]))
                val = abs(d[k]) * px
                fee = min(max(per_share * abs(d[k]), min_fee), max_fee_pct * val) + fx_cost_bps * 1e-4 * val
                cash -= d[k] * px + fee
                fees += fee + abs(d[k]) * abs(px - O[i, k])
                shares[k] = tgt[k]
        last_c = np.where(v, C[i], last_c)
        mark = np.where(np.isfinite(last_c), last_c, 0.0)
        cash += max(cash, 0) * rfa[i]
        eq = cash + float(shares @ mark)
        rows.append((idx[i], eq, cash, fees))
    out = pd.DataFrame(rows, columns=["date", "equity", "cash", "fees"]).set_index("date")
    out["ret"] = out["equity"].pct_change().fillna(0.0)
    return out


def withdrawal_paths(daily: pd.Series, capital: float, annual_withdrawal_rate: float, years: int = 20,
                     n_paths: int = 2000, ppy: int = 252, mean_block: float = 21.0, floor_frac: float = 0.5,
                     inflation: float = 0.02, seed: int = 5) -> dict:
    """Bootstrap paths; withdraw (annual_rate * initial capital, grown with inflation) monthly.
    Depletion = equity falls below floor_frac * initial capital (real terms) at any point."""
    x = daily.dropna().to_numpy(float)
    rng = np.random.default_rng(seed)
    n = years * ppy
    step = ppy // 12
    term = np.empty(n_paths)
    depleted = np.zeros(n_paths, bool)
    for p in range(n_paths):
        r = np.concatenate([x[stationary_bootstrap_idx(len(x), mean_block, rng)]
                            for _ in range(math.ceil(n / len(x)))])[:n]
        eq = capital
        for t in range(n):
            eq *= 1 + r[t]
            if (t + 1) % step == 0:
                yrs = (t + 1) / ppy
                eq -= capital * annual_withdrawal_rate / 12 * (1 + inflation) ** yrs
                if eq < floor_frac * capital * (1 + inflation) ** yrs:
                    depleted[p] = True
            if eq <= 0:
                eq = 0.0
                depleted[p] = True
                break
        term[p] = eq / (1 + inflation) ** years
    return {"withdrawal_rate": annual_withdrawal_rate, "monthly_income_start": capital * annual_withdrawal_rate / 12,
            "p_depletion": float(depleted.mean()), "real_terminal_p5": float(np.quantile(term, 0.05)),
            "real_terminal_median": float(np.median(term)), "real_terminal_p95": float(np.quantile(term, 0.95))}


def outcome_distribution(daily: pd.Series, capital: float, years: int = 10, n_paths: int = 2000, ppy: int = 252,
                         seed: int = 9) -> dict:
    x = daily.dropna().to_numpy(float)
    rng = np.random.default_rng(seed)
    n = years * ppy
    cagr, mdd = np.empty(n_paths), np.empty(n_paths)
    for p in range(n_paths):
        r = np.concatenate([x[stationary_bootstrap_idx(len(x), 21.0, rng)] for _ in range(math.ceil(n / len(x)))])[:n]
        eq = np.cumprod(1 + r)
        cagr[p] = eq[-1] ** (1 / years) - 1
        mdd[p] = float((eq / np.maximum.accumulate(eq) - 1).min())
    return {"years": years, "cagr_p5": float(np.quantile(cagr, 0.05)), "cagr_median": float(np.median(cagr)),
            "cagr_p95": float(np.quantile(cagr, 0.95)), "p_loss": float((cagr < 0).mean()),
            "maxdd_median": float(np.median(mdd)), "maxdd_p5": float(np.quantile(mdd, 0.05)),
            "terminal_median": capital * (1 + float(np.median(cagr))) ** years,
            "terminal_p5": capital * (1 + float(np.quantile(cagr, 0.05))) ** years}
