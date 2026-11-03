"""Data-quality validation.

Checks are *reported*, never silently "fixed".  The only automatic treatment downstream is that a
bar flagged as invalid makes the instrument non-tradable on that day (the engine carries the last
valid price for valuation but refuses to trade it).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import polars as pl


@dataclass
class QualityReport:
    symbol: str
    rows: int
    start: str
    end: str
    duplicates: int = 0
    non_monotonic: int = 0
    missing_sessions: int = 0
    missing_session_examples: list[str] = field(default_factory=list)
    ohlc_inconsistent: int = 0
    non_positive: int = 0
    zero_volume: int = 0
    stale_runs: int = 0             # runs of >= 5 identical closes
    outliers: int = 0               # robust z of log return > 10 that reverses next bar ("spike")
    outlier_examples: list[str] = field(default_factory=list)
    large_moves: int = 0            # |log return| > 25% (reported, usually genuine for crypto)
    flagged_rows: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def validate_bars(df: pl.DataFrame, symbol: str, time_col: str = "date",
                  expected: list | None = None) -> tuple[QualityReport, pl.DataFrame]:
    """Validate an OHLCV frame. Returns report and the frame with a boolean ``valid`` column.

    expected: optional list of expected timestamps (e.g. exchange sessions or every UTC day).
    """
    df = df.sort(time_col)
    rep = QualityReport(symbol, df.height, str(df[time_col].min()), str(df[time_col].max()))
    rep.duplicates = df.height - df[time_col].n_unique()
    df = df.unique(subset=[time_col], keep="last").sort(time_col)
    t = df[time_col].to_numpy()
    rep.non_monotonic = int((np.diff(t.astype("datetime64[ns]").astype(np.int64)) <= 0).sum())

    if expected is not None:
        exp = set(expected)
        have = set(df[time_col].to_list())
        lo, hi = df[time_col].min(), df[time_col].max()
        miss = sorted(x for x in exp - have if lo <= x <= hi)
        rep.missing_sessions = len(miss)
        rep.missing_session_examples = [str(x) for x in miss[:10]]

    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    v = df["volume"].to_numpy() if "volume" in df.columns else np.ones(len(c))
    tol = 1e-6 * c
    bad_ohlc = (l > np.minimum(o, c) + tol) | (h < np.maximum(o, c) - tol) | (h < l)
    nonpos = (o <= 0) | (h <= 0) | (l <= 0) | (c <= 0) | ~np.isfinite(c)
    rep.ohlc_inconsistent = int(bad_ohlc.sum())
    rep.non_positive = int(nonpos.sum())
    rep.zero_volume = int((v <= 0).sum())

    # stale runs
    same = np.r_[False, np.diff(c) == 0]
    run, runs = 0, 0
    for s in same:
        run = run + 1 if s else 0
        if run == 4:
            runs += 1
    rep.stale_runs = runs

    # spike outliers: huge move that is mostly reversed on the next bar
    with np.errstate(divide="ignore", invalid="ignore"):
        lr = np.diff(np.log(np.where(c > 0, c, np.nan)), prepend=np.nan)
    med = pl.Series(lr).rolling_median(63, min_samples=20).to_numpy()
    mad = pl.Series(np.abs(lr - med)).rolling_median(63, min_samples=20).to_numpy() * 1.4826
    z = (lr - med) / np.where(mad > 0, mad, np.nan)
    nxt = np.r_[lr[1:], np.nan]
    spike = (np.abs(z) > 10) & (np.sign(nxt) == -np.sign(lr)) & (np.abs(nxt) > 0.6 * np.abs(lr))
    spike = np.nan_to_num(spike).astype(bool)
    rep.outliers = int(spike.sum())
    rep.outlier_examples = [str(x) for x in df[time_col].to_numpy()[spike][:10]]
    rep.large_moves = int(np.nansum(np.abs(lr) > 0.25))

    valid = ~(bad_ohlc | nonpos | spike)
    rep.flagged_rows = int((~valid).sum())
    return rep, df.with_columns(pl.Series("valid", valid), pl.Series("spike", spike),
                                pl.Series("hard_invalid", bad_ohlc | nonpos))


def cross_check(a: np.ndarray, b: np.ndarray, periods: int = 252) -> dict:
    """Compare two aligned daily return series from independent sources."""
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 30:
        return {"n": int(len(a))}
    return {"n": int(len(a)), "corr": float(np.corrcoef(a, b)[0, 1]),
            "mean_abs_diff_bps": float(np.mean(np.abs(a - b)) * 1e4),
            "ann_return_diff": float((np.mean(a) - np.mean(b)) * periods)}
