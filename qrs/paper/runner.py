"""Build paper traders for research strategies and compare paper results with backtest assumptions.

Only strategies whose results file says ``gate_pass: true`` may be paper traded, unless the caller
passes ``shadow=True`` - then the run is labelled SHADOW (diagnostic only, not an approved strategy).
"""
from __future__ import annotations

import json
from functools import partial

import numpy as np
import pandas as pd

from qrs.backtest.engine import run_backtest
from qrs.backtest.metrics import summarize
from qrs.config import PAPER_DIR, REPORT_DIR, load_yaml
from qrs.paper.engine import PaperTrader
from qrs.paper.feeds import ReplayFeed
from qrs.research.market import Market, crypto_market, etf_market
from qrs.research.runner import RESULTS_DIR, experiments, get_market, resolve
from qrs.risk.manager import RiskLimits


def latest_params(name: str) -> dict | None:
    s = json.loads((RESULTS_DIR / f"{name}.json").read_text())
    sel = s["selections"][max(s["selections"])]
    if sel is None:
        return None
    exp = experiments()["experiments"][name]
    params = dict(exp.get("params") or {})
    for kv in sel.split(","):
        k, v = kv.split("=")
        grid_vals = exp["grid"][k]
        params[k] = next(g for g in grid_vals if str(g) == v)
    return params


def market_builder_from(full: Market):
    """Returns a function building a Market from the paper trader's accumulated panels, reusing the
    research market's static parts (costs, rf history) so the exact research code path is exercised."""
    def build(hist: dict[str, pd.DataFrame]) -> Market:
        c = hist["close"].reindex(columns=full.symbols)
        idx = c.index
        def p(k):
            return hist[k].reindex(index=idx, columns=full.symbols)
        if full.ppy == 252:
            elig = c.notna().rolling(252, min_periods=1).sum() >= 250
        else:
            hv = c.notna().rolling(120, min_periods=1).sum() >= 115
            elig = full.eligible.reindex(idx).fillna(False) & hv
        f = full.funding.reindex(index=idx, columns=full.symbols).fillna(0.0) if full.funding is not None else None
        return Market(full.name, p("open"), p("high"), p("low"), c, p("volume"), full.costs, full.ppy,
                      full.rf.reindex(idx).fillna(0.0), elig, f, full.splits, full.groups)
    return build


def make_trader(name: str, capital: float, start: str, end: str | None = None, shadow: bool = False,
                run_tag: str = "") -> PaperTrader:
    s = json.loads((RESULTS_DIR / f"{name}.json").read_text())
    if not s.get("gate_pass") and not shadow:
        raise PermissionError(f"{name} did not pass the research gate; paper trading refused (use shadow=True "
                              "for a clearly-labelled diagnostic run)")
    exp = experiments()["experiments"][name]
    m = get_market(exp["market"], exp["universe"])
    params = latest_params(name)
    fn = resolve(exp["fn"])
    strat = (lambda mm: pd.DataFrame(0.0, index=mm.close.index, columns=mm.symbols)) if params is None else partial(fn, **params)
    panels = {"open": m.open, "high": m.high, "low": m.low, "close": m.close, "volume": m.volume}
    feed = ReplayFeed(panels, start, end, source="replay:" + ("yahoo_mirror" if exp["market"] == "etf" else "binance_archive"))
    lim = RiskLimits.from_dict(load_yaml("risk.yaml")["limits"])
    eng = exp.get("engine", {})
    lim.max_gross = max(lim.max_gross, eng.get("max_gross", 1.0))
    lim.max_leverage = max(lim.max_leverage, eng.get("max_gross", 1.0))
    groups = {}
    if exp["market"] == "etf":
        u = load_yaml("universe.yaml")["etf"]["instruments"]
        groups = {k: v["asset_class"] for k, v in u.items()}
    one = (m.costs.one_way * 1e4).to_dict()
    if exp["market"] == "etf":
        from qrs.config import etf_specs
        sp = etf_specs()
        comm = {k: sp[k]["commission_bps"] for k in m.symbols if k in sp}
        slip = {k: one[k] - comm.get(k, 0) for k in m.symbols}
        bk = {"one_way_bps": slip, "commission_bps": comm, "min_fee": 1.0, "lot_step": 1.0}
    else:
        bk = {"one_way_bps": {k: v * 0.5 for k, v in one.items()}, "commission_bps": {k: v * 0.5 for k, v in one.items()},
              "min_fee": 0.0, "lot_step": 1e-5}
    tag = f"{name}{'_SHADOW' if shadow else ''}{run_tag}"
    pt = PaperTrader(tag, feed, strat, market_builder_from(m), capital, lim, bk, groups,
                     journal_path=PAPER_DIR / f"{tag}.sqlite", mode="replay")
    pt.meta = {"experiment": name, "params": params, "shadow": shadow, "gate_pass": bool(s.get("gate_pass")),
               "start": start, "end": end, "capital": capital}
    return pt


def compare_with_backtest(pt: PaperTrader) -> dict:
    """Model-decay / execution-discrepancy check: replay the same strategy in the research engine over
    the same window and compare daily returns with the paper account."""
    meta = pt.meta
    exp = experiments()["experiments"][meta["experiment"]]
    m = get_market(exp["market"], exp["universe"])
    eq = pd.DataFrame(pt.journal.query("SELECT ts, equity FROM equity WHERE run_id=? ORDER BY ts", (pt.run_id,)))
    eq["ts"] = pd.to_datetime(eq["ts"])
    paper = eq.set_index("ts")["equity"].pct_change().dropna()
    fn = resolve(exp["fn"])
    W = fn(m, **meta["params"]) if meta["params"] else pd.DataFrame(0.0, index=m.close.index, columns=m.symbols)
    eng = exp.get("engine", {})
    bt = run_backtest(W, m.open, m.close, m.costs, rf=m.rf, funding=m.funding, max_gross=eng.get("max_gross", 1.0),
                      band=eng.get("band", 0.0), start=meta["start"], end=meta["end"])
    al = pd.concat([paper.rename("paper"), bt.net.rename("backtest")], axis=1).dropna()
    ppy = m.ppy
    out = {"experiment": meta["experiment"], "run_id": pt.run_id, "shadow": meta["shadow"], "n_days": len(al),
           "paper": summarize(al["paper"], ppy), "backtest": summarize(al["backtest"], ppy),
           "daily_corr": float(al.corr().iloc[0, 1]) if len(al) > 5 and al.std().min() > 0 else None,
           "tracking_error_ann": float((al["paper"] - al["backtest"]).std() * np.sqrt(ppy)),
           "return_gap_ann": float((al["paper"] - al["backtest"]).mean() * ppy),
           "paper_costs_total": pt.broker.costs_paid, "data_class": "HISTORICAL-REPLAY (simulated, not live)"}
    (REPORT_DIR / f"paper_vs_backtest_{pt.run_id}.json").write_text(json.dumps(out, indent=1, default=str))
    return out
