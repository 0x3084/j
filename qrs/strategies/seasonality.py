"""Calendar / seasonality effects.

These use only the trading calendar (known in advance, not derived from price data) to decide WHEN
to be invested, so there is no look-ahead: knowing that 2019-01-30 is one trading day before month-end
is calendar knowledge available on every prior date too, unlike a future return or price.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.research.market import Market


def _calendar_positions(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """(days_to_month_end, days_since_month_start) for each date in `index`, computed from the
    PUBLISHED exchange calendar spanning well past the last date - not from the price index itself.
    This matters: an exchange calendar is known years in advance, so using it is not look-ahead, but
    deriving month position from "how many price rows for this month have arrived so far" would be -
    the most recent, still-incomplete month would look artificially close to month-end."""
    from qrs.data.store import nyse_sessions
    start = (index.min() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    end = (index.max() + pd.Timedelta(days=45)).strftime("%Y-%m-%d")   # pad past the last real bar
    cal = pd.DatetimeIndex(nyse_sessions(start, end))
    s = pd.Series(cal, index=cal)
    month = s.dt.to_period("M")
    d2e = pd.Series(0, index=cal, dtype=int)
    pos = pd.Series(0, index=cal, dtype=int)
    for _, idx in s.groupby(month).groups.items():
        n = len(idx)
        d2e.loc[idx] = (n - 1) - np.arange(n)
        pos.loc[idx] = np.arange(n)
    return d2e.reindex(index).to_numpy(), pos.reindex(index).to_numpy()


def turn_of_month(m: Market, universe: list[str] | None = None, days_before: int = 1, days_after: int = 3,
                  weight: float = 1.0) -> pd.DataFrame:
    """Long a broad-equity basket from `days_before` trading days before month-end through `days_after`
    trading days into the new month (the well-documented turn-of-month effect: Ariel 1987, Lakonishok
    & Smidt 1988). Equal-weighted across the eligible universe, flat (NO TRADE) the rest of the month."""
    cols = [c for c in (universe or m.symbols) if c in m.symbols]
    idx = m.close.index
    d2e, pos_in_month = _calendar_positions(idx)
    in_window = pd.Series((d2e <= days_before) | (pos_in_month < days_after), index=idx)

    e = m.eligible[cols]
    n = e.sum(axis=1).clip(lower=1)
    w_sub = e.astype(float).div(n, axis=0).mul(weight).where(in_window, 0.0)

    W = pd.DataFrame(0.0, index=idx, columns=m.symbols)
    W[cols] = w_sub
    return W
