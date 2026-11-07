"""Experiment runner: per-parameter trials -> walk-forward parameter selection -> stitched out-of-sample
backtest -> stress tests, bootstrap inference, deflated Sharpe, benchmarks, regimes -> acceptance gate.

Holdout protection: unless ``holdout=True`` every backtest is truncated at ``holdout_start - 1 day``.
Unlocking the holdout is recorded in reports/trial_ledger.csv together with the git commit, so it is
auditable whether strategies were modified after the holdout was viewed.
"""
from __future__ import annotations

import importlib
import itertools
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
import pandas as pd

from qrs.backtest.engine import BacktestResult, run_backtest
from qrs.backtest.metrics import max_drawdown, regime_table, sharpe, summarize, yearly
from qrs.backtest.stats import bootstrap_metrics, deflated_sharpe, probabilistic_sharpe
from qrs.config import REPORT_DIR, load_yaml
from qrs.data.store import load_vix
from qrs.research.market import Market, crypto_market, etf_market

RESULTS_DIR = REPORT_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
LEDGER = REPORT_DIR / "trial_ledger.csv"


def git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def experiments() -> dict:
    return load_yaml("experiments.yaml")


def protocol() -> dict:
    return load_yaml("research.yaml")


# ----------------------------------------------------------------------------------- markets
@lru_cache(maxsize=32)
def get_market(market: str, universe: str) -> Market:
    if market == "etf":
        m = etf_market()
    elif market == "crypto_spot":
        m = crypto_market("spot")
    elif market == "crypto_perp":
        m = crypto_market("perp", top_n=10)
    elif market == "crypto_carry":
        from qrs.strategies.vol import carry_market
        top_n = 18 if universe == "carry_wide" else 10
        return carry_market(top_n=top_n)
    else:
        raise ValueError(market)
    syms = experiments()["universes"][universe]
    if syms == "all":
        return m
    return m.subset(syms, name=f"{market}:{universe}")


def resolve(fn: str):
    mod, f = fn.split(":")
    return getattr(importlib.import_module(f"qrs.strategies.{mod}"), f)


def grid_params(exp: dict) -> list[dict]:
    g = exp.get("grid", {}) or {}
    keys = list(g)
    combos = itertools.product(*[g[k] for k in keys]) if keys else [()]
    return [{**(exp.get("params") or {}), **dict(zip(keys, c))} for c in combos]


def pkey(p: dict, exp: dict) -> str:
    g = exp.get("grid", {}) or {}
    return ",".join(f"{k}={p[k]}" for k in g) or "default"


def bt(m: Market, W: pd.DataFrame, engine: dict, start=None, end=None, costs=None, lag: int = 1,
       open_=None, close=None) -> BacktestResult:
    return run_backtest(W, m.open if open_ is None else open_, m.close if close is None else close,
                        costs or m.costs, rf=m.rf, funding=m.funding, lag=lag,
                        max_gross=engine.get("max_gross", 1.0), band=engine.get("band", 0.0), start=start, end=end)


# ----------------------------------------------------------------------------- walk-forward
def walk_forward_select(trials: dict[str, pd.Series], oos_start: str, end: str, ppy: int, min_train_years: float,
                        embargo: int) -> dict[pd.Timestamp, str | None]:
    """For each calendar year in [oos_start, end] choose the parameter set with the best Sharpe on all
    data before (year start - embargo). If the best training Sharpe <= 0, choose None (= NO TRADE)."""
    years = pd.date_range(pd.Timestamp(oos_start), pd.Timestamp(end), freq="YS")
    if len(years) == 0 or years[0] != pd.Timestamp(oos_start):
        years = pd.DatetimeIndex([pd.Timestamp(oos_start)]).append(years)
    sel = {}
    for y in years:
        cut = y - pd.Timedelta(days=int(embargo * 365 / ppy) + 1)
        best, best_s = None, 0.0
        for k, r in trials.items():
            tr = r.loc[:cut]
            tr = tr.loc[tr.ne(0).idxmax():] if tr.ne(0).any() else tr.iloc[0:0]   # from first active bar
            if len(tr) < min_train_years * ppy:
                continue
            s = sharpe(tr, ppy)
            if np.isfinite(s) and s > best_s:
                best, best_s = k, s
        sel[y] = best
    return sel


def stitch(Ws: dict[str, pd.DataFrame], sel: dict, index: pd.DatetimeIndex, cols) -> pd.DataFrame:
    W = pd.DataFrame(0.0, index=index, columns=cols)
    ys = sorted(sel)
    for i, y in enumerate(ys):
        nxt = ys[i + 1] if i + 1 < len(ys) else index[-1] + pd.Timedelta(days=1)
        rows = (index >= y) & (index < nxt)
        k = sel[y]
        if k is not None:
            W.loc[rows] = Ws[k].reindex(columns=cols).loc[rows].to_numpy()
        else:
            W.loc[rows] = 0.0               # NO TRADE
    return W


# ------------------------------------------------------------------------------ benchmarks
def benchmark_weights(spec, m: Market, index) -> pd.DataFrame:
    from qrs.strategies.common import rebalance_monthly
    cols = m.symbols
    W = pd.DataFrame(0.0, index=index, columns=cols)
    if spec == "cash":
        return W
    if isinstance(spec, dict):
        for k, v in spec.items():
            W[k] = v
        W = W.where(m.close.reindex(index)[cols].notna().cummax(), 0.0)
        return rebalance_monthly(W)
    if spec.startswith("equal:"):
        syms = experiments()["universes"][spec.split(":")[1]]
        e = m.eligible.reindex(index)[[s for s in syms if s in cols]]
        W[e.columns] = e.astype(float).div(e.sum(axis=1).clip(lower=1), axis=0)
        return rebalance_monthly(W)
    if spec.startswith("equal_top:"):
        n = int(spec.split(":")[1])
        qv = m.volume.rolling(30, min_periods=20).mean().where(m.eligible)
        top = qv.rank(axis=1, ascending=False).le(n)
        W = top.astype(float).div(top.sum(axis=1).clip(lower=1), axis=0).reindex(index).fillna(0.0)
        return rebalance_monthly(W)
    raise ValueError(spec)


@lru_cache(maxsize=8)
def benchmark_returns(market_kind: str, start: str, end: str) -> dict[str, pd.Series]:
    b = experiments()["benchmarks"]["etf" if market_kind == "etf" else "crypto"]
    m = etf_market() if market_kind == "etf" else crypto_market("spot")
    out = {}
    for name, spec in b.items():
        W = benchmark_weights(spec, m, m.close.index)
        if spec == "cash":
            out[name] = m.rf.loc[start:end]
            continue
        r = bt(m, W, {"max_gross": 1.0, "band": 0.0}, start=start, end=end)
        out[name] = r.net
    return out


def regimes(market_kind: str, index) -> pd.Series:
    if market_kind == "etf":
        v = load_vix().reindex(index).ffill()
        return pd.cut(v, [0, 15, 25, 1000], labels=["VIX<15", "VIX15-25", "VIX>25"]).astype(str)
    btc = crypto_market("spot").close["BTCUSDT"].reindex(index).ffill()
    up = btc > btc.rolling(200, min_periods=150).mean()
    return up.map({True: "BTC>200dMA", False: "BTC<200dMA"})


# ----------------------------------------------------------------------------------- ledger
def _ledger(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    df.to_csv(LEDGER, mode="a", header=not LEDGER.exists(), index=False)


# --------------------------------------------------------------------------- run experiment
@dataclass
class ExpOutput:
    name: str
    summary: dict
    oos: pd.DataFrame          # engine returns frame over WF-OOS (+holdout if unlocked)
    trials: dict               # key -> trial net returns (pre-holdout)
    weights_last: pd.Series


def run_experiment(name: str, holdout: bool = False, n_boot: int = 500) -> ExpOutput:
    exp = experiments()["experiments"][name]
    m = get_market(exp["market"], exp["universe"])
    sp = m.splits
    wf = protocol()["walk_forward"]
    kind = "etf" if exp["market"] == "etf" else "crypto"
    ppy = m.ppy
    pre_end = (pd.Timestamp(sp["holdout_start"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    final_end = sp["end"] if holdout else pre_end
    fn = resolve(exp["fn"])
    eng = exp.get("engine", {})

    def ex(r: pd.Series) -> pd.Series:          # excess over the risk-free rate (cash proxy)
        return r - m.rf.reindex(r.index).fillna(0.0)

    Ws, trials, trial_rows = {}, {}, []
    for p in grid_params(exp):
        k = pkey(p, exp)
        W = fn(m, **p)
        Ws[k] = W
        r = bt(m, W, eng, start=sp["data_start"], end=pre_end)
        trials[k] = r.net
        s_oos = sharpe(ex(r.net).loc[sp["wf_oos_start"]:], ppy)
        trial_rows.append({"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git": git_rev(),
                           "experiment": name, "params": k, "period": f"{sp['data_start']}..{pre_end}",
                           "sharpe_full_pre_holdout": round(sharpe(ex(r.net), ppy), 4),
                           "sharpe_wf_window": round(s_oos, 4), "holdout_viewed": False})
    _ledger(trial_rows)

    sel = walk_forward_select({k: ex(v) for k, v in trials.items()}, sp["wf_oos_start"], final_end, ppy, sp["min_train_years"], wf["embargo_days"])
    Wst = stitch(Ws, sel, m.close.index, m.symbols)
    res = bt(m, Wst, eng, start=sp["wf_oos_start"], end=final_end)
    oos_ret = res.returns
    wf_slice = oos_ret.loc[:pre_end]
    tr_wf = res.trades[res.trades["entry"] <= pd.Timestamp(pre_end)]
    summ = {"name": name, "family": exp["family"], "market": exp["market"], "universe": exp["universe"],
            "n_trials": len(Ws), "selections": {str(k.date()): v for k, v in sel.items()},
            "git": git_rev(), "holdout_unlocked": holdout}
    summ["wf_oos"] = summarize(wf_slice, ppy, tr_wf, rf=m.rf)
    summ["wf_oos"].update(bootstrap_metrics(ex(wf_slice["net"]), ppy, n_boot=n_boot))
    summ["wf_oos"]["psr0"] = probabilistic_sharpe(ex(wf_slice["net"]))
    # sub-period stability: halves of the WF-OOS window
    mid = wf_slice.index[len(wf_slice) // 2]
    summ["wf_oos_first_half"] = summarize(wf_slice.loc[:mid], ppy, rf=m.rf)
    summ["wf_oos_second_half"] = summarize(wf_slice.loc[mid:], ppy, rf=m.rf)
    summ["yearly"] = {int(k): float(v) for k, v in yearly(oos_ret["net"]).items()}
    summ["regimes"] = regime_table(ex(wf_slice["net"]), regimes(kind, wf_slice.index), ppy).to_dict("records")

    # ---- stress tests (WF-OOS window only)
    st = protocol()["stress"]
    stress = {}
    for cm in st["cost_multipliers"]:
        r = bt(m, Wst, eng, start=sp["wf_oos_start"], end=pre_end, costs=m.costs.stressed(cost_mult=cm))
        stress[f"cost_x{cm:g}"] = {"sharpe": sharpe(ex(r.net), ppy), "cagr": summarize(r.returns, ppy)["cagr"]}
    for sb in st["extra_slippage_bps"]:
        r = bt(m, Wst, eng, start=sp["wf_oos_start"], end=pre_end, costs=m.costs.stressed(slip_add_bps=sb))
        stress[f"slip_+{sb:g}bps"] = {"sharpe": sharpe(ex(r.net), ppy), "cagr": summarize(r.returns, ppy)["cagr"]}
    r = bt(m, Wst, eng, start=sp["wf_oos_start"], end=pre_end, lag=1 + st["extra_lag"])
    stress["delay_+1bar"] = {"sharpe": sharpe(ex(r.net), ppy), "cagr": summarize(r.returns, ppy)["cagr"]}
    rng = np.random.default_rng(3)
    drop = rng.random(m.close.shape) < st["missing_data_frac"]
    r = bt(m, Wst, eng, start=sp["wf_oos_start"], end=pre_end, open_=m.open.mask(drop), close=m.close.mask(drop))
    stress["missing_5pct_bars"] = {"sharpe": sharpe(ex(r.net), ppy), "cagr": summarize(r.returns, ppy)["cagr"]}
    summ["stress"] = stress

    # ---- benchmarks over the same window
    bms = benchmark_returns(kind, sp["wf_oos_start"], final_end)
    summ["benchmarks_wf"] = {}
    for bn, br in bms.items():
        b = br.loc[wf_slice.index[0]:pre_end]
        al = pd.concat([wf_slice["net"], b], axis=1).dropna()
        summ["benchmarks_wf"][bn] = {"sharpe": sharpe(ex(b), ppy), "cagr": summarize(b, ppy).get("cagr"),
                                     "max_dd": max_drawdown(b),
                                     "corr": float(al.corr().iloc[0, 1]) if len(al) > 30 and al.std().min() > 0 else None}
    if holdout:
        ho = oos_ret.loc[sp["holdout_start"]:]
        tr_ho = res.trades[res.trades["entry"] >= pd.Timestamp(sp["holdout_start"])]
        summ["holdout"] = summarize(ho, ppy, tr_ho, rf=m.rf)
        summ["holdout"].update(bootstrap_metrics(ex(ho["net"]), ppy, n_boot=n_boot))
        summ["benchmarks_holdout"] = {bn: {"sharpe": sharpe(ex(br.loc[sp["holdout_start"]:]), ppy),
                                           "cagr": summarize(br.loc[sp["holdout_start"]:], ppy).get("cagr"),
                                           "max_dd": max_drawdown(br.loc[sp["holdout_start"]:])}
                                      for bn, br in bms.items()}
        _ledger([{"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git": git_rev(),
                  "experiment": name, "params": "WF-stitched", "period": f"{sp['holdout_start']}..{sp['end']}",
                  "sharpe_full_pre_holdout": None, "sharpe_wf_window": None, "holdout_viewed": True}])
    last = Wst.iloc[-1]
    return ExpOutput(name, summ, oos_ret, trials, last)


# ---------------------------------------------------------------------------------- gating
def _nn(d: dict, default: float = float("nan")) -> dict:
    """Replace None (JSON null for NaN) with a default so comparisons fail safely."""
    return {k: (default if v is None else v) for k, v in d.items()}


def gate(s: dict, acc: dict) -> tuple[bool, list[str]]:
    w = _nn(s["wf_oos"], float("nan"))
    s = {**s, "stress": {k: _nn(v, -9.0) for k, v in s["stress"].items()},
         "holdout": _nn(s["holdout"], float("nan")) if "holdout" in s else None}
    if s["holdout"] is None:
        s.pop("holdout")
    fails = []
    def chk(cond, msg):
        if not cond:
            fails.append(msg)
    chk(np.nan_to_num(w.get("sharpe", -9), nan=-9) >= acc["wf_oos_sharpe_min"], f"WF-OOS Sharpe {w.get('sharpe', float('nan')):.2f} < {acc['wf_oos_sharpe_min']}")
    chk((w.get("sharpe_lo") or -9) > acc["wf_oos_sharpe_ci_lo_min"], f"Sharpe 95% CI lower bound {w.get('sharpe_lo', float('nan')):.2f} <= 0")
    chk((s.get("dsr") or 0) >= acc["dsr_min"], f"Deflated Sharpe {s.get('dsr', float('nan')):.2f} < {acc['dsr_min']}")
    chk(s["stress"]["cost_x2"]["sharpe"] >= acc["stress_2x_cost_sharpe_min"],
        f"Sharpe at 2x costs {s['stress']['cost_x2']['sharpe']:.2f} < {acc['stress_2x_cost_sharpe_min']}")
    chk(w.get("max_dd", -1) >= acc["max_dd_max"], f"max DD {w.get('max_dd', float('nan')):.1%} worse than {acc['max_dd_max']:.0%}")
    chk(w.get("n_trades", 0) >= acc["min_trades"], f"only {w.get('n_trades', 0)} trades")
    if acc.get("benchmark_rule"):
        bm = s["benchmarks_wf"]
        main = bm.get("SPY_buy_hold") or bm.get("BTC_buy_hold")
        ok = (np.nan_to_num(w.get("sharpe", -9), nan=-9) > (main["sharpe"] or 0)) or ((main["corr"] is not None) and abs(main["corr"]) < 0.5 and w.get("sharpe", 0) > 0)
        chk(ok, "does not beat passive benchmark Sharpe and is not a low-correlation diversifier")
    if "holdout" in s:
        chk(np.nan_to_num(s["holdout"].get("sharpe", -9), nan=-9) >= acc["holdout_sharpe_min"], f"holdout Sharpe {s['holdout'].get('sharpe', float('nan')):.2f} < 0")
    return len(fails) == 0, fails


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def save(out: ExpOutput) -> None:
    (RESULTS_DIR / f"{out.name}.json").write_text(json.dumps(jsonable(out.summary), indent=1))
    out.oos.to_parquet(RESULTS_DIR / f"{out.name}_returns.parquet")
    pd.DataFrame(out.trials).to_parquet(RESULTS_DIR / f"{out.name}_trials.parquet")
    out.weights_last.to_frame("target_weight").to_json(RESULTS_DIR / f"{out.name}_target.json")


def stitched_weights(name: str) -> tuple[pd.DataFrame, Market, dict]:
    """Rebuild the walk-forward stitched target weights of an experiment from its saved selections."""
    exp = experiments()["experiments"][name]
    s = json.loads((RESULTS_DIR / f"{name}.json").read_text())
    m = get_market(exp["market"], exp["universe"])
    fn = resolve(exp["fn"])
    Ws = {}
    for p in grid_params(exp):
        k = pkey(p, exp)
        if k in s["selections"].values():
            Ws[k] = fn(m, **p)
    sel = {pd.Timestamp(k): v for k, v in s["selections"].items()}
    return stitch(Ws, sel, m.close.index, m.symbols), m, exp
