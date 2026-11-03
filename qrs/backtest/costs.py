"""Transaction-cost and financing model."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qrs.config import crypto_specs, etf_specs


@dataclass
class CostModel:
    """One-way proportional costs per asset (fraction of traded notional) plus financing terms.

    cost_mult scales spread+slippage+commission (stress testing); slip_add_bps adds flat slippage.
    """
    one_way: pd.Series                        # fraction, per symbol
    borrow_yr: pd.Series                      # fraction per year on short notional
    shortable: pd.Series                      # bool per symbol
    financing_spread_yr: float = 0.015        # paid over the risk-free rate on borrowed cash (leverage)
    cash_yield: bool = True                   # idle cash earns the risk-free rate (ETF account)
    periods_per_year: int = 252
    cost_mult: float = 1.0
    slip_add_bps: float = 0.0
    extra: dict = field(default_factory=dict)

    def stressed(self, cost_mult: float = 1.0, slip_add_bps: float = 0.0) -> "CostModel":
        return CostModel(self.one_way, self.borrow_yr, self.shortable, self.financing_spread_yr,
                         self.cash_yield, self.periods_per_year, self.cost_mult * cost_mult,
                         self.slip_add_bps + slip_add_bps, self.extra)

    def vector(self, cols) -> np.ndarray:
        base = self.one_way.reindex(cols).fillna(self.one_way.max()).to_numpy()
        return base * self.cost_mult + self.slip_add_bps * 1e-4

    def borrow_vector(self, cols) -> np.ndarray:
        return self.borrow_yr.reindex(cols).fillna(0.05).to_numpy() / self.periods_per_year


def etf_cost_model() -> CostModel:
    s = etf_specs()
    one = pd.Series({k: (v["half_spread_bps"] + v["slippage_bps"] + v["commission_bps"]) * 1e-4 for k, v in s.items()})
    bor = pd.Series({k: v["borrow_bps_yr"] * 1e-4 for k, v in s.items()})
    sh = pd.Series({k: bool(v["shortable"]) for k, v in s.items()})
    return CostModel(one, bor, sh, periods_per_year=252, cash_yield=True)


def crypto_cost_model(symbols, market: str = "spot") -> CostModel:
    c = crypto_specs()
    d = c["spot_defaults"] if market == "spot" else c["perp_defaults"]
    tiers = {k: (v or {}).get("tier", 3) for k, v in c["instruments"].items()}
    # alts have wider spreads / thinner books than BTC/ETH
    mult = {1: 1.0, 2: 2.0, 3: 3.0}
    one = pd.Series({s: ((d["half_spread_bps"] + d["slippage_bps"]) * mult[tiers.get(s.split("#")[0], 3)]
                         + d["commission_bps"]) * 1e-4 for s in symbols})
    shortable = pd.Series({s: market == "perp" for s in symbols})
    bor = pd.Series({s: 0.0 for s in symbols})  # perp shorts pay/receive funding instead (handled separately)
    return CostModel(one, bor, shortable, financing_spread_yr=0.0, cash_yield=False, periods_per_year=365)
