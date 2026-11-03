import numpy as np
import pandas as pd
import pytest

from qrs.paper.engine import LIVE_TRADING_ENABLED, PaperTrader, SimBroker, _action
from qrs.paper.feeds import ReplayFeed
from qrs.risk.manager import Approval, RiskLimits, RiskManager, State


def test_live_trading_disabled():
    assert LIVE_TRADING_ENABLED is False


def test_position_gross_and_group_caps():
    rm = RiskManager(RiskLimits(max_position_weight=0.3, max_gross=1.0, max_group_weight=0.4),
                     groups={"A": "eq", "B": "eq", "C": "bond"})
    ap = rm.approve({"A": 0.5, "B": 0.5, "C": 0.5}, {}, {"A": 1, "B": 1, "C": 1})
    w = ap.weights
    assert max(abs(v) for v in w.values()) <= 0.3 + 1e-12
    assert abs(w["A"]) + abs(w["B"]) <= 0.4 + 1e-12
    assert sum(abs(v) for v in w.values()) <= 1.0 + 1e-12


def test_stale_data_freezes_instrument_and_feed_down_halts():
    rm = RiskManager(RiskLimits(max_data_age_hours=24, max_stale_fraction=0.5))
    ap = rm.approve({"A": 0.5, "B": 0.5}, {"A": 0.1}, {"A": 100, "B": 1})
    assert ap.weights["A"] == 0.1                       # frozen at current
    rm2 = RiskManager(RiskLimits(max_data_age_hours=24, max_stale_fraction=0.5))
    rm2.approve({"A": 0.5, "B": 0.5}, {}, {"A": 100, "B": 100})
    assert rm2.state == State.HALTED


def test_daily_loss_reduce_only_and_drawdown_halt():
    rm = RiskManager(RiskLimits(max_daily_loss=0.03, max_drawdown=0.10))
    rm.update_equity(100, "d1")
    rm.update_equity(96, "d1")
    assert rm.state == State.REDUCE_ONLY
    ap = rm.approve({"A": 0.8}, {"A": 0.5}, {"A": 1})
    assert ap.weights["A"] <= 0.5                       # can only reduce
    rm.update_equity(96, "d2")
    assert rm.state == State.ACTIVE                     # new session releases the lock
    rm.update_equity(89, "d3")
    assert rm.state == State.HALTED
    ap = rm.approve({"A": 1.0}, {"A": 0.2}, {"A": 1})
    assert ap.weights["A"] == 0.2                       # halted: positions frozen, no new risk


def test_kill_switch(tmp_path):
    k = tmp_path / "KILL"
    rm = RiskManager(RiskLimits(), kill_file=k)
    k.write_text("x")
    rm.approve({"A": 0.5}, {}, {"A": 1})
    assert rm.state == State.HALTED


def test_consecutive_errors_halt():
    rm = RiskManager(RiskLimits(max_consecutive_errors=2))
    rm.record_error("boom")
    rm.record_error("boom")
    assert rm.state == State.HALTED


def test_broker_rejects_unapproved_orders():
    rm = RiskManager(RiskLimits())
    b = SimBroker({"A": 1}, {"A": 1}, risk=rm, cash=1000)
    forged = Approval({"A": 1.0}, "deadbeef", "now", "ACTIVE")
    with pytest.raises(PermissionError):
        b.submit(forged, {"A": 10.0}, 1000, pd.Timestamp("2020-01-01"))
    ok = rm.approve({"A": 1.0}, {}, {"A": 1})
    tampered = Approval({"A": 1.0 if ok.weights["A"] != 1.0 else 0.9}, ok.digest, ok.issued_utc, ok.state)
    with pytest.raises(PermissionError):
        b.submit(tampered, {"A": 10.0}, 1000, pd.Timestamp("2020-01-01"))


def test_action_labels():
    assert _action(0, 0) == "NO_TRADE"
    assert _action(0, 0.5) == "BUY"
    assert _action(0.5, 0) == "SELL"
    assert _action(0, -0.5) == "SHORT"
    assert _action(-0.5, 0) == "COVER"
    assert _action(0.5, 0.5) == "HOLD"


def _panels(n=60):
    idx = pd.date_range("2021-01-01", periods=n, freq="D")
    px = pd.DataFrame({"A": np.linspace(100, 130, n)}, index=idx)
    return {"open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": px * 0 + 1e6}


def _trader(tmp_path, panels, start):
    from qrs.backtest.costs import CostModel
    from qrs.research.market import Market
    costs = CostModel(pd.Series({"A": 0.0}), pd.Series({"A": 0.0}), pd.Series({"A": True}), 0.0, False, 365)

    def build(h):
        c = h["close"]
        return Market("t", h["open"], h["high"], h["low"], c, h["volume"], costs, 365, pd.Series(0.0, index=c.index),
                      c.notna(), None)

    strat = lambda m: pd.DataFrame(1.0, index=m.close.index, columns=m.symbols)   # always fully long
    feed = ReplayFeed(panels, start)
    return PaperTrader("t", feed, strat, build, 10_000, RiskLimits(max_data_age_hours=1e9), {
        "one_way_bps": {"A": 0}, "commission_bps": {"A": 0}, "lot_step": 0.0001},
        journal_path=tmp_path / "t.sqlite")


def test_paper_end_to_end_and_recovery(tmp_path):
    p = _panels()
    pt = _trader(tmp_path, p, "2021-01-31")
    pt.run(max_bars=10)
    eq1 = pt.journal.query("SELECT equity FROM equity ORDER BY ts")
    assert len(eq1) == 10 and eq1[-1]["equity"] > 10_000             # rising price, long position
    assert pt.journal.query("SELECT COUNT(*) n FROM fills")[0]["n"] >= 1
    # simulate a crash + restart: state is recovered from the journal and processed bars are skipped
    pt2 = _trader(tmp_path, p, "2021-01-31")
    assert pt2.broker.positions == pt.broker.positions
    pt2.run()
    eq2 = pt2.journal.query("SELECT ts FROM equity ORDER BY ts")
    assert len(eq2) == len(set(r["ts"] for r in eq2)) == 30
