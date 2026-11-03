"""Truncation test for look-ahead bias: weights computed with data up to T must equal, for every
row <= t, the weights computed with data only up to t. Runs on the real processed datasets
(skipped if `python -m scripts.ingest` has not been run)."""
import numpy as np
import pandas as pd
import pytest

from qrs.config import PROC_DIR

pytestmark = pytest.mark.skipif(not (PROC_DIR / "etf_daily.parquet").exists(), reason="data not ingested")


def _truncate(m, t):
    from qrs.research.market import Market
    sl = lambda df: df.loc[:t] if df is not None else None
    return Market(m.name, sl(m.open), sl(m.high), sl(m.low), sl(m.close), sl(m.volume), m.costs, m.ppy,
                  m.rf.loc[:t], sl(m.eligible), sl(m.funding), m.splits, m.groups)


CASES = [
    ("trend:tsmom", "etf", "etf_futures_like", {"lookback": 252}),
    ("trend:tsmom", "etf", "etf_futures_like", {"lookback": 0}),
    ("trend:breakout", "etf", "etf_futures_like", {"n": 55}),
    ("trend:ewmac", "etf", "etf_futures_like", {"speeds": "medium", "threshold": 0.5}),
    ("meanrev:rsi_reversion", "etf", "etf_eq_index", {"entry": 10.0}),
    ("meanrev:zscore_reversion", "etf", "etf_multi", {"lookback": 5}),
    ("meanrev:xs_reversal", "etf", "etf_sectors", {"lookback": 5, "k": 2, "hold": 5}),
    ("momentum:xs_momentum", "etf", "etf_gem", {"lookback": 126, "k": 2}),
    ("momentum:trend_filtered_rotation", "etf", "etf_gem", {}),
    ("vol:vol_managed", "etf", "etf_eq_index", {}),
    ("vol:vix_regime", "etf", "etf_regime", {}),
    ("vol:risk_parity", "etf", "etf_multi", {}),
    ("trend:tsmom", "crypto_perp", "crypto_all", {"lookback": 63}),
    ("momentum:xs_momentum", "crypto_spot", "crypto_all", {"lookback": 30, "k": 3, "skip": 0, "rebalance": "7"}),
    ("ml:ml_regime", "etf", "etf_regime", {}),
    ("ml:ml_xsection", "crypto_spot", "crypto_all", {"model": "ridge", "horizon": 7, "retrain": "QS", "min_train": 540}),
]


@pytest.mark.parametrize("fn,market,universe,params", CASES)
def test_no_lookahead(fn, market, universe, params):
    from qrs.research.runner import get_market, resolve
    m = get_market(market, universe)
    f = resolve(fn)
    full = f(m, **params)
    for t in (m.close.index[-400], m.close.index[-90]):
        part = f(_truncate(m, t), **params)
        a = full.loc[:t].fillna(-999.0)
        b = part.reindex(columns=full.columns).loc[:t].fillna(-999.0)
        # rebalance-every-n schedules are anchored at the first row, so they are invariant to truncation
        np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), atol=1e-9, err_msg=f"{fn} leaks future data at {t}")


def test_pairs_no_lookahead():
    from qrs.research.runner import get_market
    from qrs.strategies.statarb import pairs_cointegration
    m = get_market("etf", "etf_sectors")
    full = pairs_cointegration(m, max_pairs=2)
    t = m.close.index[-300]
    part = pairs_cointegration(_truncate(m, t), max_pairs=2)
    # rows up to the last reselection date before t are identical (pairs close at reselection)
    last_resel = m.close.index[m.close.index.year == t.year][0]
    np.testing.assert_allclose(full.loc[:last_resel].iloc[:-1].to_numpy(),
                               part.loc[:last_resel].iloc[:-1].to_numpy(), atol=1e-9)
