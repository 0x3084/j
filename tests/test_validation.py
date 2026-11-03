from datetime import date, timedelta

import polars as pl

from qrs.data.validate import validate_bars


def _frame(closes, opens=None, highs=None, lows=None, dates=None):
    n = len(closes)
    dates = dates or [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]
    opens = opens or closes
    highs = highs or [max(a, b) * 1.01 for a, b in zip(opens, closes)]
    lows = lows or [min(a, b) * 0.99 for a, b in zip(opens, closes)]
    return pl.DataFrame({"date": dates, "open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": [1000.0] * n})


def test_detects_duplicates_and_missing_sessions():
    d = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 2), date(2020, 1, 4)]
    df = _frame([1.0, 1.1, 1.1, 1.2], dates=d)
    expected = [date(2020, 1, 1) + timedelta(days=i) for i in range(4)]
    rep, out = validate_bars(df, "X", "date", expected)
    assert rep.duplicates == 1
    assert rep.missing_sessions == 1


def test_detects_ohlc_inconsistency_and_nonpositive():
    df = _frame([1.0, 1.0, 1.0], highs=[1.1, 0.5, 1.1])
    rep, out = validate_bars(df, "X")
    assert rep.ohlc_inconsistent == 1 and not out["valid"][1]
    rep2, _ = validate_bars(_frame([1.0, -1.0, 1.0]), "Y")
    assert rep2.non_positive >= 1


def test_detects_reverting_spike_and_stale_runs():
    import numpy as np
    rng = np.random.default_rng(0)
    c = list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 120))))
    c[80] = c[79] * 1.8          # bad print that reverts next bar
    rep, out = validate_bars(_frame(c), "Z")
    assert rep.outliers == 1 and not out["valid"][80]
    rep2, _ = validate_bars(_frame([5.0] * 10 + [5.1]), "S")
    assert rep2.stale_runs == 1
