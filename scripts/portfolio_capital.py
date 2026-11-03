"""Phase 6-7: multi-strategy portfolio and capital / passive-income feasibility.
Usage: python -m scripts.portfolio_capital"""
import json

import numpy as np
import pandas as pd

from qrs.backtest.metrics import summarize
from qrs.config import PROC_DIR, REPORT_DIR
from qrs.portfolio.capital import CAPITAL_LEVELS, outcome_distribution, share_simulation, withdrawal_paths
from qrs.portfolio.combine import combine, corr_matrix
from qrs.research.market import etf_market
from qrs.research.runner import RESULTS_DIR, experiments, jsonable, stitched_weights
import polars as pl


def eur_per_usd_returns(index) -> pd.Series:
    """Daily return of holding 1 USD measured in EUR (Fed H.10 EUR/USD)."""
    fx = pl.read_parquet(PROC_DIR / "ref_fx_h10.parquet").to_pandas()
    fx.columns = [c.lower() for c in fx.columns]
    e = fx[fx["country"].str.contains("Euro")].set_index("date")["exchange rate"].astype(float)
    e.index = pd.to_datetime(e.index)
    e = e[e > 0]
    usd_per_eur = e if e.median() > 1.0 else 1 / e
    eur_per_usd = (1 / usd_per_eur).reindex(index).ffill()
    return eur_per_usd.pct_change().fillna(0.0)


def main():
    exps = experiments()["experiments"]
    summ = {n: json.loads((RESULTS_DIR / f"{n}.json").read_text()) for n in exps}
    rets = {n: pd.read_parquet(RESULTS_DIR / f"{n}_returns.parquet")["net"] for n in exps}
    passed = [n for n, s in summ.items() if s.get("gate_pass")]
    m = etf_market()
    rf = m.rf
    # ---------------- correlations (WF-OOS window per market)
    etf_names = [n for n in exps if summ[n]["market"] == "etf"]
    cr_names = [n for n in exps if summ[n]["market"] != "etf"]
    corr_etf = corr_matrix({n: rets[n].loc[:"2021-12-31"] for n in etf_names})
    corr_cr = corr_matrix({n: rets[n].loc[:"2023-12-31"] for n in cr_names})
    # ---------------- portfolio of gate-passing strategies only (all are ETF here)
    out = {"passed": passed, "corr_etf": corr_etf.round(3).to_dict(), "corr_crypto": corr_cr.round(3).to_dict()}
    port_rets = {n: rets[n] for n in passed if summ[n]["market"] == "etf"}
    portfolios = {}
    for method in ("equal", "inv_vol"):
        pr, W, s = combine(port_rets, method, 252, rf=rf, lookback=756, min_obs=126)
        portfolios[method] = {"full_oos": s, "wf_oos": summarize(pr.loc[:"2021-12-31"], 252, rf=rf),
                              "holdout": summarize(pr.loc["2022-01-01":], 252, rf=rf)}
        if method == "inv_vol":
            chosen = pr
    out["portfolios"] = portfolios
    if passed:
        out["passed_pair_corr"] = float(pd.concat(port_rets, axis=1).corr().iloc[0, 1]) if len(port_rets) > 1 else None
    spy = pd.read_parquet(RESULTS_DIR / f"{passed[0]}_returns.parquet").index if passed else rf.index
    pd.DataFrame({"portfolio": chosen}).to_parquet(REPORT_DIR / "portfolio_returns.parquet")
    # ---------------- capital levels: integer shares + min fees, USD and EUR-unhedged
    cap = {"levels": {}, "assumptions": {
        "broker_fees": "USD 0.005/share, min USD 1, max 1% of trade value (IBKR-Pro-fixed-like) + modelled spread/slippage",
        "fx_conversion_bps": 2.0, "fx_risk": "EUR account holding USD ETFs, unhedged, Fed H.10 EUR/USD",
        "taxes": "NOT modelled (country specific; e.g. DE 26.375% on gains)",
        "eu_retail_access": "US-domiciled ETFs are generally not available to EU retail clients (PRIIPs KID); UCITS "
                            "equivalents (Ireland/Lux) trade on LSE/Xetra with different TER/spreads; results are a proxy",
        "window": "full walk-forward OOS 2008-01-01..2026-10-30 (includes holdout)"}}
    fxr = eur_per_usd_returns(m.close.index)
    Wsets = {}
    for n in passed:
        W, mm, exp = stitched_weights(n)
        Wsets[n] = (W, mm)
    weights_per_strat = 1.0 / max(len(passed), 1)
    for c in CAPITAL_LEVELS:
        row = {}
        eq_usd = None
        for n, (W, mm) in Wsets.items():
            sim = share_simulation(W.loc["2008-01-01":], mm.open, mm.close, c * weights_per_strat * 1.08,
                                   mm.costs.one_way * 1e4 - 0.5, rf=rf)
            eq_usd = sim["equity"] if eq_usd is None else eq_usd + sim["equity"]
            row[f"{n}_fees_total_usd"] = float(sim["fees"].sum())
        if eq_usd is None:
            cap["levels"][c] = {"note": "no strategy passed - capital stays in cash"}
            continue
        r_usd = eq_usd.pct_change().fillna(0.0)
        r_eur = (1 + r_usd) * (1 + fxr.reindex(r_usd.index).fillna(0.0)) - 1
        frac = chosen.loc[r_usd.index[0]:]
        row.update({"usd": summarize(r_usd, 252), "eur_unhedged": summarize(r_eur, 252),
                    "fractional_engine_cagr": summarize(frac, 252)["cagr"],
                    "small_account_drag_cagr": summarize(frac, 252)["cagr"] - summarize(r_usd, 252)["cagr"],
                    "fees_pct_of_capital_per_year": sum(v for k, v in row.items() if k.endswith("fees_total_usd"))
                                                    / float(eq_usd.mean()) / (len(r_usd) / 252)})
        if c in (10_000, 100_000):
            row["outcomes_10y_eur"] = outcome_distribution(r_eur, c, years=10)
            row["withdrawals_20y_eur"] = [withdrawal_paths(r_eur, c, w, years=20) for w in (0.0, 0.02, 0.03, 0.04, 0.06)]
            # conservative: bootstrap only the 2022-2026 holdout returns (the weaker, most recent regime)
            row["withdrawals_20y_eur_holdout_only"] = [withdrawal_paths(r_eur.loc["2022-01-01":], c, w, years=20)
                                                       for w in (0.0, 0.02, 0.03, 0.04, 0.06)]
            row["outcomes_10y_eur_holdout_only"] = outcome_distribution(r_eur.loc["2022-01-01":], c, years=10)
        cap["levels"][c] = row
        print(c, round(row["usd"]["cagr"], 4), round(row["eur_unhedged"]["cagr"], 4), round(row["small_account_drag_cagr"], 4))
    # passive comparison for the income question: SPY and 60/40 under the same withdrawal model
    from qrs.research.runner import benchmark_returns
    b = benchmark_returns("etf", "2008-01-01", "2026-10-30")
    cap["benchmarks_withdrawals_20y_eur_100k"] = {
        k: [withdrawal_paths((1 + b[k]) * (1 + fxr.reindex(b[k].index).fillna(0)) - 1, 100_000, w, years=20)
            for w in (0.02, 0.03, 0.04, 0.06)] for k in ("SPY_buy_hold", "60_40_SPY_IEF")}
    (REPORT_DIR / "portfolio.json").write_text(json.dumps(jsonable(out), indent=1))
    (REPORT_DIR / "capital.json").write_text(json.dumps(jsonable(cap), indent=1))
    print(json.dumps(jsonable(portfolios), indent=1)[:2500])


if __name__ == "__main__":
    main()
