"""Machine-learning strategies with strictly purged, walk-forward training.

* ``ml_xsection``: cross-sectional return forecasting (ridge or LightGBM) on a panel of simple,
  well-known features. Retrained periodically on data whose LABELS end before the retrain date minus
  an embargo (purging overlapping forward-return labels). Used only to rank assets.
* ``ml_regime``: probabilistic classifier (L2 logistic regression) for "next-month equity excess
  return > 0", used to switch between equities and bonds/cash.

ML is held to the same standard as everything else: it must beat a simple momentum baseline
out-of-sample after costs, otherwise it is rejected.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from qrs.data.store import load_vix
from qrs.research.market import Market
from qrs.strategies.common import rebalance_every, rsi


def _features(m: Market) -> dict[str, pd.DataFrame]:
    px = m.close.ffill(limit=5)
    vol = m.vol(60)
    f = {}
    for L in (5, 21, 63, 126, 252):
        f[f"ret_{L}"] = (px / px.shift(L) - 1) / (vol * np.sqrt(L / m.ppy))
    f["ret_252_21"] = (px.shift(21) / px.shift(252) - 1) / vol
    f["vol_20_60"] = m.vol(20) / vol
    f["vol_60"] = vol
    f["dist_ma200"] = px / px.rolling(200, min_periods=150).mean() - 1
    f["rsi_14"] = rsi(px, 14) / 100 - 0.5
    if m.funding is not None:
        f["funding_7"] = m.funding.rolling(7, min_periods=5).mean() * 365
    # cross-sectional ranks (scale-free) for a subset
    for k in ("ret_21", "ret_126", "ret_252_21"):
        f[f"xr_{k}"] = f[k].rank(axis=1, pct=True) - 0.5
    return f


def _stack(f: dict[str, pd.DataFrame], mask: pd.DataFrame) -> pd.DataFrame:
    cols = []
    for k, v in f.items():
        cols.append(v.where(mask).stack(future_stack=True).rename(k))
    X = pd.concat(cols, axis=1)
    return X.dropna(how="any")


def ml_xsection(m: Market, model: str = "ridge", horizon: int = 5, k: int = 3, retrain: str = "YS",
                long_short: bool = False, min_train: int = 756, embargo: int = 10, vol_target: float | None = None,
                seed: int = 0) -> pd.DataFrame:
    from sklearn.linear_model import Ridge
    feats = _features(m)
    px = m.close.ffill(limit=5)
    fwd = (px.shift(-horizon) / px - 1)                              # label: used ONLY for training rows
    fwd = fwd.sub(fwd.mean(axis=1), axis=0) / m.vol(60)              # cross-sectionally demeaned, vol-scaled
    X = _stack(feats, m.eligible)
    y = fwd.stack(future_stack=True).reindex(X.index)
    dates = X.index.get_level_values(0)
    idx = m.close.index
    retrain_dates = pd.Series(idx, index=idx).groupby(idx.to_period("Y" if retrain == "YS" else "Q")).first().values
    preds = pd.Series(np.nan, index=X.index)
    for j, d in enumerate(retrain_dates):
        i_d = idx.get_loc(d)
        if i_d < min_train:
            continue
        label_end = idx[max(i_d - horizon - embargo, 0)]               # purge + embargo
        tr = (dates <= label_end) & y.notna().to_numpy()
        if tr.sum() < 500:
            continue
        nxt = retrain_dates[j + 1] if j + 1 < len(retrain_dates) else idx[-1] + pd.Timedelta(days=1)
        te = (dates >= d) & (dates < nxt)
        if not te.any():
            continue
        Xtr, ytr = X[tr].to_numpy(), y[tr].clip(-5, 5).to_numpy()
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
        if model == "ridge":
            mdl = Ridge(alpha=100.0).fit((Xtr - mu) / sd, ytr)
        else:
            import lightgbm as lgb
            mdl = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=8, min_child_samples=200,
                                    subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0,
                                    random_state=seed, n_jobs=1, deterministic=True, force_row_wise=True, verbose=-1).fit((Xtr - mu) / sd, ytr)
        preds[te] = mdl.predict((X[te].to_numpy() - mu) / sd)
    P = preds.unstack().reindex(index=idx, columns=m.symbols)
    rk = P.rank(axis=1, ascending=False)
    top = rk.le(k) & (P > 0)
    W = top.astype(float) / k
    if long_short:
        n = P.notna().sum(axis=1)
        bot = rk.gt(n - k, axis=0) & (P < 0)
        sh = m.costs.shortable.reindex(m.symbols).fillna(False).to_numpy()
        W = (W - bot.astype(float).mul(sh, axis=1) / k) / 2
    return rebalance_every(W.fillna(0.0), horizon)


def ml_regime(m: Market, risk: str = "SPY", safe: str | None = "IEF", horizon: int = 21, p_enter: float = 0.55,
              min_train: int = 1260, embargo: int = 21, C: float = 0.1) -> pd.DataFrame:
    """L2-logistic P(next `horizon`-day excess return of `risk` > 0). Weight in risk asset = 1 when
    p > p_enter, else rotate to `safe` (or cash)."""
    from sklearn.linear_model import LogisticRegression
    px = m.close.ffill(limit=5)
    r = px[risk]
    vix = load_vix().reindex(px.index).ffill(limit=3)
    feats = pd.DataFrame({
        "mom_21": r / r.shift(21) - 1, "mom_63": r / r.shift(63) - 1, "mom_252": r / r.shift(252) - 1,
        "ma200": r / r.rolling(200).mean() - 1, "vol20": m.vol(20)[risk], "vol_ratio": m.vol(20)[risk] / m.vol(120)[risk],
        "vix": vix, "vix_chg": vix / vix.shift(21) - 1,
        "credit": np.log(px["HYG"] / px["IEF"]).diff(63) if "HYG" in px else 0.0,
        "curve": np.log(px["TLT"] / px["SHY"]).diff(63) if "TLT" in px else 0.0,
    })
    rf_fwd = (1 + m.rf).rolling(horizon).apply(np.prod, raw=True).shift(-horizon) - 1
    y = ((r.shift(-horizon) / r - 1) > rf_fwd).astype(float).where(r.shift(-horizon).notna())
    idx = px.index
    prob = pd.Series(np.nan, index=idx)
    years = pd.Series(idx, index=idx).groupby(idx.year).first().values
    for j, d in enumerate(years):
        i_d = idx.get_loc(d)
        if i_d < min_train:
            continue
        end = idx[i_d - horizon - embargo]
        tr = feats.loc[:end].dropna().index.intersection(y.loc[:end].dropna().index)
        if len(tr) < 750:
            continue
        nxt = years[j + 1] if j + 1 < len(years) else idx[-1] + pd.Timedelta(days=1)
        te = feats.loc[d:nxt - pd.Timedelta(days=1)].dropna().index
        mu, sd = feats.loc[tr].mean(), feats.loc[tr].std() + 1e-9
        clf = LogisticRegression(C=C, max_iter=1000).fit(((feats.loc[tr] - mu) / sd).to_numpy(), y.loc[tr].to_numpy())
        prob.loc[te] = clf.predict_proba(((feats.loc[te] - mu) / sd).to_numpy())[:, 1]
    W = pd.DataFrame(0.0, index=idx, columns=m.symbols)
    on = (prob > p_enter)
    W[risk] = on.astype(float).where(prob.notna(), 0.0)
    if safe:
        W[safe] = (~on).astype(float).where(prob.notna(), 0.0)
    W = rebalance_every(W, 5)
    # after the first prediction, a missing prediction (e.g. stale VIX feature) means HOLD, not cash
    started = prob.notna().cummax()
    W.loc[(started & prob.isna()).to_numpy()] = np.nan
    return W
