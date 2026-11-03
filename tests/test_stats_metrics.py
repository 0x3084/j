import numpy as np
import pandas as pd

from qrs.backtest.metrics import cagr, max_drawdown, sharpe, summarize
from qrs.backtest.stats import (bootstrap_metrics, deflated_sharpe, expected_max_sharpe, holm,
                                probabilistic_sharpe, reality_check)
from qrs.research.runner import walk_forward_select


def _series(x):
    return pd.Series(x, index=pd.date_range("2000-01-03", periods=len(x), freq="B"))


def test_basic_metrics():
    r = _series([0.01, -0.02, 0.03, 0.0])
    assert np.isclose(max_drawdown(r), -0.02)
    assert np.isclose(cagr(_series([0.0] * 252), 252), 0.0)
    assert np.isnan(sharpe(_series([0.0] * 10), 252))


def test_noise_is_not_significant_and_drift_is():
    rng = np.random.default_rng(0)
    noise = _series(rng.normal(0, 0.01, 2500))
    drift = _series(rng.normal(0.002, 0.01, 2500))
    assert bootstrap_metrics(noise, 252, n_boot=300)["p_sharpe"] > 0.05
    assert bootstrap_metrics(drift, 252, n_boot=300)["p_sharpe"] < 0.01
    assert probabilistic_sharpe(drift) > 0.99


def test_deflated_sharpe_penalises_more_trials():
    rng = np.random.default_rng(1)
    r = _series(rng.normal(0.0006, 0.01, 2500))
    assert deflated_sharpe(r, 100) < deflated_sharpe(r, 2) <= probabilistic_sharpe(r) + 1e-12
    assert expected_max_sharpe(1, 0.01) == 0.0


def test_holm_monotone():
    adj = holm({"a": 0.01, "b": 0.02, "c": 0.5})
    assert adj["a"] <= adj["b"] <= adj["c"] and np.isclose(adj["a"], 0.03)


def test_reality_check_noise():
    rng = np.random.default_rng(2)
    R = pd.DataFrame(rng.normal(0, 0.01, (1500, 20)))
    assert reality_check(R, n_boot=200)["p_rc"] > 0.05


def test_walk_forward_selection_uses_only_past():
    idx = pd.date_range("2000-01-03", "2006-12-29", freq="B")
    good_early = pd.Series(np.where(idx < "2004-01-01", 0.001, -0.001), index=idx) + 1e-4 * np.sin(np.arange(len(idx)))
    good_late = pd.Series(np.where(idx < "2004-01-01", -0.001, 0.001), index=idx) + 1e-4 * np.cos(np.arange(len(idx)))
    sel = walk_forward_select({"early": good_early, "late": good_late}, "2004-01-01", "2006-12-29", 252, 3, 21)
    # in 2004 only pre-2004 data is visible -> must pick 'early' even though 'late' wins afterwards
    assert sel[pd.Timestamp("2004-01-01")] == "early"


def test_summarize_keys():
    rng = np.random.default_rng(3)
    s = summarize(_series(rng.normal(0.0005, 0.01, 600)), 252)
    for k in ("cagr", "sharpe", "sortino", "max_dd", "calmar", "var95", "es95"):
        assert k in s
