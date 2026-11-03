"""Performance and risk metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _clean(r: pd.Series) -> pd.Series:
    return r.dropna().astype(float)


def cagr(r: pd.Series, ppy: int) -> float:
    r = _clean(r)
    if len(r) == 0:
        return np.nan
    tot = float((1 + r).prod())
    yrs = len(r) / ppy
    return tot ** (1 / yrs) - 1 if tot > 0 else -1.0


def sharpe(r: pd.Series, ppy: int, rf: pd.Series | None = None) -> float:
    r = _clean(r)
    if rf is not None:
        r = r - rf.reindex(r.index).fillna(0)
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(ppy)) if sd > 0 else np.nan


def sortino(r: pd.Series, ppy: int) -> float:
    r = _clean(r)
    dd = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
    return float(r.mean() / dd * np.sqrt(ppy)) if dd > 0 else np.nan


def drawdown(r: pd.Series) -> pd.Series:
    eq = (1 + _clean(r)).cumprod()
    return eq / eq.cummax() - 1


def max_drawdown(r: pd.Series) -> float:
    d = drawdown(r)
    return float(d.min()) if len(d) else np.nan


def max_dd_duration(r: pd.Series) -> int:
    d = drawdown(r).to_numpy()
    longest = cur = 0
    for x in d:
        cur = cur + 1 if x < 0 else 0
        longest = max(longest, cur)
    return longest


def var_es(r: pd.Series, q: float = 0.05) -> tuple[float, float]:
    r = _clean(r)
    if len(r) < 20:
        return np.nan, np.nan
    v = float(np.quantile(r, q))
    return v, float(r[r <= v].mean())


def trade_stats(trades: pd.DataFrame) -> dict:
    if trades is None or len(trades) == 0:
        return {"n_trades": 0, "win_rate": np.nan, "avg_win": np.nan, "avg_loss": np.nan,
                "expectancy": np.nan, "profit_factor": np.nan, "avg_bars": np.nan}
    p = trades["pnl"]
    wins, losses = p[p > 0], p[p <= 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else np.inf
    return {"n_trades": int(len(p)), "win_rate": float((p > 0).mean()),
            "avg_win": float(wins.mean()) if len(wins) else 0.0,
            "avg_loss": float(losses.mean()) if len(losses) else 0.0,
            "expectancy": float(p.mean()), "profit_factor": float(pf), "avg_bars": float(trades["bars"].mean())}


def summarize(ret: pd.DataFrame | pd.Series, ppy: int, trades: pd.DataFrame | None = None,
              rf: pd.Series | None = None) -> dict:
    """Full metric set. ``ret`` is the engine's returns frame (or a plain net-return series)."""
    if isinstance(ret, pd.Series):
        ret = ret.to_frame("net")
    r = _clean(ret["net"])
    if len(r) < 2:
        return {"n_obs": len(r)}
    v, es = var_es(r)
    m = {
        "start": str(r.index[0].date()), "end": str(r.index[-1].date()), "n_obs": int(len(r)),
        "cagr": cagr(r, ppy), "ann_vol": float(r.std() * np.sqrt(ppy)),
        "sharpe": sharpe(r, ppy), "sharpe_excess": sharpe(r, ppy, rf) if rf is not None else np.nan,
        "sortino": sortino(r, ppy), "max_dd": max_drawdown(r), "max_dd_bars": max_dd_duration(r),
        "var95": v, "es95": es, "skew": float(r.skew()), "kurt": float(r.kurt()),
        "hit_rate_bars": float((r[r != 0] > 0).mean()) if (r != 0).any() else np.nan,
    }
    m["calmar"] = m["cagr"] / abs(m["max_dd"]) if m["max_dd"] < 0 else np.nan
    if "gross" in ret:
        g = ret["gross"].loc[r.index]
        m["gross_cagr"] = cagr(g, ppy)
        gross_profit = float(g.sum())
        tc = float(ret["cost"].loc[r.index].sum())
        m["cost_ann"] = tc / len(r) * ppy
        m["cost_pct_gross"] = tc / gross_profit if gross_profit > 0 else np.nan
        m["financing_ann"] = float(ret["financing"].loc[r.index].sum()) / len(r) * ppy
        m["turnover_ann"] = float(ret["turnover"].loc[r.index].sum()) / len(r) * ppy
        m["avg_gross_exp"] = float(ret["gross_exp"].loc[r.index].mean())
        m["avg_net_exp"] = float(ret["net_exp"].loc[r.index].mean())
        m["time_in_market"] = float((ret["gross_exp"].loc[r.index] > 1e-6).mean())
    if trades is not None:
        t = trades[(trades["entry"] >= r.index[0]) & (trades["entry"] <= r.index[-1])]
        m.update(trade_stats(t))
    return m


def regime_table(r: pd.Series, regimes: pd.Series, ppy: int) -> pd.DataFrame:
    """Performance split by an exogenous regime label (aligned by date)."""
    lab = regimes.reindex(r.index).ffill()
    rows = []
    for k, g in r.groupby(lab):
        if len(g) > 20:
            rows.append({"regime": k, "n": len(g), "ann_ret": g.mean() * ppy, "ann_vol": g.std() * np.sqrt(ppy),
                         "sharpe": sharpe(g, ppy), "max_dd": max_drawdown(g)})
    return pd.DataFrame(rows)


def yearly(r: pd.Series) -> pd.Series:
    return _clean(r).groupby(r.dropna().index.year).apply(lambda x: (1 + x).prod() - 1)
