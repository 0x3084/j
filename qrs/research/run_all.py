"""Run every registered experiment, apply multiple-testing corrections across ALL trials, rank on
robust out-of-sample after-cost metrics and apply the pre-registered acceptance gate.

    python -m qrs.research.run_all              # pre-holdout research phase (holdout masked)
    python -m qrs.research.run_all --holdout    # final, one-time holdout evaluation of the frozen set
"""
from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from qrs.backtest.stats import deflated_sharpe, holm, reality_check
from qrs.research.runner import RESULTS_DIR, experiments, gate, jsonable, protocol, run_experiment, save


def _one(args):
    name, holdout, n_boot = args
    t = time.time()
    out = run_experiment(name, holdout=holdout, n_boot=n_boot)
    save(out)
    return name, time.time() - t


def effective_trials(trials: pd.DataFrame, cut: float = 0.5) -> tuple[int, float]:
    """Cluster trial return streams (distance = 1 - corr, average linkage, cut at `cut`) to estimate
    the number of effectively independent trials; return (N_eff, variance of per-period Sharpe across
    cluster representatives)."""
    X = trials.dropna(how="all").fillna(0.0)
    X = X.loc[:, X.std() > 0]
    if X.shape[1] < 2:
        return max(X.shape[1], 1), 1.0 / max(len(X), 1)
    C = X.corr().fillna(0).to_numpy()
    D = np.clip(1 - C, 0, 2)
    np.fill_diagonal(D, 0)
    Z = linkage(squareform(D, checks=False), "average")
    lab = fcluster(Z, cut, criterion="distance")
    sr = X.mean() / X.std()
    reps = pd.Series(sr.values, index=lab).groupby(level=0).mean()
    var = float(reps.var()) if len(reps) > 1 else float(1.0 / len(X))
    return int(len(reps)), var


def analyse(holdout: bool, names: list[str] | None = None, out_prefix: str = "leaderboard") -> pd.DataFrame:
    """names: restrict analysis (trial counts, reality check, leaderboard) to this subset of experiment
    names - use this for a research extension opened after the main registry's holdout was evaluated,
    so its trials don't retroactively dilute the already-published statistics of the frozen set.
    out_prefix: leaderboard files are written to reports/{out_prefix}.csv and {out_prefix}_meta.json."""
    all_exps = experiments()["experiments"]
    exps = {n: v for n, v in all_exps.items() if names is None or n in names}
    acc = protocol()["acceptance"]
    summaries, oos, trials_by_kind = {}, {}, {"etf": [], "crypto": []}
    for name in exps:
        f = RESULTS_DIR / f"{name}.json"
        if not f.exists():
            continue
        s = json.loads(f.read_text())
        summaries[name] = s
        r = pd.read_parquet(RESULTS_DIR / f"{name}_returns.parquet")["net"]
        oos[name] = r
        kind = "etf" if s["market"] == "etf" else "crypto"
        t = pd.read_parquet(RESULTS_DIR / f"{name}_trials.parquet")
        t.columns = [f"{name}|{c}" for c in t.columns]
        trials_by_kind[kind].append(t)
    neff = {}
    for kind, lst in trials_by_kind.items():
        if lst:
            T = pd.concat(lst, axis=1)
            neff[kind] = effective_trials(T) + (T.shape[1],)
    from qrs.research.market import crypto_market, etf_market
    rf = {"etf": etf_market().rf, "crypto": crypto_market("spot").rf}
    pvals = {}
    for name, s in summaries.items():
        kind = "etf" if s["market"] == "etf" else "crypto"
        n_eff, var_sr, n_raw = neff[kind]
        pre_end = pd.Timestamp(s["wf_oos"]["end"])
        r = oos[name].loc[:pre_end] - rf[kind].reindex(oos[name].loc[:pre_end].index).fillna(0)
        # DSR vs the expected best of n_eff *noise* strategies (null sampling variance 1/T); the version
        # using the empirical cross-trial Sharpe variance is reported as a sensitivity check.
        s["dsr"] = deflated_sharpe(r, n_eff, None)
        s["dsr_xvar"] = deflated_sharpe(r, n_eff, var_sr)
        s["n_trials_market_raw"] = n_raw
        s["n_trials_market_effective"] = n_eff
        pvals[name] = s["wf_oos"].get("p_sharpe", np.nan)
    adj = holm({k: (v if v is not None else np.nan) for k, v in pvals.items()})
    rc = {}
    for kind in ("etf", "crypto"):
        cols = [n for n, s in summaries.items() if (s["market"] == "etf") == (kind == "etf")]
        if cols:
            R = pd.concat({n: oos[n].loc[:pd.Timestamp(summaries[n]["wf_oos"]["end"])] for n in cols}, axis=1)
            R = R.sub(rf[kind].reindex(R.index).fillna(0), axis=0)
            rc[kind] = {"vs_cash": reality_check(R, n_boot=1000)}
            # excess over the passive benchmark: does the best strategy beat simply holding the market?
            from qrs.research.runner import benchmark_returns
            s0 = summaries[cols[0]]
            sp = (etf_market() if kind == "etf" else crypto_market("spot")).splits
            bms = benchmark_returns(kind, sp["wf_oos_start"], s0["wf_oos"]["end"])
            b = bms["SPY_buy_hold" if kind == "etf" else "BTC_buy_hold"]
            Rb = pd.concat({n: oos[n].loc[:pd.Timestamp(summaries[n]["wf_oos"]["end"])] for n in cols}, axis=1)
            rc[kind]["vs_benchmark"] = reality_check(Rb.sub(b.reindex(Rb.index), axis=0).dropna(how="all"), n_boot=1000)
    rows = []
    for name, s in summaries.items():
        s["p_sharpe_holm"] = adj.get(name)
        ok, fails = gate(s, acc)
        s["gate_pass"], s["gate_failures"] = ok, fails
        (RESULTS_DIR / f"{name}.json").write_text(json.dumps(jsonable(s), indent=1))
        w = s["wf_oos"]
        bm = s["benchmarks_wf"].get("SPY_buy_hold") or s["benchmarks_wf"].get("BTC_buy_hold")
        row = {"experiment": name, "family": s["family"], "market": s["market"], "trials": s["n_trials"],
               "wf_sharpe": w.get("sharpe"), "wf_sharpe_lo": w.get("sharpe_lo"), "wf_sharpe_hi": w.get("sharpe_hi"),
               "wf_cagr": w.get("cagr"), "wf_vol": w.get("ann_vol"), "wf_maxdd": w.get("max_dd"),
               "wf_calmar": w.get("calmar"), "sortino": w.get("sortino"), "p_boot": w.get("p_sharpe"),
               "p_holm": s["p_sharpe_holm"], "dsr": s["dsr"], "dsr_xvar": s["dsr_xvar"], "sharpe_2x_cost": s["stress"]["cost_x2"]["sharpe"],
               "sharpe_3x_cost": s["stress"]["cost_x3"]["sharpe"], "sharpe_delay": s["stress"]["delay_+1bar"]["sharpe"],
               "h1_sharpe": s["wf_oos_first_half"].get("sharpe"), "h2_sharpe": s["wf_oos_second_half"].get("sharpe"),
               "cost_pct_gross": w.get("cost_pct_gross"), "turnover": w.get("turnover_ann"),
               "trades": w.get("n_trades"), "win_rate": w.get("win_rate"), "profit_factor": w.get("profit_factor"),
               "exposure": w.get("avg_gross_exp"), "bench_sharpe": bm["sharpe"] if bm else None,
               "bench_corr": bm["corr"] if bm else None, "gate": "PASS" if ok else "FAIL",
               "fail_reasons": "; ".join(fails)}
        if "holdout" in s:
            row.update({"ho_sharpe": s["holdout"].get("sharpe"), "ho_cagr": s["holdout"].get("cagr"),
                        "ho_maxdd": s["holdout"].get("max_dd"), "ho_sharpe_lo": s["holdout"].get("sharpe_lo")})
        rows.append(row)
    lb = pd.DataFrame(rows)
    # Robust ranking score: lower CI bound of Sharpe, penalised by cost fragility and instability.
    lb["robust_score"] = (lb["wf_sharpe_lo"].fillna(-9) + 0.5 * lb[["sharpe_2x_cost", "h1_sharpe", "h2_sharpe"]].min(axis=1).fillna(-9)
                          + lb["dsr"].fillna(0) * 0.5)
    lb = lb.sort_values("robust_score", ascending=False)
    lb.to_csv(RESULTS_DIR.parent / f"{out_prefix}.csv", index=False)
    meta = {"effective_trials": {k: {"n_eff": v[0], "var_sr": v[1], "n_raw": v[2]} for k, v in neff.items()},
            "reality_check": rc, "holdout_unlocked": holdout, "scope": names or "all"}
    (RESULTS_DIR.parent / f"{out_prefix}_meta.json").write_text(json.dumps(jsonable(meta), indent=1))
    return lb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 0))
    ap.add_argument("--analyse-only", action="store_true")
    ap.add_argument("--out-prefix", default="leaderboard",
                    help="leaderboard files go to reports/<prefix>.csv and <prefix>_meta.json; use a "
                         "distinct prefix (with --only) for a research extension so it doesn't "
                         "overwrite or dilute the statistics of an already-published leaderboard.")
    a = ap.parse_args()
    names = a.only or list(experiments()["experiments"])
    if not a.analyse_only:
        with ProcessPoolExecutor(a.workers) as ex:
            for name, dt in ex.map(_one, [(n, a.holdout, a.n_boot) for n in names]):
                print(f"{name:28s} {dt:6.0f}s", flush=True)
    lb = analyse(a.holdout, names=a.only, out_prefix=a.out_prefix)
    pd.set_option("display.width", 250)
    print(lb[["experiment", "wf_sharpe", "wf_sharpe_lo", "wf_cagr", "wf_maxdd", "dsr", "sharpe_2x_cost", "gate"]
             + (["ho_sharpe"] if a.holdout else [])].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
