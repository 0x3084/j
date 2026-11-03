"""Volatility-based strategies: vol-managed exposure, VIX regime switching, risk parity with vol
regime classification, and crypto funding-rate carry (delta-neutral)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.backtest.costs import CostModel
from qrs.data.store import load_vix
from qrs.research.market import Market, crypto_market
from qrs.strategies.common import rebalance_every


def vol_managed(m: Market, asset: str = "SPY", target: float = 0.12, max_lev: float = 1.0, span: int = 20,
                rebalance: int = 5) -> pd.DataFrame:
    """Moreira-Muir style: exposure = target / forecast vol (EWMA), capped at max_lev."""
    W = pd.DataFrame(0.0, index=m.close.index, columns=m.symbols)
    v = m.vol(span)[asset]
    W[asset] = (target / v).clip(upper=max_lev).fillna(0.0)
    return rebalance_every(W, rebalance)


def vix_regime(m: Market, asset: str = "SPY", alt: str | None = "IEF", pct: float = 0.8, window: int = 252,
               rebalance: int = 1) -> pd.DataFrame:
    """Hold `asset` while VIX is below its trailing `pct` quantile; otherwise rotate to `alt` (or cash).
    VIX close (16:15 ET) is known by the time the next-open order is placed."""
    vix = load_vix().reindex(m.close.index).ffill(limit=3)
    thr = vix.rolling(window, min_periods=window // 2).quantile(pct)
    calm = vix < thr
    W = pd.DataFrame(0.0, index=m.close.index, columns=m.symbols)
    W[asset] = calm.astype(float).where(thr.notna(), 0.0)
    if alt:
        W[alt] = (~calm).astype(float).where(thr.notna(), 0.0)
    W = rebalance_every(W, rebalance)
    # missing / stale VIX after the warm-up: no information -> HOLD (NaN row), never an implicit switch
    stale = vix.isna() & thr.ffill().notna()
    W.loc[stale.to_numpy()] = np.nan
    return W


def risk_parity(m: Market, target: float = 0.08, regime: bool = True, regime_asset: str = "SPY",
                hi_pct: float = 0.8, max_lev: float = 1.0, rebalance: int = 21) -> pd.DataFrame:
    """Inverse-volatility multi-asset portfolio scaled to a vol target. If regime=True, a realised-vol
    regime classifier (regime_asset's 20d vol above its trailing 2y `hi_pct` quantile = HIGH-VOL
    regime) halves risky exposure in the high-vol regime."""
    vol = m.vol(60)
    iv = (1 / vol).where(m.eligible)
    w = iv.div(iv.sum(axis=1), axis=0)
    port_vol = np.sqrt((w ** 2 * vol ** 2).sum(axis=1))          # assumes zero correlation (conservative scaler)
    lev = (target / port_vol).clip(upper=max_lev)
    W = w.mul(lev, axis=0)
    if regime:
        rv = m.vol(20)[regime_asset]
        thr = rv.rolling(504, min_periods=252).quantile(hi_pct)
        hi = (rv > thr).astype(float)
        W = W.mul(1 - 0.5 * hi, axis=0)
    return rebalance_every(W.fillna(0.0), rebalance)


# ------------------------------------------------------------------------------ crypto funding carry
def carry_market(top_n: int = 10) -> Market:
    """Combined spot+perp market: columns SYM:S (spot) and SYM:P (perp). Funding applies to :P."""
    s, p = crypto_market("spot", 30), crypto_market("perp", 30)
    syms = [x for x in p.symbols if x in s.symbols and "#" not in x]
    def both(a, b):
        return pd.concat([a[syms].add_suffix(":S"), b[syms].add_suffix(":P")], axis=1)
    idx = p.close.index.intersection(s.close.index)
    o, h, l, c = (both(getattr(s, f).reindex(idx), getattr(p, f).reindex(idx)) for f in ("open", "high", "low", "close"))
    v = both(s.volume.reindex(idx), p.volume.reindex(idx))
    elig_p = p.eligible.reindex(idx)[syms]
    qv = p.volume.reindex(idx)[syms].rolling(30, min_periods=20).mean()
    top = qv.rank(axis=1, ascending=False).le(top_n) & elig_p & s.eligible.reindex(idx)[syms]
    elig = pd.concat([top.add_suffix(":S"), top.add_suffix(":P")], axis=1)
    one = pd.concat([s.costs.one_way.reindex(syms).add_suffix(":S"), p.costs.one_way.reindex(syms).add_suffix(":P")])
    sh = pd.Series({c_: c_.endswith(":P") for c_ in c.columns})
    costs = CostModel(one, pd.Series(0.0, index=c.columns), sh, 0.0, False, 365)
    fund = pd.concat([pd.DataFrame(0.0, index=idx, columns=[x + ":S" for x in syms]),
                      p.funding.reindex(idx)[syms].add_suffix(":P")], axis=1)
    return Market("crypto_carry", o, h, l, c, v, costs, 365, pd.Series(0.0, index=idx), elig, fund,
                  splits=p.splits)


def funding_carry(m: Market, lookback: int = 7, entry_apr: float = 0.10, exit_apr: float = 0.0,
                  max_pairs: int = 5, rebalance: int = 1) -> pd.DataFrame:
    """Delta-neutral basis/funding harvest: long spot + short perp (equal notional) in coins whose
    trailing `lookback`-day funding annualises above `entry_apr`; exit when below `exit_apr`.
    Capital: half the account backs spot, half is perp collateral -> 1x gross per unit of capital."""
    pc = [c for c in m.symbols if c.endswith(":P")]
    f = m.funding[pc].rolling(lookback, min_periods=lookback).mean() * 365
    elig = m.eligible[pc]
    F, E = f.to_numpy(), elig.to_numpy()
    pos = np.zeros_like(F)
    cur = np.zeros(len(pc), bool)
    for i in range(len(F)):
        with np.errstate(invalid="ignore"):
            cur = np.where(cur & (F[i] < exit_apr), False, cur)
            cand = ~cur & (F[i] > entry_apr) & E[i]
            free = max_pairs - int(cur.sum())
            if free > 0 and cand.any():
                order = np.argsort(-np.nan_to_num(np.where(cand, F[i], -np.inf), neginf=-np.inf))
                for j in order[:free]:
                    if cand[j]:
                        cur[j] = True
            cur = cur & E[i]
        pos[i] = cur
    n = max_pairs
    Wp = pd.DataFrame(-pos * 0.5 / n, index=m.close.index, columns=pc)
    Ws = pd.DataFrame(pos * 0.5 / n, index=m.close.index, columns=[c.replace(":P", ":S") for c in pc])
    W = pd.concat([Ws, Wp], axis=1)[m.symbols]
    return rebalance_every(W, rebalance)
