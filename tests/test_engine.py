"""Backtest-engine correctness tests on small hand-constructed price paths (unit-test fixtures, not
market data)."""
import numpy as np
import pandas as pd
import pytest

from qrs.backtest.costs import CostModel
from qrs.backtest.engine import extract_trades, run_backtest


def _mk(prices_open, prices_close, cols=("A",)):
    idx = pd.date_range("2020-01-01", periods=len(prices_close), freq="B")
    o = pd.DataFrame(np.array(prices_open, float).reshape(len(idx), -1), index=idx, columns=list(cols))
    c = pd.DataFrame(np.array(prices_close, float).reshape(len(idx), -1), index=idx, columns=list(cols))
    return o, c


def _costs(cols, bps=0.0, borrow=0.0, shortable=True, cash_yield=False):
    cols = list(cols)
    return CostModel(pd.Series(bps * 1e-4, index=cols), pd.Series(borrow, index=cols),
                     pd.Series(shortable, index=cols), 0.0, cash_yield, 252)


def test_buy_and_hold_telescopes_to_close_over_entry_open():
    o, c = _mk([10, 11, 12, 11, 13], [10.5, 11.5, 11.8, 12.5, 13.5])
    W = pd.DataFrame(1.0, index=c.index, columns=["A"])
    r = run_backtest(W, o, c, _costs(["A"]))
    # signal at bar 0 close -> executed at bar 1 open (11) -> final close 13.5
    assert np.isclose((1 + r.net).prod(), 13.5 / 11.0)
    assert r.net.iloc[0] == 0.0          # nothing held on the first bar (lag)


def test_costs_charged_on_turnover_only():
    o, c = _mk([10] * 6, [10] * 6)
    W = pd.DataFrame([[1.0], [1.0], [0.0], [0.0], [1.0], [1.0]], index=c.index, columns=["A"])
    r = run_backtest(W, o, c, _costs(["A"], bps=10))
    # trades: buy at bar1, sell at bar3, buy at bar5 -> 3 x 10bp
    assert np.isclose((1 + r.net).prod(), (1 - 0.001) ** 3)
    assert np.isclose(r.returns["turnover"].sum(), 3.0)


def test_nan_row_means_hold_and_zero_row_means_flat():
    o, c = _mk([10, 10, 11, 12, 13], [10, 10.5, 11.5, 12.5, 13.5])
    W = pd.DataFrame([[1.0], [np.nan], [np.nan], [0.0], [np.nan]], index=c.index, columns=["A"])
    r = run_backtest(W, o, c, _costs(["A"]))
    assert r.weights["A"].iloc[1] == 1.0 and r.weights["A"].iloc[3] == 1.0
    assert r.weights["A"].iloc[4] == 0.0


def test_no_lookahead_signal_on_same_bar():
    """A weight decided on bar t can never earn bar t's return."""
    o, c = _mk([10, 10, 20, 20], [10, 20, 20, 20])
    W = pd.DataFrame([[0.0], [1.0], [1.0], [1.0]], index=c.index, columns=["A"])   # 'knows' after the jump
    r = run_backtest(W, o, c, _costs(["A"]))
    assert np.isclose((1 + r.net).prod(), 1.0)


def test_untradable_bar_blocks_trading_and_stale_forces_exit():
    o, c = _mk([10, 10, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan], [10, 10, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan])
    W = pd.DataFrame(1.0, index=c.index, columns=["A"])
    r = run_backtest(W, o, c, _costs(["A"], bps=10), max_stale=3)
    assert r.weights["A"].iloc[1] == 1.0
    assert r.weights["A"].iloc[2] == 1.0     # cannot trade while no data
    assert r.weights["A"].iloc[-1] == 0.0    # force-closed after max_stale bars


def test_short_borrow_and_non_shortable():
    o, c = _mk([10] * 253, [10] * 253)
    W = pd.DataFrame(-1.0, index=c.index, columns=["A"])
    r = run_backtest(W, o, c, _costs(["A"], borrow=0.0252))
    assert np.isclose(r.net.sum(), -0.0252 / 252 * 252, rtol=1e-6)
    r2 = run_backtest(W, o, c, _costs(["A"], shortable=False))
    assert (r2.weights["A"] == 0).all()


def test_funding_sign_long_pays_positive():
    o, c = _mk([10] * 5, [10] * 5)
    W = pd.DataFrame(1.0, index=c.index, columns=["A"])
    f = pd.DataFrame(0.001, index=c.index, columns=["A"])
    r = run_backtest(W, o, c, _costs(["A"]), funding=f)
    assert np.allclose(r.net.iloc[1:], -0.001)
    r2 = run_backtest(-W, o, c, _costs(["A"]), funding=f)
    assert np.allclose(r2.net.iloc[1:], 0.001)


def test_gross_leverage_cap():
    o, c = _mk(np.full((4, 2), 10.0), np.full((4, 2), 10.0), cols=("A", "B"))
    W = pd.DataFrame(1.0, index=c.index, columns=["A", "B"])
    r = run_backtest(W, o, c, _costs(["A", "B"]), max_gross=1.0)
    assert np.isclose(r.weights.abs().sum(axis=1).iloc[-1], 1.0)


def test_cash_earns_risk_free_and_leverage_pays():
    o, c = _mk([10] * 3, [10] * 3)
    rf = pd.Series(0.0001, index=c.index)
    W = pd.DataFrame(0.5, index=c.index, columns=["A"])
    r = run_backtest(W, o, c, _costs(["A"], cash_yield=True), rf=rf)
    assert np.isclose(r.net.iloc[1], 0.5 * 0.0001)


def test_trade_extraction_round_trips():
    idx = pd.date_range("2020-01-01", periods=6, freq="B")
    w = pd.DataFrame({"A": [0, 1, 1, -1, -1, 0]}, index=idx, dtype=float)
    ct = pd.DataFrame({"A": [0, 0.01, 0.02, -0.01, 0.03, 0.0]}, index=idx)
    t = extract_trades(w, ct)
    assert list(t["side"]) == ["long", "short"]
    assert np.isclose(t["pnl"].sum(), ct["A"].sum())
