"""Market context objects handed to strategies: aligned price panels, point-in-time eligibility,
risk-free rate, funding, cost model and pre-registered research splits."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from qrs.backtest.costs import CostModel, crypto_cost_model, etf_cost_model
from qrs.config import load_yaml
from qrs.data.store import load_funding_daily, load_wide


@dataclass
class Market:
    name: str
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame            # in quote currency (USD / USDT) traded value
    costs: CostModel
    ppy: int
    rf: pd.Series                   # per-period risk-free return
    eligible: pd.DataFrame          # point-in-time tradable universe (bool)
    funding: pd.DataFrame | None = None
    splits: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    def subset(self, symbols: list[str], name: str | None = None) -> "Market":
        s = [x for x in symbols if x in self.close.columns]
        f = self.funding.reindex(columns=s) if self.funding is not None else None
        return Market(name or self.name, self.open[s], self.high[s], self.low[s], self.close[s], self.volume[s],
                      self.costs, self.ppy, self.rf, self.eligible[s], f, self.splits, self.groups)

    def returns(self) -> pd.DataFrame:
        """Close-to-close simple returns (for signals only; P&L is computed by the engine)."""
        return self.close.ffill(limit=5).pct_change(fill_method=None)

    def vol(self, span: int = 60) -> pd.DataFrame:
        """Ex-ante annualised EWMA volatility of daily log returns (uses data up to t only)."""
        lr = np.log(self.close.ffill(limit=5)).diff()
        return np.sqrt((lr ** 2).ewm(span=span, min_periods=span // 2).mean() * self.ppy)


def splits() -> dict:
    return load_yaml("research.yaml")["splits"]


@lru_cache(maxsize=2)
def etf_market() -> Market:
    o, h, l, c, v = (load_wide("etf", f) for f in ("open", "high", "low", "close", "volume"))
    v = v * c
    rf_px = c["BIL"].copy()
    rf = rf_px.pct_change(fill_method=None)
    shy = c["SHY"].pct_change(fill_method=None)
    rf = rf.where(rf.notna(), shy).fillna(0.0).clip(-0.01, 0.01)   # SHY proxy before BIL inception (2007-05)
    cols = [x for x in c.columns if x != "BIL"]
    n_valid = c[cols].notna().rolling(252, min_periods=1).sum()
    elig = n_valid >= 250
    u = load_yaml("universe.yaml")["etf"]["instruments"]
    groups: dict[str, list[str]] = {}
    for s, spec in u.items():
        groups.setdefault(spec["asset_class"], []).append(s)
    return Market("etf", o[cols], h[cols], l[cols], c[cols], v[cols], etf_cost_model(), 252, rf, elig,
                  splits=splits()["etf"], groups=groups)


def _split_relistings(df_by_field: dict[str, pd.DataFrame], gap_days: int = 7) -> dict[str, pd.DataFrame]:
    """Series with a data gap > gap_days are split into separate instruments (e.g. LUNA -> new LUNA 2.0
    reusing the ticker). Prevents fake returns across the gap and look-back windows spanning two assets."""
    c = df_by_field["close"]
    out = {k: v.copy() for k, v in df_by_field.items()}
    for s in c.columns:
        ok = c[s].notna()
        dates = c.index[ok]
        if len(dates) < 2:
            continue
        gaps = np.where(np.diff(dates.values).astype("timedelta64[D]").astype(int) > gap_days)[0]
        for n, gi in enumerate(gaps, start=2):
            cut = dates[gi + 1]
            for k in out:
                new = out[k][s].where(out[k].index >= cut)
                out[k][f"{s}#{n}"] = new
                out[k][s] = out[k][s].where(out[k].index < cut)
    return out


@lru_cache(maxsize=4)
def crypto_market(kind: str = "spot", top_n: int = 15) -> Market:
    """kind='spot' or 'perp'. Eligibility: >= 115 valid bars in the last 120 days and in the top_n by
    trailing 30-day quote volume (point-in-time; includes coins that were later delisted)."""
    ds = "spot" if kind == "spot" else "perp"
    f = {k: load_wide(ds, k) for k in ("open", "high", "low", "close", "quote_volume")}
    f = _split_relistings(f)
    c = f["close"]
    hist = c.notna().rolling(120, min_periods=1).sum() >= 115
    qv = f["quote_volume"].rolling(30, min_periods=20).mean().where(hist)
    rank = qv.rank(axis=1, ascending=False)
    elig = (rank <= top_n) & hist
    costs = crypto_cost_model(list(c.columns), "spot" if kind == "spot" else "perp")
    rf = pd.Series(0.0, index=c.index)   # USDT cash assumed to earn nothing (conservative)
    fund = None
    if kind == "perp":
        fund = load_funding_daily().reindex(index=c.index).reindex(columns=c.columns).fillna(0.0)
    return Market(f"crypto_{kind}", f["open"], f["high"], f["low"], c, f["quote_volume"], costs, 365, rf, elig,
                  fund, splits=splits()["crypto"])
